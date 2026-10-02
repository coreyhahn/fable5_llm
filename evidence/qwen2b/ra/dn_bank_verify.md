# dn bank address expression — geometry invariance at 2B (Track R, R-a task 2)

**Verdict: CONFIRMED (V). The DeltaNet state URAM addressing contains no
`H` term at all.** Every field of the address is `LNH` / `LDK` / `LDV` /
DN-slot-count, and all four are identical at 0.8B and 2B. 261 URAMs stand.
The KV cache (checked alongside, same argument) is likewise invariant.

## The actual expression (`rtl/layer_chan.sv:509-538`; comments elided)

```systemverilog
// DeltaNet state: 9 URAM banks, each holds two dn slots via an in-bank MSB.
logic [4:0]  dn_layer_r;                                  // LAYER.dn_slot 0..17
wire [11:0]  dn_ra_f = {dn_layer_r[0], dn_head, dn_rda};  // in-bank read
wire [11:0]  dn_wa_f = {dn_layer_r[0], dn_wa};            // in-bank write
wire [3:0]   dn_bsel = dn_layer_r[4:1];                   // bank 0..8
generate for (gd = 0; gd < 9; gd++) begin : g_dn
    (* ram_style = "ultra" *) logic [2047:0] mem [4096];
    always_ff @(posedge aclk) begin
        dn_rdq_b[gd] <= mem[dn_ra_f];
        if (dn_w && dn_bsel == 4'(gd)) mem[dn_wa_f] <= dn_wd;
    end
end endgenerate
```

with `dn_wa = {dn_head, dn_wra}` (`layer_chan.sv:390`), i.e. in full:

```
    bank      = dn_slot[4:1]                       0 .. 8      (9 banks)
    in-bank   = { dn_slot[0], head[3:0], row[6:0] }            (12 bits)
    row width = LDV * 16 = 2048 bits
```

Field by field, with the source of each bound:

| field | width | bound | 0.8B | 2B | grows with H? |
|---|---|---|---|---|---|
| `row` = `dn_rda`/`dn_wra` | 7 b | `LDK` = 128 (`dn_step.s_rdaddr[6:0]`) | 128 | 128 | **no** |
| `head` = `dn_head` | 4 b | `LNH` = 16 | 16 | 16 | **no** |
| `dn_slot` | 5 b | # linear_attention layers = 18 | 18 | 18 | **no** |
| row data width | 2048 b | `LDV*16` (`dn_step` port `s_rddata[LDV*16-1:0]`) | 2048 | 2048 | **no** |

`H` (hidden size) appears nowhere in the expression, and cannot: the state
`S[dk][dv]` is a per-head recurrence matrix whose shape is set by
`LDK x LDV x LNH`, not by the model width. `H` only decides how many int8
activations the *projection matvec* reads before the DN block starts —
that is a scratch/matvec quantity, already covered by
`docs/QWEN2B_SCRATCH_MAP.md`.

`docs/QWEN2B_SCRATCH_MAP.md` (Task 1) confirms all four bounds are
config-identical at 2B: `LNH/LDK/LDV = 16/128/128`, layers 24 (18 DN / 6 GQA).
The only two config fields that move at 2B are `hidden_size` and
`intermediate_size`.

## The 261 URAMs, arithmetic and measured

A URAM288 is 4096 x 72 b. One bank is 4096 x 2048 b:

```
    ceil(2048 / 72) = 29 URAM per bank    x 9 banks = 261 URAM     (dn state)
    ceil(2048 / 72) = 29 URAM per bank    x 3 banks =  87 URAM     (KV cache)
                                            total    = 348 URAM
```

The resident build reports **exactly 348** (`URAM 348 / 960 = 36.25%`,
`synth/out_build_033_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/`
`bd_wrapper_utilization_placed.rpt:119`; per-SLR 0 / 123 / 225 at line 398).
So the 261 figure in `docs/QWEN2B_FEASIBILITY.md:13-14` is not an estimate —
it is the shipped netlist, and nothing in the address expression makes it
move at 2B.

Capacity check for completeness: 9 banks x 4096 rows = 36,864 rows of state,
used = 18 slots x 16 heads x 128 rows = **36,864**. The array is exactly
full at 18 DN layers, at both geometries — 2B adds no DN layer, so it still
fits exactly. (A 2B variant with more than 18 linear_attention layers would
NOT fit; the config says 18, same as 0.8B.)

## KV cache — same check, same answer (`layer_chan.sv:432-462`)

```
    bank    = kv_slot[2:1]                          0 .. 2     (3 banks)
    in-bank = { kv_slot[0], kvhead, k/v, t[8:0] }              (12 bits)
    row     = 2048 b = HD(256) x int8, plus an 8-bit shared exponent
```

`NKV = 2`, `HD = 256`, KV depth `t` = 512, GQA slots = 6 — all identical at
2B (`QWEN2B_SCRATCH_MAP.md` table). No `H` term. 3 banks x 4096 = 12,288 rows
used as 6 slots x 2 kvheads x 2 (k,v) x 512 t = 12,288 — again exactly full,
again unchanged.

## Consequence for R-b

**No R-b scope from this item.** The DN/KV URAM arrays are untouched by the
2B port: same bank count, same address expression, same 348 URAMs, same
exact-fit capacity. R-b's memory work is confined to the scratchpad
(16K -> 32K words, `smem_a`/`smem_b`, `layer_chan.sv:254-255`) and to the
14 -> 15 bit scratch-address packing that widening implies.

One adjacent fact worth carrying into R-b, since it was found while reading
this path: the DN write port is a *single muxed* port
(`dn_w = dn_wren | dnz_we`, `layer_chan.sv:384-390`) precisely because a
second conditional write makes the array URAM-infeasible (the comment
records a 150K-LUT distributed-RAM fallback). Any R-b change that adds a
second writer to this array would silently cost the whole URAM budget.
