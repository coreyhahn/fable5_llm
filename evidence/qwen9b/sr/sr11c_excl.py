#!/usr/bin/env python3
"""sr11c_excl.py — SR11c: the exclusion rule of the task brief's Addendum 2,
applied MECHANICALLY, printed as o3_cite_drift.py `--exclude` arguments.

A citing document (o3's sweep universe, at HEAD, naming any --edited file) is
EXCLUDED from a pass when
  (a) its FIRST commit (`git log --diff-filter=A`) is not an ancestor-or-equal
      of the pass's --base  (written after the base, in post-edit coordinates);
  (b) it is on the STANDING list below;
  (c) --before is given and its first commit IS an ancestor-or-equal of that
      commit (used by the 966cbcf pass: those documents belong to the
      9c8e73b pass, which re-aims them first) — unless named by --keep;
  (d) it is named by --also-exclude.
Every exclusion is printed to stderr with its reason, so it lands in the log.
stdout carries only the `--exclude <path>` words for the wrapper.

  sr11c_excl.py --base B --edited f1,f2 [--before C] [--keep P]... [--also-exclude P]...
"""
import argparse
import re
import subprocess
import sys

REPO = "/home/cah/r2d2/code/fpga/fable5_llm"

# STANDING list (Addendum + Addendum 2): the gate documents written in
# post-edit coordinates, the drift wrappers / hand-repair scripts, o3's own
# docstring, S3_CHAIN.md, SR13a's territory (all of tb/, and its sr13a_* /
# n13* files under evidence/qwen9b/sr/), and the fix-round records (this
# round's fix-round test/check scripts).
STANDING = [
    (r"^evidence/qwen9b/sr/SR11a_R2_MODEL\.md$", "standing: SR11a gate doc"),
    (r"^evidence/qwen9b/sr/SR12_R2_RTL\.md$", "standing: SR12 gate doc"),
    (r"^evidence/qwen9b/sr/SR7_R1_BUILD\.md$", "standing: SR7 gate doc"),
    (r"^evidence/qwen9b/sr/SR11b_R2_PASS\.md$", "standing: SR11b gate doc"),
    (r"^evidence/qwen9b/sr/SR13b_HOST_R2\.md$", "standing: SR13b gate doc"),
    (r"^evidence/qwen9b/sr/SR13a_R2_CHIP\.md$", "standing: SR13a gate doc"),
    (r"^evidence/qwen9b/sr/SR11c_CITE_DRIFT\.md$", "standing: this task's gate doc"),
    (r"^evidence/qwen9b/sr/[^/]*_drift\.sh$", "standing: drift wrapper"),
    (r"^evidence/qwen9b/sr/[^/]*hand_repairs\.py$", "standing: hand-repair script"),
    (r"^evidence/qwen9b/sr/sr11c_", "standing: this task's own tools"),
    (r"^evidence/qwen9b/sr/sr[0-9]+[a-z]*(f[0-9]|_?fix[0-9])", "standing: fix-round record"),
    (r"^evidence/qwen9b/o3/o3_cite_drift\.py$", "standing: o3's own docstring"),
    (r"^evidence/qwen9b/s3/S3_CHAIN\.md$", "standing: S3_CHAIN.md (history)"),
    (r"^tb/", "standing: tb/ is SR13a's (incl. tb/tb_seq_chip.sv)"),
    (r"^evidence/qwen9b/sr/(sr13a_|n13)", "standing: SR13a's files"),
]


def git(*a):
    return subprocess.run(["git"] + list(a), cwd=REPO, capture_output=True,
                          text=True).stdout


def is_anc(a, b):
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                          cwd=REPO).returncode == 0


def universe():
    out = []
    for p in git("ls-files").splitlines():
        top = p.split("/")[0]
        if ((p.endswith((".md", ".txt")) and (top in ("docs", "evidence")
             or p in ("CHARTER.md", "NEXT_SESSION.md")))
                or (p.endswith((".py", ".sh", ".sv", ".v", ".tcl"))
                    and top in ("rtl", "sw", "ref", "tb", "evidence", "synth"))):
            out.append(p)
    return out


def first_commits():
    """{path: the commit that first ADDED it} from one history walk."""
    first, cur = {}, None
    log = git("log", "--diff-filter=A", "--name-only", "--format=@%h", "HEAD")
    for line in log.splitlines():
        if line.startswith("@"):
            cur = line[1:]
        elif line.strip():
            first[line.strip()] = cur          # older commits overwrite
    return first


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--edited", required=True)
    ap.add_argument("--before", default=None)
    ap.add_argument("--keep", action="append", default=[])
    ap.add_argument("--also-exclude", action="append", default=[])
    # fix round 1 (pass 2c): --only P excludes EVERY citing document but P,
    # standing list included (the coordinator named P explicitly)
    ap.add_argument("--only", action="append", default=[])
    a = ap.parse_args()
    edited = [e for e in a.edited.split(",") if e]
    first = first_commits()
    anc = {}
    excl = []
    for p in universe():
        try:
            with open("%s/%s" % (REPO, p), errors="replace") as f:
                t = f.read()
        except OSError:
            continue
        if not any(e in t for e in edited):
            continue
        why = None
        if a.only:
            if p not in a.only:
                excl.append(p)
                sys.stderr.write("SR11C_EXCLUDE %-70s %s\n" % (p, "not named by --only"))
            continue
        for rx, reason in STANDING:
            if re.search(rx, p):
                why = reason
                break
        fc = first.get(p)
        if why is None and p in a.also_exclude:
            why = "named by --also-exclude"
        if why is None and fc is not None:
            if fc not in anc:
                anc[fc] = is_anc(fc, a.base)
            if not anc[fc]:
                why = "first commit %s is after the base %s" % (fc, a.base)
            elif a.before and p not in a.keep and is_anc(fc, a.before):
                why = ("first commit %s is at/before %s: the earlier pass "
                       "owns it" % (fc, a.before))
        if why:
            excl.append(p)
            sys.stderr.write("SR11C_EXCLUDE %-70s %s\n" % (p, why))
    sys.stderr.write("SR11C_EXCLUDE total %d document(s)\n" % len(excl))
    print(" ".join("--exclude %s" % p for p in excl))


if __name__ == "__main__":
    main()
