#!/usr/bin/env python3
"""sr8_predict.py — Task SR8: the predictions for the R1 board session,
committed and run BEFORE the first R1 board run.  No device.  Run ON SNOKE
through evidence/qwen9b/sr/sr_run.sh.

Inputs (read, never re-typed where a committed JSON carries them):
  * n95 — S1P's form-B chat511 session on build_041 (the rate every R1
    prediction scales from): evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.json.
  * n68 — BM1-T4's shipped-order control on build_041 (for x-shipped):
    evidence/qwen9b/bm/n68_T4_control_041_chat511.json.
  * T constants, each cited at its definition below.

Three predictions for R1 (form B + masked FENCEs, chat511) — ONE rate, three
ways of scaling it, all stated before any R1 run:
  P1 (the controller's addendum, the PRIMARY): n95's mean / 1.054, the chip
     TB's R1-vs-S1-B on the stream (SR5b: x1.0538, n570_sr5_derive.log:21-22).
  P2 per image: n95 / the chip TB's r1-image vs r0-B-image ratio at short
     context (SR5b n588_sr5b_chat_compare.log:10-11: lite x1.0327, full
     x1.0532).
  P3 absolute: n95 minus the TB's absolute per-launch saving (r0-B image
     cycles minus r1 image cycles, n588:10-11), i.e. the saving does not
     scale with the attention time that grows with position.  WHY stated:
     S1P's own precedent — S1 form B saved 16.65 ms/launch on the TB
     (S1T, evidence/qwen9b/ov/S1T_FORMB_IMAGE_TB.md:142-144) and 16.52 (lite)
     / 16.46 (full) on silicon at ctx <= 511 (n68 - n95), a ~1 % miss,
     while the RATIO missed by ~1.5-1.8 % (S1P §3.3).
Band method (SR5b's, the plan's for R1): |measured/predicted - 1| <= 0.5 %
HELD, <= 2 % HELD LOOSELY (attribute), else MISSED.  The model is not a gate
(SR8 acceptance): a MISS is reported, not a stop.  The tokens ARE the gate.
"""
import json
import os
import statistics as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
F = 250e6
REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]   # 083 first 9
R_STREAM = 1.054            # addendum; SR5b x1.0538 (n570_sr5_derive.log:21)
R_IMG = {"lite": 1.0327, "full": 1.0532}            # n588:10, n588:11
TB_R0B = {"lite": 26052754, "full": 28619539}       # n588:10, n588:11
TB_R1 = {"lite": 25228219, "full": 27173524}        # n588:10, n588:11
MODEL_TOKS = 8.811          # spec §3.1 R1, form B (n120_sr0_clock_sens.log:36)
TB_R1_VS_B_STREAM = 1.0538  # n570_sr5_derive.log:21-22


def chat(path):
    j = json.load(open(os.path.join(ROOT, path)))
    out = {}
    for kind in ("lite", "full"):
        L = [r for r in j["launches"] if r["image"] == kind]
        out[kind] = (len(L), st.mean(r["perf"]["cyc"] for r in L) / F * 1e3)
    ids = [t for r in j["launches"] for t in (r["tokens"] or [])]
    return out, ids


n95, ids95 = chat("evidence/qwen9b/ov/n95_s1p_chat511_reordB_041.json")
n68, ids68 = chat("evidence/qwen9b/bm/n68_T4_control_041_chat511.json")
assert ids95 == REF and ids68 == REF, "reference sessions' ids differ"
print(f"inputs: n95 (build_041, form B) and n68 (build_041, shipped) ids == REF {REF}")
print("| kind | n | n68 shipped ms | n95 form B ms | P1 = n95/1.054 | P2 = n95/img | P3 = n95 - TB saving | P1 x shipped | P3 x shipped |")
print("|---|---|---|---|---|---|---|---|---|")
for kind in ("lite", "full"):
    n, b = n95[kind]
    s = n68[kind][1]
    p1 = b / R_STREAM
    p2 = b / R_IMG[kind]
    save = (TB_R0B[kind] - TB_R1[kind]) / F * 1e3
    p3 = b - save
    print(f"| {kind} | {n} | {s:.4f} | {b:.4f} | {p1:.4f} | {p2:.4f} | "
          f"{p3:.4f} (TB saving {save:.4f} ms) | x{s / p1:.4f} | x{s / p3:.4f} |")
    for tag, p in (("P1", p1), ("P2", p2), ("P3", p3)):
        print(f"  {kind} {tag} bands: HELD {p * 0.995:.4f}..{p * 1.005:.4f} ms; "
              f"LOOSE {p * 0.98:.4f}..{p * 1.02:.4f} ms; tok/s at the band "
              f"centre {1e3 / p:.3f}")
print("S1P precedent for P3 (absolute saving, silicon vs TB):")
for kind, (tb_ship, tb_b) in (("lite", (30210292, 26047645)),
                               ("full", (32781847, 28619539))):
    tbs = (tb_ship - tb_b) / F * 1e3
    sis = n68[kind][1] - n95[kind][1]
    print(f"  {kind}: TB saving {tbs:.4f} ms (S1T:142-144), silicon {sis:.4f} ms "
          f"(n68 - n95), silicon/TB {sis / tbs:.4f}")
print("controls:")
for kind in ("lite", "full"):
    b = n95[kind][1]
    print(f"  n802 (build_041 form B, today) and n806 (R1 bitstream, r0 form B): "
          f"{kind} = n95 {b:.4f} ms, HELD +-0.5 % {b * 0.995:.4f}..{b * 1.005:.4f} "
          f"(BM1 precedent: a bitstream alone moved the step -0.0015 %)")
ps = 1e3 / MODEL_TOKS
print(f"stream census (6-token model_9b_s1 form B r1, per token): the model's "
      f"{MODEL_TOKS} tok/s = {ps:.4f} ms/token (board-scaled MODEL); HELD "
      f"{ps * 0.995:.4f}..{ps * 1.005:.4f}, LOOSE {ps * 0.98:.4f}..{ps * 1.02:.4f}")
print(f"stream census r1 vs its r0-B control on the same bitstream: TB "
      f"x{TB_R1_VS_B_STREAM} (n570:21-22); predicted r0-B control "
      f"{ps * TB_R1_VS_B_STREAM:.4f} ms/token")
print("tokens (the GATE, fail-closed): chat511 ids == REF on every session; "
      "the 6-token streams == their .seq.json expect_tokens (G4A §4.1a for "
      "model_9b_s1..s4); any difference ends the session")
print("SR8_PREDICT: DONE")
