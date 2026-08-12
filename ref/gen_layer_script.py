#!/usr/bin/env python3
"""gen_layer_script.py <outfile> <seed> [ntok]

Emit a layer_chan command script that replays one DeltaNet layer and one
full-attention layer (ntok tokens each, random weights/inputs) and checks
every intermediate against the frozen spec (ref/layer_fixed.py).

The generator maintains a scratchpad MODEL updated by the exact semantics
of each command (mirroring rtl/layer_chan.sv) and SELF-CHECKS the final
residual of every token against an independent layer_decode_fx run, so a
flawed command mapping aborts here and never reaches simulation.

Matvec round-trips are host-side (stage-2 verified engines): the script
asserts the on-chip x8/EOUT first (R/E records), then injects the raw y32
accumulators computed from those asserted values (W32 records).

Script records (hex fields):
  W <addr> <n>   + n hex16 lines     host scratch write
  C <op> <a0> <a1> <a2>              command, wait for completion
  R <addr> <n>   + n hex16 lines     read scratch, compare
  E <e>                              compare EOUT CSR
  T <val>                            write TCNT CSR (current kv_slot)
  L <hex32>                          write LAYER CSR = {kv_slot<<8, dn_slot}
                                     selects the banked layer state below
  V <wid> <x8a> <nin> <nrows> + nrows hex32   matvec point: hw runs weight
        image wid on x8 at x8a and must match these y32 (sim TB skips)
"""
import json
import sys
import numpy as np

import fixedpoint as fp
import layer_ref as LR
import layer_fixed as LF
from w4a8_ref import matvec_y32, pack_ddr_rows, rshift_round as rshr

I64 = np.int64
RS_F, QKV_F, NRM_F, S_F, GAT_F, CW_F = (LF.RS_F, LF.QKV_F, LF.NRM_F,
                                        LF.S_F, LF.GAT_F, LF.CW_F)


def clip16(x):
    return np.clip(np.asarray(x, dtype=I64), -32768, 32767)


def rs_s(v, p):
    """rshr64s: round-half-away right shift; negative p = left shift."""
    v = np.asarray(v, dtype=I64)
    return rshr(v, p) if p >= 0 else v << (-p)


