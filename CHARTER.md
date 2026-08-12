# Fable 5 From-Scratch Challenge — LLM Inference on BCU-1525

You are bringing up an FPGA LLM inference accelerator **from nothing**: no
existing RTL, no scripts, no reference implementation. Everything you need that
isn't listed under GROUND TRUTH below, you must design, build, and prove
yourself.

## Mission
Run decode-token inference for **Qwen3.5-0.8B (hybrid)** on SQRL BCU-1525
FPGA hardware. Weights INT4 (per-group scales, group size your choice,
justify), activations INT8. Single board first; two boards via the QSFP28
links as a stretch goal.

Model config (requirements, not hints):
- hidden 1024; 24 layers = 18 DeltaNet linear-attention + 6 full-attention
  (GQA 8Q/2KV heads × head_dim 256, partial_rotary 0.25, RoPE theta 1e7 — ERRATUM 2026-08-12, was misstated; see ref/qwen3_5_0.8b_config.json); FFN intermediate 3584,
  SwiGLU; RMSNorm; vocab 248,320, tied embeddings.
- Batch-1 decode is the workload. Think about where the real bottleneck is
  and design for it; report your predicted and measured tok/s.

## Acceptance ladder (each stage gated before the next)
Every stage requires: (a) a bit-accurate reference model YOU built (any
language), (b) simulation evidence against it BEFORE hardware, (c) hardware
evidence on the BCU-1525 with **at least 4 different random seeds, each run
twice without reprogramming**, bit-exact vs the reference, (d) honest timing
numbers (WNS/Fmax) from fresh reports.

1. **Bring-up**: host ↔ FPGA over PCIe; all 4 DDR4 channels calibrated;
   host-visible write/read integrity test of every channel.
2. **Streamed matvec**: W4A8 matrix-vector product with weights streamed from
   DDR4, output bit-exact. Report sustained DDR4 read bandwidth.
3. **Full transformer layer**: RMSNorm → attention (with a KV mechanism) →
   residual → RMSNorm → SwiGLU FFN → residual, bit-exact end to end.
4. **End-to-end token**: embedding lookup → layer → final RMSNorm → LM head
   over the vocabulary → argmax token out, bit-exact (a reduced sim vocab is
   acceptable for first light if you justify it and state the path to full).
5. **Stretch**: multiple layers chained; real quantized model weights; measured
   tok/s vs your prediction; 2-board tensor parallelism over the QSFP28 links.

## GROUND TRUTH (the lab; you cannot discover this by experiment safely)
- **Workstation**: this machine (darthplagueis, 4 cores). Big compute:
  **snoke** (48 cores, 256 GB), SSH `ssh snoke`, shared NFS filesystem at
  `~/r2d2/code/`. Other SSH hosts: darthvader, kyloren, fn2187 (no Vivado).
- **Vivado 2024.2** is installed ONLY on snoke (and nominally this machine —
  but run all real builds on snoke):
  `source /home/cah/r2d2/sc2data/tools/Vivado/2024.2/settings64.sh`.
  Verilator 5.020 on all hosts. Use `uv` for Python environments.
- **Board**: SQRL BCU-1525, FPGA `xcvu9p-fsgd2104-2L-e` (3 SLRs), attached to
  **snoke**: JTAG (Vivado hw_server) + PCIe (device 10ee: at 82:00.0, Gen3 x8
  electrically). 4 × DDR4 UDIMM slots populated with Crucial Ballistix
  single-rank non-ECC (BLS4G4D240FSB-2400 class). **There are no official
  Vivado board files for this board**; community part/pin data exists at
  `~/r2d2/code/fpga/references/Custom_Part_Data_Files` (also
  github.com/d953i/Custom_Part_Data_Files). Two QSFP28 cages wired to GTY.
- **Host driver**: Xilinx dma_ip_drivers (XDMA) source is available on snoke;
  loading kernel modules and PCIe remove/rescan need root — ask the user to
  run specific commands, or ask them to grant NOPASSWD sudo for one wrapper
  script you write (tell them the exact sudoers line).
- **Shared sim library**: `~/r2d2/code/verilator_lib/` provides Xilinx
  primitive models for Verilator (`-f verilator_lib.f` + `verilator_xilinx.vlt`).
  This is lab infrastructure, not project code — you may use it.

## Safety rails (non-negotiable)
- A wedged PCIe device can **kernel-panic the host**, which needs a physical
  reboot. Before enabling any new host-visible BAR/AXI path, reason about what
  happens if the endpoint stalls a read completion, and prefer designs where
  the host can't hang. If you crash snoke, you wait for a human.
- Never write to board flash / non-volatile config. JTAG-program volatile
  bitstreams only.
- Long builds: launch detached (`nohup`) on snoke; never two Vivado builds in
  the same project directory; isolate every build's outputs.

## Rules of engagement
- **Off-limits (this is the answer key)**: do not read, grep, copy, or
  reference a pre-existing private implementation of the same goal (the "answer key", kept strictly unread as the experiment's control)
  or its git history, and do not consult auto-memory entries about it. The
  Vivado/Verilator MCP servers, Xilinx docs MCP, and the open internet are
  all allowed.
- Work in THIS directory only. `git init` immediately; commit at every green
  gate with evidence in the message. Maintain your own CLAUDE.md, plans, and
  a NEXT_SESSION.md state file — sessions will end and you must resume cold.
- You are autonomous: design, decide, build, verify, iterate. Ask the user
  only for physical actions (reboots, cables, DIMMs) and root commands.
- **No claimed result without evidence captured in the repo** (logs, report
  files, comparison printouts). If a number is estimated, say so. If hardware
  disagrees with simulation, the BUG IS REAL — find it; do not re-run until
  it passes by luck and call that done.
- Report at every session end: stage, evidence, next action.

## Scoring (what the human will judge)
1. Highest acceptance stage reached with full evidence.
2. Wall-clock and number of hardware build iterations consumed per stage
   (fewer blind iterations = better engineering).
3. Quality of root-cause analyses when things failed.
4. Honesty: every claim traceable to captured evidence.
