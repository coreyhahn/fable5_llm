import sys
import numpy as np
sys.path.insert(0, "/home/cah/r2d2/code/fpga/fable5_llm/ref")
import layer_fixed as LF, load_qwen35 as LQ, model_select as MS, w4a8_ref as W4
st = LQ.SafeTensors(LQ.find_checkpoint())
W = np.asarray(st.get(f"{LQ.TEXT_PREFIX}layers.0.linear_attn.in_proj_qkv.weight"), dtype=np.float64)
q = LF.quant_linear(W)
rows = np.unique(np.nonzero(q["m"] == 1)[0])
print(MS.TAG, "shape", W.shape, "groups m==1:", int((q["m"] == 1).sum()),
      "rows:", len(rows))
print("  row idx :", rows.tolist())
print("  max|W| on those rows:", [f"{v:.3e}" for v in np.abs(W[rows]).max(axis=1)][:4], "...")
print("  full-row underflow? ", bool(np.all(q["m"][rows] == 1)))
