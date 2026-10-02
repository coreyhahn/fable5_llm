#!/usr/bin/env python3
"""o3_red_percheckout.py — the RED capture for O3 (plan Task 6 Step 1).

THE DEFECT, DEMONSTRATED RATHER THAN DESCRIBED.  `sw/.seq.lock` is
`os.path.join(SW_DIR, ".seq.lock")` — a path INSIDE the checkout that
computes it.  There are two checkouts of this repo on this machine, they
share one BCU-1525, and each therefore locks a DIFFERENT INODE.  The
mechanism (`flock(LOCK_EX|LOCK_NB)` + a 256-byte holder-identity block) is
right; only the path is wrong, which is exactly what plan Task 6's
"Interfaces" section says.

This script asserts BOTH halves of that sentence and exits 0 only if both
hold:

  CONTROL  two processes in the SAME checkout, both taking that checkout's
           `chat_seq.SeqLock()`, MUST exclude.  (The mechanism works.)
  RED      two processes in DIFFERENT checkouts, each taking its own
           `chat_seq.SeqLock()`, BOTH ACQUIRE.  (The path does not.)

It imports each checkout's own `sw/chat_seq.py`, so what is measured is the
committed code of that checkout and not a transcription of it.

IT STAYS RED FOREVER, ON PURPOSE.  `sw/board_lock.py` does not repair
`SeqLock`'s legacy default by making the old path shared — it replaces the
path.  Any checkout that has not picked up that commit still locks its own
inode, so this script keeps reporting the same defect for the legacy
mechanism.  The GREEN counterpart is `o3_lock_gate.py`, which runs the NEW
lock from two different working directories and requires exclusion.

Usage:
  python3 o3_red_percheckout.py [--checkout DIR --checkout DIR] [--hold 6]
  python3 o3_red_percheckout.py --child <checkout> <resultfile> <hold_s>
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_A = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def _discover_checkouts():
    """Every working tree of this repo, from git itself (not a guess)."""
    out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                         cwd=DEFAULT_A, capture_output=True, text=True)
    dirs = [ln.split(" ", 1)[1].strip()
            for ln in out.stdout.splitlines() if ln.startswith("worktree ")]
    return dirs or [DEFAULT_A]


# ----------------------------------------------------------------------
# the child: acquire that checkout's SeqLock, report, hold, release
# ----------------------------------------------------------------------
def child(checkout, resultfile, hold_s):
    sys.path.insert(0, os.path.join(checkout, "sw"))
    res = {"checkout": checkout, "pid": os.getpid()}
    try:
        import chat_seq as CS                                   # noqa: N806
    except Exception as e:                                      # noqa: BLE001
        res.update(ok=False, why="import chat_seq: %r" % (e,))
        open(resultfile, "w").write(json.dumps(res))
        return 2
    res["module"] = CS.__file__
    res["lock_path"] = CS.LOCK_PATH
    lk = CS.SeqLock()
    try:
        lk.acquire()
    except Exception as e:                                      # noqa: BLE001
        res.update(ok=False, why=str(e))
        open(resultfile, "w").write(json.dumps(res))
        return 1
    try:
        res["identity"] = open(CS.LOCK_PATH).read(256).strip()
    except OSError:
        res["identity"] = ""
    res.update(ok=True, why="")
    open(resultfile, "w").write(json.dumps(res))
    time.sleep(hold_s)
    lk.release()
    return 0


def _spawn(checkout, resultfile, hold_s):
    return subprocess.Popen([sys.executable, os.path.abspath(__file__),
                             "--child", checkout, resultfile, str(hold_s)],
                            cwd=tempfile.gettempdir(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)


def _await(path, proc, timeout=90.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if os.path.exists(path) and os.path.getsize(path):
            try:
                return json.load(open(path))
            except ValueError:
                pass
        if proc.poll() is not None and os.path.exists(path):
            time.sleep(0.2)
            continue
        time.sleep(0.1)
    return {"ok": None, "why": "child produced no result in %.0fs" % timeout}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkout", action="append", default=[],
                    help="repeatable; default = every git worktree")
    ap.add_argument("--hold", type=float, default=8.0)
    ap.add_argument("--child", nargs=3, metavar=("CHECKOUT", "OUT", "HOLD"))
    a = ap.parse_args()

    if a.child:
        return child(a.child[0], a.child[1], float(a.child[2]))

    cos = a.checkout or _discover_checkouts()
    print("O3 RED capture — the per-checkout lock, plan Task 6 Step 1")
    print("  python     %s" % sys.executable)
    print("  checkouts  %d" % len(cos))
    for c in cos:
        print("    %s" % c)
    if len(cos) < 2:
        print("O3_RED_PERCHECKOUT: INCONCLUSIVE — need two checkouts")
        return 2

    tmp = tempfile.mkdtemp(prefix="o3red_")
    fails = []

    # ---- CONTROL: same checkout, two processes -> must exclude ---------
    print("\n[control] two processes, ONE checkout (%s)" % cos[0])
    ra, rb = os.path.join(tmp, "c_a.json"), os.path.join(tmp, "c_b.json")
    pa = _spawn(cos[0], ra, a.hold)
    A = _await(ra, pa)
    print("    A  ok=%s  lock=%s" % (A.get("ok"), A.get("lock_path")))
    pb = _spawn(cos[0], rb, 0.1)
    B = _await(rb, pb)
    print("    B  ok=%s  why=%s" % (B.get("ok"), (B.get("why") or "")[:110]))
    pa.wait(); pb.wait()
    if not (A.get("ok") is True and B.get("ok") is False):
        fails.append("control: same-checkout exclusion did not hold "
                     "(A=%s B=%s)" % (A.get("ok"), B.get("ok")))
    else:
        print("    => EXCLUDED.  The flock mechanism is correct.")

    # ---- RED: two checkouts, two processes -> both acquire -------------
    print("\n[red] two processes, TWO checkouts")
    ra, rb = os.path.join(tmp, "r_a.json"), os.path.join(tmp, "r_b.json")
    pa = _spawn(cos[0], ra, a.hold)
    A = _await(ra, pa)
    print("    A  ok=%s  lock=%s" % (A.get("ok"), A.get("lock_path")))
    print("       module   %s" % A.get("module"))
    print("       identity %r" % A.get("identity"))
    pb = _spawn(cos[1], rb, 0.1)
    B = _await(rb, pb)
    print("    B  ok=%s  lock=%s" % (B.get("ok"), B.get("lock_path")))
    print("       module   %s" % B.get("module"))
    print("       identity %r" % B.get("identity"))
    pa.wait(); pb.wait()

    both = (A.get("ok") is True and B.get("ok") is True)
    distinct = A.get("lock_path") != B.get("lock_path")
    if not both:
        fails.append("red: the two checkouts DID exclude each other "
                     "(A=%s B=%s) — the defect is not reproducible here"
                     % (A.get("ok"), B.get("ok")))
    if not distinct:
        fails.append("red: both checkouts named the same lock path %r"
                     % A.get("lock_path"))
    if both and distinct:
        print("    => BOTH HELD THE BOARD AT ONCE.  Two inodes, one board:")
        print("       %s" % A.get("lock_path"))
        print("       %s" % B.get("lock_path"))

    print()
    for f in fails:
        print("  ! " + f)
    ok = not fails
    print("O3_RED_PERCHECKOUT: " + ("CONFIRMED" if ok else "NOT CONFIRMED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
