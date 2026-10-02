#!/usr/bin/env python3
"""sd1_count.py — Task SD1 deliverable 1: count and reconcile the two streams.

  FABLE5_MODEL=9b python evidence/qwen9b/sd/sd1_count.py

1. Counts every layer command of the host-driven script
   (tb/scripts/w9/model_9b_s1.txt) per forward step, and of the sequencer
   stream (tb/scripts/w9/model_9b_s1.e4.seq) per written-out body, by
   (command, ALU sub-op / VN mode, count) — sd1_common.key_of.
2. Checks the per-token lists are identical across steps / bodies, so a
   per-token count is well defined on each side.
3. Prints the per-opcode and per-key difference.
4. DERIVES the difference from the geometry (ref/layer_ref.py) and the
   emitter rules (ref/seq_format.py SeqEmitter: _fuse/_emit_matvec_4chan,
   _dn_block_float, _emit_attn_block; chunking by gen_layer_script.CHUNK,
   seq_format.split_rows/res_chunks/CHUNK_ROWS) and asserts the derivation
   equals the count, key by key.
5. Prints one concrete example of each substitution from each stream
   (.txt line numbers, .e4 record indices).

Read-only: opens the artifacts, writes stdout only.
"""
import collections
import json
import math
import sys

import sd1_common as C
from sd1_common import SF, GLS, LR

LDV, LNH, HD, NQ, NKV = LR.LDV, LR.LNH, LR.HD, LR.NQ, LR.NKV
H, FFN = LR.H, LR.FFN
CHUNK = GLS.CHUNK                 # .txt W32 injection chunk
CHUNK_ROWS = SF.CHUNK_ROWS        # .e4 engine run / MOVY chunk
meta = json.load(open(C.SEQJSON))
NCH = int(meta["nch"])
types = LR.CFG["layer_types"]
N_DN = sum(1 for t in types if t != "full_attention")
N_AT = sum(1 for t in types if t == "full_attention")
VOCAB = LR.CFG["vocab_size"]

print("=== SD1 count: inputs")
print(f"  .txt  {C.TXT}\n        sha256 {C.sha256(C.TXT)}")
s_sha = C.sha256(C.SEQ)
print(f"  .seq  {C.SEQ}\n        sha256 {s_sha}")
print(f"  .seq.json stream_sha256 {meta['stream_sha256']}  "
      f"{'MATCH' if s_sha == meta['stream_sha256'] else 'MISMATCH'}")
assert s_sha == meta["stream_sha256"]
print(f"  geometry: H={H} FFN={FFN} layers={len(types)} = {N_DN} DN + "
      f"{N_AT} GQA; LNH={LNH} LNKH={LR.LNKH} LDK={LR.LDK} LDV={LDV} "
      f"CONV_DIM={LR.CONV_DIM}; NQ={NQ} NKV={NKV} HD={HD}; vocab={VOCAB}")
print(f"  chunking: .txt CHUNK={CHUNK} (ref/gen_layer_script.py), .e4 "
      f"CHUNK_ROWS={CHUNK_ROWS} nch={NCH} profile={meta['profile']} "
      f"dyn_ka={meta['dyn_ka']}")

# ------------------------------------------------------------------ .txt
t_steps = collections.defaultdict(collections.Counter)
t_first = {}                      # (step, key) -> first line number
t_seq = collections.defaultdict(list)   # step 1 only: [(line, key, words)]
for (st, ln, op, a0, a1, a2) in C.txt_steps():
    k = C.key_of(op, a0, a1, a2)
    t_steps[st][k] += 1
    t_first.setdefault((st, k), ln)
    if st == 1:
        t_seq[1].append((ln, k, (op, a0, a1, a2)))
print("\n=== .txt: layer commands per forward step (step 0 = preamble)")
for st in sorted(t_steps):
    print(f"  step {st}: {sum(t_steps[st].values())} commands")
ref = t_steps[1]
for st in range(2, 7):
    assert t_steps[st] == ref, f".txt step {st} differs from step 1"
