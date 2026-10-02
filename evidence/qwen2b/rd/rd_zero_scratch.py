#!/usr/bin/env python3
# O3 BOARD LOCK (2026-09-01): this script drives the board and does
# NOT take the shared lock (sw/board_lock.py) -- it predates the O3
# ruling and its logic is frozen R-d evidence, so it was not rewritten.
# It is DESTRUCTIVE: it zeroes the whole layer_chan scratchpad.
# Take the lock around it by hand:
#     python3 sw/board_lock.py --tool <why> --exec -- <this script>
"""rd_zero_scratch.py — clear the layer_chan scratchpad, nothing else.

Uses sw/seq_run.py's own Dev (so the full identity gate runs first) and its
R-d `layer_zero_scratch`.  Touches no DDR, starts no sequencer; it exists so
a chat session can be given a KNOWN pre-run scratch state.
"""
import sys

sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/sw")

import numpy as np                                        # noqa: E402
import hwmap as HW                                        # noqa: E402
import seq_run as SR                                      # noqa: E402

dev = SR.Dev("/dev/xdma0", chan=0)
before = dev.layer_read_scratch(0, HW.SCRATCH_WORDS_BUILT)
dev.layer_zero_scratch()
after = dev.layer_read_scratch(0, HW.SCRATCH_WORDS_BUILT)
print(f"  scratch before: {int(np.count_nonzero(before))} non-zero of "
      f"{HW.SCRATCH_WORDS_BUILT}")
print(f"  scratch after : {int(np.count_nonzero(after))} non-zero")
print("SCRATCH_ZERO_OK" if not np.any(after) else "SCRATCH_ZERO_FAILED")
sys.exit(0 if not np.any(after) else 1)
