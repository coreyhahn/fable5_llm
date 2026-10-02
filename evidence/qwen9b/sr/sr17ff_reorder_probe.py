"""sr17ff_reorder_probe.py -- the seq-rtl round final fix round, item 1 (final-review
minor 1): what chat_seq's CLI actually does with --seq-rtl r2 at 9B --nch 4.
READ-ONLY, NO BOARD: main() runs its real argparse + effective_reorder(),
then a spy wraps check_seq_rtl, records its verdict and raises SystemExit
before the lock, the board or any file write.  Run with FABLE5_MODEL=9b and
FABLE5_REORDER / FABLE5_SEQ_RTL unset (sr_run.sh records the env)."""
import sys, types
sys.path.insert(0, "sw")
import chat_seq as CS
print("MODEL_TAG", CS.MODEL_TAG)
orig = CS.check_seq_rtl
def run(argv):
    got = {}
    def spy(a):
        got["reorder"] = a.reorder
        try:
            got["level"] = orig(a)
        except CS.ChatSeqError as e:
            got["refused"] = str(e)
        raise SystemExit(0)
    CS.check_seq_rtl = spy
    sys.argv = ["chat_seq.py"] + argv
    try:
        CS.main()
    except SystemExit:
        pass
    CS.check_seq_rtl = orig
    print(f"CLI {' '.join(argv):34s} -> effective reorder={got.get('reorder')!r}  "
          + (f"check_seq_rtl -> {got['level']} (ACCEPTED)" if "level" in got
             else f"REFUSED: {got.get('refused')}"))
run(["--seq-rtl", "r2", "--nch", "4"])
run(["--seq-rtl", "r2", "--nch", "4", "--reorder", "B"])
run(["--seq-rtl", "r2", "--nch", "4", "--reorder", "off"])
run(["--seq-rtl", "r2", "--nch", "4", "--reorder", "A"])
run(["--seq-rtl", "r1", "--nch", "4"])
# a namespace that bypasses main() (ChatSession's path): reorder left AUTO
ns = types.SimpleNamespace(seq_rtl="r2", reorder=CS.REORDER_AUTO)
try:
    print("bypass ns reorder=REORDER_AUTO -> ACCEPTED", orig(ns))
except CS.ChatSeqError as e:
    print("bypass ns reorder=REORDER_AUTO -> REFUSED:", e)
ns = types.SimpleNamespace(seq_rtl="r2", reorder="B")
print("bypass ns reorder='B' ->", orig(ns), "(ACCEPTED)")