print("  steps 1..6 carry IDENTICAL (key -> count) multisets: per-token "
      "counts are well defined")

# ------------------------------------------------------------------ .e4
recs = C.seq_records()
e_bodies = collections.defaultdict(collections.Counter)
e_first = {}
e_seq = collections.defaultdict(list)
for (b, i, op, a0, a1, a2) in C.seq_cmds(recs):
    k = C.key_of(op, a0, a1, a2)
    e_bodies[b][k] += 1
    e_first.setdefault((b, k), i)
    if b == 1:
        e_seq[1].append((i, k, (op, a0, a1, a2)))
emb_idx = [i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB]
print(f"\n=== .e4: {len(recs)} records; EMB records at {emb_idx}")
for b in sorted(e_bodies):
    print(f"  body {b}: {sum(e_bodies[b].values())} CMD records")
eref = e_bodies[1]
for b in range(2, 5):
    assert e_bodies[b] == eref, f".e4 body {b} differs from body 1"
print("  bodies 1..4 carry IDENTICAL multisets (body 4 is the TCNT_SEQ=3 "
      "loop body, so tokens 1..6 all run this list)")

# ------------------------------------------------------------------ tables
def by_op(cnt):
    o = collections.Counter()
    for k, v in cnt.items():
        o[k[0]] += v
    return o

to, eo = by_op(ref), by_op(eref)
print("\n=== per token, per layer command (the census's table, recounted)")
print(f"  {'cmd':8s} {'.txt':>8s} {'.e4':>8s} {'e4-txt':>8s}")
for op in sorted(set(to) | set(eo), key=lambda o: -max(to[o], eo[o])):
    print(f"  {op:8s} {to[op]:8d} {eo[op]:8d} {eo[op] - to[op]:+8d}")
print(f"  {'TOTAL':8s} {sum(to.values()):8d} {sum(eo.values()):8d} "
      f"{sum(eo.values()) - sum(to.values()):+8d}")

print("\n=== per token, per KEY — only the keys whose counts differ")
diff = {}
for k in sorted(set(ref) | set(eref), key=str):
    if ref[k] != eref[k]:
        diff[k] = eref[k] - ref[k]
        print(f"  {str(k):40s} .txt {ref[k]:6d}  .e4 {eref[k]:6d}  "
              f"delta {diff[k]:+6d}")
same_alu = sum(v for k, v in ref.items() if k[0] == "ALU" and ref[k] == eref[k])
same_vn = sum(v for k, v in ref.items() if k[0] == "VN" and ref[k] == eref[k])
print(f"  (ALU commands in keys with EQUAL counts on both sides: {same_alu}; "
      f"VN: {same_vn})")

