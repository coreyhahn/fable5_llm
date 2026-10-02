#!/usr/bin/env python3
"""g4a_torch_lockstep.py — close the loop from the bf16 checkpoint to the RTL.

The chip replay proves RTL == `ref/seq_model.py`.  The SEQ gate proves
`ref/seq_model.py` == the `.txt` generator == `ref/layer_fixed.py`.  Neither
says anything about the MODEL.  This puts the four token sequences side by
side and reports where they agree:

  EMIT     `ref/gen_model_script.py`'s own per-step `argmax=` lines, parsed
           out of the emit log (the summary line is only a cross-check --
           see `emit_tokens`).  This is the fixed-point pipeline running
           free, one argmax per forward step.
  CHIP     the `TOK` lines of `<prefix>.chip`, i.e. `ref/seq_model.py`'s
           OUT FIFO after replaying the emitted STREAM.  `TB_SEQ_CHIP PASS`
           is what makes this also the RTL's answer -- the TB reads every
           one of these out of `seq_unit`'s FIFO and fatals on a mismatch,
           so this column is the silicon column once that log is green.
  FX       `fx_argmax` from the RS_F=7 fidelity run
           (`evidence/qwen9b/g2/g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c.json`,
           Task 5 section 7.3): `ref/layer_fixed.py` TEACHER-FORCED onto the
           golden token sequence.  A third, independent implementation of
           the same fixed-point math -- no scratchpad model, no SEQ stream.
  GOLD     `golden_argmax` from the same file: the bf16 checkpoint through
           `transformers`, upcast to float32.  THE MODEL.

The interesting comparison is EMIT/CHIP/FX (which must agree exactly -- they
are the same arithmetic) against GOLD (which need not: that difference IS
the quantization, and Task 5 priced it at 98/108 top-1 over four prompts).

Free-running vs teacher-forced: `gen_model_script` feeds the real prompt for
the first P-1 steps and its OWN argmax after that, so EMIT/CHIP are
comparable to FX step for step only while the two sequences have not
diverged.  The `free_gen` list of the fidelity run is the free-running
control for exactly that reason and is reported beside them.

Usage:
  python3 evidence/qwen9b/g4/g4a_torch_lockstep.py \\
      --chip tb/scripts/w9/model_9b_s1.e4.chip \\
      --emit-log evidence/qwen9b/g4/003_emit_9b_s1.log \\
      [--fidelity <json>] [--key '<top-level key>'] [--prompt 1]

Exit 0 = the three fixed-point columns agree over every step they cover.
The GOLD column is REPORTED, never asserted: a disagreement there is the
quantization error, not a failure.
"""
import argparse
import json
import os
import re
import sys

TOP = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", ".."))
DEF_FID = os.path.join(
    TOP, "evidence/qwen9b/g2/"
         "g2c_fixed_9b_w4g128gptq_int16_rsf7_g2c.json")


def chip_tokens(path):
    return [int(m.group(1), 16) for m in
            (re.match(r"TOK ([0-9a-f]+)", ln) for ln in open(path))
            if m]