class Mach:
    """Scratchpad model + script emitter. Every emitter applies the exact
    layer_chan semantics to the model."""

    def __init__(self, f):
        self.f = f
        self.mem = np.zeros(16384, dtype=I64)    # int16 view
        self.eout = 0
        self.vnw = np.zeros(1024, dtype=I64)
        self.cos = np.zeros(64, dtype=I64)
        self.sin = np.zeros(64, dtype=I64)
        # Per-slot (banked) layer state — the LAYER CSR selects the bank.
        # dn_slot (0..17) banks the conv + DeltaNet state; kv_slot (0..5)
        # banks the KV cache + TCNT pair. Bank 0 is the reset/back-compat
        # bank, so single-layer scripts (LAYER==0) are byte-identical.
        self.cw = np.zeros((18, LR.CONV_DIM, 4), dtype=I64)
        self.cs = np.zeros((18, LR.CONV_DIM, 3), dtype=I64)
        self.S = np.zeros((18, LR.LNH, LR.LDK, LR.LDV), dtype=I64)
        self.kc = [[[], []] for _ in range(6)]   # per slot: [(x8,e)] per kvh
        self.vc = [[[], []] for _ in range(6)]
        self.T = [[0, 0] for _ in range(6)]      # per slot: TCNT pair per kvh
        self.dn_slot = 0                         # current DN/conv bank
        self.kv_slot = 0                         # current KV/attn bank
        self.ncmd = 0
        self.nw = 0
        self.wids = {}                           # id(qw) -> (wid, qw)
        self.emb = None                          # stage 4 embedding table
        self.am_val = 0                          # AMAX32 running state
        self.am_idx = 0
        self.am_g = 0
        self.am_first = True
        self.audit = None                        # see audit_on()
        # optional callback fn(dn_slot, a[16], dt[16], A[16], decay[16])
        # invoked after every GATE; used by gen_model_script to measure the
        # gate-port clamp error at the real runtime activations.
        self.gate_probe = None
        # ---- SEQ binary-stream emitter (OPT-IN, rung 1) -----------------
        # `self.seq` is None unless SEQ_EMIT is set in the environment, and
        # every hook below is guarded by `if self.seq is not None`, so the
        # DEFAULT .txt output of every generator is byte-identical to the
        # pre-sequencer tree (proved by the regen hashes in the gate log).
        # See ref/seq_format.py (records) and ref/seq_model.py (executor).
        self.seq = None
        self._seq_mute = False
        import os as _os
        if _os.environ.get("SEQ_EMIT"):
            import seq_format as _sq
            self.seq = _sq.maybe_attach(self, f)

    # ---------------- runtime range audit (opt-in, emits nothing) ----------
    # Completes the "deferred, activation-dependent" rows of
    # ref/audit_ranges_report.md section 5.  Every command that writes int16
    # scratch reports how many written words sit AT the int16 rail; a true
    # clip is always a rail hit, so "0 rail hits" proves no saturation
    # anywhere in the run.  DNST additionally reports true |S| > 32767
    # saturations (the layer_fixed.py S_F note) and matvec reports y32
    # occupancy + the DYNQ8 exponents.
    def audit_on(self):
        self.audit = {"rail": {}, "y32": {}, "eout": {}, "s_sat": 0,
                      "s_absmax": 0, "s_writes": 0, "s_where": {},
                      "silu_pre": 0}

    def _aud(self, tag, arr):
        if self.audit is None:
            return
        a = np.asarray(arr, dtype=I64)
        st = self.audit["rail"].setdefault(tag, [0, 0, 0])
        st[0] += int(((a >= 32767) | (a <= -32768)).sum())
        st[1] += int(a.size)
        if a.size:
            st[2] = max(st[2], int(np.abs(a).max()))

    def audit_report(self, out=None):
        """Human-readable audit + hard verdicts. Returns (text, ok)."""
        import io
        a = self.audit
        buf = out or io.StringIO()
        w = buf.write
        w("--- runtime range audit (activation-dependent formats) ---\n")
        w(f"{'site':<14}{'rail hits':>11}{'of words':>12}{'|max|':>9}\n")
        rail_total = 0
        for tag in sorted(a["rail"]):
            n, tot, mx = a["rail"][tag]
            rail_total += n
            w(f"{tag:<14}{n:>11d}{tot:>12d}{mx:>9d}\n")
        w(f"{'TOTAL':<14}{rail_total:>11d}\n")
        w(f"DeltaNet state S_F={S_F} (int16 Q{15 - S_F}.{S_F}, "
          f"+/-{(1 << 15) / (1 << S_F):.1f}): true saturations="
          f"{a['s_sat']} of {a['s_writes']} state writes, "
          f"|S|max={a['s_absmax']} of 32767 "
          f"({100.0 * a['s_absmax'] / 32767:.1f}% of the int16 rail, "
          f"= {a['s_absmax'] / (1 << S_F):.3f} in Q{15 - S_F}.{S_F})\n")
        if a["s_where"]:
            w("  saturating (dn_slot, head): "
              + ", ".join(f"{k}x{v}" for k, v in sorted(a["s_where"].items()))
              + "\n")
        w(f"silu 21-bit port clips: {a['silu_pre']}\n")
        w("y32 accumulator occupancy (int32 = 31 magnitude bits):\n")
        for tag in sorted(a["y32"]):
            mx, n = a["y32"][tag]
            w(f"  {tag:<12} |y32|max={mx:<12d} bits={int(mx).bit_length():>2d}"
              f"  spare={31 - int(mx).bit_length():>2d}  ({n} matvecs)\n")
        w("DYNQ8 activation exponents (e_x histogram): "
          + " ".join(f"{k}:{v}" for k, v in sorted(a["eout"].items())) + "\n")
        ok = (rail_total == 0) and (a["s_sat"] == 0) and (a["silu_pre"] == 0)
        w("RANGE AUDIT: " + ("PASS (no saturation anywhere)\n" if ok else
                             "FAIL — saturation observed, see above\n"))
        return (None if out else buf.getvalue()), ok

    # ---------------- records ----------------
    def _emit16(self, vals):
        self.f.write("".join(f"{int(v) & 0xFFFF:04x}\n" for v in vals))

    def W(self, addr, vals):
        vals = np.asarray(vals, dtype=I64)
        assert np.all(vals >= -32768) and np.all(vals <= 32767), "W range"
        assert addr + len(vals) <= 16384
        self.mem[addr:addr + len(vals)] = vals
        print(f"W {addr:x} {len(vals):x}", file=self.f)
        self._emit16(vals)
        self.nw += len(vals)
        if self.seq is not None and not self._seq_mute:
            self.seq.on_w(addr, vals)

    def W_raw(self, addr, vals):
        """16-bit raw bit patterns (e.g. low halves of 18-bit constants)."""
        vals = np.asarray(vals, dtype=I64) & 0xFFFF
        vals = np.where(vals >= 32768, vals - 65536, vals)
        self.W(addr, vals)

    def W32(self, addr, vals32):
        vals32 = np.asarray(vals32, dtype=I64)
        assert np.all(np.abs(vals32) < (1 << 31)), "y32 overflow"
        w = np.zeros(2 * len(vals32), dtype=I64)
        w[0::2] = vals32 & 0xFFFF
        w[1::2] = (vals32 >> 16) & 0xFFFF
        w = np.where(w >= 32768, w - 65536, w)
        if self.seq is not None:
            # W32 is ONLY ever the matvec y32 injection; in the SEQ stream
            # the engine writes it directly (MVGO + MOVY), so the host W is
            # muted and the following ALU command is fused instead.
            self.seq.on_w32(addr, vals32)
            self._seq_mute = True
        self.W(addr, w)
        self._seq_mute = False

    def pairs(self, addr, n):
        lo = self.mem[addr:addr + 2 * n:2] & 0xFFFF
        hi = self.mem[addr + 1:addr + 2 * n:2] & 0xFFFF
        v = lo | (hi << 16)
        return np.where(v >= (1 << 31), v - (1 << 32), v)

    def set_pairs(self, addr, vals32):
        vals32 = np.asarray(vals32, dtype=I64)
        w = np.zeros(2 * len(vals32), dtype=I64)
        w[0::2] = vals32 & 0xFFFF
        w[1::2] = (vals32 >> 16) & 0xFFFF
        self.mem[addr:addr + 2 * len(vals32)] = np.where(w >= 32768,
                                                         w - 65536, w)

    def R(self, addr, n):
        print(f"R {addr:x} {n:x}", file=self.f)
        self._emit16(self.mem[addr:addr + n])
        if self.seq is not None:
            self.seq.on_r(addr, n)

    def E(self):
        print(f"E {self.eout:x}", file=self.f)

    def Treset(self):
        self.T[self.kv_slot] = [0, 0]
        print("T 0", file=self.f)
        if self.seq is not None:
            self.seq.on_treset()

    def layer(self, dn_slot, kv_slot):
        """Select the banked layer state: dn_slot (0..17) for conv/DeltaNet,
        kv_slot (0..5) for KV cache/TCNT. Emits the LAYER CSR record
        L {21'b0, kv_slot[2:0]<<8, dn_slot[4:0]}."""
        assert 0 <= dn_slot < 18 and 0 <= kv_slot < 6
        self.dn_slot = dn_slot
        self.kv_slot = kv_slot
        print(f"L {(kv_slot << 8) | dn_slot:08x}", file=self.f)
        if self.seq is not None:
            self.seq.on_layer(dn_slot, kv_slot)

    def C(self, op, a0, a1, a2):
        # debug hook: GLS_DUMP_AT=<N> GLS_DUMP_TO=<file.npy> dumps the model
        # scratch after exactly N commands (state at entry of command N+1);
        # pairs with layer_test.py --stop-after/--dump for HW bisection.
        import os as _os
        if (self.ncmd == int(_os.environ.get("GLS_DUMP_AT", "-1"))
                and _os.environ.get("GLS_DUMP_TO")):
            np.save(_os.environ["GLS_DUMP_TO"], self.mem)
        assert 0 <= a0 < (1 << 32) and 0 <= a1 < (1 << 32) and 0 <= a2 < (1 << 32)
        print(f"C {op:x} {a0:x} {a1:x} {a2:x}", file=self.f)
        self.ncmd += 1
        if self.seq is not None:
            self.seq.on_c(op, a0, a1, a2)

    # ---------------- commands (emit + model) ----------------
    def vn(self, mode, n, inf, outf, src, dst):
        nlog2 = int(n).bit_length() - 1
        assert (1 << nlog2) == n
        self.C(1, mode | (nlog2 << 2) | (inf << 6) | (outf << 10),
               src | (dst << 14), 0)
        x = self.mem[src:src + n]
        if mode == 0:
            y = LF.rmsnorm_fx(x, self.vnw[:n], inf, True)
        elif mode == 1:
            y = LF.rmsnorm_fx(x, self.vnw[:n], inf, False)
        else:
            y = LF.l2norm_fx(x, inf, outf)
        self.mem[dst:dst + n] = np.asarray(y, dtype=I64)
        self._aud(f"vn{mode}", y)

    def vnw_(self, src, n):
        self.C(2, n, src, 0)
        self.vnw[:n] = self.mem[src:src + n]

    def ropet(self, src):
        self.C(3, 0, src, 0)
        self.cos = self.mem[src:src + 64].copy()
        self.sin = self.mem[src + 64:src + 128].copy()

    def rope(self, src, dst):
        self.C(4, 0, src | (dst << 14), 0)
        self.mem[dst:dst + 256] = LF.rope_fx(self.mem[src:src + 256],
                                             self.cos, self.sin)

    def convw(self, first, nch, src):
        self.C(5, 0 | (first << 2) | (nch << 15), src, 0)
        self.cw[self.dn_slot][first:first + nch] = \
            self.mem[src:src + 4 * nch].reshape(nch, 4)

    def convz(self, first, nch):
        self.C(5, 2 | (first << 2) | (nch << 15), 0, 0)
        self.cs[self.dn_slot][first:first + nch] = 0

    def conv(self, first, nch, src, dst):
        self.C(6, first | (nch << 13), src | (dst << 14), 0)
        x = self.mem[src:src + nch]
        cs = self.cs[self.dn_slot]
        win = np.concatenate([cs[first:first + nch], x[:, None]], axis=1)
        cs[first:first + nch] = win[:, 1:]
        acc = (win * self.cw[self.dn_slot][first:first + nch]).sum(axis=1)
        pre_raw = rshr(acc, RS_F + CW_F - 12)
        pre = np.clip(pre_raw, -(1 << 20), (1 << 20) - 1)
        if self.audit is not None:
            self.audit["silu_pre"] += int((pre_raw != pre).sum())
        self.mem[dst:dst + nch] = clip16(
            np.array([fp.silu_q(int(v)) for v in pre], dtype=I64))
        self._aud("conv", self.mem[dst:dst + nch])

    def gate(self, src_b, src_a, src_A, src_dt, dst):
        self.C(7, dst, src_b | (src_a << 14), src_A | (src_dt << 14))
        b = self.mem[src_b:src_b + 16]
        a = self.mem[src_a:src_a + 16]
        Alo = self.mem[src_A:src_A + 32:2] & 0xFFFF
        Ahi = self.mem[src_A + 1:src_A + 32:2] & 0x3
        A = Alo | (Ahi << 16)
        dt = self.mem[src_dt:src_dt + 16]
        for h in range(16):
            self.mem[dst + h] = fp.sigmoid_q(int(b[h]))
            sp = fp.softplus_q(int(a[h] + dt[h]))
            g = -rshr(I64(int(A[h])) * sp, 11)
            self.mem[dst + 16 + h] = min(
                rshr(I64(fp.exp_neg_q(int(min(g, 0)))), 15), I64(32767))
        if self.gate_probe is not None:
            self.gate_probe(self.dn_slot, a, dt, A,
                            self.mem[dst + 16:dst + 32])
        # beta/decay are Q15 gates: 32767 is their legal top rail, not a
        # clip, so they are audited separately from the int16 transports.
        if self.audit is not None:
            self.audit["rail"].setdefault("gate(Q15)", [0, 0, 0])
            self.audit["rail"]["gate(Q15)"][1] += 32
            self.audit["rail"]["gate(Q15)"][2] = max(
                self.audit["rail"]["gate(Q15)"][2],
                int(np.abs(self.mem[dst:dst + 32]).max()))

    def dnst(self, head, src_q, src_k, src_v, a_dec, a_beta, dst):
        self.C(8, head | (a_dec << 4) | (a_beta << 18),
               src_q | (src_k << 14), src_v | (dst << 14))
        dec = int(self.mem[a_dec])
        bet = int(self.mem[a_beta])
        q = self.mem[src_q:src_q + 128]
        k = self.mem[src_k:src_k + 128]
        v = self.mem[src_v:src_v + 128] << (S_F - QKV_F)
        Sh = rshr(self.S[self.dn_slot][head] * dec, GAT_F)
        kvm = rshr((Sh * k[:, None]).sum(axis=0), NRM_F)
        dlt = rshr((v - kvm) * bet, GAT_F)
        Sr = Sh + rshr(k[:, None] * dlt[None, :], NRM_F)
        Sh = clip16(Sr)
        if self.audit is not None:
            nsat = int((np.abs(Sr) > 32767).sum())
            self.audit["s_sat"] += nsat
            self.audit["s_writes"] += int(Sr.size)
            self.audit["s_absmax"] = max(self.audit["s_absmax"],
                                         int(np.abs(Sr).max()))
            if nsat:
                k = (self.dn_slot, head)
                self.audit["s_where"][k] = self.audit["s_where"].get(k, 0) + nsat
        o = rshr((Sh * q[:, None]).sum(axis=0), NRM_F)
        self.S[self.dn_slot][head] = Sh
        self.set_pairs(dst, o)

    def kvap(self, kvh, src_k, src_v, expbias=QKV_F):
        self.C(9, kvh | (expbias << 4), src_k | (src_v << 14), 0)
        k8, ke = fp.dyn_quant_i8(self.mem[src_k:src_k + 256])
        v8, ve = fp.dyn_quant_i8(self.mem[src_v:src_v + 256])
        self.kc[self.kv_slot][kvh].append((k8.astype(I64), ke - expbias))
        self.vc[self.kv_slot][kvh].append((v8.astype(I64), ve - expbias))
        self.T[self.kv_slot][kvh] += 1

    def _attn_acc(self, kvh, qn):
        """The ATTN command's numeric core: score -> softmax -> P*V.

        Pure: reads the KV cache and TCNT of the current kv_slot, mutates
        nothing.  Split out of attn() so attn_token can PEEK every head's
        output before emitting the first command (the gated-output
        block-float shift k_a is shared by the whole token, so it is not
        known until all heads have been evaluated — see attn_token)."""
        T = self.T[self.kv_slot][kvh]
        SC = int(round((1 << 15) / np.sqrt(LR.HD)))
        sc = np.zeros(T, dtype=I64)
        for t in range(T):
            k8, ke = self.kc[self.kv_slot][kvh][t]
            dot = int((qn * k8).sum())
            s_ = rshr(I64(dot) * SC, 15)
            f = QKV_F - ke - 16
            sc[t] = rshr(I64(int(s_)), f) if f >= 0 else int(s_) << (-f)
        mx = int(sc.max())
        es = np.array([fp.exp_neg_q(int(min(int(sc[t]) - mx, 0)))
                       for t in range(T)], dtype=I64)
        r, re = fp.recip_q(int(es.sum()), 30)
        p = np.clip(rshr(es * r, 30 - re + 15), 0, 1 << 15)
        acc = np.zeros(LR.HD, dtype=I64)
        for t in range(T):
            v8, ve = self.vc[self.kv_slot][kvh][t]
            term = I64(int(p[t])) * v8
            sh = 15 - ve - QKV_F
            acc += rshr(term, sh) if sh >= 0 else term << (-sh)
        return acc

    def attn(self, kvh, src_q, dst):
        self.C(10, kvh, src_q | (dst << 14), 0)
        self.set_pairs(dst, self._attn_acc(kvh, self.mem[src_q:src_q + 256]))

    def attn_peek(self, kvh, src_q):
        """_attn_acc at a scratch address, emitting nothing."""
        return self._attn_acc(kvh, self.mem[src_q:src_q + 256])

    def sigm_peek(self, n, p0, srca):
        """ALU op 7 (SIGM16) evaluated without emitting."""
        x = rs_s(self.mem[srca:srca + n], p0)
        return np.array([fp.sigmoid_q(int(v)) for v in x], dtype=I64)

    def alu(self, op, n, p0, srca, srcb, dst):
        self.C(11, op | (n << 4), srca | (srcb << 14),
               (p0 & 0x1FFFF) | (dst << 17))
        a = self.mem[srca:srca + n]
        b = self.mem[srcb:srcb + n]
        if op == 0:                                  # DYNQ8
            y, e = fp.dyn_quant_i8(a)
            self.mem[dst:dst + n] = y
            self.eout = e
            if self.audit is not None:
                self.audit["eout"][e] = self.audit["eout"].get(e, 0) + 1
        elif op == 1:                                # SHIFT32
            self.mem[dst:dst + n] = clip16(rs_s(self.pairs(srca, n), p0))
        elif op == 2:                                # SCALE
            self.mem[dst:dst + n] = clip16(rshr(a * p0, 15))
        elif op == 3:                                # EMUL
            self.mem[dst:dst + n] = clip16(rshr(a * b, p0))
        elif op == 4:                                # ADD
            self.mem[dst:dst + n] = clip16(a + b)
        elif op == 5:                                # SILU16
            x = rs_s(a, p0)
            self.mem[dst:dst + n] = clip16(
                np.array([fp.silu_q(int(v)) for v in x], dtype=I64))
        elif op == 6:                                # SILU32
            x = np.clip(rs_s(self.pairs(srca, n), p0),
                        -(1 << 20), (1 << 20) - 1)
            self.mem[dst:dst + n] = clip16(
                np.array([fp.silu_q(int(v)) for v in x], dtype=I64))
        elif op == 7:                                # SIGM16
            x = rs_s(a, p0)
            self.mem[dst:dst + n] = np.array(
                [fp.sigmoid_q(int(v)) for v in x], dtype=I64)
        elif op == 8:                                # EMUL32
            self.mem[dst:dst + n] = clip16(rshr(self.pairs(srca, n) * b, p0))
        elif op == 9:                                # SHIFT32W
            y = np.clip(rs_s(self.pairs(srca, n), p0),
                        -(1 << 31), (1 << 31) - 1)
            self.set_pairs(dst, y)
        elif op == 10:                               # AMAX32 (running)
            v = self.pairs(srca, n)
            if p0 & 1:
                self.am_g, self.am_first = 0, True
            for e in v:
                if self.am_first or int(e) > self.am_val:
                    self.am_val, self.am_idx = int(e), self.am_g
                    self.am_first = False
                self.am_first = False
                self.am_g += 1
        else:
            raise ValueError(op)
        # int8/int16 writers: audit the words just written (op 9 writes
        # int32 pairs, op 10 writes nothing, op 0 writes int8 by construction)
        if self.audit is not None and op not in (0, 9, 10):
            self._aud(f"alu{op}", self.mem[dst:dst + n])

    def dnz(self, head):
        self.C(12, head, 0, 0)
        self.S[self.dn_slot][head] = 0

    # ---------------- stage 4: embedding + argmax ----------------
    def embed(self, tokid, dst, n):
        """M record: executor looks up row tokid of the embedding table
        (TB: from <prefix>.emb.bin; HW: c2h read from board DDR) and
        writes n words at dst. Model mirrors from self.emb."""
        print(f"M {tokid:x} {dst:x} {n:x}", file=self.f)
        self.mem[dst:dst + n] = self.emb[tokid][:n]
        self._aud("embed", self.mem[dst:dst + n])
        if self.seq is not None:
            self.seq.on_embed(tokid, dst, n)

    def amax(self, n, src, fresh):
        """ALU op 10 AMAX32 over n {lo,hi} pairs at src; fresh resets the
        running scan. Strictly-greater update -> first max wins."""
        self.alu(10, n, 1 if fresh else 0, src, 0, 0)

    def A(self):
        """Assert the AMAXI/AMAXV CSRs against the model's running scan."""
        print(f"A {self.am_idx:x} {int(self.am_val) & 0xFFFFFFFF:x}",
              file=self.f)
        self.nchk_a = getattr(self, "nchk_a", 0) + 1
        if self.seq is not None:
            self.seq.on_amaxl(self.am_idx, self.am_val)

    # ---------------- host matvec round-trip ----------------
    def matvec(self, qw, x8_addr, n_in, rowchunk=None):
        """Assert the on-chip x8/EOUT, then compute raw y32 host-side
        from those asserted values. Caller stages + dequants. Emits a V
        record so the hardware host can run the REAL matvec engine on
        weight image wid and verify it reproduces these y32.

        rowchunk: evaluate matvec_y32 in row blocks (matvec_y32 is exactly
        row-separable, so this is bit-identical) — needed for the full-vocab
        LM head, whose one-shot int64 temporary is 2 GiB."""
        k = id(qw)
        if k not in self.wids:
            self.wids[k] = (len(self.wids), qw)
        wid = self.wids[k][0]
        self.R(x8_addr, n_in)                      # assert on-chip x8
        self.E()                                   # assert on-chip e_x
        x8 = np.asarray(self.mem[x8_addr:x8_addr + n_in]).astype(np.int8)
        nrows = qw["w4"].shape[0]
        g = int(qw.get("g", 128))          # v2 group size (absent == 128)
        if rowchunk is None or rowchunk >= nrows:
            y32 = np.asarray(matvec_y32(qw["w4"], qw["m"], qw["sh"], x8, g=g),
                             dtype=I64)
        else:
            parts = []
            for r0 in range(0, nrows, rowchunk):
                r1 = min(r0 + rowchunk, nrows)
                parts.append(np.asarray(
                    matvec_y32(qw["w4"][r0:r1], qw["m"][r0:r1], qw["sh"], x8,
                               g=g),
                    dtype=I64))
            y32 = np.concatenate(parts)
        print(f"V {wid:x} {x8_addr:x} {n_in:x} {len(y32):x}", file=self.f)
        self.f.write("".join(f"{int(v) & 0xFFFFFFFF:08x}\n" for v in y32))
        if self.seq is not None:
            self.seq.on_matvec(wid, qw, x8_addr, n_in, y32)
        if self.audit is not None:
            tag = f"{nrows}x{qw['w4'].shape[1]}"
            st = self.audit["y32"].setdefault(tag, [0, 0])
            st[0] = max(st[0], int(np.abs(y32).max()))
            st[1] += 1
        return y32, self.eout

    def dump_weights(self, prefix):
        """Pack each registered matrix's DDR image + manifest.

        Manifest fields (per wid) — the host tools derive EVERYTHING from
        these, so the v2 group size travels with the image:
          nrows/k     matrix shape
          ng          WEIGHT-beat count = K//128, in BOTH group modes (this
                      is the SHAPE CSR ng field; its meaning did not change)
          nbeats      total 64B beats of the whole image = nrows*stride/64,
                      i.e. it already includes the extra g=64 scale beat
          stride      row stride in bytes (w4a8_ref.row_stride)
          g           group size — EMITTED ONLY WHEN != 128, so every g=128
                      manifest stays byte-identical to the pre-v2 tree.
                      Consumers must read it as `int(m.get("g", 128))`.
        """
        man = {}
        for wid, qw in sorted(self.wids.values(), key=lambda t: t[0]):
            g = int(qw.get("g", 128))
            img, stride = pack_ddr_rows(qw["w4"], qw["m"], g=g)
            fn = f"{prefix}_w{wid}.bin"
            with open(fn, "wb") as wf:
                wf.write(img)
            nrows, K = qw["w4"].shape
            man[wid] = {"file": fn.split("/")[-1], "nrows": nrows, "k": K,
                        "ng": K // 128, "sh": qw["sh"], "e": qw["e"],
                        "nbeats": len(img) // 64, "stride": stride}
            if g != 128:
                man[wid]["g"] = g
        with open(f"{prefix}.weights.json", "w") as jf:
            json.dump(man, jf, indent=1)
        return len(man)

    def shift_for(self, qw, e_x, in_f, out_f):
        return (15 - qw["e"] - qw["sh"]) - e_x + in_f - out_f

    def inject_dequant(self, y32, p0, stage, dst, op=1):
        """W32 + SHIFT32(op1)/SHIFT32W(op9)/SILU32(op6) in <=2048 chunks."""
        n = len(y32)
        c = 0
        while c < n:
            m = min(2048, n - c)
            self.W32(stage, y32[c:c + m])
            if op == 9:
                self.alu(9, m, p0, stage, 0, dst + 2 * c)
            else:
                self.alu(op, m, p0, stage, 0, dst + c)
            c += m


# ----------------------------------------------------------------------
# region maps
# ----------------------------------------------------------------------
X0, XN, X8 = 0, 1024, 2048
STG = 4096                       # 4096-word staging window (4096..8191)


def dn_token(M, qd, ln1, ln2, qm, gold_x):
    QKV = 8192                   # qkv16/qkv8 (6144) 8192..14335
    Z16 = 14336                  # z (2048) 14336..16383
    B16, A16, GD = 3072, 3104, 3136
    QN, QNS, KN = 3168, 3296, 3424
    DO32, OH, NH = 3552, 3808, 3936   # NH ends 4064 < STG
    ZG = QN                      # reuse (q path done before z path)

    # ln1 norm
    M.W(STG, ln1)
    M.vnw_(STG, 1024)
    M.vn(0, 1024, RS_F, RS_F, X0, XN)
    M.alu(0, 1024, 0, XN, 0, X8)
    # 4 matvecs off xn
    y, ex = M.matvec(qd["in_qkv"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qd["in_qkv"], ex, RS_F, RS_F), STG, QKV)
    y, _ = M.matvec(qd["in_z"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qd["in_z"], ex, RS_F, QKV_F), STG, Z16)
    y, _ = M.matvec(qd["in_b"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qd["in_b"], ex, RS_F, 12), STG, B16)
    y, _ = M.matvec(qd["in_a"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qd["in_a"], ex, RS_F, 12), STG, A16)
    # conv + silu + requant to QKV_F (in place)
    M.conv(0, LR.CONV_DIM, QKV, QKV)
    for c in range(0, LR.CONV_DIM, 2048):
        M.alu(2, 2048, 1 << (15 - (12 - QKV_F)), QKV + c, 0, QKV + c)
    M.R(QKV, 256)
    # gates (A/dt staged each token; cheap and keeps staging free)
    M.W_raw(STG, np.stack([qd["A_q15"] & 0xFFFF, qd["A_q15"] >> 16],
                          axis=1).reshape(-1))
    M.W(STG + 32, qd["dt_bias_q12"])
    M.gate(B16, A16, STG, STG + 32, GD)
    M.R(GD, 32)
    # per-head recurrence.  norm_w stays RESIDENT in scratch at NW: the
    # gated RMSNorm is an op-3 EMUL against it now, not a vecnorm, so no
    # vnw_ load is needed (and none must be emitted — vnw still holds ln1,
    # which nothing between here and mlp_block reads).
    NW = STG + 64
    M.W(NW, qd["norm_w_q14"])
    INVQ = int(round((1 << 15) / np.sqrt(LR.LDK)))
    ON = 1024                    # gated outputs (2048) overwrite XN/X8
    for h in range(LR.LNH):
        q_src = QKV + h * 128
        k_src = QKV + 2048 + h * 128
        v_src = QKV + 4096 + h * 128
        M.vn(2, 128, QKV_F, NRM_F, q_src, QN)
        M.alu(2, 128, INVQ, QN, 0, QNS)
        M.vn(2, 128, QKV_F, NRM_F, k_src, KN)
        M.dnst(h, QNS, KN, v_src, GD + 16 + h, GD + h, DO32)
        # int32 -> int16 block float + script-side gated RMSNorm
        # (layer_fixed: dn_o_shift / dn_norm_scale / script_norm_fx).
        # Both immediates are computed from the o32 the DNST command just
        # produced in the MODEL, which is bit-identical to what dn_step
        # wrote into the on-chip scratch — so script and hardware agree by
        # construction, exactly like every other immediate here.
        o32 = M.pairs(DO32, 128)
        k_h = LF.dn_o_shift(o32, note=False)          # op 1 p0, signed
        m_q15 = LF.dn_norm_scale(o32, k_h, note=False)
        # dn_norm_scale already clips to the positive cfg_p0 range and
        # counts the clips (LF.BF_CLIP, reported by gen_model_script); this
        # is the belt-and-braces field check on the emitted immediate.
        assert 0 <= m_q15 <= LF.M_Q15_MAX, \
            f"SCALE immediate {m_q15} out of range"
        # SEQ hint (opt-in, emits nothing): the next two ALU commands are
        # the DeltaNet block-float pair, which the sequencer expresses as
        # DYNQ16 (+ EPS-NORM in the epsnorm profile).  See ref/seq_format.py.
        if M.seq is not None:
            M.seq.dn_bf(k_h, m_q15, 128, DO32, OH)
        M.alu(1, 128, k_h, DO32, 0, OH)               # SHIFT32
        M.alu(2, 128, m_q15, OH, 0, OH)               # SCALE   >>15
        M.alu(3, 128, 14, OH, NW, NH)                 # EMUL norm_w >>14
        M.alu(5, 128, QKV_F - 12, Z16 + h * 128, 0, ZG)
        M.alu(3, 128, 12, NH, ZG, ON + h * 128)
    M.R(ON, 256)
    # out projection + residual
    M.alu(0, 2048, 0, ON, 0, STG)
    y, ex = M.matvec(qd["out"], STG, 2048)
    M.inject_dequant(y, M.shift_for(qd["out"], ex, LF.DN_NORM_F, RS_F),
                     STG + 2048, 6144 + 2048)
    M.alu(4, 1024, 0, X0, 6144 + 2048, X0)
    mlp_block(M, ln2, qm)
    M.R(X0, 1024)
    assert np.array_equal(M.mem[X0:X0 + 1024], gold_x), "dn token mismatch"


def attn_token(M, qa, ln1, ln2, qm, pos, gold_x):
    QG = 8192                    # q_proj out (4096) 8192..12287
    K16, V16 = 12288, 12800
    QR, KR = 13312, 15360        # roped q (2048), roped k (512)
    AO32, OG, GATED = STG, STG + 512, STG + 768   # in staging

    M.W(STG, ln1)
    M.vnw_(STG, 1024)
    M.vn(0, 1024, RS_F, RS_F, X0, XN)
    M.alu(0, 1024, 0, XN, 0, X8)
    y, ex = M.matvec(qa["q_proj"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qa["q_proj"], ex, RS_F, QKV_F), STG, QG)
    y, _ = M.matvec(qa["k_proj"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qa["k_proj"], ex, RS_F, QKV_F), STG, K16)
    y, _ = M.matvec(qa["v_proj"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qa["v_proj"], ex, RS_F, QKV_F), STG, V16)
    # rope tables for this position
    cq, sq = LF.rope_tables_q15(pos)
    # SEQ hint (opt-in, emits nothing): the ONLY position-dependent constant
    # in the whole token body.  The emitter stores it in a strided DDR region
    # so the load can be XRF[4]-indexed and the decode loop can close.
    if M.seq is not None:
        M.seq.pos_hint = pos
    M.W(STG, np.concatenate([cq, sq]))
    M.ropet(STG)
    # q heads: rmsnorm(q_norm) + rope
    M.W(STG + 128, qa["q_norm"])
    M.vnw_(STG + 128, 256)
    for h in range(LR.NQ):
        M.vn(0, 256, QKV_F, QKV_F, QG + h * 512, STG + 384)
        M.rope(STG + 384, QR + h * 256)
    M.W(STG + 128, qa["k_norm"])
    M.vnw_(STG + 128, 256)
    for h in range(LR.NKV):
        M.vn(0, 256, QKV_F, QKV_F, K16 + h * 256, STG + 384)
        M.rope(STG + 384, KR + h * 256)
    for kv in range(LR.NKV):
        M.kvap(kv, KR + kv * 256, V16 + kv * 256)
    group = LR.NQ // LR.NKV
    # The gated attention output uses ONE block-float shift for the whole
    # token (layer_fixed.attn_o_shift: the heads are concatenated into the
    # o_proj matvec, so a per-head shift would reweight them).  k_a is not
    # known until every head has been evaluated, so PEEK all of them first
    # — attn_peek/sigm_peek mutate nothing and emit nothing, and the loop
    # below then recomputes the identical values through the real commands.
    amax = 0
    for h in range(LR.NQ):
        prod = (M.attn_peek(h // group, QR + h * 256)
                * M.sigm_peek(256, QKV_F - 12, QG + h * 512 + 256))
        amax = max(amax, int(np.abs(prod).max()))
    k_a = LF.attn_o_shift(amax, note=False)           # op 8 p0, unsigned
    # SEQ hint (opt-in, emits nothing): k_a WAS the one remaining
    # data-dependent command immediate the ISA had no XRF answer for
    # (docs SEQ_ISA A3 / seq_format.py).  With ISA v1.3 the emitter buffers
    # the 3*NQ commands below and re-emits them as the op-8 probe double
    # pass, so it needs the head count too.  Emits nothing on the .txt path.
    if M.seq is not None:
        M.seq.attn_bf(k_a, nq=LR.NQ)
    for h in range(LR.NQ):
        M.attn(h // group, QR + h * 256, AO32)
        M.alu(7, 256, QKV_F - 12, QG + h * 512 + 256, 0, OG)
        M.alu(8, 256, k_a, AO32, OG, GATED + h * 256)
    M.R(GATED, 256)
    M.alu(0, 2048, 0, GATED, 0, STG + 2880)
    y, ex = M.matvec(qa["o_proj"], STG + 2880, 2048)
    # k_a moved the gated vector's binary point; the o_proj requant shift
    # absorbs it exactly (dyn_quant_i8 is power-of-two invariant).
    M.inject_dequant(y, M.shift_for(qa["o_proj"], ex,
                                    QKV_F + GAT_F - k_a, RS_F),
                     9216, 12288)
    M.alu(4, 1024, 0, X0, 12288, X0)
    mlp_block(M, ln2, qm)
    M.R(X0, 1024)
    assert np.array_equal(M.mem[X0:X0 + 1024], gold_x), "attn token mismatch"


def mlp_block(M, ln2, qm):
    GP = 4096                    # gate/up y32 pairs (7168) 4096..11263
    SG = 11264                   # silu(gate) (3584) 11264..14847
    M.W(STG, ln2)
    M.vnw_(STG, 1024)
    M.vn(0, 1024, RS_F, RS_F, X0, XN)
    M.alu(0, 1024, 0, XN, 0, X8)
    y, ex = M.matvec(qm["gate"], X8, 1024)
    M.inject_dequant(y, M.shift_for(qm["gate"], ex, RS_F, 12), GP, SG, op=6)
    y, _ = M.matvec(qm["up"], X8, 1024)
    # u kept 32-bit: SHIFT32W in place, then EMUL32 in place
    p0 = M.shift_for(qm["up"], ex, RS_F, RS_F)
    M.W32(GP, y[:2048])
    M.alu(9, 2048, p0, GP, 0, GP)
    M.W32(GP + 4096, y[2048:])
    M.alu(9, 1536, p0, GP + 4096, 0, GP + 4096)
    M.alu(8, 2048, 12, GP, SG, GP)
    M.alu(8, 1536, 12, GP + 4096, SG + 2048, GP + 2048)
    M.R(GP, 128)
    M.alu(0, 3584, 0, GP, 0, GP + 3584)
    y, ex = M.matvec(qm["down"], GP + 3584, 3584)
    M.inject_dequant(y, M.shift_for(qm["down"], ex, RS_F, RS_F),
                     11264, 13312)
    M.alu(4, 1024, 0, X0, 13312, X0)


def main():
    outfile, seed = sys.argv[1], int(sys.argv[2])
    ntok = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    rng = np.random.default_rng(seed)

    with open(outfile, "w") as f:
        M = Mach(f)

        # ---------- DeltaNet layer ----------
        wf = LR.init_layer_weights(rng, "linear_attention")
        qw = LF.quant_layer(wf)
        cache = LF.new_cache_fx("linear_attention")
        x = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)

        qd = qw["dn"]
        # stage conv weights through scratch (3 chunks x 2048 channels)
        for c in range(0, LR.CONV_DIM, 2048):
            M.W(STG, qd["conv_w"][c:c + 2048].reshape(-1))
            M.convw(c, 2048, STG)
        M.convz(0, LR.CONV_DIM)
        for h in range(LR.LNH):
            M.dnz(h)
        M.W(X0, x)
        for t in range(ntok):
            gold = LF.layer_decode_fx(x, qw, cache, t)
            dn_token(M, qd, qw["ln1"], qw["ln2"], qw["mlp"], gold)
            x = gold

        # ---------- full-attention layer ----------
        wf = LR.init_layer_weights(rng, "full_attention")
        qw = LF.quant_layer(wf)
        cache = LF.new_cache_fx("full_attention")
        x = np.round(rng.normal(0, 1, LR.H) * (1 << RS_F)).astype(I64)

        M.Treset()
        M.kc[0] = [[], []]
        M.vc[0] = [[], []]
        M.W(X0, x)
        for t in range(ntok):
            gold = LF.layer_decode_fx(x, qw, cache, t)
            attn_token(M, qw["attn"], qw["ln1"], qw["ln2"], qw["mlp"],
                       t, gold)
            x = gold

        print("Q", file=f)

    prefix = outfile.rsplit(".", 1)[0]
    nW = M.dump_weights(prefix)
    print(f"layer script: seed={seed} ntok={ntok} cmds={M.ncmd} "
          f"hostwords={M.nw} weights={nW} -> {outfile}")


if __name__ == "__main__":
    main()
