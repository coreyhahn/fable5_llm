#!/usr/bin/env python3
"""G4b Step 3 — turn the three census tables into the MEASURED layer term.

Reads the `LAYER_CENSUS` tables `tb_layer_census` wrote (one per
configuration) and prints, per configuration:

  * cycles per DNST command, measured, beside the two comparators the brief
    names -- `rtl/dn_step.sv:14`'s ~1300 cycles/head and Task 10's isolated
    per-head numbers, RE-MEASURED ON THE TASK-14-A RTL (control 1799 /
    option (i) 1931 / option (ii) 1803 -- Task 10's 1798/1930/1802 are
    PRE-14-A and every one of them moved by exactly +1;
    evidence/qwen9b/g3/G3_4_LAYER.md section 4.3 for the originals,
    evidence/qwen9b/g5/G5C_RTL.md section 5.2 and
    evidence/qwen9b/g4/089_dn_step_pipe_ii_t14a.log for the re-measurements);
  * the LAYER TERM per token, in cycles and in ms at 250 MHz.

WHY THE COMPARISON IS APPLES-TO-APPLES.  The model's "layer 47.00 ms" is the
L_LCYC accumulator: `evidence/qwen2b/rd/RD_GATE.md` reports
"layer busy (LCYC) 22,692,603 cyc = 15.128 ms/token" at 0.8B and
"26,940,149 cyc = 17.960 ms/token" at 2B, and
`evidence/qwen_next/feas/toks_model.py` fits its layer term to exactly those
two points ("same L_LCYC accumulator, same board, same bitstream").  This
census sums the SAME CSR on the SAME engine at the SAME 250 MHz.

The step decomposition it is folded into is spec section 10's:
  step 138.61 ms = matvec 58.95 + movers 32.66 + layer 47.00 -> 7.21 tok/s.
Only the layer term is replaced.  matvec and movers stay MODELLED (E), and
the result is therefore a model with one measured term, not a measured
tok/s -- said here so no reader mistakes it for silicon.

Usage:
  python3 evidence/qwen9b/g4/g4b_layer_term.py \
      shipped=evidence/qwen9b/g4/census_shipped.txt \
      optii=evidence/qwen9b/g4/census_optii.txt \
      pipe0=evidence/qwen9b/g4/census_pipe0.txt
"""
import re
import sys

CLK_HZ = 250e6
MODEL_MATVEC_MS = 58.95        # spec section 10 (E)
MODEL_MOVERS_MS = 32.66        # spec section 10 (E)
MODEL_LAYER_MS = 47.00         # spec section 10 (E) -- the term this replaces
MODEL_STEP_MS = 138.61
RTL_EST_CYC_HEAD = 1300        # rtl/dn_step.sv:14
# THE BASELINES ARE POST-14-A (#190, triage (b)16).  Task 14-A's free-running
# first mux level costs exactly ONE extra cycle per 128 emitted words, and
# `tb_dn_step` measures it directly, so every entry below moved by +1 and a
# post-bitstream tok/s re-derivation against the old numbers was silently
# wrong.  Each value is a MEASUREMENT on the shipping RTL, not a derivation:
#   1799  evidence/qwen9b/g5/G5C_RTL.md 5.2 (log 077), vs S2's 1798
#   1931  evidence/qwen9b/g5/G5C_RTL.md 5.2 (log 075), vs G3's 1930
#   1803  evidence/qwen9b/g4/089_dn_step_pipe_ii_t14a.log -- option (ii) was
#         the one configuration 14-A never re-ran, so this chore ran
#         `make -C tb tb_dn_step_pipe_ii` on snoke: TB_DN_STEP PASS on all
#         four seeds, `DN_CYCLES RLAT=6 P2W=0 cycles_per_head=1803`.
T10 = {"control RLAT=2 P2_WAIT=0": 1799,      # 14-A; G3's pre-14-A was 1798
       "option (i)  RLAT=6 P2_WAIT=1": 1931,  # 14-A; pre-14-A 1930
       "option (ii) RLAT=6 P2_WAIT=0": 1803}  # 14-A; pre-14-A 1802

# THE CENSUS GREW COLUMNS AND LOST ONE (#190's other half).  The Task-12
# census this script was written for printed `DN_PIPE=n DN_RLAT=r
# DN_P2WAIT=p`, seven opcode columns and four per-step columns.  The S4
# census (`evidence/qwen9b/s4/run_s4_census.sh`, the one that is not
# superseded) DROPPED `DN_PIPE=` -- S2 retired the parameter -- and ADDED an
# `excess` opcode column and the two state-DMA per-step columns
# (`SLD+SST`, `sdma_cyc`).  With the old anchors this script read NOTHING at
# all from `evidence/qwen9b/s4/census_t14a.txt`: no header, no DNST row, no
# steps, and it still printed a comparator table and a modelled tok/s, which
# is the worst shape a stale parser can take.  Every added group is OPTIONAL,
# so the Task-12 censuses still parse byte-identically.
OP_RE = re.compile(r"^LAYER_CENSUS\s+(\d+)\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)"
                   r"\s+(\d+)\s+(\d+)(?:\s+(\d+))?\s*$")
