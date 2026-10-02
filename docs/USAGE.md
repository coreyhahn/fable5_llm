# USAGE — operator's guide to the fable5_llm accelerator

Everything here is host-side. Nothing in this document programs flash,
and nothing in `sw/` ever will (`sw/seq_run.py:61`, `sw/chat_seq.py:80`).

Companion documents:
- `docs/ARCHITECTURE.md` — what the machine is.
- `NEXT_SESSION.md` — what state the board and the repo are in *right now*.
- `docs/SNOKE_REBUILD.md` — the disaster checklist (OS disk died 2026-08-10).

---

## 0. Where things run

| host | role |
|---|---|
| **snoke** | the board lives here (PCIe `0000:82:00.0`, JTAG via `hw_server`). All `sw/` tools, all Vivado builds, all heavy Verilator runs. |
| darthplagueis | the workstation. `ref/` generators run here (see §6 for the interpreter quirk). No board. |
| kyloren / fn2187 / darthvader | NFS peers. **No Vivado, no board.** |

The repo is on NFS (`~/r2d2/code/...`) and identical on every host. Always
`cd` into the project directory in the same SSH command:

```
ssh snoke 'cd /home/cah/r2d2/code/fpga/fable5_llm/sw && ./.venv/bin/python chat_seq.py --smoke'
```

---

## 1. Bring-up after a snoke reboot

The XDMA driver **does not autoload** — that is deliberate, because the
bitstream is JTAG-volatile and a driver bound to a dead endpoint can panic
the host (`sw/pcie_helper.sh`, its `load` subcommand).

```bash
# 1. (only if the kernel version changed) rebuild the module first
cd /home/cah/r2d2/code/fpga/references/dma_ip_drivers/XDMA/linux-kernel/xdma && make

# 2. load it — requires a sudoers NOPASSWD grant for this script (template in the script header)
sudo -n /home/cah/r2d2/code/fpga/fable5_llm/sw/pcie_helper.sh load

# 3. sanity
ls -l /dev/xdma0_user /dev/xdma0_h2c_0 /dev/xdma0_c2h_0 /dev/xdma0_control
```

`load` does `insmod xdma.ko` (from `$XDMA_KO`, default
`.../dma_ip_drivers/XDMA/linux-kernel/xdma/xdma.ko`) and then
`chmod a+rw /dev/xdma0_*`.

If the machine also lost power, the FPGA lost its volatile bitstream — go to
§2 before §3. Other `sw/pcie_helper.sh` subcommands, all root:
`remove`, `rescan`, `status`, `debug` (lspci -vvv + dmesg tail), `sbr`
(secondary bus reset on the root port), `cfgkick`, `peek`.

**For a rebuilt/replaced OS disk, follow `docs/SNOKE_REBUILD.md` end to end** —
it carries the exact sudoers lines, the fstab/NFS notes, the hw_server systemd
unit, and the Python/venv recreation steps.

### Verify the board is alive

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/sw
./.venv/bin/python -c "
import os; f=os.open('/dev/xdma0_user', os.O_RDWR)
rd=lambda a: int.from_bytes(os.pread(f,4,a),'little')
print('MAGIC   %#010x (want 0xfab1e001)' % rd(0x00))
print('VERSION %#010x' % rd(0x04))
print('CALIB   %#x (want 0xf)' % rd(0x0c))
print('LAYER   %#010x (want 0xfab1e5a0)' % rd(0x5024))
print('SEQ     %#010x (want 0xfab1e5e0)' % rd(0x6028))
print('TOPK    %#010x (want 0xfab1704b)' % rd(0x5048))"
```

Addresses are from `sw/hwmap.py`. VERSION must equal
`sw/seq_run.py:EXPECTED_SEQ_VERSION` (today **`0xC973C18A`, build_041
`ckr2_AltSpreadLogic_high`** — the 9B state-spill bitstream, WNS 0.000 /
WHS +0.001, zero failing endpoints, no waiver, HW-validated by
`evidence/qwen9b/g6/RD9_GATE.md`; build_035 was `0x54443B9F` and build_034
`0x4F908DF2`) or every sequencer tool refuses. Keep it in lockstep with
`sw/infer.py:EXPECT_VERSION` **and** with `sw/hwmap.py:SHAPE_ISA_BY_VERSION`,
which decides the `R_SHAPE` layout and has no default — an unmapped VERSION
raises `UnknownBitstream` rather than guessing.

> **`sw/hwmap.py:SCRATCH_WORDS_BUILT` is 65,536 for build_041.** A
> build_034/build_035 board needs a checkout from before G6: at 32,768 words
> the tools would walk half an array that exists, and at 65,536 they walk
> twice an array that does not. `evidence/qwen9b/g6/RD9_GATE.md` §4.2.

**The DDR state region (9B only).** The layer state lives in DDR and the host
uploads it before any run. `sw/seq_run.upload_state` memsets the DN region,
writes the 24 conv images with readback, and programs three CSRs in 64 KiB
units — `L_SB_DN 0x5064`, `L_SB_KV 0x5068`, `L_SB_CV 0x506C` (resident values
`0x38000` / `0x38180` / `0x38980`, i.e. the region at `0x3_8000_0000` on DDR
**channel 3**, 162,529,280 B). `seq_check_state_bases` refuses a run whose
bases are zero; the RTL would answer `E_DMA_BASE` at the first SLD/SST.

> **`--skip-weights` programs the CSRs and writes NO region byte.** A run on
> a region the previous run left dirty halts cleanly, reports `err_code 0x00`
> — and answers with the WRONG TOKEN. Re-establish it with a full `seq_run`
> or `evidence/qwen9b/g6/g6_state.py --write-initial`.
> `evidence/qwen9b/g6/RD9_GATE.md` §14.2.

---

## 2. Safe reprogram (JTAG, volatile only)

> **NEVER write board flash.** `sw/program_fpga.sh` uses
> `synth/scripts/program.tcl` over JTAG and is volatile by construction; there
> is no flash path in this repo and none should be added.

The order matters: a host MMIO read to a removed/dead endpoint can kernel-panic
snoke, which then needs a physical reboot (CHARTER safety rails).

**`sw/program_fpga.sh` now runs the whole sequence itself, under the board
lock** (user ruling O3, 2026-08-29). That is the point: the dangerous window
is not the JTAG step, it is `remove` → JTAG → `rescan`, during which the device
is gone from the PCI tree and anybody else's `/dev/xdma0_*` fd points at a dead
endpoint. One hold of `.fable5_board.lock` covers all three.

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
./sw/program_fpga.sh \
  synth/out_build_041_ckr2_AltSpreadLogic_high/proj/stage1.runs/impl_1/bd_wrapper.bit
# rollback (the 2B design, known good, DIFFERENT path — not under proj/):
#   ./sw/program_fpga.sh synth/out_build_035_fp2a_exc_po/bd_wrapper.bit
sudo -n $PWD/sw/pcie_helper.sh load              # only if xdma isn't loaded yet
```

