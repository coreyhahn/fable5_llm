# R3-8 — the MOVX broadcast in RTL, form (a): the direct x-push bus

Task R3-8 of the R3 campaign (`docs/superpowers/plans/2026-09-29-r3-broadcast.md`, Task R3-8, and
the controller addendum in the task brief). Contract: `docs/SEQ_ISA.md` v2.3 §B17.3 (R3-1). Golden:
`ref/seq_model.py`'s R3 block (R3-3), through `tb/scripts/gen_seq_unit_vectors.py`'s twin executor.
Design: spec `docs/superpowers/specs/2026-09-27-seq-rtl-round-design.md` §1.3 (a).

Scope: RTL, the two IP-integrator wrappers, the block-design loop, unit TBs, lint, a BD-only
Vivado check and OOC counts. **No project build, no board.** Base a65f87c (HEAD at dispatch 1f450af);
every run is on snoke through `evidence/qwen9b/sr/sr_run.sh`; the log block is n3000–n3099 (used
n3000–n3046). Every obj_dir is task-private (tb/obj_dir_*_r3*, one host).

**Acceptance, one line each.**

1. **RED → GREEN.** On the pre-R3 RTL the unit TB scores 0 of 47
   (`evidence/qwen9b/sr/n3002_r3_8_tb_seq_RED.log:775`), and `tb_matvec_chan` does not elaborate
   (PINNOTFOUND on the push ports, `evidence/qwen9b/sr/n3003_r3_8_tb_matvec_chan_RED.log:11`).
   GREEN:
   * the unit TB 47 of 47 (`evidence/qwen9b/sr/n3005_r3_8_tb_seq_each_GREEN.log:744`);
   * `tb_seq_all` 77 SEQ PASS with the four lockstep holds
     (`evidence/qwen9b/sr/n3006_r3_8_tb_seq_all_GREEN.log:667`,
     `evidence/qwen9b/sr/n3006_r3_8_tb_seq_all_GREEN.log:1154`);
   * `tb_matvec_chan` 52 PASS: 36 pre-R3 runs and 16 push-leg runs, 4 seeds each
     (`evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:656`);
   * `tb_seq_offifo` (`evidence/qwen9b/sr/n3009_r3_8_tb_seq_offifo_GREEN.log:668`);
   * `tb_matvec` (`evidence/qwen9b/sr/n3014_r3_8_tb_matvec_GREEN.log:214`);
   * `tb_mvshim_b` (`evidence/qwen9b/sr/n3010_r3_8_tb_mvshim_b_GREEN.log:47`).
2. **Lint:** zero `%Warning` over `lint_seq_unit`, `lint_matvec`, `lint_mvshim_b`,
   `lint_seq_chip_9b`, `lint_seq_chip_9b_tl` and the new `lint_r3`
   (`evidence/qwen9b/sr/n3004_r3_8_lint.log:44-46`). It ran before the first GREEN simulation.
3. **SEQ_CAPS** = `HW.seq_caps_word({"R1","R2","R3"})` = 0xFAB1CA07, read back on every
   `tb_seq_all` run (77 of 77) and on every `tb_seq_offifo` run (41 of 41,
   `evidence/qwen9b/sr/n3009_r3_8_tb_seq_offifo_GREEN.log:664`).
4. **Backward compatibility.**
   * Every pre-R3 golden is byte-identical: 387 of 387. The 43 caps.hex files move exactly
     fab1ca03 → fab1ca07 (`evidence/qwen9b/sr/n3011_r3_8_golden_same.log:11`).
   * The 40 pre-R3 unit vectors run cycle-identical, base vs R3
     (`evidence/qwen9b/sr/n3024_r3_8_cycles_base_vs_r3.log:48`).
   * The 36 pre-R3 `tb_matvec_chan` runs are cycle-identical to SR12 fix 1's n1249, in order
     (`evidence/qwen9b/sr/n3023_r3_8_mv_cycles_vs_sr12f1.log:8`).
   * `tb_mvshim_b`'s four PASS lines are identical to SR12's n1243
     (`evidence/qwen9b/sr/n3031_r3_8_mvshim_vs_sr12.log:6`).
5. **The block design validates** with exactly the new nets: CREATE_PROJECT_OK, 0 ERROR, and the
   CRITICAL WARNING set identical to build_045_r2's (`evidence/qwen9b/sr/n3021_r3_8_bdcheck.log:9-12`).
   It has 20 BD nets = 188 bits (47 per channel), and every end is on `xdma_0_axi_aclk`
   (`evidence/qwen9b/sr/n3021_r3_8_bdcheck.log:33`).
6. **OOC:** no new BRAM, URAM or DSP in `seq_unit` or `matvec_chan`. The LUT/FF deltas are in §6.
   `layer_chan` is exact at 182 / 79 / 8 / 1840 (§6).
7. **Step 5b, the twin:** the generator's broadcast executor and `ref/seq_model.py`'s agree on
   every XWIN word, the MOVX source scratch, XPTR and the admission refusals (0 FAIL,
   `evidence/qwen9b/sr/n3019_r3_8_twin.log:27`).
8. **Negative controls:** a mover that ignores room, and a channel whose XP_INFLIGHT is 1, are
   both caught (`evidence/qwen9b/sr/n3032_r3_8_mutants.log:18-22`).