STEP_RE = re.compile(r"^LAYER_CENSUS\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)"
                     r"(?:\s+(\d+)\s+(\d+))?\s*$")
HDR_RE = re.compile(r"^LAYER_CENSUS (?:DN_PIPE=(\d+) )?DN_RLAT=(\d+)"
                    r" DN_P2WAIT=(\d+)")
TOT_RE = re.compile(r"^LAYER_CENSUS TOTAL_BUSY_CYCLES (\d+)")
CMD_RE = re.compile(r"^LAYER_CENSUS commands=(\d+) checks=(\d+) errors=(\d+)")


def parse(path):
    d = {"ops": {}, "steps": {}, "path": path}
    in_step = False
    for line in open(path):
        m = HDR_RE.match(line)
        if m:
            d["pipe"] = int(m.group(1)) if m.group(1) else None
            d["rlat"], d["p2w"] = int(m.group(2)), int(m.group(3))
            continue
        m = CMD_RE.match(line)
        if m:
            d["commands"], d["checks"], d["errors"] = (int(m.group(1)),
                                                       int(m.group(2)),
                                                       int(m.group(3)))
            continue
        m = TOT_RE.match(line)
        if m:
            d["total_busy"] = int(m.group(1))
            continue
        if "per forward step" in line:
            in_step = True
            continue
        if not in_step:
            m = OP_RE.match(line)
            if m:
                d["ops"][int(m.group(1))] = dict(
                    name=m.group(2), n=int(m.group(3)), cyc=int(m.group(4)),
                    mean=int(m.group(5)), lo=int(m.group(6)), hi=int(m.group(7)),
                    excess=int(m.group(8)) if m.group(8) else None)
        else:
            m = STEP_RE.match(line)
            if m:
                d["steps"][int(m.group(1))] = dict(
                    n=int(m.group(2)), cyc=int(m.group(3)), dnst=int(m.group(4)),
                    sdma_cmds=int(m.group(5)) if m.group(5) else None,
                    sdma_cyc=int(m.group(6)) if m.group(6) else None)
    return d


