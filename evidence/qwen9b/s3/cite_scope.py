#!/usr/bin/env python3
"""cite_scope.py — which documents changed ONLY by citation numbers?

    python evidence/qwen9b/s3/cite_scope.py [<base>]      (default 07eea51)

WHY IT EXISTS (S3 fix round 3, O4).  Fix round 2's drift re-anchor could
only be run at base `07eea51` over documents whose citations were still in
`07eea51` coordinates, so those documents were RESTORED with
`git checkout 07eea51 -- <doc>`.  Restoring a document is safe exactly when
its only change since the base is line NUMBERS — and that is a mechanical
question, not a judgement: normalise every `:\\d+` to `:N` in both texts and
compare.  The round asserted the answer; this prints it, so the scoping can
be re-derived instead of believed.

  CITES-ONLY   equal once normalised -> a restore loses nothing but numbers
  CONTENT      the texts differ in something else -> a restore would lose it,
               and a --fix at that base would double-shift its citations,
               so it is excluded from the mechanical pass and hand-repaired

`--verbose` prints, for a CONTENT document, the first normalised line that
differs, which is what tells a reader WHY it is on that side.
"""
import os
import re
import subprocess
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
NORM = re.compile(r":\d+")


def git_show(rev, path):
    p = subprocess.run(["git", "-C", REPO, "show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    return None if p.returncode else p.stdout


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    base = argv[0] if argv else "07eea51"
    verbose = "--verbose" in sys.argv[1:]
    changed = subprocess.run(
        ["git", "-C", REPO, "diff", "--name-only", base, "HEAD"],
        capture_output=True, text=True).stdout.split()
    print(f"cite_scope: base {base} -> HEAD, {len(changed)} changed path(s)")
    cites, content, gone = [], [], []
    for d in changed:
        b = git_show(base, d)
        if b is None:
            gone.append(d)
            continue
        try:
            with open(os.path.join(REPO, d)) as f:
                w = f.read()
        except OSError:
            gone.append(d)
            continue
        bn, wn = NORM.sub(":N", b), NORM.sub(":N", w)
        (cites if bn == wn else content).append((d, bn, wn))
    print(f"\nCITES-ONLY ({len(cites)}) — a `git checkout {base} -- <doc>` "
          f"restores these losing nothing but line numbers:")
    for d, _b, _w in sorted(cites):
        print("   ", d)
    print(f"\nCONTENT ({len(content)}) — excluded from any mechanical pass "
          f"at this base:")
    for d, bn, wn in sorted(content):
        print("   ", d)
        if verbose:
            for i, (x, y) in enumerate(zip(bn.split("\n"), wn.split("\n"))):
                if x != y:
                    print(f"        first differing normalised line {i + 1}")
                    break
    if gone:
        print(f"\nNEW OR DELETED ({len(gone)}) — no `{base}` text to compare:")
        for d in sorted(gone):
            print("   ", d)
    print(f"\nCITE_SCOPE: {len(cites)} cites-only, {len(content)} content, "
          f"{len(gone)} new/deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
