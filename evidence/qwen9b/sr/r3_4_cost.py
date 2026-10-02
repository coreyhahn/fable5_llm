#!/usr/bin/env python3
"""r3_4_cost.py — Task R3-4 (R3 campaign, MOVX broadcast form (a)): the cost
model's one-window assumption — characterised, pinned, and handed to the
prediction task (R3-7).  NO pricing change: this tool only READS
ref/seq_cost.py.  Run ON SNOKE via sr_run.sh with FABLE5_MODEL=9b:

    FABLE5_MODEL=9b bash evidence/qwen9b/sr/sr_run.sh <log> \\
        /home/cah/.venv/bin/python evidence/qwen9b/sr/r3_4_cost.py <mode>

Modes (one per run):
  --char            the CHARACTERISATION case, against the ref/seq_cost.py
                    of the tree it runs on: a broadcast MOVX (flags[7:4] =
                    0xF, seq_format.MOVX_BCAST) prices exactly as a unicast
                    of the same length (x4096 = 4216, x12288 = 12507, the
                    selftest's anchors), and four unicasts price 4x one.  It
                    PASSES AT BASE — seq_cost's MOVX row reads the length,
                    never the channel — so it is not a RED; it exists so a
                    later edit that prices a broadcast differently trips.
                    The same case is in seq_cost --selftest, section (d).
  --selftest-count  runs seq_cost.selftest() and prints its output, then the
                    [PASS] / [FAIL] line counts (the selftest prints none).
  --fingerprint [--base <commit>]
                    seq_cost's rows (ov_census shape) over EVERY record of
                    the twenty w9 model_9b_s{1..4} streams (shipped, reordA,
                    reordB, reordB_r1, reordB_r2; each stream's FULL sha256
                    checked against its manifest first), segmented as the
                    pass segments them (reorder_e4.segments; the prologue
                    too), segment k priced at position k (the pass's default
                    --pos0 0).  Per stream: segment count, the sum of row
                    windows, the sum of stream S, the MOVX count and window
                    sum, and a sha256 over every row.  Plus a sha256 over the
                    static TABLE (every upper-case module constant).  With
                    --base, the base commit's ref/seq_cost.py (git show,
                    read-only) prices the same records and every stream and
                    the table must be IDENTICAL (the SR11b (e) check,
                    widened from the two synthetics to twenty streams).
  --derive          the numbers R3-7 consumes, from COMMITTED logs only
                    (arithmetic here, none by hand): OV1's census rows
                    R1+R2 -> R1+R2+R3 (n120) and SR16's sibling census
                    (n1600), in cycles and in ms at the 250 MHz TB aclk.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "ref"))
sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
sys.path.insert(0, os.path.join(REPO, "evidence", "qwen9b", "ov"))

import seq_format as SF        # noqa: E402
import seq_cost as SC          # noqa: E402

W9 = os.path.join(REPO, "tb", "scripts", "w9")
VARIANTS = ("", "_reordA", "_reordB", "_reordB_r1", "_reordB_r2")
STREAMS = [f"model_9b_s{s}{v}" for s in (1, 2, 3, 4) for v in VARIANTS]
TB_HZ = 250_000_000            # the chip TB's aclk (seq_cost's docstring)

OK = True


def check(name, cond, detail=""):
    global OK
    OK &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          f"{('  ' + detail) if detail else ''}")


# ======================================================================
# --char
# ======================================================================
def movx(chan, ln, src=0x2000):
    return SF.Rec(SF.OP_MOVX, flags=(chan << SF.CHAN_SHIFT), addr_lo=src,
                  len_or_addr_hi=ln)


def seg_sum(sc, recs):
    rows = sc.cost_of_segment(recs, 0, len(recs) - 1, 0)
    return sum(rows[pc][2] for pc in rows)


def char(sc):
    print("=== CHARACTERISATION (passes at base, not a RED): a broadcast MOVX "
          "prices as ONE unicast MOVX window of the same length")
    b = getattr(SF, "MOVX_BCAST", None)
    check("seq_format.MOVX_BCAST = 0xF", b == 0xF, repr(b))
    for ln, want in ((4096, 4216), (12288, 12507)):
        uni = sc.node_cost([movx(0, ln)], 0)
        bc = sc.node_cost([movx(0xF, ln)], 0)
        check(f"broadcast MOVX x{ln} = unicast = ({want}, 0)",
              uni == (want, 0) and bc == (want, 0),
              f"unicast {uni}, broadcast {bc}")
    one = seg_sum(sc, [movx(0xF, 4096)])
    four = seg_sum(sc, [movx(c, 4096) for c in range(4)])
    check("a segment of ONE broadcast x4096 = 4216; of FOUR unicasts "
          "x4096 = 4 x 4216 = 16864", one == 4216 and four == 4 * 4216,
          f"one broadcast {one}, four unicasts {four}")


# ======================================================================
# --selftest-count
# ======================================================================
def selftest_count():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = SC.selftest()
    out = buf.getvalue()
    sys.stdout.write(out)
    npass = sum(1 for ln in out.splitlines() if "[PASS]" in ln)
    nfail = sum(1 for ln in out.splitlines() if "[FAIL]" in ln)
    nchar = sum(1 for ln in out.splitlines()
                if "[PASS]" in ln or "[FAIL]" in ln
                if "broadcast" in ln or "BCAST" in ln)
    print(f"SEQ_COST SELFTEST COUNT: {npass} passed / {nfail} failed "
          f"(of which characterisation lines: {nchar}); selftest() "
          f"returned {ok}")
    return ok and nfail == 0


# ======================================================================
# --fingerprint
# ======================================================================
def load_base(commit):
    src = subprocess.check_output(["git", "-C", REPO, "show",
                                   f"{commit}:ref/seq_cost.py"])
    d = tempfile.mkdtemp(prefix="r3_4_base_")
    f = os.path.join(d, "seq_cost_base.py")
    open(f, "wb").write(src)
    spec = importlib.util.spec_from_file_location("seq_cost_base", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, hashlib.sha256(src).hexdigest()


def table_fp(sc):
    items = []
    for k in sorted(vars(sc)):
        v = getattr(sc, k)
        if k.isupper() and isinstance(v, (int, float, tuple, dict)):
            items.append(f"{k}={v!r}")
    return hashlib.sha256("\n".join(items).encode()).hexdigest(), len(items)


def stream_fp(sc, recs, segs):
    h = hashlib.sha256()
    tot = S = nmovx = movx_sum = 0
    refused = []
    for tag, k, lo, hi in segs:
        try:
            rows = sc.rows_for(recs, 0)(k, lo, hi)
        except AssertionError as e:
            refused.append(f"{tag}{k}: {type(e).__name__}: {e}")
            h.update(f"REFUSED {tag}{k} {e}\n".encode())
            continue
        for pc in sorted(rows):
            o, t, dur, cls = rows[pc]
            h.update(f"{pc} {o} {t} {dur} {tuple(cls)}\n".encode())
            tot += dur
            S += sum(cls)
            if o == SF.OP_MOVX:
                nmovx += 1
                movx_sum += dur
    return {"sha": h.hexdigest(), "win": tot, "S": S, "nmovx": nmovx,
            "movx": movx_sum, "refused": refused}


def segment(RE, recs):
    """The pass's segmentation (reorder_e4.segments) where it applies — the
    pass's INPUT streams.  Its OUTPUT streams (reordB_r1 / _r2) fail its
    input check "the JMP must close the last segment" (first run, n2604), so
    they are cut at every EMB and at the JMP's target instead (fallback,
    printed per stream).  Either way every record from 0 to HALT-1 is
    priced; the proof only needs the SAME cut before and after."""
    try:
        pe, segs, _halt = RE.segments(recs)
        return (([("pro", 0, 0, pe - 1)] if pe > 0 else [])
                + [("seg", k, lo, hi) for k, (lo, hi, _b)
                   in enumerate(segs)]), "pass segmentation"
    except AssertionError as e:
        halt = len(recs) - 1
        cuts = {0} | {i for i, r in enumerate(recs) if r.opcode == SF.OP_EMB}
        cuts |= {r.imm32 for r in recs if r.opcode == SF.OP_JMP}
        cuts = sorted(c for c in cuts if 0 <= c < halt)
        out = [("cut", k, lo, (cuts[k + 1] - 1) if k + 1 < len(cuts)
                else halt - 1) for k, lo in enumerate(cuts)]
        return out, f"fallback cuts at EMBs + JMP target; pass said: {e}"


def fingerprint(base):
    import reorder_e4 as RE
    bsc = None
    if base:
        bsc, bsha = load_base(base)
        print(f"=== base {base}: ref/seq_cost.py sha256 {bsha}")
    wsha = hashlib.sha256(open(os.path.join(REPO, "ref", "seq_cost.py"),
                               "rb").read()).hexdigest()
    print(f"=== tree ref/seq_cost.py sha256 {wsha}")
    tfp, nt = table_fp(SC)
    print(f"TABLE {nt} constants sha256 {tfp}")
    if bsc is not None:
        bfp, bnt = table_fp(bsc)
        check(f"static table = base's ({nt} constants)",
              tfp == bfp and nt == bnt, f"base {bnt} sha256 {bfp}")
    agg = hashlib.sha256()
    for name in STREAMS:
        p = os.path.join(W9, name + ".e4")
        stream = open(p + ".seq", "rb").read()
        meta = json.load(open(p + ".seq.json"))
        sha = hashlib.sha256(stream).hexdigest()
        if sha != meta["stream_sha256"]:
            check(f"{name}: stream sha256 = manifest", False,
                  f"{sha} vs {meta['stream_sha256']}")
            continue
        recs = SF.unpack_stream(stream)
        segl, how = segment(RE, recs)
        fp = stream_fp(SC, recs, segl)
        agg.update(f"{name} {fp['sha']}\n".encode())
        print(f"FP {name}: stream {sha}  nrec {len(recs)}  segs {len(segl)}"
              f" ({how})"
              f"  win {fp['win']}  S {fp['S']}  MOVX {fp['nmovx']} / "
              f"{fp['movx']}  refused {len(fp['refused'])}  rows sha256 "
              f"{fp['sha']}")
        for r in fp["refused"]:
            print(f"    refused {r}")
        if bsc is not None:
            bfp = stream_fp(bsc, recs, segl)
            check(f"{name}: every row = base's", bfp == fp,
                  f"base rows sha256 {bfp['sha']}")
    print(f"FP ALL {len(STREAMS)} streams: sha256 {agg.hexdigest()}")


# ======================================================================
# --derive
# ======================================================================
def grab(path, lineno, pattern):
    """(the committed line, the regex match) — refuses a mismatch."""
    lines = open(os.path.join(REPO, path)).read().splitlines()
    ln = lines[lineno - 1]
    m = re.search(pattern, ln)
    if not m:
        raise SystemExit(f"{path}:{lineno} does not match {pattern!r}: {ln!r}")
    print(f"  {path}:{lineno}: {ln.strip()}")
    return m


def ms(c):
    return c * 1000.0 / TB_HZ


def derive():
    n120 = "evidence/qwen9b/ov/n120_sr0_clock_sens.log"
    n1600 = "evidence/qwen9b/sr/n1600_sr16_r3_census.log"
    print("=== inputs (committed lines, read back)")
    r2 = int(grab(n120, 18, r"REPRO B:R1\+R2\s+(\d+) cyc").group(1))
    r3 = int(grab(n120, 19, r"REPRO B:R1\+R2\+R3\s+(\d+) cyc").group(1))
    m = grab(n1600, 19, r"broadcast carriers \(first live MOVX\) (\d+): "
             r"(\d+) cyc")
    ncar, car = int(m.group(1)), int(m.group(2))
    m = grab(n1600, 20, r"SIBLINGS R3 zeroes: (\d+) MOVX, (\d+) cyc")
    nsib, sib = int(m.group(1)), int(m.group(2))
    m = grab(n1600, 17, r"live (\d+): (\d+) cyc")
    nlive, live = int(m.group(1)), int(m.group(2))
    m = grab(n1600, 36, r"SAVE B:R3\s+(\d+) cyc .* lane work removed (\d+) "
             r"cyc .* lane idle change \+(\d+) cyc")
    save36, rem36, idle36 = (int(m.group(i)) for i in (1, 2, 3))
    m = grab(n1600, 26, r"B:R3\s+makespan\s+(\d+) cyc")
    r3_1600 = int(m.group(1))
    m = grab(n1600, 23, r"B:R2\s+makespan\s+(\d+) cyc")
    r2_1600 = int(m.group(1))

    print("=== consistency (each must hold)")
    save = r2 - r3
    check("n1600's R2 / R3 makespans = n120's rows", r2_1600 == r2
          and r3_1600 == r3, f"{r2_1600}/{r3_1600} vs {r2}/{r3}")
    check("census saving R1+R2 - R1+R2+R3 = n1600's SAVE B:R3",
          save == save36, f"{save} vs {save36}")
    check("SAVE = siblings removed - lane idle rise", save == sib - idle36
          and rem36 == sib, f"{sib} - {idle36} = {sib - idle36}")
    check("siblings = 3 x carriers (every live matvec has 4 live MOVX of "
          "one length)", nsib == 3 * ncar and sib == 3 * car,
          f"{nsib} = 3 x {ncar}; {sib} = 3 x {car}")
    check("live = carriers + siblings", nlive == ncar + nsib
          and live == car + sib, f"{nlive}, {live}")

    print("=== MODEL: the per-token saving R3 (form B, census convention, "
          "siblings free) at the 250 MHz TB aclk")
    print(f"  D  siblings zeroed        {nsib} MOVX  {sib:>9,d} cyc = "
          f"{ms(sib):.6f} ms TB  (mean {sib / nsib:.2f} cyc = "
          f"{sib / nsib * 1e6 / TB_HZ:.3f} us each; "
          f"{100.0 * sib / live:.2f} % of the live MOVX window)")
    print(f"  D  lane idle on stream    +{idle36:>8,d} cyc = "
          f"+{ms(idle36):.6f} ms TB")
    print(f"  D  NET saving per token    {save:>9,d} cyc = "
          f"{ms(save):.6f} ms TB")
    print(f"  D  census rows            R1+R2 {r2:,d} ({ms(r2):.3f} ms) -> "
          f"R1+R2+R3 {r3:,d} ({ms(r3):.3f} ms): x{r2 / r3:.4f}, "
          f"-{100.0 * save / r2:.3f} % of R1+R2")
    print(f"  D  per broadcast carrier  {save / ncar:.1f} cyc net "
          f"({sib / ncar:.1f} removed) over {ncar} broadcasts per token")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--char", action="store_true")
    g.add_argument("--selftest-count", action="store_true")
    g.add_argument("--fingerprint", action="store_true")
    g.add_argument("--derive", action="store_true")
    ap.add_argument("--base", default=None,
                    help="--fingerprint: compare against this commit's "
                         "ref/seq_cost.py")
    a = ap.parse_args()
    if a.base:
        subprocess.check_output(["git", "-C", REPO, "rev-parse", "--verify",
                                 "-q", f"{a.base}^{{commit}}"])
    if a.char:
        char(SC)
    elif a.selftest_count:
        if not selftest_count():
            global OK
            OK = False
    elif a.fingerprint:
        fingerprint(a.base)
    else:
        derive()
    print("R3_4_COST: " + ("PASS" if OK else "FAIL"))
    raise SystemExit(0 if OK else 1)


if __name__ == "__main__":
    main()