It refuses if anyone else — any checkout, either host — holds the board, and
names them. `--jtag-only` programs without the remove/rescan, for a caller that
owns the sequence *and already holds the lock* (`sw/stage1_hw_bringup.sh`,
`sw/test_ctl.sh`); `--no-lock` skips the lock entirely and says so loudly (§5).

**Name the file you mean (R3-0, `evidence/qwen9b/sr/R3_0_TOOLING.md`).**
`--expect-sha256 <64 hex>` (or `--expect-sha256=<64 hex>`) makes the script
hash the bit file **inside the same lock hold that programs it**, before
`remove`: a mismatch is `FATAL: sha256 mismatch`, exit 5, nothing removed.
Use it on every non-default bitstream — two bitstreams of one netlist share
VERSION, SEQ_CAPS and BM_IDENT, so the CSRs cannot tell a twin from the ruled
file afterwards (`evidence/qwen9b/sr/SR14_R2_BUILD.md` §4). For **every**
caller, in the same place, an ESTABLISHED client of hw_server's port 3121
(another hw_manager / xsdb attached) is `FATAL: a client is attached to
hw_server`, exit 6, nothing removed. `--check-only` stops after both checks
(`CHECK_ONLY: sha256 OK, no attached client`) and touches nothing:

```bash
./sw/program_fpga.sh --expect-sha256 <sha256 of the ruled file> --check-only <bitfile>
./sw/program_fpga.sh --expect-sha256 <sha256 of the ruled file> <bitfile>
```

> **Two things to know before you run it.**
> **(1) The endpoint always comes back.** Every exit path after the remove —
> a vivado failure, a `set -e` abort, Ctrl-C — rescans from an `EXIT INT TERM`
> trap, because leaving the endpoint off the PCI tree is worse than a bad
> bitstream: the board then looks *dead* to `lspci` and to every tool. The
> same trap is in `sw/stage1_hw_bringup.sh` and `sw/test_ctl.sh`, which own their
> own remove/rescan when they call `--jtag-only`.
> **(2) A JTAG failure does not mean the FPGA changed.** A run that never
> starts configuration leaves the **old** bitstream in the device, and it
> re-enumerates and answers CSR reads perfectly normally. `sw/program_fpga.sh`
> exits non-zero and that exit code is the *only* warning you get — check the
> CSR `VERSION` (§1) against the build you meant to load before any DMA.

Then re-run the identity check in §1 and confirm `CALIB == 0xF` **before any
DMA**. Writing DDR before the MIG reports calibrated is a hard project rule.

`sw/stage1_hw_bringup.sh <bitfile> <version_hex8>` wraps the whole flow
(preconditions → remove → program → rescan → CSR/DDR gates) and logs to
`evidence/stage1/`. `SKIP_PROGRAM=1` reuses the resident design. It takes the
board lock **once, for the entire bring-up** — the reprogram window and the
16 GiB of `sw/ddr_test.py` writes that follow are one critical section — and
`sw/program_fpga.sh` / `sw/ddr_test.py` inherit that hold rather than re-taking it.

---

## 3. `chat_seq.py` — the CLI

`sw/chat_seq.py` is the fast chat path: three SEQ record images stay resident
in DDR and each forward step is **one sequencer launch** after a 48-byte
in-place patch of the image head. Run it from `sw/` with the repo venv.

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/sw
./.venv/bin/python chat_seq.py                       # REPL, greedy, nch=1
./.venv/bin/python chat_seq.py --nch 4 --ntok 48     # 30.4 tok/s path
./.venv/bin/python chat_seq.py --nch 4 --temp 0.8 --seed 4242 \
    --prompt "Write a haiku about winter."
```

These three are not 9B, so they run the **shipped order**: the S1 reorder's
default is model-aware and picks form B only at `FABLE5_MODEL=9b --nch 4` on
the shipped template, and the tool prints one line saying it chose the
shipped order and why — see "`--reorder A|B|off`" below.

### Chat at 9B (build_041) — `FABLE5_MODEL=9b --nch 4`

**The 9B chat path is `--nch 4` and nothing else.** `--nch 1`'s three images
are byte slices of the frozen 0.8B/2B artifact and always will be; `--nch 4`
DERIVES its geometry from the stream it is given, and the model selection
picks which stream that is (`sw/chat_seq.TEMPLATE4_BY_MODEL`): `9b` →
`tb/scripts/w9/model_9b_s1.e4`, everything else → the frozen
`tb/scripts/w4/model_v2_s1.e4`. Run it from the REPO ROOT, not from `sw/`,
so the artifact paths resolve:

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
FABLE5_MODEL=9b /home/cah/.venv/bin/python sw/chat_seq.py --nch 4 --ntok 24 \
    --prompt "What is the capital of France?"
FABLE5_MODEL=9b /home/cah/.venv/bin/python sw/chat_seq.py --nch 4 --ntok 24 \
    --temp 0.8 --top-k 32 --top-p 0.95 --seed 4242 --prompt "…"
```

| | 9B on build_041 |
|---|---|
| decode step | **137.7 ms** device (`evidence/qwen9b/g6/078_chat_greedy_9b.log`) = **7.26 tok/s** steady state; a 19-id turn + 24 tokens is **4.22 tok/s** end to end, 98 % of it device time |
| prefill step | **126.5 ms** (`lite`), i.e. 91.9 % of a decode step — prefill is decode-rate, there is no batched prefill |
| position mode | **`ldc`.** `--pos-mode xrf` is REFUSED whenever the geometry cannot reach the context — `XRF_POS_MAX < --max-ctx - 1`. XRF[4] is signed 18-bit and the 9B position stride is 2,048 B, so it reaches pos **63** and `rtl/seq_unit.sv` truncates silently past it; any real chat context at 9B is therefore `ldc`, which is what `auto` picks |
| context | `--max-ctx` up to **4,095** (`T_MAX` = `sw/hwmap.STATE_T_MAX` = 4,096 **at 9B**; the frozen 0.8B/2B path keeps 512, because build_034/035 still address KV with `kv_waddr = tcnt[8:0]`). The position blob is 8.0 MiB at 9B, 768 KiB on the frozen path |
| state region | uploaded by the session itself at bring-up — the DN memset, the 24 conv images, and `SB_DN`/`SB_KV`/`SB_CV` read back. A context reset re-zeroes DN **and restores the conv taps** |
| weights | 5,845 MiB, and a healthy board is **not** re-uploaded: `residency 1122 witness blocks … 0 MISS` → `upload SKIPPED` |
| `--ntok` | **≥ 24**, unchanged at 9B (`evidence/qwen9b/g2/G2C_CHAIN.md` §8.4) |

