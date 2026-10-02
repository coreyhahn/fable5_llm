#!/usr/bin/env python3
"""s1p_base_selftest.py — run `sw/chat_seq.py --selftest` AS IT WAS at a git
rev (default 06ebccd, before S1P touched chat_seq.py), in place: the source
is read with `git show` and executed as __main__ with __file__ pointing at
sw/chat_seq.py, so every relative path resolves as the real tool's does.
Used to tell a pre-existing selftest failure from one S1P introduced.

    python evidence/qwen9b/ov/s1p_base_selftest.py [rev]
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
rev = sys.argv[1] if len(sys.argv) > 1 else "06ebccd"
src = subprocess.check_output(["git", "-C", ROOT, "show", f"{rev}:sw/chat_seq.py"])
path = os.path.join(ROOT, "sw", "chat_seq.py")
sys.path[:0] = [os.path.join(ROOT, "sw"), os.path.join(ROOT, "ref")]
sys.argv = [path, "--selftest"]
print(f"=== sw/chat_seq.py at {rev} --selftest")
g = {"__name__": "__main__", "__file__": path}
exec(compile(src, f"chat_seq@{rev}", "exec"), g)
