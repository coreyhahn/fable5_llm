#!/usr/bin/env python3
"""state_sha.py — does each artifact's manifest name the sha of ITS image?

    python evidence/qwen9b/s3/state_sha.py [<prefix> ...]
    (default: the eight w9 smoke artifacts under tb/scripts/w9/)

WHY IT EXISTS (S3 fix round 3, O3).  Fix round 1's M6 made
`weights.json`'s `state.sha256` the digest of the emitted
`<base>.state.bin` bytes, and `sw/seq_run.verify_state_image` is the host's
refusal: a stream replayed against a re-planned or re-emitted region is
what spec 7.2 forbids, and the host must see it before it writes a byte.
The gate doc asserted the post-M6 pair (`36969da4…` against the pre-M6
`d2b48091…`) in PROSE, with no log to stand on.  This prints BOTH digests
for every artifact, so the claim is read off a run instead of believed.

It calls `sw/seq_run.verify_state_image` itself — the same code the host
runs — so a bug in the check is a bug in this evidence too, which is the
point: it measures the shipped refusal, not a re-implementation of it.

Exit 0 only when every artifact matches.  An artifact with no state region
(pre-S3) is reported ABSENT and is not a failure.
"""
import hashlib
import os
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "sw"))
import seq_run as R                                        # noqa: E402

DEFAULT = [os.path.join(REPO, "tb", "scripts", "w9", n + ".e4")
           for n in ("lay9b_s1", "lay9b_s2", "lay9b_s3", "lay9b_s4",
                     "tok9b_s1", "tok9b_s2", "tok9b_s3", "tok9b_s4")]


def main():
    prefixes = sys.argv[1:] or DEFAULT
    ok = bad = absent = 0
    for p in prefixes:
        name = os.path.basename(p)
        art = R.Artifacts(p)
        if art.state is None:
            print(f"{name:20s}  ABSENT  (artifact declares no state region)")
            absent += 1
            continue
        want = art.state.get("sha256")
        img = art.base + ".state.bin"
        h = hashlib.sha256()
        with open(img, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        got = h.hexdigest()
        try:
            R.verify_state_image(art)
            verdict = "MATCH"
            ok += 1
        except R.SeqError as e:
            verdict = f"REFUSED: {e}"
            bad += 1
        print(f"{name:20s}  manifest {want}\n"
              f"{'':20s}  image    {got}  ({os.path.getsize(img)} B)  {verdict}")
    print(f"\nSTATE_SHA: {'PASS' if not bad else 'FAIL'} — {ok} match, "
          f"{bad} mismatch, {absent} without a region "
          f"({len(prefixes)} artifact(s))")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