### Greedy vs sampled

| | greedy (default) | sampled |
|---|---|---|
| flag | `--temp 0` (the default) | `--temp T > 0` |
| where the token is decided | **100% on-chip** — LM head + AMAX32 argmax on the FPGA, token arrives via the SEQ OUT FIFO | still on-chip LM head + on-chip top-32 capture; the host does one seeded RNG draw over the 32 chip-provided scores |
| bit-exact vs the reference | yes | seed-deterministic, not bit-exact by definition |
| extra cost | — | ~68 MMIO reads/token ≈ 0.11 ms (`sw/chat_seq.py:1972`) |

Sampling flags: `--temp/--temperature T`, `--top-k K` (default 50, capped at
the chip's capture depth 32), `--top-p P` (default 1.0 = off), `--seed N`
(one is drawn and *reported* if omitted), `--topk-base ADDR` (default `0x5048`,
`0` skips the probe entirely).

If the resident bitstream has no top-k unit, `--temp` **refuses at session
start with the reason** and exits 3 — it never silently falls back to greedy
and never moves the model onto the host.

### `--nch` and the re-upload cost

`--nch 1` (default) is the shipped bit-exact greedy stream. `--nch 4` selects
`tb/scripts/w4/model_v2_s1.e4` and a **different weight placement in DDR**: the
LM head's chunks are interleaved chunk *j* → engine *j* mod 4.

- A session is one `--nch` for its whole life.
- Flipping modes means a **full weight re-upload, ~900 MiB** (measured upload
  927,970,288 B / 6.5 s in `evidence/rung4/seqrun_1chan_build033.json`). The
  residency probe detects the miss and does it for you — slow, safe, minutes.
- Same in reverse: going back to `--nch 1` re-uploads again.

### The other flags you will actually use

| flag | effect |
|---|---|
| `--prompt TEXT` (repeatable) | non-interactive turns; no REPL |
| `--ntok N` | reply length budget per turn (default 32) |
| `--system TEXT` | system message, fed once at session start / after every context reset. Costs `5 + len(text)` ids |
| `--raw` | **template OFF** — feed the prompt verbatim, no `<\|im_start\|>` wrapper. The model will *continue* your text instead of answering it. This is the pre-`INSTRUCT_SPEC` behaviour |
| `--canned` | greedy regression gate B1: replays the committed `model_v2_s1` schedule and compares every argmax against the artifact's `expect_tokens`; implies `--prefill full`; refuses `--temp > 0` |
| `--smoke` | preamble + ONE full step (token 760 at pos 0), reports PERF_CYC. Nothing else touches the board |
| `--model-only` | gate G2: one templated turn through `ref/seq_model` vs the bf16 reference. **No board, no lock**, ~5-7 s/step. Since the form-B default (2026-09-27) a 9B `--nch 4` run models the **form-B images** (without the B6 gate, which only a board session or `--reorder-check` runs); `--reorder off` models the shipped order |
| `--selftest` | pure-host unit tests; touches no device at all (175/175 as of the instruct gate) |
| `--verify` | lockstep `ref/seq_model` prediction for every step; the board idles meanwhile. **The host cost is per model**: ~6 s/step at 0.8B/2B, **~140 s/step at 9B** (`evidence/qwen9b/g6/074_ref_cost_9b.log` measured 131.2 `lite` / 149.3 `full`). The tool prints the one that applies |
| `--verify-head` | verification only: rebuild the head's logits on the host from the chip's own x8/e_x and assert host argmax == chip token, every step. The chip still decides |
| `--prefill lite\|full` | `lite` (default) prefill steps skip the LM head; `full` makes every step emit a token |
| `--continue-context` | keep KV/DN state across `--prompt` turns (default: preamble between them) |
| `--max-ctx N` | default 500; must be **< `T_MAX`** — 512 on the frozen 0.8B/2B path (the KV bank depth: the RTL wraps silently past it) and **4,096 at 9B**, where the state spill made the KV cache `{kv, t[11:0]}` |
| `--pos-mode auto\|xrf\|ldc` | how a step addresses its RoPE tables. `xrf` is the frozen spec's `XRF[4]=pos*POS_STRIDE`, a **signed** 18-bit field that silently truncates past `XRF_POS_MAX` — pos **85** at the 0.8B/2B stride of 1,536 B, **63** at 9B's 2,048 B; `ldc` patches the position-LDC addresses and reaches the whole KV depth. `auto` (default) picks by the geometry, so any real chat context is `ldc`. `xrf` is REFUSED, not warned about, when `XRF_POS_MAX < --max-ctx - 1` — in the tool AND in the `--verify` model, which does not model the truncation either |
| `--force-upload` | skip the residency probe, re-upload everything |
| `--out FILE.json` | JSON report (perf, launches, sampling, template telemetry) |
| `--dev`, `--chan`, `--lock`, `--no-lock`, `--timeout`, `--preamble-timeout` | plumbing; `--no-lock` is the audited board-lock escape (§5) |

### `--reorder A|B|off` — the S1 overlap schedule (form B by default at 9B `--nch 4` since 2026-09-27)

**Form B is the default at 9B** (user decision 2026-09-27, Task S1D; it was
off from S1P until then). The default is **model-aware** (S1D fix round 1):
with neither `--reorder` nor `$FABLE5_REORDER` given, "auto" picks form B
only at `FABLE5_MODEL=9b --nch 4` on the shipped template — so the plain 9B
command above (`FABLE5_MODEL=9b … sw/chat_seq.py --nch 4 …`) is a form-B
session — and the **shipped order everywhere else** (`--nch 1`, every non-9B
model, a custom `--template`), with one log line saying so and why.

`--reorder` (9B, `--nch 4` only) runs the S1 schedule — fence-at-use, a
dependency-safe reorder, redundant-MOVX elision — on the **shipped** build_041
RTL. `B` (the default) reorders each step image on its own with the static
cost table (`ref/seq_cost.py`) and makes the per-launch position patch follow
its record (pins `sw/chat_seq.REORDER_B_IMAGES`). `A` is still available
(`--reorder A` or `FABLE5_REORDER=A`): it uses the SV1-gated reordered
template (regenerated in-process at the static costs of `ref/seq_cost.py` and
compared with its pin; neither form reads the BN1 timeline CSV — for A,
proven on the committed tree with the CSV made unreadable,
`evidence/qwen9b/ov/n113_final_reorderA_nocsv.log:22`).

**The per-session gate cost.** Whichever form runs, before the board is
opened the tool regenerates the images and compares them with their pins,
runs the image hazard assert, and runs the **B6 model gate** (shipped vs
reordered images replayed in `ref/seq_model`, exact) — about **510–530 s of
host time with the board lock held**, once per `chat_seq.py` process, before
the first token. That is the cost the default now pays on every 9B
`--nch 4` session (the boardless proof at the model-aware default,
`--reorder-check` with no flag and the variable unset, took **545 s
wall**, B6 535.6 s: `evidence/qwen9b/ov/n135_S1Dfix1_reorder_check_default.log:21`).
`--reorder-check` runs the same gates alone, with no board and no lock.

**Getting the shipped order back at 9B `--nch 4`.** `FABLE5_REORDER=off`
(or `none`) in the environment, or `--reorder off` on the command line, runs
the shipped (unreordered) images with no gates and no gate cost —
byte-identical to the pre-S1 tool. Elsewhere auto already runs the shipped
order. **Explicit values are used as given**: `FABLE5_REORDER=B` or
`--reorder B` (or `A`) where the form cannot run (`--nch 1`, a non-9B model)
**refuses before the lock and the board** (exit 4), naming both ways back —
an explicit request never falls back silently.

**The switch.** `$FABLE5_REORDER` is read at argument parse: unset or empty =
auto (above); `off`/`none` = shipped order; `A`, `B`; case-insensitive;
anything else is refused at argument parse. An explicit `--reorder` beats
it. It sets `chat_seq.py`'s `--reorder` default
ONLY — **`sw/serve.py` and `sw/cycle_census.py` are unaffected**: they build
their own session namespaces with no `reorder` field and always run the
shipped order. The measured numbers, the original decision record and the
flip are in `evidence/qwen9b/ov/S1P_SHIP.md` §4; what is still not
established (no chip-TB run of form B's per-image order, among others) is
§5 there.

### `--seq-rtl r0|r1|r2` — the sequencer RTL level the images are built for (Tasks SR6, SR13b)

`--seq-rtl` (or `$FABLE5_SEQ_RTL`, read at argument parse; an unknown value
is refused there) picks the RTL level. **`r0` is the default** and is
everything above, byte for byte (the form-B pins regenerate identical,
`evidence/qwen9b/sr/n601_r1_pins.log:20-21`). **`r1`** targets the FENCE
channel mask of `docs/SEQ_ISA.md` §B17.1: form B's per-image reorder emits
masked FENCEs, and the two step images carry their own pins,
`REORDER_B_R1_IMAGES` in `sw/chat_seq.py` (from
`evidence/qwen9b/sr/n601_r1_pins.log:22-23`). `r1` needs `--reorder B` at 9B
`--nch 4`; with `A` or `off` it refuses before the lock and the board
(exit 4). The same three gates run before the board is opened: pins, hazard
assert, and B6, with the r1 images modelled at capability R1 (boardless
`--reorder-check` PASS, 540 s:
`evidence/qwen9b/sr/n608_chat_seq_r1_reorder_check.log:21`). **The device
decides whether they load.** `open_board` reads SEQ_CAPS (SEQ 0x64) and
re-validates the template and the three images at the device's capability
set before any upload. On build_041/042, which read 0xDEADC0DE there (the
empty set), an r1 session is refused with exit 4, naming the masked FENCE
record. Nothing in a manifest can change that. That refusal comes at
`open_board`, i.e. AFTER the ~540 s B6 gate (S1P's gate order, pins then
hazards then B6 then the board). To fail fast, check both halves first:
`--reorder-check` catches a B6 failure without the board (it never reads
the device, so it cannot tell which bitstream is resident); the VERSION
check — and, since SR7, `evidence/qwen9b/bm/bm1_ident.py`'s SEQ_CAPS line
(`--want-version <hash> --want-caps R1`: the raw word and the decoded set,
FAIL unless the device reports exactly R1) — catches a non-R1 bitstream.
`sw/seq_run.py`'s identity gate also compares SEQ_CAPS against the word
the VERSION's `SEQ_VERSIONS` row expects, and refuses a mismatch before
any DMA (`evidence/qwen9b/sr/n707_SR7_host_tdd_GREEN.log`).
`sw/seq_run.py` does the same device-keyed validation for every stream it
loads; its `--caps` flag is for `--dry-run` only, where the SEQ window is
never read, and a dry-run with a non-empty `--caps` validates and relocates
at that set but uploads nothing. `sw/serve.py` pins its level to r0. The
evidence and what is not established are in
`evidence/qwen9b/sr/SR6_HOST.md`. Since SR7 the R1 bitstream
`build_044_r1_incr` (VERSION e3c2ff1e, SEQ_CAPS 0xFAB1CA01) has a
`SEQ_VERSIONS` row, admitted only when named (`--expect-version e3c2ff1e`);
SR8 loaded it once on 2026-09-29 under the user's Q9 ruling — `--seq-rtl r1` there: tokens IDENTICAL, 7.929 decode tok/s — and restored build_041; loading it again needs a load ruling
(`evidence/qwen9b/sr/SR7_R1_BUILD.md`, `evidence/qwen9b/sr/SR8_R1_BOARD.md`).

**`r2`** (Task SR13b; paragraph written at the round's close, SR17)
targets `docs/SEQ_ISA.md` §B17.2 — the XWIN/RES bank bits — on top of r1's
masked FENCEs: form B's per-image reorder emits both, and the two step
images carry their own pins, `REORDER_B_R2_IMAGES` in `sw/chat_seq.py`
(lite `c78312bb…`, full `868ba4e0…`,
`evidence/qwen9b/sr/n1351_sr13b_r2_pins.log:24-25`). Like `r1` it needs
`--reorder B` at 9B `--nch 4` — on the command line the model-aware auto default already resolves to B there (main() runs effective_reorder before `check_seq_rtl`, `sw/chat_seq.py:753-770`), so `--seq-rtl r2 --nch 4` alone passes, while `--reorder off` or `A` is refused at r2 (`evidence/qwen9b/sr/n1719_sr17ff_reorder_probe.log:7-10`); a ChatSession built directly must pass reorder "B" (an unresolved auto is refused, `evidence/qwen9b/sr/n1719_sr17ff_reorder_probe.log:12`), and `sw/serve.py` pins reorder=None and so r0 — and the same three gates run first (pins,
hazard assert, B6 with the r2 images modelled at {R1,R2}; boardless
`--reorder-check` PASS, 534.7 s,
`evidence/qwen9b/sr/n1360_chat_seq_r2_reorder_check.log:21-22`). **The
device decides, exactly as for r1** — and here it matters more, because R2
is NOT fail-closed on an older netlist (an R1-only or pre-round bitstream
would silently ignore the bank fields and compute on the wrong x):
the board-open admission (`admit_caps`, `sw/chat_seq.py:2814`) re-validates
at the device's SEQ_CAPS, so an r2 session is
refused on 0xDEADC0DE (build_041/042) AND on 0xFAB1CA01 (the R1 bitstream),
and loads only where the set has R2, 0xFAB1CA03; a manifest's claim changes
nothing (`evidence/qwen9b/sr/SR13b_HOST_R2.md`, the verdict). The one
bitstream with R2 is **build_045_r2_incr** (VERSION 266e3ae7, SEQ_CAPS
0xFAB1CA03), admitted only when named — `--expect-version 266e3ae7` /
`FABLE5_SEQ_EXPECT_VERSION=266e3ae7`; its pre-flight is
`evidence/qwen9b/bm/bm1_ident.py --want-version 266e3ae7 --want-caps R1,R2`.
**Program it by path AND sha256 only**
(`synth/out_build_045_r2_incr/proj/stage1.runs/impl_1/bd_wrapper.bit`,
53,080,061 B, sha256 `c4caeb09…4dcb`): a TWIN
(`synth/out_build_045_r2/…`, WNS −0.865, not signed off) shares VERSION,
SEQ_CAPS and BM_IDENT, so the CSRs cannot tell them apart
(`evidence/qwen9b/sr/SR14_R2_BUILD.md` §4; `NEXT_SESSION.md` §3). SR15
loaded it once on 2026-09-29 under the user's Q9 ruling — the chat511 run
was `FABLE5_SEQ_EXPECT_VERSION=266e3ae7 … --reorder B --seq-rtl r2`
(`evidence/qwen9b/sr/n1508_sr15_r2_chat511.log:3`): tokens IDENTICAL,
8.182 decode tok/s, ×1.0319 against r1 on the same bitstream
(`evidence/qwen9b/sr/SR15_R2_BOARD.md` §3.1) — and restored build_041;
loading it again needs a load ruling. `r1` (and `r0`) also run on the R2
bitstream, whose set contains R1: SR15's r1 chat session there read
−0.0011 % against SR8's on the R1 bitstream (same section).

### REPL commands

```
/reset            preamble: zero KV/DN/conv, T = 0
/stats            per-session timing + context accounting
/ntok N           change the reply budget
/system TEXT      set the system message (RESETS the context — T5 is
                  session-start scoped); refused under --raw
/quit, /q, /exit  leave              (Ctrl-C stops generation)
```

### `ntok` / EOS guidance (read this before blaming the model)

Generation stops on `{248044 endoftext, 248046 im_end}`.

**Use `--ntok >= 24` so replies actually reach EOS.** A reply cut mid-sentence
at the token budget leaves a ragged assistant turn in the KV cache, and the
0.8B W4 model answers the *next* question noticeably worse from ragged context.
The measured datum: over the API with `max_tokens=12`, turn 1's "capital of
France" answer was truncated and turn 2 then answered **"Milan"** for Italy;
the CLI session, whose turn 1 reached EOS, answered **"Rome"**
(`evidence/instruct/INSTRUCT_GATE.md`). The plumbing is correct in both cases.

Context budget: wrapper overhead is `5 × messages + 7` ids, plus 4 retained
think-block ids per past turn (`docs/INSTRUCT_SPEC.md` T7 + the T3 amendment).

---

## 4. `sw/serve.py` + `sw/chat_client.py` — the HTTP/SSE front end

`sw/serve.py` is stdlib-only (no fastapi, no uvicorn — it runs in the same
`sw/.venv`). It **owns no inference logic**: it imports `chat_seq` as a library.

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/sw
./.venv/bin/python -u serve.py --port 8137 --nch 4 --prefill lite
# from a laptop:
ssh -N -L 8137:127.0.0.1:8137 snoke
./.venv/bin/python chat_client.py --port 8137
```

### Endpoints

| endpoint | notes |
|---|---|
| `POST /v1/generate` | SSE stream: `queue` (0+) → `start` → `prefill` (0+) → `token` (0+) → exactly one `stats` (or `error`) last. `429` if the queue is full, `400` malformed, `503` if the backend never came up |
| `GET /v1/health` | cached ident + idle heartbeat, VERSION, board free/busy, queue depth. Never takes a turn, never touches the device from an HTTP thread |
| `GET /v1/metrics` | cumulative turns / tokens / mean tok/s / uptime / device ms |
| `GET /v1/sessions` | the named histories the server holds |
| `POST /v1/reset` | `{"session_id"?}` — drop that history (lazy; the KV banks clear on the next turn's preamble) |

### `/v1/generate` request fields (validated in `sw/serve.py:_validate`)

| field | type | notes |
|---|---|---|
| `prompt` | str | **required**, non-empty |
| `max_tokens` | int | `1..--max-tokens-cap` (default cap 256); server default 32 |
| `session_id` | str | 1..64 chars from `[A-Za-z0-9_.:-]`, default `"default"` |
| `raw` | bool | default **false** = the chat template IS applied |
| `system` | str\|null | used on the session's first templated turn only |
| `temperature` | number | `0..MAX_TEMP`; 0 = greedy |
| `top_k` | int | `0..100000`, 0 = no cut |
| `top_p` | number | `(0, 1]`, 1.0 = off |
| `seed` | int | `0..2^63-1` |
| `nch` | int | an **assertion**, not a switch: if it disagrees with the server's `--nch`, you get a `400`. Honouring a flip would mean re-uploading ~900 MiB mid-queue |

Omitted sampling fields fall back to the server-wide `--temp/--top-k/--top-p/--seed`.

### Single-context queue semantics — the part that surprises people

The board holds **exactly one context at a time**.

- One worker thread owns the device; HTTP threads never call the backend.
- Requests are served **strictly FIFO** from a bounded queue (`--queue-cap`,
  default 8); waiting clients get honest `queue` events with position and ETA.
- **Sessions are named histories.** Serving a different `session_id` than the
  one currently resident = preamble (context reset) + **replay of that
  session's history as prefill steps, one launch per replayed token**
  (~45 ms lite / ~63 ms full on build_032; faster on build_033). A 200-token
  history costs tens of seconds before the first new token. The `start` event
  reports `replayed` so a client can see exactly what it paid for.
- **Chat from one `session_id` and this never happens.** Ping-pong between two
  long sessions and it happens on every turn.
- A crashed/timed-out/disconnected request never wedges the queue: the worker
  drops board session ownership and re-preambles on the next turn.

### Safety

Binds `127.0.0.1` and **refuses a non-loopback bind** without
`--i-know-what-im-doing`. There is no auth — reach it over an SSH tunnel.
`--mock` runs the entire server (queue, sessions, SSE, metrics) against a
deterministic fake backend: no board, no flock, no `chat_seq` import.
`--selftest` and `--check-backend-api` touch no device.

Sampling on the server needs an explicit `--topk-base <addr>`: unlike
`chat_seq.py`, `sw/serve.py`'s `--topk-base` defaults to `None`, and a server-wide
`--temp > 0` without it is refused **at argument parse time**, before the flock
and the bring-up.

### `sw/chat_client.py`

Stdlib-only readline REPL / one-shot client. Runs in `sw/.venv`, the system
python, or on a laptop over the tunnel with nothing installed.

```
--host --port --session NAME --max-tokens N --prompt TEXT (repeatable)
--reset --health --metrics --raw (dump every SSE event verbatim) --timeout
REPL: /reset /health /metrics /sessions /session NAME /ntok N /raw /help /quit
```

---

## 5. Lock discipline (the one that bites)

**One board, one lock, one holder — since the O3 ruling of 2026-08-29.**

```
/home/cah/r2d2/code/fpga/.fable5_board.lock
```

An exclusive `fcntl.flock()` taken **before any device fd is opened** and held
for the process lifetime (`sw/board_lock.py`; `chat_seq.py:SeqLock` is that
class under its old name). The file is **above every checkout** and on the NFS
export both hosts mount at the same path, so it is one inode for
`fable5_llm`, for `grok46_llm/fable5`, for snoke and for darthplagueis.

> **What it replaced, and why.** The lock used to be `sw/.seq.lock` — inside
> whichever checkout computed it. Two checkouts share this machine and one
> board, so they locked two different inodes and excluded nothing. That is how
> the R-b gate took an unattributed reprogram. Captured rather than described:
> `evidence/qwen9b/o3/00_red_percheckout.log` shows both checkouts holding the
> board at the same time. The mechanism was always right; the path was not.

### Who takes it

| takes the lock | does **not**, and does not need to |
|---|---|
| `sw/chat_seq.py` | `sw/chat_client.py` (talks to `sw/serve.py`, never the board) |
| `sw/serve.py` (real mode; `--mock` does not) | `sw/head_cache.py` (host-side verification only) |
| `sw/cycle_census.py` | `sw/hwmap.py` (not a tool) |
| `sw/seq_run.py` (including `--dry-run`, which DMAs ~900 MiB) | `--selftest` / `--mock` / `--model-only` / `--tok-test` modes of any of the above |
| `sw/infer.py` | |
| `sw/tok_meter.py` | |
| `sw/mover_bench.py` | |
| `sw/layer_test.py` | |
| `sw/matvec_test.py` | |
| `sw/ddr_test.py` | |
| `sw/program_fpga.sh` — **held across `remove` → JTAG → `rescan`** | |
| `sw/stage1_hw_bringup.sh` — one hold for the whole bring-up | |
| `sw/test_ctl.sh` — one hold across `remove` → JTAG → `rescan` → the 4 KiB DMA | |

The right-hand column is now only board-free things. Every tool that programs
or DMAs the board is in the left one, and each is verified *by running it under
contention* in `evidence/qwen9b/o3/o3_lock_gate.py` phase 7 — the table is
checked, not maintained by hand.

### Reading it

```bash
python3 sw/board_lock.py --status     # holder, or "stale block, not held"
python3 sw/board_lock.py --probe      # fstype + a real acquire/release
pgrep -af 'chat_seq|serve|seq_run|infer|tok_meter|mover_bench|layer_test|matvec_test|ddr_test|cycle_census'
```

A refusal already names the holder — **host, pid, user, tool, time, tree sha
and checkout** — so it tells you which machine and which working tree to go
and look at.

### Stale locks: there are none

`flock` is kernel-owned, so the lock dies with its holder — SIGKILL, a dropped
ssh, a crash, all of them. **There is no stale lock to break and no
`--force-unlock`.** What *can* go stale is the 256-byte identity **text**,
which a killed holder does not get to erase; `--status` tells the two apart by
probing the lock itself, and the next successful acquire rewrites the block.
If the lock will not open, someone really has the board.

### `--no-lock` — the escape hatch, written out because it exists

**Every escape, by name.** There are no others, and none of them is quiet:

| tool | how you ask for it |
|---|---|
| every Python tool in the left column above | `--no-lock` |
| `sw/program_fpga.sh` | `--no-lock` |
| `sw/test_ctl.sh` | `--no-lock` |
| `sw/stage1_hw_bringup.sh` | **`STAGE1_NO_LOCK=1`** in the environment |

`sw/stage1_hw_bringup.sh` uses an environment variable rather than a flag only
because its positional arguments are fixed by its callers. It is the most
dangerous escape in the repo — that script removes the endpoint, reprograms
it, and then writes all 16 GiB of DDR twice — so it is listed here first
rather than buried in the source.

It must be typed explicitly, and using **any** of them:

- prints a banner on **stdout and stderr**, including the current holder if
  there is one;
- appends a line to **the `.nolock` audit log beside the board lock** naming tool, host, pid,
  user, time, tree and argv.

The three shell tools do not hand-roll that banner: they call
`python3 sw/board_lock.py --announce-no-lock`, which is the *same*
`NullLock` the Python tools construct, so the wording, the standing rule
and the audit line cannot drift apart from theirs.

**The standing rule: `--no-lock` is for a human who has confirmed sole use of
the board. Never for a script, and never to get past a stuck lock** — a lock
that will not open means a live holder, and there is no stale state to clear.
Full write-up: `evidence/qwen9b/o3/BOARD_LOCK.md` §6.

To relocate the lock instead (both participants must agree, or it excludes
nothing): `$FABLE5_BOARD_LOCK`, or `--lock PATH`.

### Residual hazards

- **A checkout that has not picked up O3 still locks its own `sw/.seq.lock`.**
  The other worktree on this machine (`grok46_llm/fable5`) is one, until it
  merges this commit. The lock cannot protect you from code that does not take
  it, and `sw/.seq.lock` files left lying around are inert — `--status` points
  at them and says so.
- **`sw/serve.py` left running** holds the lock indefinitely (it has been left up
  on `snoke:8137` before). Get its pid from `GET /v1/health`, or from
  `--status`, and `kill` it to free the board.
- **`sw/mover_bench.py` clobbers the chat-resident stream images** at
  `0x0900_0000`. It takes the lock now, so it can no longer do that under a
  live session, but the next chat session still re-uploads ~2 MiB.
- **`sw/ddr_test.py` overwrites all 16 GiB of DDR**, weights and KV state
  included. It takes the lock now too.

---

## 6. Regenerating gitignored artifacts

Big artifacts are **not** committed (`.gitignore`): `tb/scripts/model_*`,
`tb/scripts/w3/`, `tb/scripts/w4/`, `tb/scripts/chain_*`, `token24_*`,
`seqlayer_*`, `seqvec/`, `tb/vecv2/`, `tb/vecseq/`, `tb/vectopk/`,
`tb/obj_dir_*`, `synth/out_*`. One prompt seed of the real model is ~950 MB.

**Committed and frozen** (do not regenerate — the generator has moved on and
would not reproduce the bytes): `tb/scripts/layer_s*` and `tb/scripts/token_s*`
plus their weight images and manifests. `make layer_scripts` / `make
token_scripts` deliberately **refuse** with an explanation.

### The Python interpreter quirk (this is the #1 time-waster)

`ref/.venv`'s interpreter lives under `~/.local/share/uv`, which is **not**
NFS-shared. So:

| variable | darthplagueis | snoke |
|---|---|---|
| `GENPY` (`tb/Makefile:355`) — script generators, run after `cd ../ref` | `.venv/bin/python` (default) | `/home/cah/.venv/bin/python` |
| `MODELPY` (`tb/Makefile:505`) — real-model generators; also needs the HF cache on that machine | defaults to `$(GENPY)` | `/home/cah/.venv/bin/python` |
| `VECPY` (`tb/Makefile:32`) — TB vector generators | auto: system `python3` if it has numpy, else `../ref/.venv/bin/python` | same auto-detect |
| `CHAT_PY` (`tb/Makefile`, chat gate I1) | defaults to `$(VECPY)` | `/home/cah/.venv/bin/python` |
| `PY` (`sw/Makefile:23`) — host tools | — | `.venv/bin/python` (i.e. `sw/.venv`) |

### The targets

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/tb

# TB stimulus (cheap, no HF cache needed)
make v2_vectors ng_vectors topk_cases seq_c_vectors seq_unit_vectors

# synthetic multi-layer / token scripts
make chain_scripts  GENPY=/home/cah/.venv/bin/python
make token24_scripts GENPY=/home/cah/.venv/bin/python

# THE real model script (~950 MB/seed; needs the HF checkpoint cache)
make model_v2_script_s1 MODELPY=/home/cah/.venv/bin/python
#   MODEL_V2_FLAGS defaults to "--res-scale=8 --allow-clip".
#   --allow-clip is REQUIRED: the runtime range audit correctly reports that
#   S_F=13 saturates on the real weights, and S_F is frozen in the RTL.
#   Leaving MODEL_FLAGS empty is the honest default: it fails loudly.

# full-chip SEQ gate artifacts
make seq_chip_scripts GENPY=/home/cah/.venv/bin/python
make chat_i1_gate     CHAT_PY=/home/cah/.venv/bin/python
```

### The `.e` / `.e4` SEQ artifacts the chat path needs

`tb/scripts/w4/model_v2_s1.e*` are produced by the **same** generator with the
SEQ emitter switched on via environment variables (`sw/Makefile:32-46`):

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm/ref
SEQ_EMIT=$PWD/../tb/scripts/w4/model_v2_s1.e SEQ_PROFILE=epsnorm \
  /home/cah/.venv/bin/python gen_model_script.py \
  ../tb/scripts/w4/model_v2_s1.txt 1 3 --res-scale=8 --allow-clip

# the opt-in 4-chan variant: same .txt / weight images / const blob,
# only the matvec encoding differs
SEQ_EMIT=$PWD/../tb/scripts/w4/model_v2_s1.e4 SEQ_PROFILE=epsnorm SEQ_NCH=4 \
  /home/cah/.venv/bin/python gen_model_script.py \
  ../tb/scripts/w4/model_v2_s1.txt 1 3 --res-scale=8 --allow-clip
```

`chat_seq.py` asserts `sha256(model_v2_s1.e.seq) ==
a69864d25b6b129a4d6c74b3c78dfcbedf1edce219d32cc05d05bc54f444aaf1` and
`nrec == 60495` on every start-up. If you regenerate and the sha moves, the
chat path stops — that is the intended behaviour, not a bug
(`--any-template` bypasses it, development only).

**The 4-chan pin is PER MODEL** (`sw/chat_seq.TEMPLATE4_BY_MODEL`). The
default entry is the frozen `model_v2_s1.e4` (68,119 records, sha
`e102e2df0835097d…`); `FABLE5_MODEL=9b` selects `tb/scripts/w9/model_9b_s1.e4`
(158,536 records, sha `9760899df53b3b42…`), which S4 emitted
(`evidence/qwen9b/s4/001_emit_9b_s1.log:203`) and the `seq_model` 4-chan SEQ
gate passed on this tree (`evidence/qwen9b/g6/024_seqmodel_gate_s1to4.log`).
**Re-pinning either entry means running that gate on the new artifact
first** — the refusal message says so, and it means it.

Both commands above emit the **nch-independent** weight pack: one span per
image that every channel reserves, MVGO WBASE = `base + GLOBAL row *
stride`. `SEQ_REPACK=1` (R-c, needs `SEQ_NCH>1`) emits the **per-channel**
pack instead — each channel packs only the rows it owns, the stream's JSON sidecar gets
`"weight_repack": true` and per-image `"base"` becomes a list of nch
addresses. It is OFF by default because the frozen 0.8B streams above encode
the other pack; it is what makes the 2B W8 (V5) pack fit, 464.8 MiB on the
busiest channel instead of 1,847 MiB in one span (`docs/SEQ_ISA.md` B14):

```bash
# check the fit BEFORE emitting anything (no checkpoint needed)
python3 ref/scripts/bytes_per_token.py --fit --model 2b \
  --map all:w8g128 --nch 4          # -> per-channel tops + FIT PASS

SEQ_EMIT=<prefix> SEQ_PROFILE=epsnorm SEQ_NCH=4 SEQ_REPACK=1 \
  python gen_model_script.py <prefix>.txt 1 3 --res-scale=8 --allow-clip
```

The host reads the flag out of the stream's own meta (`sw/seq_run.py:
plan_weights_for`), so `seq_run.py` / `chat_seq.py` need no extra option —
and a stream and a pack that disagree about it are refused, not guessed.

### Host-tool make targets (`sw/Makefile`, run on snoke)

```
make seq_selftest                # pure python, no board
make seq_dry_run                 # upload + readback verify, touches NO SEQ CSRs
make seq_run                     # the real sequencer run (1-chan)
make seq_dry_run4 / seq_run4     # the 4-chan variants
make chat4 / chat4_canned        # chat_seq --nch 4
make tok_meter / tok_meter4      # device-counter tok/s
make chat / chat_verify / infer_gate   # the legacy host-driven infer.py
make smoke_lcyc regress_hwmap
```

Note there is **no** `serve` / `chat_client` / 1-chan `chat_seq` target in
`sw/Makefile` — `sw/serve.py:79-82` and `chat_seq.py:98-100` *suggest* them as an
integrator TODO that was never applied. Invoke those two directly.

---

## 7. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `REFUSING TO TOUCH THE BOARD — identity gate failed: MAGIC=0x… / CALIB=0x… / layer IDENT=… / matvecN IDENT=…` | the resident bitstream is not this design, or DDR is not calibrated | Reprogram (§2). `CALIB != 0xF` means a DDR4 channel did not train — power-cycle, then reprogram; never DMA in this state. The tool never programs the FPGA itself, by design |
| `VERSION=0x… != EXPECTED_SEQ_VERSION 0xC973C18A: this bitstream has no sequencer (or is the wrong one)` | **stale bitstream** — an older build is resident, or a power cycle wiped the volatile config | Reprogram build_041 `ckr2_AltSpreadLogic_high` (§2). `--dry-run` still works: it performs zero accesses to the `0x6000` window |
| `UnknownBitstream: VERSION=0x… is not a bitstream this checkout knows the SHAPE layout of` | the resident VERSION has no row in `sw/hwmap.py:SHAPE_ISA_BY_VERSION` | **Do not guess** — the two `R_SHAPE` layouts decode each other's words as plausible garbage. Add the row, or use a checkout that matches the resident image |
| `SEQ halted with err_code=0x10 (layer_chan err_op) at pc=5/1526` from `sw/chat_seq.py` | a 0.8B/2B (SEQ_ISA v1.7) stream on the 9B netlist. **There is no back-compat ladder on build_041** | Nothing to fix on the board — run the 9B chat path instead: `FABLE5_MODEL=9b … --nch 4` (§3). `--nch 1`'s templates are byte slices of `tb/scripts/w4/model_v2_s1.e` and are 0.8B/2B by construction. `evidence/qwen9b/g6/RD9_GATE.md` §8 |
| `template geometry: 8 position-indexed LDCs in the body, expected 6` | `sw/chat_seq.py` pointed at a 4B/9B artifact without `FABLE5_MODEL=9b` | Export `FABLE5_MODEL=9b`. The guard is correct: `POS_COPIES` counts full-attention layers and it refuses to derive a stride from a count that does not match the stream |
| `… .e4.seq sha256 … != the gated 4-chan template …` | the `--nch 4` artifact is not the one pinned for this model selection | Check `FABLE5_MODEL`. The pin is per model (`sw/chat_seq.TEMPLATE4_BY_MODEL`); re-pinning it means re-running the `seq_model` 4-chan gate on the new artifact first |
| `--pos-mode xrf cannot reach --max-ctx N` (or `--verify with pos_mode='xrf' is REFUSED at this geometry`) | `xrf` addresses positions through the signed 18-bit XRF[4]; it reaches `XRF_POS_MAX` (63 at 9B's 2,048 B stride, 85 at 1,536 B) and the RTL truncates silently past it | Use `--pos-mode ldc`, or `auto`, which picks it. `ref/seq_model` does not model the truncation, so lockstep would not catch it — which is why it is a refusal, on both sides, and why the condition is the geometry and not the model name |
| a run halts with `err_code 0x00` at the right PC and emits the WRONG tokens | the DDR state region is dirty — `--skip-weights` does not reset it | `evidence/qwen9b/g6/g6_state.py --write-initial`, or a full `seq_run` without `--skip-weights`. `evidence/qwen9b/g6/RD9_GATE.md` §14.2 |
| `--temp` exits with "sampling needs the on-chip top-k capture unit…" | the resident bitstream is pre-build_033, or `--topk-base` is wrong/omitted (`sw/serve.py` requires it explicitly) | Confirm `0x5048` reads `0xFAB1704B`; otherwise reprogram. Greedy is unaffected |
| no `/dev/xdma0_*` | **xdma module not loaded** — it never autoloads | `sudo -n .../sw/pcie_helper.sh load`. If `insmod` says *Invalid module format*, the kernel was bumped: rebuild `xdma.ko` first (§1) |
| `lspci` does not show `10ee:9038` at `82:00.0` — **board off the bus** | the endpoint was removed, or the FPGA has no bitstream (volatile config lost to a power cycle), or the link did not train | `pcie_helper.sh status` → `rescan` → if still absent, `sbr` (secondary bus reset) → if still absent, JTAG-reprogram (§2). `pcie_helper.sh debug` dumps endpoint + root-port config space and the dmesg tail |
| `lsusb` shows no FTDI (`0403:xxxx`) so JTAG cannot program | the micro-USB JTAG cable/header | physical: reseat the cable (`docs/SNOKE_REBUILD.md` §0). Ask the user — Claude cannot do this |
| the sequencer halted with an error | the STATUS word's err_code field | decode it by calling hwmap.seq_err_name(0x12) from a python shell with `sw/` on the path. The full table is `sw/hwmap.py:SEQ_ERR` (mirrors `rtl/seq_unit.sv:40-58` + `rtl/seq_movers.sv:136-139`). `0x0C` is your own ABORT; `0x10/0x11` are layer_chan; `0x20-0x23` are matvec/mover |
| `of_ovf` sticky bit set in `S_STATUS[23]` | the OUT FIFO (depth 64) overflowed — **a token was DROPPED**, not stalled. Sticky until reset | every later token of that session is suspect; restart the session |
| `REFUSED: another process holds the board lock …` | somebody has the board — the message names their host, pid, user, tool, time and checkout | go and look at the named host/tree. `--no-lock` overrides it and is audited (§5); there is no `--force-unlock`, because a held flock always means a live holder |
| a second tool "works" but results are garbage | something drove the board under a live session: a `--no-lock` run, or a checkout that predates O3 and still locks its own `sw/.seq.lock` (§5) | `python3 sw/board_lock.py --status`; check the `.nolock` audit log beside the board lock; `pgrep` |
| SSH to snoke resets before the banner (kex reset) | historical infra wedge (NVIDIA driver / disk), not this project | the user reboots snoke; then §1 |
| a chat reply is a quiz continuation that never stops | `--raw` (template off) | drop `--raw`; the chat template is the default (`docs/INSTRUCT_SPEC.md` T4) |
| multi-turn answers degrade | turn 1 was cut at the token budget before EOS | `--ntok >= 24` (§3) |
