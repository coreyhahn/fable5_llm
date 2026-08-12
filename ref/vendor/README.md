Vendor reference sources (Apache-2.0), saved 2026-06-12 for exactness:
- modeling_qwen3_5.py / modular_qwen3_5.py: huggingface/transformers @ main,
  src/transformers/models/qwen3_5/. THE ground truth for layer math
  (GatedDeltaNet recurrence, attention with output gate, partial mRoPE,
  RMSNormGated). ref/layer_ref.py mirrors these in numpy.
