#!/usr/bin/env python3
"""bm1_census_ids_test.py — BM1-T4 fix I2: boardless TDD for
`bm1_census.py --chat --want-ids` (fail-closed token identity).

    python evidence/qwen9b/bm/bm1_census_ids_test.py

  U1  parse_ids('760,20438') == [760, 20438]; junk is refused.
  U2  verdict(): a synthetic 512-launch log whose reply ids EQUAL the pinned
      reference -> exit 0 and 'TOKENS IDENTICAL'.
  U3  the same log with ONE differing id -> non-zero exit, and the message
      prints BOTH lists.
  U4  a non-zero chat_seq rc is never masked by an identical token list.
  U5  a missing/short token list (fewer ids than wanted) FAILS.
  U6  no --want-ids -> the rc passes through unchanged (pre-flag behaviour).
  U7  the CLI: `--chat --want-ids X --` parses X; bm1_chat511.sh honours
      $BM1_WANT_IDS (the script passes --want-ids when it is set).
"""
import io
import os
import sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bm1_census as B                                         # noqa: E402

REF = [760, 20438, 18253, 5134, 421, 279, 3177, 314, 11751]
P, F = [], []


def check(name, ok, extra=""):
    (P if ok else F).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {extra}" if extra else ""))


def synth(ids):
    log = [{"image": "preamble", "tokens": []}]
    log += [{"image": "lite", "tokens": []} for _ in range(502)]
    log += [{"image": "full", "tokens": [t]} for t in ids]
    return log


def run(log, rc, want):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = B.verdict(log, rc, want)
    return code, buf.getvalue()


def main():
    try:
        check("U1 parse", B.parse_ids("760,20438, 18253") == [760, 20438, 18253])
        try:
            B.parse_ids("760,abc")
            check("U1 junk refused", False)
        except (ValueError, SystemExit):
            check("U1 junk refused", True)
        code, out = run(synth(REF), 0, REF)
        check("U2 identical -> 0", code == 0 and "TOKENS IDENTICAL" in out, out.strip()[:120])
        bad = list(REF)
        bad[4] = 999
        code, out = run(synth(bad), 0, REF)
        check("U3 one differing id -> non-zero, both lists printed",
              code != 0 and str(bad) in out and str(REF) in out, out.strip()[:200])
        code, out = run(synth(REF), 3, REF)
        check("U4 rc 3 not masked", code == 3, f"code {code}")
        code, out = run(synth(REF[:5]), 0, REF)
        check("U5 short list FAILS", code != 0, out.strip()[:120])
        code, out = run(synth(bad), 0, None)
        check("U6 no want -> rc passes through", code == 0)
        a = B.split_chat_argv(["--json", "x.json", "--want-ids", "1,2", "--", "--nch", "4"])
        check("U7 CLI parse", a == ("x.json", [1, 2], ["--nch", "4"]), str(a))
        sh = open(os.path.join(HERE, "bm1_chat511.sh")).read()
        check("U7 bm1_chat511.sh honours BM1_WANT_IDS",
              "BM1_WANT_IDS" in sh and "--want-ids" in sh)
    except AttributeError as e:
        check("API present", False, repr(e))
    print(f"BM1_CENSUS_IDS_TEST: {len(P)} passed, {len(F)} failed")
    return 0 if not F else 1


if __name__ == "__main__":
    sys.exit(main())
