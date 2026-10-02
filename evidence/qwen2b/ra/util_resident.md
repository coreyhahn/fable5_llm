# Resident build utilization — the real baseline for the 2B scratch growth

Closes the first (U) item of `docs/QWEN2B_FEASIBILITY.md:66-72` ("resident
reroll's own utilization report — the study read the base build's").

**Source (read 2026-08-12, timestamp checked):**
`synth/out_build_033_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/bd_wrapper_utilization_placed.rpt`
(Vivado 2024.2, generated 2026-08-12 01:45:32 on snoke, device
xcvu9p-fsgd2104-2L-e, design state *Fully Placed*). This is the build that is
resident on the board (netlist `33d720e5`, VERSION CSR verified,
WNS **+0.009** / TNS 0.000 / WHS +0.010 — `evidence/rung4/RUNG4_GATE.md:1-9`).

## Device totals (report sections 3 and 4, lines 108-132)

| site type | used | available | util% |
|---|---|---|---|
| Block RAM Tile | 560.5 | 2160 | 25.95 |
| — RAMB36/FIFO | 543 | 2160 | 25.14 |
| — RAMB18 | 35 | 4320 | 0.81 |
| URAM | 348 | 960 | 36.25 |
| DSP48E2 | 1858 | 6840 | 27.16 |
| CLB LUTs | 265,083 | 1,182,240 | 22.42 |
| CLB Registers | 277,150 | 2,364,480 | 11.72 |

## Per-SLR (report section 14, lines 369-400) — SLR1 is the constrained die

| site type | SLR0 | **SLR1** | SLR2 | SLR0 % | **SLR1 %** | SLR2 % |
|---|---|---|---|---|---|---|
| CLB | 3464 | 36414 | 15215 | 7.03 | **73.92** | 30.89 |
| CLB LUTs | 15495 | 181463 | 68125 | 3.93 | **46.05** | 17.29 |
| CLB Registers | 22051 | 207548 | 47551 | 2.80 | 26.33 | 6.03 |
| **Block RAM Tile** | **25.5** | **505.5** | **29.5** | **3.54** | **70.21** | **4.10** |
| — RAMB36/FIFO | 25 | 489 | 29 | 3.47 | 67.92 | 4.03 |
| — RAMB18 | 1 | 33 | 1 | 0.07 | 2.29 | 0.07 |
| URAM | 0 | 123 | 225 | 0.00 | 38.44 | 70.31 |
| DSPs | 3 | 739 | 1116 | 0.13 | 32.41 | 48.95 |

SLR capacity implied by the report: **720 BRAM tiles / SLR** (505.5 / 0.7021),
320 URAM, 2280 DSP, 49,260 CLB.

## Projection for the R-b scratch widening

The scratchpad is `16K x 16 b`, **replicated** for the two read ports
(`rtl/layer_chan.sv:450-451`):

```systemverilog
logic signed [15:0] smem_a [16384];
logic signed [15:0] smem_b [16384];
```

Each replica is 16,384 x 16 b = 8 RAMB36 in 2048x18 mode, so scratch costs
**16 RAMB36 today** and **32 after the 16K -> 32K widening**
(`docs/QWEN2B_SCRATCH_MAP.md`: 2B peak 25,600 words -> `SCRATCH = 32768`).

| variant | SLR1 BRAM tiles | SLR1 % | note |
|---|---|---|---|
| today (build 033) | 505.5 | 70.21 | measured |
| feasibility study's "+14 RAMB36" | 519.5 | 72.15 | `QWEN2B_FEASIBILITY.md:22-26` |
| **RTL-derived +16 RAMB36 (2 replicas x 8)** | **521.5** | **72.43** | 2 x (32768/2048) = 32 total |

Both land at ~72%; the study's +14 was a bits/36-Kib estimate that ignored the
port replication and the 2048x18 mapping granularity. **Use +16.**

## Headroom sentence (the point of this file)

At 72.4% of SLR1's 720 BRAM tiles the widening leaves ~198 free tiles on the
critical die, so **the 2B scratch is a timing risk, not a capacity risk** —
consistent with the feasibility verdict, and the reason R-b's risk ranking
puts timing first: this build closed at WNS +0.009 ns, and the scratch is on
the closed paths (`bd_i/layer_0/inst/u_core/...` dominates the near-critical
list in `evidence/rung4/build_033_firstroll_census.txt`).

Two second-order notes for R-b, both from the table above:

- **URAM is not touched** (348 total, see `dn_bank_verify.md`): SLR2 is at
  70.31% URAM but nothing in the 2B port allocates URAM.
- **SLR1 CLB occupancy is 73.92% while its LUT occupancy is only 46.05%** —
  the die is already *placement*-tight rather than logic-tight, so +16 BRAM
  worth of extra address/mux logic will land in a congested region. Budget a
  reroll spread for it (the 5-way spread in rung 4 saw ±0.4 ns).
