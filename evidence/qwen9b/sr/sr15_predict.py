#!/usr/bin/env python3
"""sr15_predict.py — Task SR15: the predictions for the R2 board session,
committed and run BEFORE the first R2 board run (before the R2 bitstream is
even programmed).  No device.  Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.

Inputs (read from the committed JSONs, never re-typed):
  * n807 — SR8's chat511 at --seq-rtl r1 on the R1 bitstream (the rate every
    R2 prediction scales from): evidence/qwen9b/sr/n807_sr8_r1_chat511.json.
  * n806 — SR8's chat511 r0 form B on the R1 bitstream (the control arm).
  * n808 / n809 — SR8's 6-token stream census r1 / r0-B on the R1 bitstream.
  * n805 — SR8's RD9 §7 lockstep device ms (shipped order) on the R1 bitstream.
  * T constants, each cited at its definition below.

THREE predictions (the controller addendum; SR8's lesson: at ctx ~510 the
saving is a fixed number of ms per launch, not a ratio, so the ABSOLUTE form
is PRIMARY):
  P1' (PRIMARY, absolute): n807's lite/full ms minus the absolute per-launch
     saving of r2 over r1 for the CHAT IMAGES.  WHICH saving: no chip-TB run
     of the r2 chat images exists (SR13b_HOST_R2.md, "NOT established"), so it is
     DERIVED from the static model of both image lineages at position 0 —
     r1 lite 25,195,119 / full 27,135,354 cyc (n601_r1_pins.log:9, :15) minus
     r2 lite 24,341,703 / full 26,131,018 cyc (n1351_sr13b_r2_pins.log:9, :15)
     — the same model on both sides (its r1 image makespans sat +0.13 % /
     +0.14 % under the chip TB, n588_sr5b_chat_compare.log:10-11, so the
     error largely cancels in the difference).  Printed beside it for
     reference (NOT a prediction): the stream-scaled saving, SR13a's token-4
     body r1 27,163,998 (n570_sr5_derive.log:36) minus r2 26,171,253
     (n1349g_sr13a_derive.log:42) per launch.
  P2' (ratio): n807 / 1.0379 — the chip TB's whole-run R2-vs-R1
     (n1349g_sr13a_derive.log:24).
  P3' (the census, stream level): n808's r1 ms/token x (26,171,253 /
     27,163,998) — the TB's measured r2/r1 token-4 body ratio (SR13a vs
     SR5b); the form that matched to four digits for R1.
Controls on the R2 bitstream: r0-B chat = n806, r1 chat = n807, r1/r0-B
census = n808/n809, lockstep device ms = n805's — each HELD at +-0.5 % (the
TB says R2 moves neither shipped nor R1 by a cycle, SR13a rung 1); a
movement > +-0.5 % on r1 is REPORTED, not a stop.  build_041 control = n802.
Band method (SR5b's, as SR8): |measured/predicted - 1| <= 0.5 % HELD, <= 2 %
HELD LOOSELY, else MISSED.  The model is not a gate: a MISS is reported, not a
stop.  The tokens ARE the gate (fail-closed; a difference ends the session).
"""
import json
import os
import statistics as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SR = "evidence/qwen9b/sr/"
F = 250e6
REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]   # 083 first 9
STATIC_R1 = {"lite": 25195119, "full": 27135354}     # n601_r1_pins.log:9, :15
STATIC_R2 = {"lite": 24341703, "full": 26131018}     # n1351_sr13b_r2_pins.log:9, :15
TB_IMG_R1 = {"lite": 25228219, "full": 27173524}     # n588:10, n588:11 (chip TB)
BODY_R1 = 27163998                                   # n570_sr5_derive.log:36
BODY_R2 = 26171253                                   # n1349g_sr13a_derive.log:42
TB_R2_VS_R1 = 1.0379                                 # n1349g_sr13a_derive.log:24
MODEL_TOKS_R2 = 9.144        # spec §3.1 R1+R2, form B (seq-rtl-round-design.md:497)


def J(p):
    return json.load(open(os.path.join(ROOT, p)))


def chat(path):
    j = J(path)
    out = {}
    for kind in ("lite", "full"):
        L = [r for r in j["launches"] if r["image"] == kind]
        out[kind] = (len(L), st.mean(r["perf"]["cyc"] for r in L) / F * 1e3)
    ids = [t for r in j["launches"] for t in (r["tokens"] or [])]
    return out, ids


def stream_ms(path):
    j = J(path)
    return j["perf"]["cyc"] / j["ntok"] / F * 1e3, j["tokens"], j["want"]


def bands(p):
    return (f"HELD {p * 0.995:.4f}..{p * 1.005:.4f}; LOOSE {p * 0.98:.4f}.."
            f"{p * 1.02:.4f}; tok/s at centre {1e3 / p:.3f}")