9. **Chip-TB smoke on the new top:** shipped s1 on the R3 binary (K=r3), **196,706,821 cycles =
   n1310's**, tokens identical (`evidence/qwen9b/sr/n3043_r3_8_chip_smoke_s1_shipped.log:32`) — §8.
10. **Cite drift:** zero. No cited line of any edited file moved (§9).
11. **The chip-TB top change:** the first cut hung the smoke. It was diagnosed to the TB clock
    construct (the RTL runs cycle-identical under the original clock) and fixed; §8.

## 1. The RTL, by site

Every edit to a pre-existing line is **in place**: one line rewritten, no line inserted. All new
logic is **appended below the last line any document cites** in that file. So every
post-edit line number below equals its pre-edit number, and the appended blocks start after the
last cited line (§9). Line numbers are at the RTL commit bfc2eff, which is unchanged since then.

| file | line(s) | change |
|---|---|---|
| `rtl/seq_unit.sv` | `rtl/seq_unit.sv:53` | Header map: r3 = 1 (the MOVX broadcast, B17.3). |
| | `rtl/seq_unit.sv:272` | Ports, on the mv_busy_bm line: xpush_valid [3:0], xpush_idx [47:0], xpush_data [127:0] (out); xpush_room [3:0], xpush_busy [3:0] (in). |
| | `rtl/seq_unit.sv:335-339` | SEQ_CAPS → `{24'hFAB1CA, 5'd0, 1'b1 /*r3*/, 1'b1 /*r2*/, 1'b1 /*r1*/}` = 0xFAB1CA07. |
| | `rtl/seq_unit.sv:800` | Validator: E_CHAN for flags[7:4] ≥ 4, except MOVX 0xF. The broadcast falls through to B17.2's start-word rule (v_movx_rsvd, err 0x06). MOVX 4..14 and every MVGO ≥ 4 still get 0x05. MOVY is untouched. |
| | `rtl/seq_unit.sv:892`, `rtl/seq_unit.sv:977`, `rtl/seq_unit.sv:1087` | `mv_bcast`: declared, reset with the other mv_*, set by the MOVX dispatch to (flags[7:4] == 0xF). |
| | `rtl/seq_unit.sv:1521`, `rtl/seq_unit.sv:1550` | u_mov: `.cmd_bcast(mv_bcast)` and the four-channel push ports. |
| | `rtl/seq_unit.sv:1653-1676` | R3 block (comment only): what the above does. |
| `rtl/seq_movers.sv` | `rtl/seq_movers.sv:105`, `rtl/seq_movers.sv:168` | Ports: `cmd_bcast`; the push bus. |
| | `rtl/seq_movers.sv:252` | Declarations: bcast_q, xp_fire, xp_done; `cmd_is_bc = cmd_bcast && (cmd_op == MOP_MOVX)`, so a stale mv_bcast under a later MVGO/MOVY/FENCE is inert. |
| | `rtl/seq_movers.sv:575` | The elastic buffer pops on a push (`xp_fire`) as it pops on a W beat. |
| | `rtl/seq_movers.sv:613`, `rtl/seq_movers.sv:637`, `rtl/seq_movers.sv:644` | Reset; for a broadcast, chan_q latches 0 (the STATUS walk starts at channel 0) and bcast_q is latched. |
| | `rtl/seq_movers.sv:663` | X_SPTR goes to X_DRAIN for a broadcast: **no XPTR write** (B17.3). |
| | `rtl/seq_movers.sv:673` | X_DRAIN: no burst-write descriptor for a broadcast. The scratch read descriptor and the XWIN window $error are unchanged, so the sim-only overflow check covers the broadcast. |
| | `rtl/seq_movers.sv:707` | X_END also waits for `xp_done` (the commit contract, §2.3). |
| | `rtl/seq_movers.sv:715` | X_STATW: for a broadcast, the four STATUS reads are walked channel 0..3. Any xfifo_ovfl → E_XFIFO_OVF, the unicast's error surface ×4. |
| | `rtl/seq_movers.sv:939-1029` | R3 block: XP_FWD_STAGES / XP_RET_STAGES / XP_RT; the input flops; the per-channel output flops; xp_widx; xp_fire (lockstep); xp_done; xp_rt. |
| `rtl/matvec_chan.sv` | `rtl/matvec_chan.sv:187` | Ports, on the mv_busy_bm line: xpush_valid, xpush_idx [11:0], xpush_data [31:0] (in); xpush_room, xpush_busy (out). |
| | `rtl/matvec_chan.sv:255-256`, `rtl/matvec_chan.sv:261-263` | The XWIN FIFO mux gains the third source: xf_push_p / xf_din_p, priority AXI-Lite > push > burst. |
| | `rtl/matvec_chan.sv:592` | The burst's ws_can also holds on a push drain. |
| | `rtl/matvec_chan.sv:707-831` | R3 block: the input register, the skid (8 × 44, LUTRAM), the drain (it holds on `!xf_full && !xf_push_a && !axil_wr_commit`, the ws_can condition), the room/busy flops, the sim-only checks. |
| `rtl/seq_unit_ipi.v` | `rtl/seq_unit_ipi.v:191`, `rtl/seq_unit_ipi.v:241` | 20 per-channel pins xpush0..3 _valid / _idx / _data / _room / _busy (on a blank line); the concatenation into u_seq (on the mv_busy_bm line). |
| `rtl/matvec_chan_ipi.v` | `rtl/matvec_chan_ipi.v:121`, `rtl/matvec_chan_ipi.v:178` | The five push pins (on a blank line); their connection. |
| `synth/scripts/create_project.tcl` | `synth/scripts/create_project.tcl:568` | The 20 `connect_bd_net` calls as a one-line loop on the blank line before `validate_bd_design`. |
| | `synth/scripts/create_project.tcl:586-637` | The comment ("no clock, no CDC, no constraint", the SLR crossings) and a read-only check after the save. The check requires one net per pin pair, the expected width, both ends' `aclk` on the `xdma_0/axi_aclk` net, and 188 bits / 20 nets. It prints XPUSH_NET per net and XPUSH_BUS_OK. |

