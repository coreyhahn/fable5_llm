#!/usr/bin/env python3
"""ov_census.py — Task OV1: the dependency census of the shipped 9B schedule.

    FABLE5_MODEL=9b python evidence/qwen9b/ov/ov_census.py <mode> [opts]

    modes:  dump LO HI      decoded records LO..HI (static pc) of the loop
                            body with their read/write sets and token-4 window
            census          D1: the fence census (per fence + tables)
            sched           D2/D3: the list-schedule variants + sensitivities
            all             census + sched

READ-ONLY over every input.  It opens
  * the shipped stream  tb/scripts/w9/model_9b_s1.e4.seq (sha256 checked
    against the manifest's stream_sha256, exactly as SD1 did:
    evidence/qwen9b/sd/sd1_common.py);
  * BN1's per-record timeline CSV evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv
    (UNTRACKED by design; its sha256 is checked against the committed
    evidence/qwen9b/bn/bn_timeline_model_9b_s1.csv.sha256 before a row is
    read);
and writes stdout only.  Nothing under rtl/ ref/ tb/ is modified, nothing is
simulated: the "schedule" below is arithmetic over measured per-record
windows, not an execution of any model or testbench.

THE READ/WRITE-SET MODEL (the modelling choice that matters most) is the
table in rw_sets() below; every row cites the ISA / emitter / reference line
that defines the extent, and rows marked INFERRED are the ones no source
states directly.  OV1_DEPENDENCY_CENSUS.md §2 carries the same table.
"""
import argparse
import bisect
import collections
import hashlib
import heapq
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "evidence", "qwen9b", "sd"))

import sd1_common as C            # noqa: E402  (SD1's decoder path, reused)

SF, GLS, LR = C.SF, C.GLS, C.LR

CSV = os.path.join(REPO, "evidence", "qwen9b", "bn",
                   "bn_timeline_model_9b_s1.csv")
CSV_SHA = CSV + ".sha256"
ACLK_HZ = 250_000_000.0
TB_MS = 131.138          # BN_CENSUS.md §3 (S)
BOARD_MS = 137.121       # BN_CENSUS.md §0 / RD9 §10.1 (S)
SCR_N = 65536

CLS = ["L_CMP", "L_DMA", "MOVER", "SEQBULK",
       "MV0_STR", "MV1_STR", "MV2_STR", "MV3_STR",
       "MV0_BSY", "MV1_BSY", "MV2_BSY", "MV3_BSY",
       "SMEM_RD", "SMEM_WR", "RECDDR", "BFAB"]
BSY0 = CLS.index("MV0_BSY")

OPN = {1: "CSRWR", 2: "CMD", 3: "MOVX", 4: "MOVY", 5: "MVGO", 6: "EMB",
       7: "AMAXL", 8: "JMP", 9: "FENCE", 10: "HALT", 11: "LDC", 12: "XOP"}
CHAIN_OPS = {SF.OP_CSRWR, SF.OP_CMD, SF.EXT_XOP, SF.OP_AMAXL, SF.OP_JMP}

# per-layer matvec order, from the emitter (ref/gen_layer_script.py:1945-1951,
# 2047, 2068-2072, 2154, 2174-2188) with the row counts the manifest gives
DN_SEQ = [("in_qkv", 8192), ("in_z", 4096), ("in_b", 32), ("in_a", 32),
          ("dn_out", 4096), ("mlp_gate", 12288), ("mlp_up", 12288),
          ("mlp_down", 4096)]
GQA_SEQ = [("q_proj", 8192), ("k_proj", 1024), ("v_proj", 1024),
           ("o_proj", 4096), ("mlp_gate", 12288), ("mlp_up", 12288),
           ("mlp_down", 4096)]


def ms(c):
    return c / ACLK_HZ * 1e3


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


# ======================================================================
# inputs
# ======================================================================
def load_stream():
    recs = C.seq_records()
    got = sha256(C.SEQ)
    with open(C.SEQJSON) as f:
        man = json.load(f)
    want = man["stream_sha256"]
    print(f"=== stream {C.SEQ}")
    print(f"    sha256 {got}  manifest {want}  "
          f"{'MATCH' if got == want else 'MISMATCH'}")
    assert got == want, "stream sha mismatch"
    return recs, man


def load_csv(toks=(4, 5, 6)):
    want = open(CSV_SHA).read().split()[0]
    got = sha256(CSV)
    print(f"=== timeline {CSV}")
    print(f"    sha256 {got}  committed {want}  "
          f"{'MATCH' if got == want else 'MISMATCH'}")
    assert got == want, "CSV sha mismatch"
    rows = {t: {} for t in toks}
    nr = 0
    with open(CSV) as f:
        for line in f:
            if not line.startswith("R,"):
                continue
            p = line.rstrip("\n").split(",")
            if len(p) != 32:
                continue
            nr += 1
            tok = int(p[2])
            if tok not in rows:
                continue
            pc = int(p[3])
            assert pc not in rows[tok], f"pc {pc} twice in token {tok}"
            rows[tok][pc] = (int(p[4]), int(p[8]), int(p[9]),
                             [int(x) for x in p[10:26]])
    print(f"    R rows read {nr}; kept tokens {toks}: "
          + ", ".join(f"tok{t}={len(rows[t])}" for t in toks))
    return rows


def body_range(recs):
    embs = [i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB]
    jmps = [i for i, r in enumerate(recs)
            if r.opcode == SF.OP_JMP and (r.flags & 1)]
    lo = embs[-1]
    assert len(jmps) == 1 and recs[jmps[0]].imm32 == lo, (jmps, lo)
    hi = jmps[0]
    print(f"=== loop body: static pc {lo}..{hi} ({hi - lo + 1} records); "
          f"EMB records at {embs}; JMP(flags 1) at {hi} -> {lo}")
    return lo, hi


# ======================================================================
# the READ/WRITE-SET MODEL
# ======================================================================
# Scratch extents are in 16-bit scratch WORDS (layer_chan scratch, 65536
# words; docs/SEQ_ISA.md:1142-1151).  "pairs" = an int32 stored as {lo,hi}
# in two words (ref/gen_layer_script.py:681-693).
#
#  op                reads                           writes                  source
#  VN / EPS-NORM     [src, src+n)  (+XRF[k] if EPS)  [dst, dst+n)            gen_layer_script.py:916-929; seq_model.py:628-642
#  VNW               [src, src+n)                    (vecnorm wbuf, internal) gen_layer_script.py:955-967
#  ROPET             [src, src+2*ROT)                (rope table, internal)   gen_layer_script.py:969-972
#  ROPE              [src, src+HD)                   [dst, dst+HD)           gen_layer_script.py:974-977
#  CONVW sel2        —                               (conv state, internal)  gen_layer_script.py:1024-1030
#  CONV              [src, src+nch)                  [dst, dst+nch)          gen_layer_script.py:1032-1047
#  GATE              b,a,dt [.,+LNH); A [.,+2LNH)    [dst, dst+2LNH)         gen_layer_script.py:1077-1100
#  DNST              q,k [.,+LDK); v [.,+LDV);       [dst, dst+2LDV) pairs   gen_layer_script.py:1195-1246; SEQ_ISA.md:1078-1087
#                    beta=DNSB.lo+h, dec=DNSB.hi+h
#  KVAP              k,v [.,+HD)                     (KV slot, internal)     gen_layer_script.py:1248-1264
#  ATTN              [src_q, +HD)                    [dst, dst+2HD) pairs    gen_layer_script.py:1341-1350
#  DNZ / SLD / SST   —                               (state slots, internal) SEQ_ISA.md:1262-1284
#  ALU sub 0 DYNQ8   a[n]                            dst[n], XRF[0]          gen_layer_script.py:1389-1395; SEQ_ISA.md:462-466
#      1 SHIFT32     pairs a[2n]                     dst[n]                  gen_layer_script.py:1397-1398
#      2 SCALE,5,7   a[n]                            dst[n]                  gen_layer_script.py:1399-1417
#      3 EMUL, 4 ADD a[n], b[n]                      dst[n]                  gen_layer_script.py:1401-1404
#      6 SILU32      pairs a[2n]                     dst[n]                  gen_layer_script.py:1409-1413
#      8 EMUL32      pairs a[2n], b[n]               dst[n] (+XRF[2] probe)  gen_layer_script.py:1418-1419; seq_model.py:739-752
#      9 SHIFT32W    pairs a[2n]                     pairs dst[2n]           gen_layer_script.py:1420-1423
#     10 AMAX32      pairs a[2n]                     (AMAX/TOPK, internal)   gen_layer_script.py:1424-1433
#     12 DYNQ16      pairs a[2n]                     dst[n], XRF[1|2]        seq_model.py:733-738
#  MOVX c            scratch [addr, addr+len)        XWIN_c                  SEQ_ISA.md:368-373; seq_movers.sv:643-647
#  MVGO c            XWIN_c (whole stream)           RES_c rows [0,nrows)    SEQ_ISA.md:386-391; matvec_engine.sv:202-207; matvec_chan.sv:437-439
#  MOVY c            RES_c rows [0,len) (+XRF ind)   scratch [dst, dst+len|2len) SEQ_ISA.md:375-384
#  LDC               DDR const (+XRF ind)            scratch [tgt, tgt+cnt)  SEQ_ISA.md:422-429
#  EMB               DDR row, XRF[3]                 scratch [dst, dst+len)  SEQ_ISA.md:393-402
#  XOP               XRF[a], XRF[b] (if s!=0)        XRF[tgt]                SEQ_ISA.md:431-434
#  AMAXL             layer AMAXI                     XRF[3]                  SEQ_ISA.md:404-407
#  CSRWR (ind!=0)    XRF[i]                          CSR (layer: in chain)   SEQ_ISA.md:346-361
#
# INFERRED (marked in the memo): (i1) the ALU b operand is read ONLY by
# sub-ops 3/4/8 — the reference reads b for every sub-op
# (gen_layer_script.py:1389-1390) but uses it only in those three;
# (i2) VN reads n words whatever its in-format (the reference's slice);
# (i3) every layer-internal resource (vnw buffer, rope table, conv/DN/KV
# slots, AMAX/TOPK, the LAYER/DNSB/TCNT/SB_* CSRs, ARG0-2) is ordered by
# keeping ALL chain records (CSRWR/CMD/XOP/AMAXL/JMP) in program order —
# so no internal resource needs a set of its own.