n807, i807 = chat(SR + "n807_sr8_r1_chat511.json")
n806, i806 = chat(SR + "n806_sr8_r1bit_r0B_chat511.json")
n802, i802 = chat(SR + "n802_sr8_control_041_chat511.json")
assert i807 == REF and i806 == REF and i802 == REF, "reference sessions' ids differ"
print(f"inputs: n807 (R1 bitstream, r1), n806 (R1 bitstream, r0 form B), n802 "
      f"(build_041 form B) ids == REF {REF}")
print("| kind | n | n806 r0-B ms | n807 r1 ms | model saving r1->r2 ms | P1' = n807 - saving | P2' = n807/1.0379 | P1' x r0-B (n806) | P1' tok/s |")
print("|---|---|---|---|---|---|---|---|---|")
P = {}
for kind in ("lite", "full"):
    n, r1 = n807[kind]
    b = n806[kind][1]
    save = (STATIC_R1[kind] - STATIC_R2[kind]) / F * 1e3
    p1 = r1 - save
    p2 = r1 / TB_R2_VS_R1
    P[kind] = {"P1'": p1, "P2'": p2}
    print(f"| {kind} | {n} | {b:.4f} | {r1:.4f} | {save:.4f} | {p1:.4f} | "
          f"{p2:.4f} | x{b / p1:.4f} | {1e3 / p1:.3f} |")
for kind in ("lite", "full"):
    for tag in ("P1'", "P2'"):
        print(f"  {kind} {tag} bands: {bands(P[kind][tag])}")
sb = (BODY_R1 - BODY_R2) / F * 1e3
print(f"reference only (NOT a prediction): the stream-scaled saving r1->r2 "
      f"token-4 body {BODY_R1:,} - {BODY_R2:,} = {BODY_R1 - BODY_R2:,} cyc = "
      f"{sb:.4f} ms/launch -> lite {n807['lite'][1] - sb:.4f}, full "
      f"{n807['full'][1] - sb:.4f} ms")
print("SR8's silicon retention of the TB's absolute R1 saving (informational, "
      "for reading P1'):")
for kind in ("lite", "full"):
    tb = (26052754 if kind == "lite" else 28619539) - TB_IMG_R1[kind]  # n588:10-11
    si = n806[kind][1] - n807[kind][1]
    print(f"  {kind}: TB R1 saving {tb / F * 1e3:.4f} ms (n588), silicon "
          f"n806-n807 {si:.4f} ms, retained {si / (tb / F * 1e3):.4f}")
print("controls (each HELD at +-0.5 %; R2 moves neither shipped nor R1 on the TB):")
for tag, src in (("n1502 build_041 form B = n802", n802),
                 ("n1506 R2 bitstream r0 form B = n806", n806),
                 ("n1507 R2 bitstream r1 = n807", n807)):
    for kind in ("lite", "full"):
        b = src[kind][1]
        print(f"  {tag} {kind} {b:.4f} ms: HELD {b * 0.995:.4f}..{b * 1.005:.4f}")
m808, t808, w808 = stream_ms(SR + "n808_sr8_census_r1.json")
m809, t809, w809 = stream_ms(SR + "n809_sr8_census_r0B.json")
assert t808 == w808 and t809 == w809
p3 = m808 * BODY_R2 / BODY_R1
print(f"P3' (census, 6-token model_9b_s1 form B r2, per token): n808 "
      f"{m808:.4f} ms/token x ({BODY_R2:,} / {BODY_R1:,}) = {p3:.4f} ms/token "
      f"= {1e3 / p3:.3f} tok/s; {bands(p3)}")
print(f"  census controls on the R2 bitstream: r1 = n808 {m808:.4f}, r0-B = n809 "
      f"{m809:.4f} ms/token (HELD +-0.5 %); r2 vs r1 TB x{BODY_R1 / BODY_R2:.4f}")
ps = 1e3 / MODEL_TOKS_R2
print(f"the model (spec §3.1 R1+R2 form B, board-scaled MODEL, a report): "
      f"{MODEL_TOKS_R2} tok/s = {ps:.4f} ms/token; {bands(ps)}")
ls = [J(SR + f"n805_sr8_r1_model_9b_s{s}.json")["run"]["device_ms"] for s in (1, 2, 3, 4)]
print(f"lockstep (RD9 §7, shipped order) device ms on the R1 bitstream n805: "
      f"{min(ls):.3f}..{max(ls):.3f}; on R2 predicted the same (HELD +-0.5 %)")
print("tokens (the GATE, fail-closed): chat511 ids == REF on every session; the "
      "6-token streams == their .seq.json expect_tokens (G4A §4.1a s1 for every "
      "s1 variant); the lockstep == G4A §4.1a + .chip golden; any difference "
      "ends the session")
print("SR15_PREDICT: DONE")
