# W4A8 quantization spec (frozen for stage 2+)

Everything is integer; no floating point anywhere in the matvec datapath.
Bit-exactness between reference and RTL is then trivial to define: same
integers in, same integers out.

## Formats
- **Weights**: INT4 signed, w ∈ [-8, 7], two per byte (low nibble = even k).
- **Groups**: along the input (K) dimension, **group size G = 128**.
  Justification: power of two; divides every K in the model (1024, 3584,
  256); 128×7×127 < 2^17 so group partial sums fit comfortably in int18
  (we use int32); scale storage overhead = 16/(128·4) = 3.1%; accuracy
  difference vs G=64 to be measured on real weights in stage 5 (spec allows
  G change via parameter, but 128 is the default).
- **Group scales**: UINT16 mantissa `m_g` (per group), plus ONE per-matrix
  exponent `e` (int8). Effective scale of group g = m_g · 2^(e-15).
- **Activations**: INT8 signed vector x ∈ [-128, 127], with one per-tensor
  scale handled outside the matvec (folded into requant constants).
- **Requantization** (to produce INT8 outputs for the next op): per-matrix
  constants (M: uint32 multiplier, S: shift). All rounding is
  **round-half-away-from-zero** implemented as `(v + (1<<(S-1))) >> S` for
  v>=0 and symmetric for v<0 — see ref code, the RTL must match it exactly.

## Matvec pipeline (output row r, K inputs, NG = K/G groups)
1. acc_g = Σ_{k∈group g} w4[r,k] · x8[k]            (int32; |acc| ≤ 8·128·128 = 2^17)
2. p = Σ_g m_g[r·NG+g] · acc_g                       (int64; |p| ≤ NG·2^16·2^17 ≤ 2^38 for NG≤32)
3. y32 = rshift_round(p, sh)                          (int32)
   sh = per-matrix constant >= 0, computed by the quantizer as the smallest
   shift such that worst-case |p|·2^-sh < 2^31 (max int32 headroom is kept,
   so the final rounding is negligible relative to y32 magnitude).
   Dequantization scale of y32 is: xs · 2^(e-15+sh).
4. (optional INT8 out) y8 = clamp(rshift_round(y32 · M, 31), -128, 127)

Step 2-4 constants are computed by the quantizer (ref/w4a8_ref.py) such that
y32 approximates (W_fp @ x_fp) / out_scale.

## Memory layout (DDR4, per matrix, per channel slice)
Row-major, K packed first: for each output row r:
  ceil(K/2) bytes of packed INT4, then NG × 2 bytes of m_g (uint16 LE).
Rows are padded to 64-byte boundaries (one 512-bit AXI beat) so each row
slice starts beat-aligned. 4 DDR channels each hold a contiguous slice of
output rows (row-parallel split).
(Layout may gain a weights-header in stage 4; revisit then.)