ALU_RB = {3, 4, 8}                        # (i1) sub-ops that read b
ALU_PAIRS_IN = {1, 6, 8, 9, 10, 12}       # a read as int32 pairs
ALU_NO_DST = {10}


def rw_cmd(op, a0, a1, a2, dnsb):
    """-> (reads, writes, xrf_r, xrf_w, label) for one layer command."""
    lo1, hi1 = GLS.dec_a1_lo(a1), GLS.dec_a1_hi(a1)
    lo2, hi2 = GLS.dec_a1_lo(a2), GLS.dec_a1_hi(a2)
    R, W, xr, xw = [], [], set(), set()
    name = C.LOP_NAME.get(op, f"op{op}")
    if op == 1:                                     # VN
        n = 1 << ((a0 >> 2) & 0xF)
        mode = a0 & 3
        R.append((lo1, lo1 + n))
        W.append((hi1, hi1 + n))
        if mode == SF.VN_EPSNORM_MODE and (a2 & SF.VN_ARG2_EPS):
            xr.add((a2 >> SF.VN_ARG2_XRF_SHIFT) & 7)
            name = "VN-EPS"
        name += f"x{n}"
    elif op == 2:                                   # VNW
        n = a0 & 0x1FFF
        R.append((lo1, lo1 + n))
    elif op == 3:                                   # ROPET
        R.append((lo1, lo1 + 2 * LR.ROT))
    elif op == 4:                                   # ROPE
        R.append((lo1, lo1 + LR.HD))
        W.append((hi1, hi1 + LR.HD))
    elif op == 5:                                   # CONVW (sel 2 only)
        pass
    elif op == 6:                                   # CONV
        first, nch = a0 & 0x3FFF, (a0 >> 14) & 0x3FFF
        R.append((lo1, lo1 + nch))
        W.append((hi1, hi1 + nch))
    elif op == 7:                                   # GATE
        nh = LR.LNH
        dst = a0 & 0xFFFF
        src_a, src_b = hi1, lo1                     # enc_a1(src_b, src_a)
        src_A, src_dt = lo2, hi2                    # enc_a1(src_A, src_dt)
        R += [(src_b, src_b + nh), (src_a, src_a + nh),
              (src_A, src_A + 2 * nh), (src_dt, src_dt + nh)]
        W.append((dst, dst + 2 * nh))
    elif op == 8:                                   # DNST
        head = a0 & 0x1F
        q, k, v, dst = lo1, hi1, lo2, hi2
        assert dnsb is not None, "DNST before DNSB"
        beta = (dnsb & 0xFFFF) + head
        dec = ((dnsb >> 16) & 0xFFFF) + head
        R += [(q, q + LR.LDK), (k, k + LR.LDK), (v, v + LR.LDV),
              (beta, beta + 1), (dec, dec + 1)]
        W.append((dst, dst + 2 * LR.LDV))
        name += f"h{head}"
    elif op == 9:                                   # KVAP
        R += [(lo1, lo1 + LR.HD), (hi1, hi1 + LR.HD)]
    elif op == 10:                                  # ATTN
        R.append((lo1, lo1 + LR.HD))
        W.append((hi1, hi1 + 2 * LR.HD))
    elif op == 11:                                  # ALU
        sub = a0 & 0xF
        n = GLS.dec_alu_len(a0)
        p0 = GLS.dec_alu_p0(a0, a2)
        dst = GLS.dec_alu_dst(a2)
        srca, srcb = lo1, hi1
        R.append((srca, srca + (2 * n if sub in ALU_PAIRS_IN else n)))
        if sub in ALU_RB:
            R.append((srcb, srcb + n))
        if sub not in ALU_NO_DST:
            W.append((dst, dst + (2 * n if sub == 9 else n)))
        if sub == 0:
            xw.add(0)
        elif sub == 12:
            xw.add(2 if (p0 & 1) else 1)
        elif sub == 8 and (p0 & SF.ALU_PROBE_BIT) and p0 < (1 << 16):
            xw.add(2)
        name = f"ALU.{C.ALU_NAME.get(sub, sub)}x{n}"
    elif op in (12, 13, 14):                        # DNZ / SLD / SST
        pass
    else:
        raise ValueError(f"layer op {op}")
    return R, W, xr, xw, name


class ScrMap:
    """Interval map over the 65536-word scratch: each segment carries its
    last writer and the readers since that write."""

    def __init__(self):
        self.starts = [0]
        self.seg = {0: [SCR_N, -1, []]}

    def _split(self, x):
        if x >= SCR_N:
            return
        i = bisect.bisect_right(self.starts, x) - 1
        s = self.starts[i]
        if s == x:
            return
        end, w, rd = self.seg[s]
        self.seg[s] = [x, w, rd]
        self.seg[x] = [end, w, list(rd)]
        self.starts.insert(i + 1, x)

    def read(self, lo, hi, node):
        assert 0 <= lo < hi <= SCR_N, (lo, hi)
        self._split(lo)
        self._split(hi)
        i = bisect.bisect_left(self.starts, lo)
        writers = set()
        while i < len(self.starts) and self.starts[i] < hi:
            seg = self.seg[self.starts[i]]
            if seg[1] >= 0:
                writers.add(seg[1])
            seg[2].append(node)
            i += 1
        return writers

    def writers_of(self, lo, hi):
        self._split(lo)
        self._split(hi)
        i = bisect.bisect_left(self.starts, lo)
        out = []
        while i < len(self.starts) and self.starts[i] < hi:
            out.append(self.seg[self.starts[i]][1])
            i += 1
        return tuple(out)

    def write(self, lo, hi, node):
        assert 0 <= lo < hi <= SCR_N, (lo, hi)
        self._split(lo)
        self._split(hi)
        i = bisect.bisect_left(self.starts, lo)
        j = i
        deps = set()
        while j < len(self.starts) and self.starts[j] < hi:
            seg = self.seg[self.starts[j]]
            if seg[1] >= 0:
                deps.add(seg[1])
            deps.update(seg[2])
            j += 1
        for k in range(i + 1, j):
            del self.seg[self.starts[k]]
        del self.starts[i + 1:j]
        self.seg[lo] = [hi, node, []]
        return deps


# ======================================================================
# the node list
# ======================================================================
class Node:
    __slots__ = ("pc", "op", "kind", "dur", "chan", "R", "W", "xr", "xw",
                 "label", "preds", "sdeps", "S", "grp", "mv", "cyc0",
                 "movx_key", "redundant", "nrows", "n_in", "nr", "nw", "bank")

    def __init__(self, pc, op):
        self.pc, self.op = pc, op
        self.R, self.W, self.xr, self.xw = [], [], set(), set()
        self.preds = {}           # pred node id -> edge kind (done-edges)
        self.sdeps = set()        # MVGO node ids whose STREAM must be done
        self.S = 0
        self.grp = -1
        self.mv = -1
        self.chan = -1
        self.redundant = False
        self.movx_key = None
        self.nrows = 0
        self.n_in = 0
        self.nr, self.nw = set(), set()
        self.bank = None


CSR_NAMED = {                        # config CSRWR -> the named resource
    SF.CSR_L_LAYER: "LAYER", SF.CSR_L_DNSB: "DNSB",
    SF.CSR_L_TCNT: "TCNT", SF.CSR_L_TCNT2: "TCNT",
    SF.CSR_L_SB_DN: "SDMA_CFG", SF.CSR_L_SB_KV: "SDMA_CFG",
    SF.CSR_L_SB_CV: "SDMA_CFG", SF.CSR_L_SDMA: "SDMA_CFG",
}
CSR_SEEN = collections.Counter()