`rtl/matvec_engine.sv` is untouched, as planned.

## 2. The design

### 2.1 The bus

Per channel c, all on aclk (`xdma_0/axi_aclk`):
* **Forward, 45 bits**, seq_0 → mvchan_c: valid (1), the XWIN word index (12), the word (32).
* **Return, 2 bits**, mvchan_c → seq_0: room, busy.

That is **47 per channel and 188 in all**. Both ends are flops:

| end | cells (Verilog names; the synthesized names carry `_reg`) |
|---|---|
| seq_0 output | `xp_v_q[c]`, `xp_i_q[c]`, `xp_d_q[c]` (seq_movers R3 block). One copy per channel, KEEP, loaded from the elastic buffer's head when all four rooms are high. |
| mvchan_c input | `xp_in_v`, `xp_in_d[43:0]` (idx at [43:32], data at [31:0]; matvec_chan R3 block), KEEP. |
| mvchan_c room / busy | `xpush_room`, `xpush_busy`: flops, reset 0. |
| seq_0 input | `xp_room_q[c]`, `xp_busy_q[c]`, KEEP, reset 0. |

The FIFO entry stays {12-bit word index, 32-bit data} for every leg. The push carries the
absolute XWIN word: the broadcast's start word plus the offset, from xp_widx. So R2's bank 1 is
word 1536 + w, as on the burst leg, and the bank semantics are unchanged.

### 2.2 The register stages, XP_INFLIGHT and the skid

There is **one parameter set**, declared in both modules. The chip TB and `tb_matvec_chan` check
that the two copies are equal.
* **XP_FWD_STAGES = 2:** seq_movers' output flop and matvec_chan's input register.
* **XP_RET_STAGES = 2:** matvec_chan's room/busy flop and seq_movers' input flop.

**XP_INFLIGHT = XP_FWD_STAGES + XP_RET_STAGES + 1 = 5.** Suppose the room flop is computed from
the skid count in cycle T. Five words can be in flight that the count does not include:
* the two in the forward flops (fired in T-2 and T-1);
* the three fired in T, T+1 and T+2. T+2 is the last fire that can still see that room value
  high.

So "at least 5 free entries" covers every word in flight.

**The skid is XP_SKID = 8.** It is the smallest power of two that is at least 5 + 3. With a free
drain, the count stays at 1 or 2 at one word per cycle, so room never drops.

