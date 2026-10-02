#!/usr/bin/env python3
"""Q6 supplement: the residual SEED at production res_scale.

audit_ranges.py section 4 measures the embedding seed at res_scale = 1
(`quant_layer`'s default).  Production does NOT: gen_model_script.py:421
emits the seed as

    clip16(round(emb * res_scale * 2**RS_F))

and :425 ASSERTS that zero values clipped.  So the seed occupancy scales
linearly with S while everything else in section 4 (the rmsnorm probe) is
scale-invariant.  Track Q task 5 ruled S = 4 the 2B fixed-point default
(S = 8, the 0.8B production value, rails the 2B int16 residual).

This probe is weights-only and reproduces the production expression
verbatim; run it under FABLE5_MODEL to pick the model.
"""
import os
import sys

import numpy as np

sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")
import layer_fixed as LF        # noqa: E402
import load_qwen35 as LQ        # noqa: E402
import model_select as MS       # noqa: E402

I16_MIN, I16_MAX = -32768, 32767

st = LQ.SafeTensors(LQ.find_checkpoint())
emb = np.asarray(st.get(f"{LQ.TEXT_PREFIX}embed_tokens.weight"), dtype=np.float64)
print(f"model               : {MS.TAG}  ({MS.REPO_DIR})")
print(f"checkpoint          : {LQ.find_checkpoint()}")
print(f"header sha256       : {st.header_sha}")
print(f"embed_tokens        : {emb.shape}  RS_F={LF.RS_F}")
print(f"max |emb| (float)   : {np.abs(emb).max():.6f}")
print(f"rms  emb  (float)   : {np.sqrt((emb * emb).mean()):.6f}")
print()
print("S    | seed = clip16(round(emb*S*2^RS_F))            "
      "| peak LSB / 32767 | util%   | clipped (gen_model_script:425 asserts 0)"
      " | rel RMS err")
print("-----+-----------------------------------------------"
      "+------------------+---------+----------------------------------------"
      "+------------")
rms = np.sqrt((emb * emb).mean())
for S in (1, 2, 4, 8, 16):
    r = np.round(emb * S * (1 << LF.RS_F))
    nclip = int(((r < I16_MIN) | (r > I16_MAX)).sum())
    q = np.clip(r, I16_MIN, I16_MAX)
    peak = float(np.abs(r).max())
    err = q / (S * (1 << LF.RS_F)) - emb
    rel = float(np.sqrt((err * err).mean()) / rms)
    print(f"{S:<4} | Q{7 - int(np.log2(S))}.{8 + int(np.log2(S))} effective "
          f"                        | {peak:>8.0f} /32767 | "
          f"{100.0 * peak / 32767:6.3f}% | {nclip:>10d} / {emb.size:<11d}"
          f"            | {rel:>9.4%}")
print()
print("NOTE the rmsnorm probe of section 4 is scale-invariant (rmsnorm_fx "
      "normalises), so S moves ONLY the seed resolution / clip count above.")
