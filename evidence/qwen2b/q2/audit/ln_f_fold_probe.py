#!/usr/bin/env python3
"""Q6 supplement: the PRODUCTION final-norm container.

audit_ranges.py section 1 audits `model.norm` at Q1.14 (the vecnorm wbuf
format used for ln1/ln2) and flags it ATTENTION.  The real-model emitter
does not use that format for ln_f: gen_model_script.py:401-406 folds the
weight to (1+w) and emits it at Q3.12, with a hard assert.  This probe runs
that exact expression so the 2B report's section-1 row can be read
correctly.
"""
import sys
import numpy as np
sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")
import load_qwen35 as LQ        # noqa: E402
import model_select as MS       # noqa: E402

st = LQ.SafeTensors(LQ.find_checkpoint())
w = np.asarray(st.get(f"{LQ.TEXT_PREFIX}norm.weight"), dtype=np.float64)
q14 = np.round(w * (1 << 14))                       # audit_ranges section 1
q12 = np.round((1.0 + w) * (1 << 12))               # gen_model_script:401
print(f"model                                  : {MS.TAG}")
print(f"model.norm                             : {w.shape[0]} values")
print(f"max |w|      (zero-centered)           : {np.abs(w).max():.6f}")
print(f"max |1+w|    (effective RMSNorm scale) : {np.abs(1.0 + w).max():.6f}")
print(f"AUDIT  Q1.14 round(w * 2^14)   |q|max  : {int(np.abs(q14).max())}"
      f"  -> {int((np.abs(q14) > 32767).sum())}/{w.size} over int16")
print(f"PROD   Q3.12 round((1+w)*2^12) |q|max  : {int(np.abs(q12).max())}"
      f"  -> {int((np.abs(q12) > 32767).sum())}/{w.size} over int16"
      f"   (gen_model_script.py:404 asserts 0)")