Measured (`tb_matvec_chan`, one push per cycle, which is four times the mover's own rate):
* with a free drain, the skid peaks at 1 and room never drops;
* with the ui clock stopped until room drops, the skid peaks at **exactly 8, never over**;
* no word is lost in any of the 16 push-leg runs (sent = landed on every run,
  `evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:437`).

The mutant M2 (XP_INFLIGHT 1) overflows the skid and trips the RTL's own check
(`evidence/qwen9b/sr/n3032_r3_8_mutants.log:20`).

### 2.3 The commit contract (plan review I-4)

**XP_RT = XP_FWD_STAGES + XP_RET_STAGES = 4.** When the last word sits in the output flop, xp_rt
loads XP_RT and counts down. The broadcast retires only when:
* xp_rt has reached 0;
* no word is in the output flop;
* all four busy input flops read low.

A busy low in the input flop in cycle X describes the channel in cycle X-2: the input register
and the skid were both empty then. After the wait, that is later than the last word's arrival in
the input register, so every pushed word is in u_xfifo. This is the burst leg's contract
(`rtl/matvec_chan.sv:100-110`) restated for the push leg.

The shortest last-push → retire is 5 cycles in the TB's cycle-accurate model of seq_0's side
(`evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:425`), which is also the RTL's.

Retiming either end changes these numbers, and both modules' copies must change together. That is
R3-10's retiming note.

**Where the sim-only checks live (plan minor n3):**
* **`rtl/matvec_chan.sv:815-831`:**
  * a push that arrives with the skid full (a lost word);
  * a push-leg FIFO write while xpush_busy reads low (the local half of "nothing lands after
    retire");
  * a push outside the 3072-word XWIN;
  * x-push with AXI-Lite, or x-push with burst, draining in the same cycle.
* **`tb/tb_seq_chip.sv`, R3 block, the end-to-end half:**
  * at every broadcast retire, each built channel's push-leg FIFO writes must equal the words the
    bus carried to it;
  * a push-leg write after that retire is a $fatal.
* **`tb/tb_matvec_chan.sv`, R3 block:** the same two checks, against the TB's model of seq_0.
* **`tb/seq_stub_mvchan.sv`, R3 block:** at most two pushes may arrive after room drops (the
  return path is two flops).
* **`tb/tb_seq_unit.sv`, R3 block:**
  * lockstep: xpush_valid is 0 or 4'hF, and the four idx/data are equal;
  * a push with the mover idle;
  * the B windows.

### 2.4 Priority and the holds

**AXI-Lite > push > burst.** The push drain holds exactly as the burst's does: on `!xf_full`,
`!xf_push_a` and `!axil_wr_commit`. So the AXI-Lite leg's full test in the commit cycle cannot be
made stale by a push taking the last slot. The burst's ws_can also holds while a push drains, so
the two never drain in one cycle.

Forced in `tb_matvec_chan +pushcoll`:
* The XWIN FIFO holds 31 words with ui_clk stopped
  (`evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:448`).
* With the FIFO one slot from full and a push word waiting in the skid, an AXI-Lite XWIN write
  commits. AXI-Lite takes the slot, xfifo_ovfl stays 0 and both words land
  (`evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:457`, 1 of 8 swept phases, every
  seed).
* Push vs burst contention was measured on 964 / 132 / 580 / 324 cycles across the seeds. On none
  of those cycles did a burst beat drain while a push waited.

## 3. The tests

* **`tb/scripts/gen_seq_unit_vectors.py`, the twin**, all in its R3 block after line 1427:
  * BUILD_CAPS gains R3.
  * The validator admits MOVX 0xF, mirroring ref/seq_format's `_movx_bcast_admitted`.
  * The executor mirrors `_movx_bcast`: the running check on every destination first, one
    scratch read, the same words to channels 0..3, no XPTR write, each stub xsum grown.
  * The MVGO dispatch mirrors the stub's doorbell xsum reset. The pre-R3 Model never needed it,
    and no existing golden moved (n3011).
  * New: build_bcast, one stream per seed (seq_h_bcast, seq_h_bcast2..4). It has:
    * bank-0 and bank-1 broadcasts, the bank-1 one while no-wait bank-0 streams run on all four;
    * a mask-0 FENCE;
    * MOVYs of every channel;
    * XBANK MVGOs;
    * a broadcast followed by a unicast over the same window;
    * a ragged odd-start broadcast and a zero-length one.
  * New error vectors: bcast_mvgo (0x05), movx_chan5 (0x05) and bcast_range (0x06). Each follows
    legal records including a legal broadcast.
* **`tb/tb_seq_unit.sv` + `tb/seq_stub_mvchan.sv`:**
  * the push monitor: lockstep, B windows, the canonical four-writes trace, no push with the mover
    idle;
  * the stub's push port;
  * `+xp_lowroom`, the lockstep case: one stub drops room mid-broadcast. After the 2-cycle return
    path nothing may arrive anywhere, and pushes must resume. It runs once per seed, on channels
    0/1/2/3.
* **`tb/tb_matvec_chan.sv`:** `+push`, `+pushstall`, `+pushcoll`, `+pushburst` and
  `+pushthenburst` (a broadcast-then-unicast to the same window: ~x is pushed, then x is burst,
  and the engine computes on x). Bank 0 and bank 1. x_mem is checked word for word and the
  results bit-exact, 4 seeds × 4 modes.
* **`tb/tb_mvshim_b.sv`:** ties the new ports idle.
* **`tb/Makefile`:** SEQ_ERRS / SEQ_DIRECTED gain the new vectors. The tb_seq recipe runs
  SEQ_XPHOLD. SEQ_DEFS (`+define+R3_NO_XPUSH_PORTS`) is for the RED build. The tb_matvec_chan
  recipe gains the push runs. `lint_r3` is new. Every addition rides on an existing line or is
  appended after line 1884.

## 4. RED → GREEN, lint

| run | log | result |
|---|---|---|
| RED unit TB, pre-R3 RTL at 14d321c, `+define+R3_NO_XPUSH_PORTS` | `evidence/qwen9b/sr/n3002_r3_8_tb_seq_RED.log:775` | **0 / 47**. Every vector reads SEQ_CAPS fab1ca03 against fab1ca07. seq_h_bcast ×4 halt err 0x05 at the first broadcast. bcast_range faults 0x05, not 0x06. movx_chan5 faults at pc 0, on its legal broadcast. |
| RED tb_matvec_chan build | `evidence/qwen9b/sr/n3003_r3_8_tb_matvec_chan_RED.log:78` | Does not elaborate (22 errors, PINNOTFOUND on the five xpush pins first). |
| lint | `evidence/qwen9b/sr/n3004_r3_8_lint.log:44-46` | 0 %Warning, rc 0. |
| GREEN unit TB, each vector | `evidence/qwen9b/sr/n3005_r3_8_tb_seq_each_GREEN.log:744` | 47 / 47. |
| `make tb_seq_all` (SEQ_SEEDS 1 2 3 4) | `evidence/qwen9b/sr/n3006_r3_8_tb_seq_all_GREEN.log:1154` | rc 0. 77 SEQ PASS; 77 SEQ_CAPS fab1ca07 == hwmap; 4 TB_SEQ_XPHOLD PASS (`evidence/qwen9b/sr/n3006_r3_8_tb_seq_all_GREEN.log:667`). |
| `make tb_seq_offifo` | `evidence/qwen9b/sr/n3009_r3_8_tb_seq_offifo_GREEN.log:668` | 41 SEQ PASS, each fab1ca07. |
| `make tb_matvec_chan` | `evidence/qwen9b/sr/n3020_r3_8_tb_matvec_chan_GREEN.log:656` | 52 PASS: 4 frozen + 12 9B + 20 SR12 bank + 16 push-leg. |
| `make tb_matvec` | `evidence/qwen9b/sr/n3014_r3_8_tb_matvec_GREEN.log:214` | Unchanged. |
| `make tb_mvshim_b` | `evidence/qwen9b/sr/n3010_r3_8_tb_mvshim_b_GREEN.log:47` | 4 seeds + the sabotage self-test. |
| negative controls | `evidence/qwen9b/sr/n3032_r3_8_mutants.log:22` | M1 (the mover ignores room) is caught by the stub's return-path bound. M2 (XP_INFLIGHT 1) is caught by the skid-full check. 2 of 2. |

The lockstep holds are non-vacuous: each resumed after the hold (230 / 402 / 580 / … pushes).

## 5. Backward compatibility and the BD

* **Goldens:** `evidence/qwen9b/sr/n3011_r3_8_golden_same.log:11`. It uses sr12_golden_same.sh
  with its new optional caps-set arguments; the defaults are unchanged.
* **Unit cycles:** 40 of 40 identical (`evidence/qwen9b/sr/n3024_r3_8_cycles_base_vs_r3.log:48`).
  The per-vector table is above that line.
* **Channel cycles:** 36 of 36 perf lines and PASS lines identical to n1249, in order
  (`evidence/qwen9b/sr/n3023_r3_8_mv_cycles_vs_sr12f1.log:8-10`). n3022 compared against the
  28-run n1244 by mistake and is superseded.
* **The BD** (`evidence/qwen9b/sr/r3_8_bdcheck.sh`, into the fresh `synth/out_r3_bdcheck2/`):
  0 ERROR, 11 CRITICAL WARNINGs, the set identical to `synth/out_build_045_r2/create.log`'s, and
  the 20 XPUSH_NET lines (`evidence/qwen9b/sr/n3021_r3_8_bdcheck.log:13-32`).
  The first attempt, n3012, connected the nets after the first `validate_bd_design`. That
  validate saw the 20 new input pins unconnected (BD 41-759) and the CW list doubled. It was fixed
  in 761d1b7 (§1) and is superseded.

## 6. OOC counts

`evidence/qwen9b/g4/run_g4b_ooc.sh` (SR12's method), fresh `synth/out_ooc9b_r3_*` dirs. The base
runs were on 1f450af before any RTL edit; the R3 runs were on 5d52639 (RTL = bfc2eff).

| top | run | LUT | FF | RAMB36 / RAMB18 | URAM | DSP | log |
|---|---|---|---|---|---|---|---|
| `seq_unit` | base | 4,100 | 3,050 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n3000_r3_8_ooc_seq_base.log:743-747` |
| | R3 | 4,078 | 3,255 | 0 / 0 | 0 | 0 | `evidence/qwen9b/sr/n3016_r3_8_ooc_seq_r3.log:744-748` |
| | **Δ** | **−22** | **+205** | 0 | 0 | 0 | |
| `matvec_chan` (one of four) | base | 14,958 | 14,123 | 4 / 0 | 0 | 2 | `evidence/qwen9b/sr/n3001_r3_8_ooc_mv_base.log:1123-1127` |
| | R3 | 15,012 | 14,180 | 4 / 0 | 0 | 2 | `evidence/qwen9b/sr/n3017_r3_8_ooc_mv_r3.log:1128-1132` |
| | **Δ** per channel (×4 = +216 LUT, +228 FF) | **+54** (LUT-as-memory +28) | **+57** | 0 | 0 | 0 | |
| `layer_chan` | R3 tree (control; untouched by R3) | 113,216 | 61,437 | **79 / 8** | **182** | **1840** | `evidence/qwen9b/sr/n3018_r3_8_ooc_layer_r3.log:16683-16687` |

* **The base runs equal SR12's R2 numbers exactly** (4,100 / 3,050 and 14,958 / 14,123).
* **`layer_chan` is exact** in every count against SR12's control (`evidence/qwen9b/sr/n1245_ooc_r2.log:84-88`): URAM 182, RAMB36 79 / RAMB18 8, DSP 1840 (`evidence/qwen9b/g5/G5C_RTL.md:773-777`), LUT 113,216, FF 61,437.
* **seq_unit's +205 FF is exactly the new state:**
  * output flops 4 × 45 = 180;
  * input flops 8;
  * xp_widx 12;
  * xp_rt 3;
  * bcast_q 1;
  * mv_bcast 1.

  Its LUT count fell by 22 (synthesis movement; no cell-by-cell attribution was done).
* **matvec_chan's +57 FF is exactly the new state:**
  * the input register 45;
  * wp 3;
  * rp 3;
  * count 4;
  * room 1;
  * busy 1.

  The skid is LUTRAM (+28 LUT as memory). No new memory or DSP primitive.

## 7. Step 5b — the twin cross-check

`evidence/qwen9b/sr/r3_8_twin.py`, run with FABLE5_MODEL=9b and FABLE5_RS_F=7. For each seed's
build_bcast stream, the generator's Model runs it whole. `ref/seq_model.SeqExec` at caps
{R1,R2,R3} runs its data-movement records: the LDC, rebased, and every MOVX, unicast and
broadcast. MVGO needs weight images, and the stub's matvec is not the model's.

The scratch mapping: the RTL moves each 16-bit scratch word's low byte, and the model's scratch is
int8-packed. So the model's blob holds the sign-extended low bytes.

Compared:
* the 4 × 3072-word XWIN images: 560 / 1,280 / 2,048 / 1,280 written words, **0 differ**;
* the MOVX source scratch, words 0..8191: 0 differ;
* XPTR: the unicast's channel only; broadcasts write none;
* the three error vectors: the generator's (err, pc) against ref/seq_format.validate_stream's
  refusal;
* build_bcast at caps {R1,R2}: refused by the validator naming R3, and err 0x05 at the first
  broadcast in the generator.

**0 FAIL** (`evidence/qwen9b/sr/n3019_r3_8_twin.log:27`). n3015 is the same run with
FABLE5_MODEL set only in the child, so the wrapper header read "unset". It is superseded.

## 8. The chip-TB top (`tb/tb_seq_chip.sv`) and the smoke

The push ports are wired between seq_unit and the NMV real matvec_chan instances, exactly as
create_project.tcl wires them. An unbuilt slot ties room = 1 and busy = 0. The end-to-end commit
check is in place (§2.3).

**The ui clock.** The original single ui_clk generator is kept, byte for byte
(`tb/tb_seq_chip.sv:111`). Each channel runs on its own gated copy, ui_clk_c[c] = ui_clk AND NOT
xph_l[c] (`tb/tb_seq_chip.sv:106`): its matvec_chan's ui side and its weight memory. xph_l is an ICG-style
enable, latched on ui_clk's negedge, so it changes only while ui_clk is low and the gated clock
cannot glitch.

`+xp_hold=<chan>:<start>:<cycles>` (default off) holds one channel's clock low for <cycles> aclk
cycles from aclk cycle <start>, counted from reset release. That is R3-9a's back-pressure case.
Absent the plusarg xph_l stays 0 and every channel's clock is ui_clk.

**The first cut hung, and was fixed.** The first cut toggled a 4-bit clock vector bit by bit inside
the one delay process. Its smoke (n3030, binary built from 761d1b7) never halted: SEQ STATUS stayed
busy until the TB's 100 M-poll guard, at about 300 M cycles.

The debug went like this:
* On `lay9b_s1` the R2 binary runs 3,644,824 cycles
  (`evidence/qwen9b/sr/n3033_r3_8_dbg_lay_s1_sr13.log:16`); the 761d1b7 binary hung.
* A debug build of that top shows the mover in G_POLL/G_POLLW at pc 60 with every engine idle, from
  cycle 250,000 on (`evidence/qwen9b/sr/n3037_r3_8_dbgB_lay_s1.log:7`). The engines never saw a
  doorbell.
* The same RTL with the single-generator clock runs 3,644,824 cycles
  (`evidence/qwen9b/sr/n3036_r3_8_dbgA_lay_s1.log:7`). So the fault is the TB clock construct, not
  the RTL.
* The fix (e4d8166, the form above) runs 3,644,824 cycles
  (`evidence/qwen9b/sr/n3039_r3_8_dbgC_lay_s1.log:8`).
* With `+xp_hold=1:100:2000000` it runs 5,599,861 cycles and still PASSes, so the hold does stall
  channel 1 (`evidence/qwen9b/sr/n3041_r3_8_dbgC_lay_s1_xphold_long.log:9-10`).
* The top is -Wall clean after the fix (`evidence/qwen9b/sr/n3044_r3_8_lint_chiptop.log:31-33`).

**The smoke binary.** It was built by `evidence/qwen9b/sr/sr_build.sh` from e4d8166 (every rtl/
and tb/ file of R3-8's final state) as `tb/obj_dir_seq_chip_srr3/tb_seq_chip_9b_srr3`. The
identity check passed on 63 files; the binary's sha256 is 200b153f…
(`evidence/qwen9b/sr/n3042_r3_8_chip_build_srr3.log:27`). The 761d1b7 binary was moved aside to
`tb/obj_dir_seq_chip_srr3_bad761d1b7` so that the name R3-9a's brief uses holds the good one.

**R3-9a can use this binary as is.** sr_build.sh would refuse to rebuild into that obj_dir.

**The stream.** The model_9b_s1 .seq and .chip sha256 match the recorded full hashes
(`evidence/qwen9b/sr/n3029_r3_8_smoke_stream_sha.log:10`).

**The run.** `run_sr_chip.sh model_9b_s1 model_9b_s1 control --cycles-equal 196706821
--tokens-ref evidence/qwen9b/s4/S4_REPLAY.md` with K=r3. **PASS: 196,706,821 cycles, identical to n1310's to the
cycle, and tokens [2614,314,279,369,11751,13] identical to the shipped record**
(`evidence/qwen9b/sr/n3043_r3_8_chip_smoke_s1_shipped.log:30-35`,
`evidence/qwen9b/sr/n3043_r3_8_chip_smoke_s1_shipped.log:38`; wall 8,850 s).

The binary reads SEQ_CAPS fab1ca07 after the run (line 21 of the seed log). The seed log is
`tb/obj_dir_seq_chip_srr3/srr3_seed_model_9b_s1_control.log`, gitignored beside the binary.

The run's tree stamp is `e4d8166+dirty` solely for this document, untracked at launch. No rtl/ or
tb/ file was dirty.

## 9. Cite drift

The o3 check covers the 15 edited files: the 14 above plus sr17_spec_cites_baseline.sh. It ran on
the final tree (base ec7c2be, doc-base e4d8166): **773 distinct cited (file, line) pairs, 749
unmoved, 0 drifted** (`evidence/qwen9b/sr/n3045_r3_8_drift_check.log:11-12`,
`evidence/qwen9b/sr/n3045_r3_8_drift_check.log:106`). n3026 is the same check before the chip-top
fix.

The remainder are 24 UNRESOLVED and 11 HALF-MAPPED. These are exactly the cited lines rewritten in
place (§1). Every such token still names the line that holds the same construct:
* the SEQ_CAPS literal and its comment;
* the E_CHAN arm;
* the mux;
* ws_can;
* the mv_busy_bm port and instance lines;
* the X_SPTR, X_END and X_STATW lines;
* the declaration and reset lines;
* the BUILD_CAPS assignment;
* SEQ_DIRECTED.

No digit repair applies, and none was made. These are rewritten in place, not moved: a
`--verify` would report them rather than prove them.

The documents citing them do not gain a spec_cites failure. `sr17_spec_cites_baseline.sh`
(new SC_PRE flag) over the 8 citing documents, base ec7c2be vs the R3 tree, finds 0 INTRODUCED;
the 2 FAILs in SR3_R1_RTL.md are pre-existing
(`evidence/qwen9b/sr/n3028_r3_8_spec_cites_citers_baseline.log:12-13`).

## 10. Checklist for R3-10 (SR14 style)

**The push-bus cells, per channel c = 0..3.** Every cell is on `xdma_0_axi_aclk`: both ends'
`aclk` are the one BD net (`evidence/qwen9b/sr/n3021_r3_8_bdcheck.log:33`).

**Forward, 45 per channel.**
* **From** (seq_0):
  * `bd_i/seq_0/inst/u_seq/u_mov/xp_v_q_reg[c]`
  * `bd_i/seq_0/inst/u_seq/u_mov/xp_i_q_reg[c][0..11]`
  * `bd_i/seq_0/inst/u_seq/u_mov/xp_d_q_reg[c][0..31]`
* **BD nets:** `/seq_0_xpush<c>_valid`, `/seq_0_xpush<c>_idx`, `/seq_0_xpush<c>_data`.
* **To** (mvchan_c):
  * `bd_i/mvchan_<c>/inst/u_chan/xp_in_v_reg`
  * `bd_i/mvchan_<c>/inst/u_chan/xp_in_d_reg[0..43]` (idx at [43:32], data at [31:0])

**Return, 2 per channel.**
* **From** (mvchan_c):
  * `bd_i/mvchan_<c>/inst/u_chan/xpush_room_reg`
  * `bd_i/mvchan_<c>/inst/u_chan/xpush_busy_reg`
* **BD nets:** `/mvchan_<c>_xpush_room`, `/mvchan_<c>_xpush_busy`.
* **To** (seq_0):
  * `bd_i/seq_0/inst/u_seq/u_mov/xp_room_q_reg[c]`
  * `bd_i/seq_0/inst/u_seq/u_mov/xp_busy_q_reg[c]`

These are the Verilog register names with Vivado's `_reg` suffix. The KEEP attributes hold them
through synthesis; R3-10 should confirm the names on its netlist before probing.

**The three SLR crossings.** On the ship placement, mvchan_0 is in SLR0 and seq_0 / mvchan_1..3
are in SLR1 (`evidence/qwen9b/g5/G5D_TIMING.md:1062-1066`).
1. **mvchan_0 forward, SLR1 → SLR0:** the 45 paths `xp_*_q_reg[0]` → `mvchan_0/.../xp_in_*_reg`.
2. **mvchan_0 room, SLR0 → SLR1:** `mvchan_0/.../xpush_room_reg` → `xp_room_q_reg[0]`.
3. **mvchan_0 busy, SLR0 → SLR1:** `mvchan_0/.../xpush_busy_reg` → `xp_busy_q_reg[0]`.

Channels 1..3 are SLR1 → SLR1 on that placement. Every one of the 188 bits is flop-to-flop with
no logic between. Each output flop drives exactly one input flop.

**The other new paths the build will see**, each worth a line in R3-10's per-clock report. They
are not crossings.
* **In each mvchan:** the skid LUTRAM read → the 3:1 mux → u_xfifo din (one more mux level on
  the XWIN FIFO write path).
* **In each mvchan:** xp_cnt → xf_push_p → ws_can → s_axib_wready. This is a new combinational
  term on the burst shim's WREADY toward burst_slice_c.
* **In seq_0:** yf_dout → the four xp_d_q copies (fanout 4 × 32).
* **In seq_0:** the room input flops → xp_fire → yf_pop / the output flops' enables.

**The values:**

| item | value |
|---|---|
| XP_FWD_STAGES | 2 |
| XP_RET_STAGES | 2 |
| XP_RT | 4 |
| XP_INFLIGHT | 5 |
| XP_SKID | 8 |
| FIFO capacity seen | 31 |

## 11. Judgment calls

1. **Zero drift over readability.** The new ports and instance connections ride on existing lines
   (the mv_busy_bm lines, blank lines), not new ones. Every new block is appended after the
   file's last cited line. The cost is a handful of long lines; the saving is a drift pass over
   ~5,000 citations into these files.
2. **The BD loop is not beside the BM1 nets** (`synth/scripts/create_project.tcl:352-362`,
   where the brief put it). It is a one-line loop on the blank line before `validate_bd_design`,
   so the design is validated with the bus and no cited line of the script moves. The comment and
   a read-only check sit after the save.
3. **Per-channel output flops, with KEEP.** There are four copies of valid/idx/data at seq_0,
   not one set with fanout 4. Each bundle then starts at its own flop and can be placed toward its
   channel (mvchan_0's crossing), at +135 FF. KEEP also sits on the input flops at both ends, to
   keep "registered at both ends" through synthesis. R3-10 may relax KEEP if retiming wants it;
   XP_* then changes (the note in both R3 blocks).
4. **XP_RT follows the brief's formula.** The formula is forward = out flop → input register →
   skid and return = busy flop → input flop, so XP_RT = 4. By my analysis, busy is already
   trustworthy 2 cycles earlier. The margin costs 2 cycles per broadcast, and the
   `tb_matvec_chan` commit check proves the chosen value.
5. **Room counts the skid only** (not the input register), hence XP_INFLIGHT = FWD + RET + 1.
6. **The STATUS walk reuses X_STAT/X_STATW.** It uses chan_q from 0, and chan_q is forced in
   seq_movers, not seq_unit (seq_unit still passes flags[5:4] = 3). The walk is qualified with
   MOP_MOVX so a stale mv_bcast is inert.
7. **A zero-length broadcast retires with no traffic,** as a zero-length unicast does. The
   broadcast keeps the unicast's layer SPTR write.
8. **The chip TB's per-channel ui clock is a gated copy of the one generator.** It is
   `ui_clk & ~xph_l[c]`, with the enable latched on ui_clk's negedge. Each channel's engine and its
   weight memory share that gated clock, so no delta separates them. My first cut toggled a clock
   vector bit by bit in one delay process, and it hung (§8). The single generator is kept byte for
   byte.
9. **The smoke's seed log** goes beside the binary (LOGDIR=`tb/obj_dir_seq_chip_srr3`,
   gitignored). R3-9a's rung-1 seed-log name under evidence/qwen9b/sr therefore stays free, and
   its run is not refused. The verdict lines are in n3030.
10. **Flags, not copies:**
    * `evidence/qwen9b/sr/sr12_golden_same.sh`: two optional caps-set arguments;
    * `evidence/qwen9b/sr/sr17_spec_cites_baseline.sh`: SC_PRE.

    Defaults are unchanged, so their committed logs reproduce.

    New files, because no existing tool does their job:
    * `evidence/qwen9b/sr/r3_8_bdcheck.sh`: no launcher stops after create_project;
    * `evidence/qwen9b/sr/r3_8_twin.py`: no tool compares the two executors;
    * `evidence/qwen9b/sr/r3_8_mutants.sh`: R3's own mutants.
11. **Dirty stamps.** Several GREEN logs read `+dirty` for R3-5's untracked R3_5_PASS.md,
    its gate doc in flight. It is not an input to any R3-8 run, and no rtl/ or tb/ file was
    dirty in any log quoted here. n3027 read `M sr17_spec_cites_baseline.sh` through NFS lag right
    after its commit (the md5 matched on snoke); n3028 is the clean rerun.
12. **The RED unit TB is built with `+define+R3_NO_XPUSH_PORTS`,** because the pre-R3 seq_unit
    has no push ports. The TB then reads the bus idle, and SEQ_CAPS plus err 0x05 carry the RED.
13. **A TB bug found on the way.** `tb_matvec_chan`'s burst writer sampled READY one edge late and
    hung on `+pushburst` (n3013). It was fixed in a375abe (the negedge discipline wr32 uses);
    n3020 is the run of record.

## 12. Logs

| log | what |
|---|---|
| n3000, n3001 | Step 0: base OOC `seq_unit`, `matvec_chan` |
| n3002, n3003 | RED |
| n3004 | lint |
| n3005, n3006, n3009, n3010, n3014, n3020 | GREEN (n3007, n3008: VECPY, superseded; n3013: TB burst handshake, superseded) |
| n3011, n3023, n3024, n3031 | backward compatibility (n3022 superseded) |
| n3012, n3021 | BD check (n3012 superseded) |
| n3015, n3019 | the twin (n3015 superseded) |
| n3016, n3017, n3018 | OOC R3 |
| n3025, n3029, n3030 | chip binary (761d1b7), stream sha, smoke: HUNG, the TB clock construct, superseded |
| n3033–n3041 | the hang's debug: n3033 R2 binary on lay9b_s1; n3034 the 761d1b7 binary (killed after 20 min); n3035 debug builds; n3036 single-generator top = R2; n3037 the state trace; n3038 the fixed top built and linted; n3039 the fixed top = R2; n3040 / n3041 +xp_hold short (no overlap) / long (stalls) |
| n3042, n3043 | chip binary from e4d8166, the smoke of record |
| n3044 | lint after the chip-top fix |
| n3045 | o3 drift check on the final tree (n3026 superseded) |
| n3026 | o3 drift check (before the chip-top fix) |
| n3027, n3028 | spec_cites over the citing documents (n3027 superseded) |
| n3032 | negative controls |
| n3046 | spec_cites over this document, LAST, alone |

## 13. Does NOT establish

* Chip-level identity of the r3 streams, or the +xp_hold back-pressure at chip level. Those are
  R3-9a's; the chip-TB end-to-end commit check first fires on a broadcast stream there.
* Timing and the SLR crossings' slack: R3-10.
* Anything on the board.