def main():
    cfgs = []
    for a in sys.argv[1:]:
        tag, _, path = a.partition("=")
        cfgs.append((tag, parse(path)))
    if not cfgs:
        sys.exit(__doc__)

    print("LAYERTERM ==== per-DNST cycles, measured ====")
    print("LAYERTERM cfg       DN_PIPE RLAT P2W  DNST cmds  cyc/DNST  min  max")
    for tag, d in cfgs:
        o = d["ops"].get(8)
        if not o:
            print(f"LAYERTERM {tag:10s} NO DNST COMMANDS IN THIS CENSUS")
            continue
        pipe = "-" if d.get("pipe") is None else str(d["pipe"])
        print(f"LAYERTERM {tag:10s} {pipe:>6s} {d['rlat']:4d} {d['p2w']:3d} "
              f"{o['n']:10d} {o['mean']:9d} {o['lo']:6d} {o['hi']:6d}")
    print(f"LAYERTERM comparator rtl/dn_step.sv:14 estimate   : "
          f"{RTL_EST_CYC_HEAD} cycles/head")
    for k, v in T10.items():
        print(f"LAYERTERM comparator tb_dn_step ON THE 14-A RTL {k}: "
              f"{v} cycles/head")

    print()
    print("LAYERTERM ==== the LAYER TERM per token ====")
    print("LAYERTERM cfg        step  commands   busy_cyc      ms@250MHz  "
          "vs model 47.00 ms")
    base = None
    for tag, d in cfgs:
        for s, v in sorted(d["steps"].items()):
            if s == 0:
                continue
            ms = v["cyc"] / CLK_HZ * 1e3
            rel = ms / MODEL_LAYER_MS
            print(f"LAYERTERM {tag:10s} {s:5d} {v['n']:9d} {v['cyc']:12d} "
                  f"{ms:12.3f}  {rel:8.3f}x")
            if tag == "shipped" and base is None:
                base = ms
    print()
    print("LAYERTERM ==== the preamble (step 0), reported separately ====")
    print("LAYERTERM   MEASURED contents: 120 CONVW + 768 DNZ = 888 commands,")
    print("LAYERTERM   and NOTHING else -- the once-per-launch conv weight/state")
    print("LAYERTERM   load and the DeltaNet state zeroing.  ROPET is NOT in it:")
    print("LAYERTERM   the stream re-emits its 8 RoPE-table loads every forward")
    print("LAYERTERM   step.  The preamble is not per-token, so it is NOT in the")
    print("LAYERTERM   layer term.")
    for tag, d in cfgs:
        v = d["steps"].get(0)
        if v:
            print(f"LAYERTERM {tag:10s} preamble {v['n']:9d} cmds "
                  f"{v['cyc']:12d} cyc = {v['cyc']/CLK_HZ*1e3:.3f} ms")

    print()
    print("LAYERTERM ==== the T-DEPENDENT opcodes, per step ====")
    print("LAYERTERM   rtl/attn_core.sv:29 takes cfg_t (cache length T) and its")
    print("LAYERTERM   inner loop runs over the cache, so ATTN and KVAP are the")
    print("LAYERTERM   two opcodes whose cost grows with sequence position.")
    print("LAYERTERM   Every other opcode is context-independent by construction.")
    for tag, d in cfgs:
        if len(d["steps"]) <= 2:
            continue
        print(f"LAYERTERM {tag} per-step ATTN/KVAP (T = step number):")
        for s, v in sorted(d["steps"].items()):
            if s == 0:
                continue
            print(f"LAYERTERM   step {s}  T={s}  busy {v['cyc']:12d} cyc = "
                  f"{v['cyc'] / CLK_HZ * 1e3:8.3f} ms  "
                  f"({v['cyc'] - d['steps'][1]['cyc']:+d} cyc vs step 1)")

    print()
    print("LAYERTERM ==== spec section 10's step, with ONE term replaced ====")
    print("LAYERTERM   matvec 58.95 + movers 32.66 stay MODELLED (E).")
    print("LAYERTERM   THE PER-TOKEN TERM IS THE MEAN OVER THE STEPS PRESENT, and")
    print("LAYERTERM   the reason is like-for-like: the model's layer coefficient")
    print("LAYERTERM   is fitted to RD_GATE's two SILICON points, each of which is")
    print("LAYERTERM   an LCYC total DIVIDED BY ITS TOKEN COUNT (0.8B 22,692,603")
    print("LAYERTERM   cyc = 15.128 ms/token over 6 tokens; 2B 26,940,149 =")
    print("LAYERTERM   17.960 over 6).  A mean over the same six steps is the same")
    print("LAYERTERM   quantity.  Step 1 and the last step are given as the")
    print("LAYERTERM   bracket, because only ATTN and KVAP move between them.")
    print("LAYERTERM cfg        basis     layer_ms    step_ms   tok/s   vs 7.21")
    for tag, d in cfgs:
        steps = {k: v for k, v in d["steps"].items() if k != 0}
        if not steps:
            continue
        rows = [("step 1", steps[1]["cyc"])]
        if len(steps) > 1:
            last = max(steps)
            rows.append((f"step {last}", steps[last]["cyc"]))
            rows.append(("MEAN 1..%d" % last,
                         sum(v["cyc"] for v in steps.values()) / len(steps)))
        for basis, cyc in rows:
            ms = cyc / CLK_HZ * 1e3
            step = MODEL_MATVEC_MS + MODEL_MOVERS_MS + ms
            print(f"LAYERTERM {tag:10s} {basis:9s} {ms:9.3f} {step:10.3f} "
                  f"{1e3/step:7.3f} {1e3/step/(1e3/MODEL_STEP_MS):8.3f}x")
    print(f"LAYERTERM  modelled  {'—':9s} {MODEL_LAYER_MS:9.3f} "
          f"{MODEL_STEP_MS:10.3f} {1e3/MODEL_STEP_MS:7.3f}   1.000x")

    print()
    print("LAYERTERM ==== the wait state, priced on the real stream ====")
    got = {t: d for t, d in cfgs}
    if "shipped" in got and "optii" in got:
        a = got["shipped"]["steps"].get(1)
        b = got["optii"]["steps"].get(1)
        if a and b:
            dc = a["cyc"] - b["cyc"]
            print(f"LAYERTERM option (i) - option (ii) = {dc} cyc/token = "
                  f"{dc/CLK_HZ*1e3:.3f} ms = "
                  f"{100.0*dc/b['cyc']:.2f} % of the option-(ii) layer term")
            da = got["shipped"]["ops"][8]["mean"] - got["optii"]["ops"][8]["mean"]
            print(f"LAYERTERM per DNST command: {da} cycles; x "
                  f"{a['dnst']} DNST/token = {da*a['dnst']} cyc/token")
    if "shipped" in got and "pipe0" in got:
        a = got["shipped"]["steps"].get(1)
        c = got["pipe0"]["steps"].get(1)
        if a and c:
            dc = a["cyc"] - c["cyc"]
            print(f"LAYERTERM DN_PIPE=2 - DN_PIPE=0 = {dc} cyc/token = "
                  f"{dc/CLK_HZ*1e3:.3f} ms = "
                  f"{100.0*dc/c['cyc']:.2f} % of the unpipelined layer term")

    print()
    print("LAYERTERM ==== DNST share of the layer term ====")
    for tag, d in cfgs:
        v = d["steps"].get(1)
        o = d["ops"].get(8)
        if not (v and o):
            continue
        # the DNST commands of step 1 only: mean x count in that step
        dn_cyc = o["mean"] * v["dnst"]
        print(f"LAYERTERM {tag:10s} DNST {v['dnst']} x {o['mean']} = {dn_cyc} "
              f"cyc = {100.0*dn_cyc/v['cyc']:.2f} % of the layer term")

    print()
    print("LAYERTERM ==== correctness: every census is also a replay ====")
    for tag, d in cfgs:
        print(f"LAYERTERM {tag:10s} commands={d.get('commands')} "
              f"checks={d.get('checks')} errors={d.get('errors')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
