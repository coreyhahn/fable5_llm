# Stage-3 layer orchestration — design (frozen for the gate)

## Decision: command-dispatched layer engine, host as scheduler only
For the stage-3 GATE, the layer is executed by a new `layer_chan` block:
a 16-bit scratchpad SRAM + a command dispatcher + the 7 verified units +
two small new units (gate_unit, vec_alu) + the layer state memories
(DeltaNet state, KV cache, conv state). The HOST issues ~50 commands per
token over AXI-Lite (each command = run one unit over scratchpad
regions); ALL arithmetic — including quantization, requant shifts,
elementwise products and residual adds — happens on-chip. The host moves
no numbers except: weight images (DDR via DMA, as in stage 2), the
initial embedding vector in, the final layer output out, and the 7
matvec round-trips per layer via the EXISTING stage-2 CSR paths
(x8 in via XWIN verbatim-copy, y32 out via RES_DATA verbatim-copy).

Rationale: a fully on-chip sequencer (incl. direct engine plumbing) is
the stage-4 deliverable where tok/s matters; for stage 3 the gate is
bit-exactness of the layer math. Host-mediated matvec transport costs
~30 ms/token — irrelevant for an 8-run x ~24-token gate — and every
transported bit is produced and consumed by verified on-chip units.

## layer_chan contents
- scratchpad: 16K x 16b dual-port BRAM (signed). CSR window with
  auto-increment for host load/store. All units read/write it through
  the dispatcher's port mux.
- units: vecnorm_unit (modes rms1p/rms/l2), rope_unit, conv4_silu (+ its
  weight & state BRAMs: 6144x4 weights, 6144x3 conv state, auto window
  shift per invocation), dn_step (+ state URAM 16 heads x 128 rows x
  2048b), attn_core (+ KV BRAM 2 kv-heads x T<=512 x {k8,v8,exp}, append
  port), gate_unit, vec_alu, fx_silu (exposed via vec_alu SILU op).
- per-layer static params loaded once by host: ln1/ln2/qnorm/knorm
  weights (into vecnorm wbuf via commands), conv weights, A_q15/dt_bias
  per head, rope cos/sin for current position (host-precomputed tables,
  part of the spec).

## Command set (CSR: CMD reg + ARG regs; busy/done status)
  VN  mode,nlog2,inf,outf, src,dst,wsel   — vecnorm over scratch
  ROPE src,dst,tab                         — rope (tables preloaded)
  CONV src,dst,first_ch,nch                — conv4_silu over channels
  GATE src_b,src_a,dst                     — per-head beta/decay (16x)
  DNST head,src_q,src_k,src_v,dec,beta,dst — dn_step on state[head]
  ATTN kvhead,src_q,dst,T                  — attn_core over KV[kvhead]
  KVAP kvhead,src_k,src_v                  — quantize+append KV entry
  ALU  op,src_a,src_b,dst,len,p0           — DYNQ8|SHIFT|SCALE|EMUL|ADD|SUBCLIP
  (exact semantics = ref/layer_fixed.py; the integration TB replays a
  command script and compares against layer_decode_fx golden.)

## Memory budget (gate, T<=512)
scratch 32KB BRAM; DN state 16x128x2048b = 512KB URAM (one layer);
KV 2x512x(256+256+2)B ~ 526KB BRAM/URAM; conv state+weights ~ 86KB.

## Stage-4 path (not gate-blocking)
- direct x8/y32 plumbing matvec_chan <-> layer_chan (CDC streams)
- on-chip token sequencer replacing host commands
- dn_step row pipelining + parallel heads; attn_core score/pv overlap