def named_cmd(lop, a0, a1, a2, layer_w):
    """Named layer-INTERNAL resources a command reads / writes (the second
    modelling form, 'free chain').  Slots come from the LAYER CSR as B15.2
    packs it (docs/SEQ_ISA.md:1286-1293); SLD/SST carry kind/slot in ARG0
    (docs/SEQ_ISA.md:1262-1284) and run in program order among themselves
    on the DMA lane (docs/SEQ_ISA.md:1321-1326)."""
    dn = layer_w & 3
    kv = (layer_w >> 3) & 3
    cv = (layer_w >> 12) & 3
    r, w = set(), set()
    if lop == 1 and (a0 & 3) in (0, 1):
        r.add("VNWBUF")                     # rmsnorm reads the wbuf
    elif lop == 2:
        w.add("VNWBUF")
    elif lop == 3:
        w.add("ROPETAB")
    elif lop == 4:
        r.add("ROPETAB")
    elif lop in (5, 6):
        r |= {"LAYER"}
        r.add(f"CV{cv}")
        w.add(f"CV{cv}")
    elif lop in (8, 12):
        r |= {"LAYER", "DNSB"}
        r.add(f"DN{dn}")
        w.add(f"DN{dn}")
    elif lop == 9:
        r.add("LAYER")
        r.add(f"KV{kv}")
        w.add(f"KV{kv}")
    elif lop == 10:
        r |= {"LAYER", f"KV{kv}"}
    elif lop == 11 and (a0 & 0xF) == 10:
        r.add("AMAX")
        w.add("AMAX")
    elif lop in (13, 14):
        kind, slot, _l, _h = SF.sdma_fields(a0)
        k = {0: "DN", 1: "KV", 2: "CV"}[kind]
        r |= {"SDMA_CFG", "TCNT"}
        r.add("DMAQ")
        w.add("DMAQ")
        if lop == 13:
            w.add(f"{k}{slot}")
        else:
            r.add(f"{k}{slot}")
    return r, w


