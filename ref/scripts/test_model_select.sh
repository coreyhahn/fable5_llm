#!/bin/bash
set -e
PY=ref/.venv/bin/python
# default unchanged
[ "$($PY -c 'import sys; sys.path.insert(0,"ref"); import layer_ref as LR; print(LR.H, LR.FFN, LR.CONV_DIM)')" = "1024 3584 6144" ]
# default loader unchanged (regression lock on the byte-identical-default contract)
[ "$($PY -c 'import sys; sys.path.insert(0,"ref"); import load_qwen35 as LQ; print(LQ.REPO_DIR, LQ.load_config()["hidden_size"])')" = "models--Qwen--Qwen3.5-0.8B 1024" ]
# 2b selected
[ "$(FABLE5_MODEL=2b $PY -c 'import sys; sys.path.insert(0,"ref"); import layer_ref as LR; print(LR.H, LR.FFN, LR.CONV_DIM)')" = "2048 6144 6144" ]
# loader follows
[ "$(FABLE5_MODEL=2b $PY -c 'import sys; sys.path.insert(0,"ref"); import load_qwen35 as LQ; print(LQ.REPO_DIR)')" = "models--Qwen--Qwen3.5-2B" ]
echo MODEL_SELECT_PASS
