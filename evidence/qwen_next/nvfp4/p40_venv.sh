#!/usr/bin/env bash
# p40_venv.sh — Ruling C2: a SEPARATE uv venv on snoke's local disk with a CUDA
# torch that still carries sm_61 (Tesla P40, Pascal) plus the shipped venv's
# transformers/numpy/safetensors pins.  /home/cah/.venv (the provenance of
# every committed number) is never touched.
#   evidence/qwen_next/nvfp4/nvfp4_run.sh n##_p40_venv.log \
#       bash evidence/qwen_next/nvfp4/p40_venv.sh <torch-version> <cuXYZ>
set -euxo pipefail
TORCH="$1"; CU="$2"
UV=/home/cah/.local/bin/uv
VENV=/home/cah/.venv_nvfp4_cuda
"$UV" --version
[ -x "$VENV/bin/python" ] || "$UV" venv --python 3.12 "$VENV"
"$UV" pip install --python "$VENV/bin/python" \
    --index-url "https://download.pytorch.org/whl/$CU" "torch==$TORCH"
"$UV" pip install --python "$VENV/bin/python" \
    transformers==5.11.0 numpy==2.4.6 safetensors==0.8.0
"$UV" pip freeze --python "$VENV/bin/python"
"$VENV/bin/python" - <<'PY'
import sys, torch, transformers, numpy
print("python", sys.version.split()[0], "torch", torch.__version__,
      "cuda", torch.version.cuda, "transformers", transformers.__version__,
      "numpy", numpy.__version__)
print("cuda available", torch.cuda.is_available())
print("arch list", torch.cuda.get_arch_list())
print("device", torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))
x = torch.randn(256, 256, device="cuda", dtype=torch.float16)
print("fp16 matmul finite:", bool(torch.isfinite(x @ x).all()))
PY