def emit_tokens(path):
    """(argmax per step, generated) out of gen_model_script's own output.

    The PER-STEP lines are the primary source and the summary line is a
    cross-check, not the other way round: `gen_model_script` prints the
    summary only AFTER the runtime range audit, and the audit `raise`s
    without `--allow-clip` — so a run that measured a saturation (which is
    the point of running without the flag) has the per-step lines and no
    summary at all.  `generated` is then the steps the generator itself
    labelled `generate`.
    """
    txt = open(path, errors="replace").read()
    steps = re.findall(
        r"^  step\s+(\d+) \((prefill |generate)\) in_tok=\s*\d+ "
        r"argmax=\s*(\d+)", txt, re.M)
    per = [int(a) for (_i, _k, a) in steps]
    gen = [int(a) for (_i, k, a) in steps if k.strip() == "generate"]
    a = re.search(r"argmax per step=\[([0-9,\s]*)\]", txt)
    g = re.search(r"generated=\[([0-9,\s]*)\]", txt)
    lst = lambda m: ([int(x) for x in m.group(1).replace(",", " ").split()]
                     if m else None)
    for name, from_steps, from_summary in (("argmax per step", per, lst(a)),
                                           ("generated", gen, lst(g))):
        if from_summary is not None and from_summary != from_steps:
            raise SystemExit(
                f"{path}: the per-step lines and the summary disagree about "
                f"{name}: {from_steps} vs {from_summary}")
    return (per or None), (gen or None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chip", required=True)
    ap.add_argument("--emit-log", required=True)
    ap.add_argument("--fidelity", default=DEF_FID)
    ap.add_argument("--key", default=None,
                    help="top-level key inside the fidelity json "
                         "(default: the single one, or the only rsf7 one)")
    ap.add_argument("--prompt", default="1")
    a = ap.parse_args()

    bad = []
    chip = chip_tokens(a.chip)
    emit, gen = emit_tokens(a.emit_log)
    fid = json.load(open(a.fidelity))
    key = a.key
    if key is None:
        cands = [k for k in fid if "rsf7" in k] or list(fid)
        if len(cands) != 1:
            raise SystemExit(f"--key needed; candidates {cands}")
        key = cands[0]
    e = fid[key][a.prompt]
    fx, gold, free = e["fx_argmax"], e["golden_argmax"], e["free_gen"]

    print(f"G4a torch-golden lockstep — prompt {a.prompt}")
    print(f"  chip     {a.chip}  ({len(chip)} TOK lines)")
    print(f"  emit log {a.emit_log}")
    print(f"  fidelity {os.path.relpath(a.fidelity, TOP)}  key {key!r}  "
          f"({len(fx)} teacher-forced steps, {len(free)} free-running)")
    print(f"  fidelity top1 {sum(e['top1'])}/{len(e['top1'])}, "
          f"rank max {max(e['rank'])}")

    if emit is None:
        bad.append("the emit log carries no per-step `argmax=` lines")
        emit = []
    n = len(chip)
    if emit and len(emit) != n:
        bad.append(f"EMIT has {len(emit)} steps, CHIP has {n} TOK lines")

    print("\n  step | EMIT   CHIP   FX     GOLD   | fx==chip  gold==chip")
    agree_fx = agree_gold = 0
    for i in range(n):
        ce = emit[i] if i < len(emit) else None
        cf = fx[i] if i < len(fx) else None
        cg = gold[i] if i < len(gold) else None
        ok_f = (cf is not None and cf == chip[i])
        ok_g = (cg is not None and cg == chip[i])
        agree_fx += ok_f
        agree_gold += ok_g
        if ce is not None and ce != chip[i]:
            bad.append(f"step {i}: EMIT {ce} != CHIP {chip[i]} — the "
                       "generator and the stream replay disagree")
        print(f"  {i:4d} | {ce!s:6} {chip[i]:<6} {cf!s:6} {cg!s:6} | "
              f"{'YES' if ok_f else 'no ':9} {'YES' if ok_g else 'no '}")

    print(f"\n  EMIT == CHIP  : {'IDENTICAL' if emit == chip else 'DIFFER'} "
          f"({n} steps)")
    print(f"  FX   == CHIP  : {agree_fx}/{n}")
    print(f"  GOLD == CHIP  : {agree_gold}/{n}   <-- the quantization error, "
          "reported not asserted")
    if gen is not None:
        k = len(gen)
        print(f"  generated     : {gen}")
        print(f"  free_gen[:{k}]  : {free[:k]}"
              + ("   IDENTICAL" if gen == free[:k] else "   DIFFER"))
        if gen != free[:k]:
            bad.append("the generator's free-running tokens differ from the "
                       "fidelity harness's free-running tokens")
    if agree_fx != n:
        bad.append(f"FX agrees with CHIP on only {agree_fx} of {n} steps; "
                   "the two fixed-point implementations must be identical "
                   "while the fed prefix is (see the free-running note)")

    print("\nG4A_TORCH_LOCKSTEP: %s (%d problem(s))"
          % ("PASS" if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  ! " + b)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