# ------------------------------------------------------------------ derive
print("\n=== DERIVATION from the geometry and the emitter rules")
cdiv = lambda a, b: -(-a // b)


def e4_chunks(nrows):
    """ALU commands the 4-chan emitter issues for a staged (sub 6/10)
    matvec: one per (channel, res_chunk) — _emit_parallel_matvec."""
    return sum(len(SF.res_chunks(r0, n, CHUNK_ROWS))
               for (r0, n) in SF.split_rows(nrows, NCH) if n > 0)


# fused dequants (ALU sub 1/9 after a W32): .txt issues ceil(rows/CHUNK)
# ALU per matvec (gen_layer_script.inject_dequant / mlp_block's up loop);
# the .e4 issues NONE (SeqEmitter._emit_parallel_matvec: fused -> MOVY).
dn_fused = {"in_qkv": LR.CONV_DIM, "in_z": LR.LVD, "in_b": LNH,
            "in_a": LNH, "out": H, "mlp.up (op9)": FFN, "mlp.down": H}
at_fused = {"q_proj": 2 * NQ * HD, "k_proj": NKV * HD, "v_proj": NKV * HD,
            "o_proj": H, "mlp.up (op9)": FFN, "mlp.down": H}
f_dn = sum(cdiv(r, CHUNK) for r in dn_fused.values())
f_at = sum(cdiv(r, CHUNK) for r in at_fused.values())
print(f"  (a) fused dequant ALUs removed: DN layer "
      + " + ".join(f"{k} {cdiv(r, CHUNK)}" for k, r in dn_fused.items())
      + f" = {f_dn}")
print(f"      GQA layer "
      + " + ".join(f"{k} {cdiv(r, CHUNK)}" for k, r in at_fused.items())
      + f" = {f_at}")
A = -(N_DN * f_dn + N_AT * f_at)
print(f"      per token: -({N_DN} x {f_dn} + {N_AT} x {f_at}) = {A}")
# SILU32 (mlp.gate, ALU sub 6) re-chunked per channel
s_txt, s_e4 = cdiv(FFN, CHUNK), e4_chunks(FFN)
B = (N_DN + N_AT) * (s_e4 - s_txt)
print(f"  (b) SILU32 re-chunk: .txt ceil({FFN}/{CHUNK}) = {s_txt} per layer, "
      f".e4 split_rows({FFN},{NCH}) x res_chunks(<= {CHUNK_ROWS}) = {s_e4}; "
      f"{N_DN + N_AT} x ({s_e4} - {s_txt}) = {B:+d}")
# DN block-float pair: SHIFT32 -> DYNQ16 (ALU for ALU), SCALE -> VN EPS-NORM
Cc = -N_DN * LNH
print(f"  (c) DN block-float pair: per head SHIFT32 -> DYNQ16 (0) and SCALE "
      f"-> VN EPS-NORM (-1 ALU, +1 VN): {N_DN} x {LNH} = {Cc} ALU, "
      f"{-Cc:+d} VN")
# attention: NQ EMUL32 -> probe + real
D = -N_AT * (NQ - 2)
print(f"  (d) gated attention: {NQ} EMUL32 -> 1 probe + 1 real per GQA "
      f"layer: {N_AT} x ({NQ} - 2) = {D}")
# LM head AMAX32 chunks
h_txt = cdiv(VOCAB, 2048)
h_e4 = len(SF.res_chunks(0, VOCAB, CHUNK_ROWS))
E = h_e4 - h_txt
print(f"  (e) LM-head AMAX32: .txt ceil({VOCAB}/2048) = {h_txt}, .e4 "
      f"res_chunks = {h_e4}: {E:+d}")
dALU = A + B + Cc + D + E
dVN = -Cc
print(f"  DERIVED  dALU = {A} {B:+d} {Cc:+d} {D:+d} {E:+d} = {dALU}   "
      f"dVN = {dVN:+d}   dTOTAL = {dALU + dVN:+d}")
print(f"  COUNTED  dALU = {eo['ALU'] - to['ALU']}   dVN = "
      f"{eo['VN'] - to['VN']:+d}   dTOTAL = "
      f"{sum(eo.values()) - sum(to.values()):+d}")
assert dALU == eo["ALU"] - to["ALU"] and dVN == eo["VN"] - to["VN"]
assert dALU + dVN == sum(eo.values()) - sum(to.values())

# key-level expectation
exp = collections.Counter()
for (rows_map, nl) in ((dn_fused, N_DN), (at_fused, N_AT)):
    for name, rows in rows_map.items():
        sub = "SHIFT32W" if "op9" in name else "SHIFT32"
        c = 0
        while c < rows:
            m = min(CHUNK, rows - c)
            exp[("ALU", sub, m)] -= nl
            c += m
exp[("ALU", "SHIFT32", LDV)] -= N_DN * LNH
exp[("ALU", "DYNQ16", LDV)] += N_DN * LNH
exp[("ALU", "SCALE", LDV)] -= N_DN * LNH
exp[("VN", "EPS-NORM", LDV)] += N_DN * LNH
exp[("ALU", "EMUL32", HD)] -= N_AT * NQ
exp[("ALU", "EMUL32", NQ * HD, "probe")] += N_AT
exp[("ALU", "EMUL32", NQ * HD)] += N_AT
for (r0, n) in SF.split_rows(FFN, NCH):
    for (_c0, rc) in SF.res_chunks(r0, n, CHUNK_ROWS):
        exp[("ALU", "SILU32", rc)] += N_DN + N_AT
c = 0
while c < FFN:
    m = min(CHUNK, FFN - c)
    exp[("ALU", "SILU32", m)] -= N_DN + N_AT
    c += m
exp = {k: v for k, v in exp.items() if v}
print("  key-level: derived vs counted")
ok = True
for k in sorted(set(exp) | set(diff), key=str):
    d0, d1 = exp.get(k, 0), diff.get(k, 0)
    ok &= d0 == d1
    print(f"    {str(k):40s} derived {d0:+6d}  counted {d1:+6d}  "
          f"{'OK' if d0 == d1 else 'MISMATCH'}")
assert ok, "key-level derivation does not match the count"
print("  RECONCILED EXACTLY, key by key.")

# ------------------------------------------------------------------ examples
print("\n=== EXAMPLES (step 1 of the .txt, body 1 of the .e4)")


def show_txt(ln, k, w):
    op, a0, a1, a2 = w
    print(f"    .txt line {ln}: C {op:x} {a0:x} {a1:x} {a2:x}   -> {k}")


def show_e4(i, k):
    for j in range(i - 3, i + 1):
        print(f"    .e4 rec {j}: {SF.disasm(recs[j], j)}")
    print(f"      -> {k}")


tl = t_seq[1]
el = e_seq[1]
# (c) the first DN head pair
for j, (ln, k, w) in enumerate(tl):
    if k == ("ALU", "SHIFT32", LDV):
        print("  (c) DN head 0 of the first DN layer — .txt SHIFT32 k_h + "
              "SCALE m_q15:")
        show_txt(ln, k, w)
        show_txt(*tl[j + 1])
        break
for j, (i, k, w) in enumerate(el):
    if k == ("ALU", "DYNQ16", LDV):
        print("      .e4 DYNQ16 + VN EPS-NORM (k from XRF[1]):")
        show_e4(i, k)
        show_e4(el[j + 1][0], el[j + 1][1])
        break
# (a) the first fused dequant
for j, (ln, k, w) in enumerate(tl):
    if k[:2] == ("ALU", "SHIFT32") and k[2] == CHUNK:
        print("  (a) the first fused dequant — .txt SHIFT32 over a host W32 "
              "chunk (the in_qkv matvec's first 2048 rows):")
        show_txt(ln, k, w)
        break
first_movy = next(i for i in range(emb_idx[0], len(recs))
                  if recs[i].opcode == SF.OP_MOVY)
print("      .e4: the same rows arrive by MVGO x4 (no-wait) + FENCE + "
      "MOVY x4 — no ALU command at all:")
g0 = first_movy
while recs[g0 - 1].opcode in (SF.OP_MVGO, SF.OP_FENCE, SF.OP_MOVX):
    g0 -= 1
for j in range(g0, first_movy + 4):
    print(f"    .e4 rec {j}: {SF.disasm(recs[j], j)}")
# (d) the first gated-attention block
for j, (ln, k, w) in enumerate(tl):
    if k == ("ALU", "EMUL32", HD):
        print(f"  (d) the first gated-attention EMUL32 (head 0 of {NQ}, "
              f"k_a as a literal):")
        show_txt(ln, k, w)
        break
for j, (i, k, w) in enumerate(el):
    if k == ("ALU", "EMUL32", NQ * HD, "probe"):
        print("      .e4 probe + real pass over all heads (k_a via XRF[2]):")
        show_e4(i, k)
        show_e4(el[j + 1][0], el[j + 1][1])
        break
# (b) SILU32 re-chunk
for j, (i, k, w) in enumerate(el):
    if k == ("ALU", "SILU32", FFN // NCH - CHUNK_ROWS):
        print("  (b) the first SILU32 1024-row chunk (the 4-chan re-chunk):")
        show_e4(i, k)
        break
print("\nSD1_COUNT: PASS")