def build_nodes(recs, lo, hi, rows4):
    nodes = []
    arg = {SF.CSR_L_ARG0: 0, SF.CSR_L_ARG1: 0, SF.CSR_L_ARG2: 0}
    dnsb = None
    layer_w = 0
    pend = []                 # ARG CSRWR nodes waiting for their CMD
    for pc in range(lo, hi + 1):
        r = recs[pc]
        n = Node(pc, r.opcode)
        row = rows4[pc]
        assert row[0] == r.opcode, (pc, row[0], r.opcode)
        n.cyc0, n.dur = row[1], row[2]
        op = r.opcode
        if op == SF.OP_CSRWR:
            n.kind = "chain"
            CSR_SEEN[r.target] += 1
            if r.target in arg:
                arg[r.target] = r.imm32
                # an ARG write belongs to the CMD that follows it: merged
                # into that CMD's node (its window and any XRF read)
                n.kind = "arg"
                pend.append(n)
            if r.target == SF.CSR_L_DNSB:
                dnsb = r.imm32
            if r.target == SF.CSR_L_LAYER:
                layer_w = r.imm32
            if r.target in CSR_NAMED:
                n.nw.add(CSR_NAMED[r.target])
            if r.ind:
                n.xr.add(r.xrf & 7)
            sp = r.target & 0xF000
            if sp == SF.CSR_SPACE_SEQ and (r.target & 0xFF) >= SF.SOFF_XRF0:
                n.xw.add(((r.target & 0xFF) - SF.SOFF_XRF0) // 4)
            elif sp == SF.CSR_SPACE_SEQ:
                n.nw.add("TCNT_SEQ")
            if sp == SF.CSR_SPACE_MV:
                raise AssertionError(f"matvec CSRWR at {pc}: not modelled")
            if (sp == SF.CSR_SPACE_LAYER and r.target not in arg
                    and r.target not in CSR_NAMED):
                n.nw.add("BARRIER")          # unknown layer CSR: a barrier
            n.label = f"CSRWR {r.target:#06x}"
        elif op == SF.OP_CMD:
            n.kind = "chain"
            lop = r.imm32 & 0xFF
            R, W, xr, xw, name = rw_cmd(lop, arg[SF.CSR_L_ARG0],
                                        arg[SF.CSR_L_ARG1],
                                        arg[SF.CSR_L_ARG2], dnsb)
            n.R, n.W = R, W
            n.xr |= xr
            n.xw |= xw
            n.label = name
            n.nr, n.nw = named_cmd(lop, arg[SF.CSR_L_ARG0],
                                   arg[SF.CSR_L_ARG1], arg[SF.CSR_L_ARG2],
                                   layer_w)
            n.nr.add("BARRIER")
            for a in pend:
                n.dur += a.dur
                n.xr |= a.xr
                a.dur = 0
            pend = []
        elif op == SF.EXT_XOP:
            n.kind = "chain"
            imm = r.imm32
            if (imm >> 8) & 3:
                n.xr.add(imm & 7)
            if (imm >> 10) & 3:
                n.xr.add((imm >> 4) & 7)
            n.xw.add(r.target & 7)
            n.label = f"XOP x{r.target & 7}"
        elif op == SF.OP_AMAXL:
            n.kind = "chain"
            n.xw.add(3)
            n.nr.add("AMAX")
            n.label = "AMAXL"
        elif op == SF.OP_JMP:
            n.kind = "chain"
            n.label = "JMP"
            n.nr |= {"TCNT_SEQ", "BARRIER"}
            n.nw.add("BARRIER")
        elif op == SF.OP_MOVX:
            n.kind = "movx"
            n.chan = r.chan
            ln = r.len_or_addr_hi & 0xFFFFFF
            n.R = [(r.addr_lo & 0xFFFF, (r.addr_lo & 0xFFFF) + ln)]
            n.n_in = ln
            n.label = f"MOVX c{r.chan} [{r.addr_lo:#x}+{ln}]"
        elif op == SF.OP_MOVY:
            n.kind = "movy"
            n.chan = r.chan
            ln = r.len_or_addr_hi & 0xFFFFFF
            w = ln if r.movy_mode == SF.MOVY_INT16 else 2 * ln
            n.W = [(r.addr_lo & 0xFFFF, (r.addr_lo & 0xFFFF) + w)]
            if r.ind:
                n.xr.add(r.xrf & 7)
            n.nrows = ln
            n.label = f"MOVY c{r.chan} {ln}r -> {r.addr_lo:#x}"
        elif op == SF.OP_MVGO:
            n.kind = "mvgo"
            n.chan = r.chan
            n.nrows = (r.imm32 >> 6) & 0xFFFF
            n.label = f"MVGO c{r.chan} {n.nrows}r nw={r.target & 1}"
            assert r.target & 1, f"blocking MVGO at {pc}"
        elif op == SF.OP_FENCE:
            n.kind = "fence"
            n.label = "FENCE"
        elif op == SF.EXT_LDC:
            n.kind = "ldc"
            cnt = r.imm32 & 0xFFFFFF
            n.W = [(r.target, r.target + cnt)]
            if r.ind:
                n.xr.add(r.xrf & 7)
            n.label = f"LDC -> {r.target:#x}+{cnt}"
        elif op == SF.OP_EMB:
            n.kind = "emb"
            ln = r.len_or_addr_hi & 0xFFFFFF
            n.W = [(r.addr_lo & 0xFFFF, (r.addr_lo & 0xFFFF) + ln)]
            n.xr.add(3)
            n.label = f"EMB -> {r.addr_lo:#x}+{ln}"
        else:
            raise AssertionError(f"opcode {op} at {pc} in the body")
        nodes.append(n)
    return nodes


def stream_durations(nodes, rows4):
    """Per MVGO: S = its channel's engine-busy cycles summed over the rows
    from the MVGO through the FENCE that drains it (the CSV's MVc_BSY,
    tb/seq_timeline.svh via rtl/matvec_chan.sv:233-236).  Per group:
    tau = FENCE end - max_c(MVGO_c end + S_c), the poll tail."""
    groups = []
    cur = []
    leak = 0
    for i, n in enumerate(nodes):
        if n.kind == "mvgo":
            cur.append(i)
        elif n.kind == "fence":
            assert cur, f"FENCE at {n.pc} with no MVGO"
            f = i
            ends = []
            for m in cur:
                c = nodes[m].chan
                s = 0
                for k in range(m, f + 1):
                    s += rows4[nodes[k].pc][3][BSY0 + c]
                nodes[m].S = s
                ends.append(nodes[m].cyc0 + nodes[m].dur + s)
            fend = n.cyc0 + n.dur
            tau = fend - max(ends)
            groups.append({"mvgos": cur, "fence": f, "tau": tau,
                           "fwin": n.dur, "movys": []})
            for m in cur:
                nodes[m].grp = len(groups) - 1
            n.grp = len(groups) - 1
            cur = []
        elif n.kind in ("movy",) and groups and not cur:
            g = groups[-1]
            if nodes[g["fence"]].pc < n.pc:
                g["movys"].append(i)
                n.grp = len(groups) - 1
        # engine-busy AFTER a fence (should be ~0: the fence drains)
        if n.kind != "mvgo" and n.kind != "fence" and not cur:
            leak += sum(rows4[n.pc][3][BSY0:BSY0 + 4])
    assert not cur
    return groups, leak


def segment_matvecs(nodes, groups):
    """A matvec = a run of MOVX records + the groups up to the next run."""
    mvs = []
    in_run = False
    for i, n in enumerate(nodes):
        if n.kind == "movx":
            if not in_run:
                mvs.append({"movx": [], "groups": [], "rows": 0,
                            "n_in": n.n_in})
            mvs[-1]["movx"].append(i)
            in_run = True
        elif not (n.kind == "chain" and n.op == SF.EXT_XOP):
            in_run = False
        if n.kind == "fence":
            mvs[-1]["groups"].append(n.grp)
    for k, mv in enumerate(mvs):
        for g in mv["groups"]:
            for m in groups[g]["mvgos"]:
                mv["rows"] += nodes[m].nrows
                nodes[m].mv = k
            groups[g]["mv"] = k
        for x in mv["movx"]:
            nodes[x].mv = k
    # label by the emitter's per-layer order
    i = 0
    layer = 0
    ltypes = []
    while i < len(mvs) - 1:
        rows = [m["rows"] for m in mvs[i:i + 8]]
        if rows == [r for _, r in DN_SEQ]:
            seq, lt = DN_SEQ, "DN"
        elif rows[:7] == [r for _, r in GQA_SEQ]:
            seq, lt = GQA_SEQ, "GQA"
        else:
            raise AssertionError(f"matvec {i}: rows {rows} match no layer")
        for j, (nm, _r) in enumerate(seq):
            mvs[i + j].update(cls=nm, lt=lt, layer=layer)
        ltypes.append(lt)
        i += len(seq)
        layer += 1
    assert i == len(mvs) - 1 and mvs[-1]["rows"] == 248320, \
        (i, len(mvs), mvs[-1]["rows"])
    mvs[-1].update(cls="lm_head", lt="HEAD", layer=layer)
    return mvs, ltypes


# ======================================================================
# dependency edges
# ======================================================================
def build_edges(nodes, elide_movx, xdepth, rdepth, chain="order"):
    """Fill preds (done-edges) and sdeps (stream-edges).

    elide_movx : a MOVX whose (chan, src range) equals the last MOVX on that
                 channel, with no scratch write to the source range since, is
                 REDUNDANT — matvec_engine's x_mem is written only by x_we
                 (rtl/matvec_engine.sv:219-224) and a start does not clear it
                 (rtl/matvec_engine.sv:478-485).  Marked either way; removed
                 (dur 0, no edges) only when elide_movx.
    xdepth/rdepth: XWIN / RES buffers per channel (1 = as built; 2 = the
                 double-buffer RTL option).  Depth 2 applies only where the
                 matvec fits half the buffer (K <= 6144: 48 of x_mem's 96
                 lines; nrows <= 2048: half of the 4096-row RES BRAM)."""
    scr = ScrMap()
    xrf_w = {}                  # xrf -> last writer
    xrf_r = collections.defaultdict(list)   # xrf -> readers since write
    nm_w = {}
    nm_r = collections.defaultdict(list)
    last_chain = -1
    # per channel, per buffer: XWIN {writer MOVX, readers MVGO}, RES {writer
    # MVGO, readers MOVY}; engine: last MVGO
    xw = {c: [{"w": -1, "r": []} for _ in range(2)] for c in range(4)}
    rs = {c: [{"w": -1, "r": []} for _ in range(2)] for c in range(4)}
    xsel = {c: 0 for c in range(4)}
    rsel = {c: 0 for c in range(4)}
    eng = {c: -1 for c in range(4)}
    last_movx_key = {c: None for c in range(4)}
    nred = 0
    for i, n in enumerate(nodes):
        n.preds = {}
        n.sdeps = set()
        n.redundant = False
        if n.kind in ("fence", "arg"):
            continue      # fences become implicit; ARG writes ride their CMD
        if n.kind == "movx":
            key = (n.R[0], scr.writers_of(*n.R[0]))
            if last_movx_key[n.chan] == key:
                n.redundant = True
                nred += 1
                if elide_movx:
                    continue
            last_movx_key[n.chan] = key
        # ---- chain order ----
        if n.kind == "chain" and chain == "order":
            if last_chain >= 0:
                n.preds[last_chain] = "chain"
            last_chain = i
        # ---- scratch ----
        for (a, b) in n.R:
            for w in scr.read(a, b, i):
                if w != i:
                    n.preds.setdefault(w, "raw")
        for (a, b) in n.W:
            for d in scr.write(a, b, i):
                if d != i:
                    n.preds.setdefault(d, "war/waw")
        # ---- XRF ----
        for x in n.xr:
            if x in xrf_w:
                n.preds.setdefault(xrf_w[x], "xrf-raw")
            xrf_r[x].append(i)
        for x in n.xw:
            for r_ in xrf_r[x]:
                if r_ != i:
                    n.preds.setdefault(r_, "xrf-war")
            if x in xrf_w and xrf_w[x] != i:
                n.preds.setdefault(xrf_w[x], "xrf-waw")
            xrf_w[x] = i
            xrf_r[x] = []
        # ---- named layer-internal resources (free-chain form only; in the
        # chain-order form program order already orders them) ----
        if chain == "free":
            for x in n.nr:
                if x in nm_w:
                    n.preds.setdefault(nm_w[x], "int-raw")
                nm_r[x].append(i)
            for x in n.nw:
                for r_ in nm_r[x]:
                    if r_ != i:
                        n.preds.setdefault(r_, "int-war")
                if x in nm_w and nm_w[x] != i:
                    n.preds.setdefault(nm_w[x], "int-waw")
                nm_w[x] = i
                nm_r[x] = []
        # ---- channel resources ----
        c = n.chan
        if n.kind == "movx":
            dbl = xdepth == 2 and n.n_in <= 6144
            b = (xsel[c] ^ 1) if dbl else xsel[c]
            xsel[c] = b
            # fix round 1: a vector too long for half of x_mem (K > 6144,
            # mlp_down) spans BOTH banks when double buffering is on, so it
            # must wait for the readers of both and it overwrites both
            banks = [b] if (dbl or xdepth == 1) else [0, 1]
            n.bank = b if len(banks) == 1 else -1
            for bb in banks:
                buf = xw[c][bb]
                for m in buf["r"]:      # WAR: the engine reads x all stream
                    n.sdeps.add(m)
                if buf["w"] >= 0 and buf["w"] != i:
                    n.preds.setdefault(buf["w"], "xwin-waw")
                buf["w"], buf["r"] = i, []
        elif n.kind == "mvgo":
            buf = xw[c][xsel[c]]
            if buf["w"] >= 0:
                n.preds.setdefault(buf["w"], "xwin-raw")
            # fix round 2: a vector whose writer spans both XWIN banks is
            # read from both, so this stream is a reader of both banks
            xspan = buf["w"] >= 0 and nodes[buf["w"]].bank == -1
            if xspan:
                for bb in (0, 1):
                    xw[c][bb]["r"].append(i)
            else:
                buf["r"].append(i)
            if eng[c] >= 0:             # one stream per engine at a time
                n.sdeps.add(eng[c])
            eng[c] = i
            dbl = rdepth == 2 and n.nrows <= 2048
            b = (rsel[c] ^ 1) if dbl else rsel[c]
            rsel[c] = b
            # fix round 1: a chunk over 2048 rows spans both RES banks
            rbanks = [b] if (dbl or rdepth == 1) else [0, 1]
            n.bank = (-1 if xspan else xsel[c],
                      b if len(rbanks) == 1 else -1)
            for bb in rbanks:
                rb = rs[c][bb]
                for m in rb["r"]:       # WAR: RES rows drained first
                    n.preds.setdefault(m, "res-war")
                rb["w"], rb["r"] = i, []
        elif n.kind == "movy":
            rb = rs[c][rsel[c]]
            assert rb["w"] >= 0, f"MOVY at {n.pc} before any MVGO"
            n.sdeps.add(rb["w"])
            w = rb["w"]
            # SR11b (spec §1.2 "Emitter / pass"): the MOVY records the RES
            # bank it drains — its writer's (0/1; -1 when that MVGO spans
            # both banks), so the R2 pass can emit MOVY target[15:4].  A
            # recorded field only: no edge or timing reads it.
            n.bank = nodes[w].bank[1] if nodes[w].bank is not None else 0
            if nodes[w].bank is not None and nodes[w].bank[1] == -1:
                for bb in (0, 1):       # the writer spans both banks
                    rs[c][bb]["r"].append(i)
            else:
                rb["r"].append(i)
    return nred


# ======================================================================
# the list scheduler
# ======================================================================
def schedule(nodes, groups, cfg, rebal=None):
    """Event-driven list schedule.  cfg keys:
         lanes   : 1 (one issue lane: today's single-threaded issue FSM and
                   the single-ported scratch) or 2 (chain lane + mover lane:
                   a hypothetical second scratch port — a BOUND, not a proposal)
         fence   : 'global' (today's FENCE drains every pending channel,
                   rtl/seq_movers.sv:845-861) or 'perchan'
         hoist_guard : (global only) an MVGO may not issue while a candidate
                   with a smaller pc waits on a not-yet-fenced stream, so a
                   hoisted stream never lengthens an earlier wait
    Returns (makespan, per-node start/finish, stats)."""
    N = len(nodes)
    lane_of = [0] * N
    live = [n.kind not in ("fence", "arg") and not (cfg["elide"] and n.redundant)
            for n in nodes]
    for i, n in enumerate(nodes):
        if cfg["lanes"] == 2 and n.kind in ("movx", "movy", "mvgo", "ldc",
                                            "emb"):
            lane_of[i] = 1
    S = [n.S if rebal is None else rebal.get(i, n.S)
         for i, n in enumerate(nodes)]
    tau = [groups[n.grp]["tau"] if n.kind == "mvgo" else 0 for n in nodes]
    succ = [[] for _ in range(N)]
    indeg = [0] * N
    for i, n in enumerate(nodes):
        if not live[i]:
            continue
        ps = [p for p in n.preds if live[p]] + [m for m in n.sdeps if live[m]]
        indeg[i] = len(set(ps))
        for p in set(ps):
            succ[p].append(i)
    # priority: 'bl' = bottom level (longest path to the end, streams
    # included) — the standard HLFET list-scheduling rule, so a stream is
    # started as early as its dependencies allow; 'pc' = program order
    bl = [0] * N
    for i in range(N - 1, -1, -1):
        if not live[i]:
            continue
        n = nodes[i]
        best = (S[i] + tau[i]) if n.kind == "mvgo" else 0
        for s_ in succ[i]:
            via_stream = (n.kind == "mvgo" and i in nodes[s_].sdeps)
            v = bl[s_] + ((S[i] + tau[i]) if via_stream else 0)
            if v > best:
                best = v
        bl[i] = n.dur + best
    if cfg.get("prio", "bl") == "bl":
        pk = [(-bl[i], i) for i in range(N)]
    else:
        pk = [(i,) for i in range(N)]
    start = [None] * N
    fin = [None] * N
    send = [None] * N           # stream end (MVGO)
    fenced_at = [None] * N      # global mode: time the stream was fenced
    unfenced = []               # issued, unfenced MVGOs (global mode)
    pend_users = {}             # unscheduled user -> group of its unfenced stream
    nlanes = cfg["lanes"]
    t_lane = [0] * nlanes
    now = [[] for _ in range(nlanes)]
    fut = [[] for _ in range(nlanes)]
    fneed = [[] for _ in range(nlanes)]   # candidates with unfenced sdeps
    stats = {"fences": 0, "idle": collections.Counter(),
             "idle_by_mv": collections.Counter(), "waits": 0}

    def ready_of(i):
        n = nodes[i]
        r, why, whom = 0, "none", -1
        for p, k in n.preds.items():
            if live[p] and fin[p] > r:
                r, why, whom = fin[p], "dep:" + k, p
        need_fence = False
        for m in n.sdeps:
            if not live[m]:
                continue
            if cfg["fence"] == "perchan":
                v = send[m] + tau[m]
                if v > r:
                    r, why, whom = v, "stream", m
            else:
                if fenced_at[m] is not None:
                    if fenced_at[m] > r:
                        r, why, whom = fenced_at[m], "stream", m
                else:
                    need_fence = True
        if need_fence:
            # a FENCE drains EVERY issued, unfenced stream
            best, bm = 0, -1
            for m in unfenced:
                v = send[m] + tau[m]
                if v > best:
                    best, bm = v, m
            if best > r:
                r, why, whom = best, "stream", bm
        return r, why, whom, need_fence

    def push_cand(i):
        L = lane_of[i]
        r, _, _, nf = ready_of(i)
        heapq.heappush(fut[L], (r, i))
        if nf:
            heapq.heappush(fneed[L], i)

    for i in range(N):
        if live[i] and indeg[i] == 0:
            push_cand(i)
    done = 0
    total = sum(live)
    while done < total:
        # pick the lane with the earliest clock that can make progress
        order = sorted(range(nlanes), key=lambda L: t_lane[L])
        progressed = False
        for L in order:
            t = t_lane[L]
            # promote
            while fut[L] and fut[L][0][0] <= t:
                r, i = heapq.heappop(fut[L])
                r2 = ready_of(i)[0]
                if r2 <= t:
                    heapq.heappush(now[L], (pk[i], i))
                else:
                    heapq.heappush(fut[L], (r2, i))
            pick = None
            skipped = []
            while now[L]:
                _k, i = heapq.heappop(now[L])
                r2 = ready_of(i)[0]
                if r2 > t:
                    heapq.heappush(fut[L], (r2, i))
                    continue
                if (cfg["fence"] == "global" and cfg.get("hoist_guard")
                        and nodes[i].kind == "mvgo"):
                    while fneed[L] and (start[fneed[L][0]] is not None
                                        or not ready_of(fneed[L][0])[3]):
                        heapq.heappop(fneed[L])
                    if (fneed[L] and fneed[L][0] < i) or (
                            cfg.get("guard") == "strong" and any(
                                g != nodes[i].grp for g in pend_users.values())):
                        skipped.append(i)
                        continue
                pick = i
                break
            for s_ in skipped:
                heapq.heappush(now[L], (pk[s_], s_))
            if pick is None:
                # nothing startable at t on this lane: advance its clock
                cands = []
                if fut[L]:
                    cands.append(fut[L][0][0])
                for M in range(nlanes):
                    if M != L and t_lane[M] > t:
                        cands.append(t_lane[M])
                if skipped and not cands:
                    # only guarded MVGOs are startable: release the guard
                    pick = heapq.heappop(now[L])[1]
                elif cands:
                    nt = min(cands)
                    if fut[L] and fut[L][0][0] == nt:
                        r, i = fut[L][0]
                        _, why, whom, _ = ready_of(i)
                        key = (why, nodes[whom].mv if whom >= 0 else -1)
                        stats["idle"][why] += nt - t
                        if why == "stream":
                            stats["idle_by_mv"][nodes[whom].mv] += nt - t
                    else:
                        stats["idle"]["other-lane"] += nt - t
                    t_lane[L] = nt
                    progressed = True
                    break
                else:
                    continue
            # schedule pick
            i = pick
            r, why, whom, nf = ready_of(i)
            assert r <= t, (i, r, t)
            if nf:
                stats["fences"] += 1
                for m in unfenced:
                    fenced_at[m] = r
                unfenced = []
                pend_users.clear()
            pend_users.pop(i, None)
            start[i] = t
            fin[i] = t + nodes[i].dur
            if nodes[i].kind == "mvgo":
                send[i] = fin[i] + S[i]
                if cfg["fence"] == "global":
                    unfenced.append(i)
                    for s_ in succ[i]:
                        if (i in nodes[s_].sdeps and start[s_] is None
                                and nodes[s_].kind != "mvgo"):
                            pend_users[s_] = nodes[i].grp
            t_lane[L] = fin[i]
            done += 1
            for s_ in succ[i]:
                indeg[s_] -= 1
                if indeg[s_] == 0:
                    push_cand(s_)
            progressed = True
            break
        if not progressed:
            raise AssertionError("scheduler deadlock")
    mk = max(max(fin[i], (send[i] + tau[i]) if send[i] is not None else 0)
             for i in range(N) if live[i])
    stats["post"] = postcheck(nodes, live, start, fin, send, tau, lane_of)
    return mk, start, fin, send, stats


def postcheck(nodes, live, start, fin, send, tau, lane_of):
    """Fix round 1 (review I1/I3): an INDEPENDENT check of the finished
    schedule — it re-reads start/finish times and does not trust the
    scheduler's own readiness test.
      (e) every done-edge: start >= pred finish; every stream-edge:
          start >= stream end + poll tail;
      (x) no MOVX writes an XWIN bank while a stream on that channel reads
          that bank (rtl/matvec_engine.sv:219-224 — x_mem is written
          whenever the x FIFO pops);
      (g) no MVGO starts on a channel whose engine is still streaming
          (rtl/matvec_engine.sv:478-485 — a start re-initialises it);
      (y) no MOVY reads RES before its own stream ended, nor while another
          stream writes the same RES bank;
      (l) no two records overlap on one lane.
    Raises on any violation; returns the counts checked."""
    N = len(nodes)
    ne = nc = 0
    bad = []
    streams = collections.defaultdict(list)     # chan -> (s0, s1, i)
    for i in range(N):
        if live[i] and nodes[i].kind == "mvgo":
            streams[nodes[i].chan].append((fin[i], send[i] + tau[i], i))
    for i in range(N):
        if not live[i]:
            continue
        n = nodes[i]
        for p in n.preds:
            if live[p]:
                ne += 1
                if start[i] < fin[p]:
                    bad.append(("e-dep", n.pc, nodes[p].pc))
        for m in n.sdeps:
            if live[m]:
                ne += 1
                if start[i] < send[m] + tau[m]:
                    bad.append(("e-stream", n.pc, nodes[m].pc))
        if n.kind == "movx":
            for (s0, s1, m) in streams[n.chan]:
                nc += 1
                xb = nodes[m].bank[0] if nodes[m].bank else 0
                same = (n.bank in (None, -1) or xb == -1 or xb == n.bank)
                if same and s0 < fin[i] and start[i] < s1:
                    bad.append(("x-movx-on-streaming-bank", n.pc,
                                nodes[m].pc))
        elif n.kind == "mvgo":
            for (s0, s1, m) in streams[n.chan]:
                if m != i:
                    nc += 1
                    if s0 < send[i] + tau[i] and fin[i] < s1:
                        bad.append(("g-two-streams-one-engine", n.pc,
                                    nodes[m].pc))
        elif n.kind == "movy":
            w = next(iter(n.sdeps))
            wb = nodes[w].bank[1] if nodes[w].bank else 0
            for (s0, s1, m) in streams[n.chan]:
                nc += 1
                mb = nodes[m].bank[1] if nodes[m].bank else 0
                if m == w and start[i] < s1:
                    bad.append(("y-movy-before-own-stream", n.pc,
                                nodes[m].pc))
                elif (m != w and (mb == wb or -1 in (mb, wb))
                      and s0 < fin[i] and start[i] < s1):
                    bad.append(("y-movy-while-bank-written", n.pc,
                                nodes[m].pc))
    by_lane = collections.defaultdict(list)
    for i in range(N):
        if live[i]:
            by_lane[lane_of[i]].append((start[i], fin[i], i))
    for L, v in by_lane.items():
        v.sort()
        for (a0, a1, _a), (b0, _b1, _b) in zip(v, v[1:]):
            nc += 1
            if b0 < a1:
                bad.append(("l-lane-overlap", nodes[_a].pc, nodes[_b].pc))
    if bad:
        raise AssertionError(f"POSTCHECK FAILED: {len(bad)} violations, "
                             f"first {bad[:5]}")
    return ne, nc


def best_schedule(nodes, groups, lanes, fence, elide):
    """The makespan of the best of the issue heuristics (global FENCE: the
    three rules run_sched names; per-channel: bottom level)."""
    if fence == "global":
        hs = ({"prio": "pc", "guard": "weak"}, {"prio": "bl", "guard": "weak"},
              {"prio": "bl", "guard": "strong"})
    else:
        hs = ({"prio": "bl"},)
    best = None
    for h in hs:
        cfg = {"lanes": lanes, "fence": fence, "elide": elide,
               "hoist_guard": True}
        cfg.update(h)
        mk = schedule(nodes, groups, cfg)[0]
        best = mk if best is None else min(best, mk)
    return best


def today_replay(nodes, groups, tau_mode="measured"):
    """V0: the shipped order, one lane, global FENCE."""
    t = 0
    tv = sorted(g["tau"] for g in groups)
    tmed = tv[len(tv) // 2]
    fin_mv = {}
    for i, n in enumerate(nodes):
        if n.kind == "fence":
            g = groups[n.grp]
            tau = g["tau"] if tau_mode == "measured" else tmed
            t = max(t, max(fin_mv[m] + nodes[m].S for m in g["mvgos"])) + tau
        else:
            t += n.dur
            if n.kind == "mvgo":
                fin_mv[i] = t
    return t, tmed


# ======================================================================
# D1 — the fence census
# ======================================================================
def census(nodes, groups, mvs, form):
    """D1 for one read/write-set form.  Per fence (group of MVGOs + FENCE):
      RES consumer   the MOVY that reads the channel's RES (always right
                     after the FENCE in the shipped stream);
      data consumer  the first later node with a RAW edge from a group MOVY;
      after          lane cycles in (FENCE, data consumer) not descended from
                     the group's streams — overlappable without moving
                     anything past the consumer;
      pull           lane cycles ANYWHERE after the FENCE not descended from
                     the group's streams (streams of later groups on the same
                     channels are descendants through the engine edge, so
                     this is bounded by construction);
      hoist          per MVGO: lane cycles between its latest dependency and
                     itself that are not its ancestors (mean over the group).
    All three are per-fence POTENTIALS, capped at the stream; they are not
    additive across fences (the same independent work can be counted for
    several fences) — the joint answer is D2's list schedule."""
    N = len(nodes)
    live = [n.kind not in ("fence", "arg") for n in nodes]
    succ = [[] for _ in range(N)]
    for i, n in enumerate(nodes):
        if not live[i]:
            continue
        for p in n.preds:
            succ[p].append(i)
        for m in n.sdeps:
            succ[m].append(i)
    print(f"\n=== D1: THE FENCE CENSUS, form {form} (token 4, per fence)")
    print("  cols: F# layer type class chunk | chans rows/ch | S_max cyc | "
          "FENCE win | tau | data consumer pc (label) | non-CSRWR records "
          "between FENCE and consumer (group MOVYs excluded) | after | pull | "
          "hoist | hideable = min(S, max(after, pull) + hoist)")
    agg = collections.defaultdict(lambda: collections.Counter())
    for gi, g in enumerate(groups):
        mv = mvs[g["mv"]]
        f = g["fence"]
        S_max = max(nodes[m].S for m in g["mvgos"])
        chunk = mv["groups"].index(gi)
        movys = set(g["movys"])
        cons = None
        for j in range(f + 1, N):
            if any(nodes[j].preds.get(y) == "raw" for y in movys):
                cons = j
                break
        # descendants of the group's streams, whole remainder
        mark = set(g["mvgos"])
        stack = list(g["mvgos"])
        while stack:
            k = stack.pop()
            for s_ in succ[k]:
                if s_ not in mark:
                    mark.add(s_)
                    stack.append(s_)
        hi = cons if cons is not None else N
        after = sum(nodes[j].dur for j in range(f + 1, hi)
                    if live[j] and j not in mark)
        pull = sum(nodes[j].dur for j in range(f + 1, N)
                   if live[j] and j not in mark)
        # per-MVGO hoist room
        hs = []
        for m in g["mvgos"]:
            dp = [p for p in nodes[m].preds] + list(nodes[m].sdeps)
            own = [p for p in nodes[m].preds
                   if nodes[p].kind == "movx" and nodes[p].chan == nodes[m].chan]
            for x in own:
                dp += list(nodes[x].preds) + list(nodes[x].sdeps)
            dp = [p for p in dp if p not in own]
            la = max(dp) if dp else -1
            anc = set()
            stack = [m]
            while stack:
                k = stack.pop()
                for p in list(nodes[k].preds) + list(nodes[k].sdeps):
                    if p > la and p not in anc:
                        anc.add(p)
                        stack.append(p)
            hs.append(sum(nodes[j].dur for j in range(la + 1, m)
                          if live[j] and j not in anc
                          and nodes[j].kind != "mvgo"))
        hoist = sum(hs) // len(hs)
        hide = min(S_max, max(after, pull) + hoist)
        gap = (sum(1 for j in range(f + 1, cons)
                   if j not in movys and nodes[j].op != SF.OP_CSRWR
                   and live[j])
               if cons is not None else -1)
        key = (mv["lt"], mv["cls"])
        a = agg[key]
        a["fences"] += 1
        a["S"] += S_max
        a["fwin"] += g["fwin"]
        a["after"] += min(after, S_max)
        a["pull"] += min(pull, S_max)
        a["hoist"] += min(hoist, S_max)
        a["hide"] += hide
        a["cons_next"] += (gap == 0)
        cl = nodes[cons].label if cons is not None else "-"
        cpc = nodes[cons].pc if cons is not None else -1
        chans = "".join(str(nodes[m].chan) for m in g["mvgos"])
        rows = nodes[g["mvgos"][0]].nrows
        print(f"  F{gi:03d} L{mv['layer']:02d} {mv['lt']:4s} "
              f"{mv['cls']:9s} {chunk + 1}/{len(mv['groups'])} | "
              f"c{chans} {rows:5d} | {S_max:7d} | {g['fwin']:7d} | "
              f"{g['tau']:4d} | {cpc} ({cl}) | {gap} | {after:7d} | "
              f"{pull:8d} | {hoist:6d} | {hide:7d}")
    print(f"\n=== D1 table, form {form}: by layer type and matrix class "
          "(ms/token; per-fence potentials capped at the stream, NOT additive)")
    print("  type class      fences  S_max_sum  FENCEwin    after     pull"
          "    hoist  hideable  consumer-next")
    tot = collections.Counter()
    for key in sorted(agg, key=lambda k: (["DN", "GQA", "HEAD"].index(k[0]),
                                          k[1])):
        a = agg[key]
        for k2 in a:
            tot[k2] += a[k2]
        print(f"  {key[0]:4s} {key[1]:9s} {a['fences']:6d}  "
              f"{ms(a['S']):9.3f} {ms(a['fwin']):9.3f} {ms(a['after']):8.3f} "
              f"{ms(a['pull']):8.3f} {ms(a['hoist']):8.3f} "
              f"{ms(a['hide']):9.3f}  {a['cons_next']:5d}")
    print(f"  ALL  {'':9s} {tot['fences']:6d}  {ms(tot['S']):9.3f} "
          f"{ms(tot['fwin']):9.3f} {ms(tot['after']):8.3f} "
          f"{ms(tot['pull']):8.3f} {ms(tot['hoist']):8.3f} "
          f"{ms(tot['hide']):9.3f}  {tot['cons_next']:5d}")
    return agg


# ======================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["dump", "census", "sched", "all"])
    ap.add_argument("lo", nargs="?", type=int)
    ap.add_argument("hi", nargs="?", type=int)
    args = ap.parse_args()

    recs, man = load_stream()
    lo, hi = body_range(recs)
    rows = load_csv()
    r4 = rows[4]
    miss = [pc for pc in range(lo, hi + 1) if pc not in r4]
    assert not miss, f"token 4 misses {len(miss)} body pcs"
    extra = sorted(set(r4) - set(range(lo, hi + 1)))
    print(f"    token 4: {len(r4)} rows, body pcs all present; "
          f"rows outside the body: {len(extra)} {extra[:5]}")
    tok_cyc = {t: sum(v[2] for v in rows[t].values()) for t in rows}
    for t in rows:
        print(f"    token {t}: sum of record windows = {tok_cyc[t]} cyc "
              f"= {ms(tok_cyc[t]):.3f} ms")

    nodes = build_nodes(recs, lo, hi, r4)
    body_cyc = sum(n.dur for n in nodes)
    print(f"    body (pcs {lo}..{hi}) window sum, token 4: {body_cyc} cyc "
          f"= {ms(body_cyc):.3f} ms")
    kinds = collections.Counter(n.kind for n in nodes)
    print("    records by kind: " + ", ".join(f"{k} {v}"
                                              for k, v in sorted(kinds.items())))
    print("    CSRWR targets in the body: " + ", ".join(
        f"{t:#06x} x{v}" for t, v in sorted(CSR_SEEN.items())))
    nbar = sum(1 for n in nodes if "BARRIER" in n.nw)
    print(f"    records treated as a full barrier in form B: {nbar} "
          f"(unknown layer CSRWRs + the JMP)")

    groups, leak = stream_durations(nodes, r4)
    print(f"    groups (MVGO set + FENCE): {len(groups)}; engine-busy cycles "
          f"outside any MVGO..FENCE span: {leak}")
    taus = sorted(g["tau"] for g in groups)
    print(f"    FENCE poll tail tau: min {taus[0]} median "
          f"{taus[len(taus) // 2]} max {taus[-1]} sum {sum(taus)}")
    mvs, ltypes = segment_matvecs(nodes, groups)
    print(f"    matvecs: {len(mvs)}; layer order: {''.join(x[0] for x in ltypes)}"
          f" (D=DN, G=GQA) + HEAD")
    nfence_by = collections.Counter(mvs[g['mv']]['lt'] for g in groups)
    print(f"    fences by layer type: {dict(nfence_by)}")

    if args.mode == "dump":
        build_edges(nodes, False, 1, 1)
        for i, n in enumerate(nodes):
            if not (args.lo <= n.pc <= args.hi):
                continue
            pr = ",".join(f"{nodes[p].pc}:{k}" for p, k in sorted(n.preds.items())
                          if nodes[p].kind != "chain" or k != "chain")
            sd = ",".join(str(nodes[m].pc) for m in sorted(n.sdeps))
            print(f"  {n.pc:6d} {n.kind:5s} dur {n.dur:6d} S {n.S:6d} "
                  f"{n.label:32s} R{n.R} W{n.W} xr{sorted(n.xr)} "
                  f"xw{sorted(n.xw)} red={int(n.redundant)} "
                  f"preds[{pr}] sdeps[{sd}]")
        return

    # ---- V0: the shipped order, as a check of the stream extraction ----
    v0, tmed = today_replay(nodes, groups, "measured")
    v0m, _ = today_replay(nodes, groups, "median")
    print(f"\n=== V0 replay of the SHIPPED order (one lane, global FENCE)")
    print(f"    per-group measured tau: {v0} cyc = {ms(v0):.3f} ms "
          f"(body window sum {body_cyc}; delta {v0 - body_cyc})")
    print(f"    single median tau {tmed}: {v0m} cyc = {ms(v0m):.3f} ms "
          f"(delta {v0m - body_cyc} = {100.0 * (v0m - body_cyc) / body_cyc:+.4f} %)")

    nred = build_edges(nodes, False, 1, 1)
    red_cyc = sum(n.dur for n in nodes if n.kind == "movx" and n.redundant)
    nmovx = sum(1 for n in nodes if n.kind == "movx")
    print(f"\n=== redundant MOVX (same chan, same source, source unwritten "
          f"since): {nred} of {nmovx}, window sum {red_cyc} cyc = "
          f"{ms(red_cyc):.3f} ms")
    rc = collections.Counter()
    for n in nodes:
        if n.kind == "movx" and n.redundant:
            rc[(mvs[n.mv]["lt"], mvs[n.mv]["cls"])] += 1
    print("    by class: " + ", ".join(f"{k[0]}/{k[1]} {v}"
                                        for k, v in sorted(rc.items())))

    if args.mode in ("census", "all"):
        for fk, chain in (("A", "order"), ("B", "free")):
            build_edges(nodes, False, 1, 1, chain)
            census(nodes, groups, mvs, fk)
    if args.mode in ("sched", "all"):
        run_sched(nodes, groups, mvs, body_cyc, rows)


def run_sched(nodes, groups, mvs, body_cyc, rows):
    # per-class exposure TODAY = the FENCE windows (the lane waits for them)
    today_cls = collections.Counter()
    for g in groups:
        mv = mvs[g["mv"]]
        today_cls[(mv["lt"], mv["cls"])] += g["fwin"]
    # rebalancing: each group's streams at the mean of its channels, spread
    # over all four (BN_CENSUS.md §9.1's 2.40x construction, per group)
    rebal = {}
    for g in groups:
        tot = sum(nodes[m].S for m in g["mvgos"])
        for m in g["mvgos"]:
            rebal[m] = tot // len(g["mvgos"]) if len(g["mvgos"]) == 4 \
                else tot // 4
    variants = [
        ("S0", "SW only: reorder, global FENCE", 1, "global",
         False, 1, 1, False),
        ("S1", "SW only: S0 + redundant-MOVX elision", 1, "global",
         True, 1, 1, False),
        ("R1", "RTL: per-channel fence (S1 + fence mask)", 1, "perchan",
         True, 1, 1, False),
        ("R2", "RTL: R1 + XWIN/RES double buffer", 1, "perchan",
         True, 2, 2, False),
        ("R3", "RTL: R2 + MOVX broadcast (one MOVX per matvec)", 1,
         "perchan", True, 2, 2, True),
        ("B2", "BOUND: R2 + second scratch port (mover lane || layer lane)",
         2, "perchan", True, 2, 2, False),
    ]
    # the global-FENCE (software-only) rows are a HEURISTIC search: three
    # issue rules are tried and the best feasible schedule is kept
    heur = (("pc/weak", {"prio": "pc", "guard": "weak"}),
            ("bl/weak", {"prio": "bl", "guard": "weak"}),
            ("bl/strong", {"prio": "bl", "guard": "strong"}))
    forms = (("A", "order"), ("B", "free"))
    print("\n=== D2: LIST-SCHEDULE VARIANTS (token 4 durations)")
    print("    form A = layer-chain records kept in program order (i3); "
          "form B = layer commands reorderable under named internal "
          "resources (named_cmd)")
    print(f"    today (body window sum): {body_cyc} cyc = {ms(body_cyc):.3f} ms"
          f" = {1000.0 / ms(body_cyc):.3f} tok/s (TB)")
    results = {}
    first_movx = set()
    for mv in mvs:
        if mv["movx"]:
            first_movx.add(mv["movx"][0])
    for fk, chain in forms:
        for (tag, desc, lanes, fence, elide, xd, rd, bcast) in variants:
            build_edges(nodes, elide, xd, rd, chain)
            saved = None
            if bcast:
                # one MOVX per matvec: the first MOVX of each run keeps its
                # window, its siblings cost 0 (they still carry their own
                # channel's dependencies)
                saved = [n.dur for n in nodes]
                for i, n in enumerate(nodes):
                    if n.kind == "movx" and not n.redundant:
                        mvk = n.mv
                        live_first = [x for x in mvs[mvk]["movx"]
                                      if not nodes[x].redundant]
                        if live_first and i != live_first[0]:
                            n.dur = 0
            for rb_tag, rb in (("", None), ("+rebal", rebal)):
                hs = heur if fence == "global" else (("bl", {"prio": "bl"}),)
                best = None
                for hname, h in hs:
                    cfg = {"lanes": lanes, "fence": fence, "elide": elide,
                           "hoist_guard": True}
                    cfg.update(h)
                    mk, st, fi, se, stt = schedule(nodes, groups, cfg, rb)
                    if fence == "global":
                        print(f"      ({fk}:{tag}{rb_tag} heuristic {hname}: "
                              f"{mk} cyc = {ms(mk):.3f} ms)")
                    if best is None or mk < best[0]:
                        best = (mk, stt, hname)
                mk, stt, hname = best
                key = f"{fk}:{tag}{rb_tag}"
                results[key] = (mk, stt)
                sp = body_cyc / mk
                bms = ms(mk) * BOARD_MS / TB_MS
                print(f"  {key:11s} {mk:9d} cyc = {ms(mk):8.3f} ms  "
                      f"{1000.0 / ms(mk):6.3f} tok/s(TB)  x{sp:.4f}  "
                      f"board-scaled {bms:8.3f} ms {1000.0 / bms:6.3f} tok/s"
                      f"  fences {stt['fences']}  rule {hname}   [{desc}]")
                if rb is None:
                    print(f"      POSTCHECK: {stt['post'][0]} edges + "
                          f"{stt['post'][1]} channel/lane checks, "
                          f"0 violations (independent of the scheduler)")
                    print("      lane idle by binding reason: " + ", ".join(
                        f"{k} {ms(v):.3f}ms"
                        for k, v in sorted(stt["idle"].items())))
                    ex = collections.Counter()
                    for mvk, v in stt["idle_by_mv"].items():
                        mv = mvs[mvk]
                        ex[(mv["lt"], mv["cls"])] += v
                    results[key + ":ex"] = ex
            if saved is not None:
                for n, d in zip(nodes, saved):
                    n.dur = d

    # the one-lane floor and the dependency-only critical path
    lane_sum_noelide = sum(n.dur for n in nodes
                           if n.kind not in ("fence", "arg"))
    build_edges(nodes, True, 2, 2, "free")
    lane_sum = sum(n.dur for n in nodes if n.kind not in ("fence", "arg")
                   and not n.redundant)
    N = len(nodes)
    ef = [0] * N
    se = [0] * N
    via = [None] * N          # (pred, is_stream) that set ef
    for i, n in enumerate(nodes):
        if n.kind in ("fence", "arg") or n.redundant:
            continue
        r, v = 0, None
        for p in n.preds:
            if nodes[p].kind not in ("fence", "arg") and not nodes[p].redundant:
                if ef[p] > r:
                    r, v = ef[p], (p, False)
        for m in n.sdeps:
            x = se[m] + groups[nodes[m].grp]["tau"]
            if x > r:
                r, v = x, (m, True)
        ef[i] = r + n.dur
        via[i] = v
        if n.kind == "mvgo":
            se[i] = ef[i] + n.S
    cp = max(max(ef), max(se))
    # walk the critical path back and split it by what it is made of
    end = max(range(N), key=lambda i: ef[i])
    parts = collections.Counter()
    k = end
    while k is not None:
        n = nodes[k]
        cls = n.kind if n.kind != "chain" else (
            "layer-cmd" if n.op == SF.OP_CMD else "other-chain")
        parts[cls] += n.dur
        v = via[k]
        if v is None:
            break
        p, is_s = v
        if is_s:
            mv = mvs[nodes[p].mv]
            parts[f"stream:{mv['lt']}/{mv['cls']}"] += \
                nodes[p].S + groups[nodes[p].grp]["tau"]
        k = p
    print("    critical path made of (ms): " + ", ".join(
        f"{k2} {ms(v2):.3f}" for k2, v2 in sorted(parts.items(),
                                                  key=lambda kv: -kv[1])))
    print(f"    critical path: streams {ms(sum(v2 for k2, v2 in parts.items() if k2.startswith('stream'))):.3f} ms, "
          f"everything else {ms(sum(v2 for k2, v2 in parts.items() if not k2.startswith('stream'))):.3f} ms")
    # the priority rule matters: form B, S1, program-order priority
    build_edges(nodes, True, 1, 1, "free")
    mk, *_ = schedule(nodes, groups, {"lanes": 1, "fence": "global",
                                      "elide": True, "hoist_guard": True,
                                      "prio": "pc"})
    print(f"    [priority check] B:S1 with PROGRAM-ORDER priority instead of "
          f"bottom level: {mk} cyc = {ms(mk):.3f} ms")
    print(f"\n    ONE-LANE FLOOR: lane work (every non-FENCE window) "
          f"{lane_sum_noelide} cyc = {ms(lane_sum_noelide):.3f} ms "
          f"(x{body_cyc / lane_sum_noelide:.4f}); with redundant-MOVX "
          f"elision {lane_sum} cyc = {ms(lane_sum):.3f} ms "
          f"(x{body_cyc / lane_sum:.4f})")
    print(f"    dependency critical path (unlimited lanes, form B, R2 "
          f"buffers, elision): {cp} cyc = {ms(cp):.3f} ms "
          f"(x{body_cyc / cp:.4f})")

    # exposure by class
    for fk, _chain in forms:
        print(f"\n=== D2 sensitivity, form {fk}: exposed stream wait by class "
              f"(ms/token) — today's FENCE windows vs each variant's lane "
              f"idle-on-stream")
        keys = sorted(today_cls,
                      key=lambda k: (["DN", "GQA", "HEAD"].index(k[0]), k[1]))
        tags = ("S0", "S1", "R1", "R2", "R3", "B2")
        print("  type class       today   " + "  ".join(f"{t:>7s}"
                                                        for t in tags))
        tots = collections.Counter()
        for k in keys:
            cells = []
            for t in tags:
                v = results[f"{fk}:{t}:ex"].get(k, 0)
                tots[t] += v
                cells.append(f"{ms(v):7.3f}")
            tots["today"] += today_cls[k]
            print(f"  {k[0]:4s} {k[1]:9s} {ms(today_cls[k]):8.3f}   "
                  + "  ".join(cells))
        print(f"  ALL  {'':9s} {ms(tots['today']):8.3f}   " + "  ".join(
            f"{ms(tots[t]):7.3f}" for t in tags))

    # T -> 511: the attention phase grows.  RD9_GATE.md §8.7 measures the
    # board's decode step at 147.9 ms at T ~ 520 against 137.7 ms at T ~ 30
    # (evidence/qwen9b/g6/RD9_GATE.md:1213-1214).  That growth (+10.2 ms,
    # board) is re-expressed at TB scale (x TB_MS/BOARD_MS) and added to the
    # token's ATTN commands in equal parts.
    grow_ms = (147.9 - 137.7) * TB_MS / BOARD_MS
    grow = int(round(grow_ms * ACLK_HZ / 1e3))
    attn = [i for i, n in enumerate(nodes) if n.label == "ATTN"]
    print(f"\n=== T -> 511 sensitivity: +{grow} cyc = +{ms(grow):.3f} ms "
          f"(TB scale) over {len(attn)} ATTN commands")
    save = [n.dur for n in nodes]
    for i in attn:
        nodes[i].dur += grow // len(attn)
    bc = sum(n.dur for n in nodes)
    for fk, chain in forms:
        for (tag, lanes, fence, elide, xd, rd) in (
                ("S1", 1, "global", True, 1, 1),
                ("R2", 1, "perchan", True, 2, 2)):
            build_edges(nodes, elide, xd, rd, chain)
            mk = best_schedule(nodes, groups, lanes, fence, elide)
            print(f"  T~511 {fk}:{tag}: today {bc} cyc = {ms(bc):.3f} ms "
                  f"({1000.0 / ms(bc):.3f} tok/s TB); {mk} cyc = "
                  f"{ms(mk):.3f} ms ({1000.0 / ms(mk):.3f} tok/s TB)  "
                  f"x{bc / mk:.4f}")
    for n, d in zip(nodes, save):
        n.dur = d

    print("\n=== robustness: S1 and R2 on tokens 5 and 6 durations")
    for t in (5, 6):
        for i, n in enumerate(nodes):
            n.dur = rows[t][n.pc][2]
            n.cyc0 = rows[t][n.pc][1]
        # re-merge the ARG windows into their CMD, as build_nodes did
        pend = 0
        for n in nodes:
            if n.kind == "arg":
                pend += n.dur
                n.dur = 0
            elif n.op == SF.OP_CMD:
                n.dur += pend
                pend = 0
        g2, _ = stream_durations(nodes, rows[t])
        for k, g in enumerate(g2):
            groups[k]["tau"] = g["tau"]
        bc = sum(n.dur for n in nodes)
        for fk, chain in forms:
            for (tag, lanes, fence, elide, xd, rd) in (
                    ("S1", 1, "global", True, 1, 1),
                    ("R2", 1, "perchan", True, 2, 2)):
                build_edges(nodes, elide, xd, rd, chain)
                mk = best_schedule(nodes, groups, lanes, fence, elide)
                print(f"  token {t}: today {bc} cyc = {ms(bc):.3f} ms; "
                      f"{fk}:{tag} {mk} cyc = {ms(mk):.3f} ms  "
                      f"x{bc / mk:.4f}")


if __name__ == "__main__":
    main()
