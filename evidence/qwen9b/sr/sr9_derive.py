#!/usr/bin/env python3
"""sr9_derive.py — Task SR9 (the docs pass): the three derived figures the
SR15 task review asked the gate doc SR15_R2_BOARD.md to state, printed from
committed inputs so the doc can cite a log line instead of a reviewer's
arithmetic.  No device.  Run ON SNOKE through evidence/qwen9b/sr/sr_run.sh.

  (1) The stream census beside SR13a's TB MODEL as well as the spec's:
      n1509's measured ms/token against SR13a's board-scaled TB figure,
      109.450 ms/token = 9.137 tok/s (n1349g_sr13a_derive.log:25, T), as
      measured/model in tok/s (= model ms / measured ms), the same form as
      n1516:99's 0.9905 against spec §3.1's 9.144.
  (2) P1' with SR13b's CORRECTED static r2 makespans instead of the
      uncorrected ones sr15_predict.py used: the same n1351 lines carry
      "corrected prediction 24377574 cyc" (lite, :9) and "26168056 cyc"
      (full, :15) beside the replay figures 24,341,703 / 26,131,018.  P1'c =
      n807 ms - (static r1 - corrected r2) / 250 MHz, and its band verdict
      against n1508 (SR5b's bands: |m/p - 1| <= 0.5 % HELD).
  (3) The wall-clock gap between the two build_041 control sessions n802
      (SR8) and n1502 (SR15), from their own `=== host … date:` stamps.

Every input is read from a committed file; the constants are cited where
they are defined.  The arithmetic is sr15_predict.py's (chat(), stream_ms()).
"""
import datetime as dt
import json
import os
import re
import statistics as st

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SR = "evidence/qwen9b/sr/"
F = 250e6
STATIC_R1 = {"lite": 25195119, "full": 27135354}     # n601_r1_pins.log:9, :15
TB_MODEL_MS = 109.450                                # n1349g_sr13a_derive.log:25
SPEC_TOKS = 9.144                                    # spec §3.1 (n1516:99)


def P(p):
    return os.path.join(ROOT, p)


def chat(path):
    j = json.load(open(P(path)))
    out = {}
    for kind in ("lite", "full"):
        L = [r for r in j["launches"] if r["image"] == kind]
        out[kind] = st.mean(r["perf"]["cyc"] for r in L) / F * 1e3
    return out


def stream_ms(path):
    j = json.load(open(P(path)))
    assert j["tokens"] == j["want"], path
    return j["perf"]["cyc"] / j["ntok"] / F * 1e3


def corrected_r2():
    txt = open(P(SR + "n1351_sr13b_r2_pins.log")).read().splitlines()
    got = {}
    for kind, ln in (("lite", 9), ("full", 15)):
        m = re.search(r"corrected prediction (\d+) cyc", txt[ln - 1])
        assert m, f"n1351:{ln} has no corrected prediction"
        got[kind] = int(m.group(1))
        print(f"n1351:{ln} {kind}: corrected prediction {got[kind]:,} cyc")
    return got


def stamp(path):
    first = open(P(path)).readline()
    m = re.search(r"date: (\S+)", first)
    return dt.datetime.fromisoformat(m.group(1))


# (1) the census against both models
ms = stream_ms(SR + "n1509_sr15_census_r2.json")
print(f"(1) n1509 stream r2: {ms:.4f} ms/token = {1e3 / ms:.3f} tok/s")
print(f"    vs spec §3.1 {SPEC_TOKS} tok/s: measured/model {1e3 / ms / SPEC_TOKS:.4f}")
print(f"    vs SR13a TB MODEL {TB_MODEL_MS} ms/token = {1e3 / TB_MODEL_MS:.3f} tok/s: "
      f"measured/model {TB_MODEL_MS / ms:.4f}")

# (2) P1' with the corrected r2 makespans
r2c = corrected_r2()
n807 = chat(SR + "n807_sr8_r1_chat511.json")
n1508 = chat(SR + "n1508_sr15_r2_chat511.json")
for kind in ("lite", "full"):
    save = (STATIC_R1[kind] - r2c[kind]) / F * 1e3
    p = n807[kind] - save
    x = (n1508[kind] / p - 1) * 100
    v = "HELD" if abs(x) <= 0.5 else ("HELD LOOSELY" if abs(x) <= 2 else "MISSED")
    print(f"(2) {kind}: saving (static r1 {STATIC_R1[kind]:,} - corrected r2 "
          f"{r2c[kind]:,}) = {save:.4f} ms; P1'c = n807 {n807[kind]:.4f} - "
          f"{save:.4f} = {p:.4f} ms; n1508 {n1508[kind]:.4f} ms: {x:+.3f} % -> {v}")

# (3) the two control sessions' stamps
a = stamp(SR + "n802_sr8_control_041_chat511.log")
b = stamp(SR + "n1502_sr15_control_041_chat511.log")
d = b - a
print(f"(3) n802 started {a.isoformat()}, n1502 started {b.isoformat()}: "
      f"{d} apart ({int(d.total_seconds() // 3600)} h "
      f"{int(d.total_seconds() % 3600 // 60)} min)")
