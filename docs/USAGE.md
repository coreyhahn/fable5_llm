# USAGE — operator's guide to the fable5_llm accelerator

Everything here is host-side. Nothing in this document programs flash,
and nothing in `sw/` ever will (`sw/seq_run.py:39`, `sw/chat_seq.py:80`).

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
the host (`sw/pcie_helper.sh:10-13`).

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
§2 before §3. Other `pcie_helper.sh` subcommands, all root:
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
`sw/seq_run.py:EXPECTED_SEQ_VERSION` (today `0x33D720E5`, build_033) or every
sequencer tool refuses.

---

## 2. Safe reprogram (JTAG, volatile only)

> **NEVER write board flash.** `sw/program_fpga.sh` uses
> `synth/scripts/program.tcl` over JTAG and is volatile by construction; there
> is no flash path in this repo and none should be added.

The order matters: a host MMIO read to a removed/dead endpoint can kernel-panic
snoke, which then needs a physical reboot (CHARTER safety rails).

```bash
cd /home/cah/r2d2/code/fpga/fable5_llm
sudo -n $PWD/sw/pcie_helper.sh remove            # detach driver + drop from PCI tree
./sw/program_fpga.sh synth/out_build_033_rr_AltSpreadLogic_medium/proj/stage1.runs/impl_1/bd_wrapper.bit
sudo -n $PWD/sw/pcie_helper.sh rescan            # re-enumerate, driver rebinds
sudo -n $PWD/sw/pcie_helper.sh load              # only if xdma isn't loaded yet
```

Then re-run the identity check in §1 and confirm `CALIB == 0xF` **before any
DMA**. Writing DDR before the MIG reports calibrated is a hard project rule.

`sw/stage1_hw_bringup.sh <bitfile> <version_hex8>` wraps the whole flow
(preconditions → remove → program → rescan → CSR/DDR gates) and logs to
`evidence/stage1/`. `SKIP_PROGRAM=1` reuses the resident design.

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

### Greedy vs sampled

| | greedy (default) | sampled |
|---|---|---|
| flag | `--temp 0` (the default) | `--temp T > 0` |
| where the token is decided | **100% on-chip** — LM head + AMAX32 argmax on the FPGA, token arrives via the SEQ OUT FIFO | still on-chip LM head + on-chip top-32 capture; the host does one seeded RNG draw over the 32 chip-provided scores |
| bit-exact vs the reference | yes | seed-deterministic, not bit-exact by definition |
| extra cost | — | ~68 MMIO reads/token ≈ 0.11 ms (`sw/chat_seq.py:1099`) |

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
| `--model-only` | gate G2: one templated turn through `ref/seq_model` vs the bf16 reference. **No board, no lock**, ~5-7 s/step |
| `--selftest` | pure-host unit tests; touches no device at all (175/175 as of the instruct gate) |
| `--verify` | lockstep `ref/seq_model` prediction for every step; ~6 s host time per step, the board idles |
| `--verify-head` | verification only: rebuild the head's logits on the host from the chip's own x8/e_x and assert host argmax == chip token, every step. The chip still decides |
| `--prefill lite\|full` | `lite` (default) prefill steps skip the LM head; `full` makes every step emit a token |
| `--continue-context` | keep KV/DN state across `--prompt` turns (default: preamble between them) |
| `--max-ctx N` | default 500; must be **< 512** (the KV bank depth — the RTL wraps silently past it) |
| `--pos-mode auto\|xrf\|ldc` | how a step addresses its RoPE tables. `xrf` is the frozen spec's `XRF[4]=pos*1536`, which is a **signed** 18-bit field and silently truncates past pos 85; `ldc` patches the six position-LDC addresses and reaches the whole KV depth. `auto` (default) picks by `--max-ctx`, so the shipped path is `ldc` |
| `--force-upload` | skip the residency probe, re-upload everything |
| `--out FILE.json` | JSON report (perf, launches, sampling, template telemetry) |
| `--dev`, `--chan`, `--lock`, `--timeout`, `--preamble-timeout` | plumbing |

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

## 4. `serve.py` + `chat_client.py` — the HTTP/SSE front end

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
`chat_seq.py`, `serve.py`'s `--topk-base` defaults to `None`, and a server-wide
`--temp > 0` without it is refused **at argument parse time**, before the flock
and the bring-up.

### `chat_client.py`

Stdlib-only readline REPL / one-shot client. Runs in `sw/.venv`, the system
python, or on a laptop over the tunnel with nothing installed.

```
--host --port --session NAME --max-tokens N --prompt TEXT (repeatable)
--reset --health --metrics --raw (dump every SSE event verbatim) --timeout
REPL: /reset /health /metrics /sessions /session NAME /ntok N /raw /help /quit
```

---

## 5. Lock discipline (the one that bites)

`sw/.seq.lock` is an exclusive `fcntl.flock()` taken **before any device fd is
opened** and held for the process lifetime (`chat_seq.py:SeqLock`).

| takes the lock | does **NOT** take the lock |
|---|---|
| `sw/chat_seq.py` (owner) | `sw/infer.py` |
| `sw/serve.py` (real mode; `--mock` does not) | `sw/seq_run.py` |
| `sw/cycle_census.py` | `sw/tok_meter.py`, `sw/mover_bench.py` |
| | `sw/layer_test.py`, `sw/matvec_test.py`, `sw/ddr_test.py` |

So the lock only serialises `chat_seq`/`serve`/`cycle_census` **against each
other**. The legacy tools will happily drive the same board underneath a live
chat session. Before starting any of them:

```bash
pgrep -af 'infer.py|seq_run.py|tok_meter.py|mover_bench.py|serve.py|chat_seq.py'
cat /home/cah/r2d2/code/fpga/fable5_llm/sw/.seq.lock   # holder pid + tool + timestamp
```

Two specific hazards:

- **`serve.py` left running** holds the lock indefinitely (it has been left up
  on `snoke:8137` before). Get its pid from `GET /v1/health` and `kill` it to
  free the board.
- **`sw/mover_bench.py` clobbers the chat-resident stream images** at
  `0x0900_0000` and takes no lock. The next chat session re-uploads ~2 MiB
  automatically, but do not run it against a live session.

Retrofitting the flock into `infer.py` / `seq_run.py` / `tok_meter.py` is a
known open follow-on.

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
| `GENPY` (`tb/Makefile:459`) — script generators, run after `cd ../ref` | `.venv/bin/python` (default) | `/home/cah/.venv/bin/python` |
| `MODELPY` (`tb/Makefile:548`) — real-model generators; also needs the HF cache on that machine | defaults to `$(GENPY)` | `/home/cah/.venv/bin/python` |
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
`sw/Makefile` — `serve.py:79-82` and `chat_seq.py:98-100` *suggest* them as an
integrator TODO that was never applied. Invoke those two directly.

---

## 7. Troubleshooting

| symptom | cause | fix |
|---|---|---|
| `REFUSING TO TOUCH THE BOARD — identity gate failed: MAGIC=0x… / CALIB=0x… / layer IDENT=… / matvecN IDENT=…` | the resident bitstream is not this design, or DDR is not calibrated | Reprogram (§2). `CALIB != 0xF` means a DDR4 channel did not train — power-cycle, then reprogram; never DMA in this state. The tool never programs the FPGA itself, by design |
| `VERSION=0x… != EXPECTED_SEQ_VERSION 0x33D720E5: this bitstream has no sequencer (or is the wrong one)` | **stale bitstream** — an older build is resident, or a power cycle wiped the volatile config | Reprogram build_033 (§2). `--dry-run` still works: it performs zero accesses to the `0x6000` window |
| `--temp` exits with "sampling needs the on-chip top-k capture unit…" | the resident bitstream is pre-build_033, or `--topk-base` is wrong/omitted (`serve.py` requires it explicitly) | Confirm `0x5048` reads `0xFAB1704B`; otherwise reprogram. Greedy is unaffected |
| no `/dev/xdma0_*` | **xdma module not loaded** — it never autoloads | `sudo -n .../sw/pcie_helper.sh load`. If `insmod` says *Invalid module format*, the kernel was bumped: rebuild `xdma.ko` first (§1) |
| `lspci` does not show `10ee:9038` at `82:00.0` — **board off the bus** | the endpoint was removed, or the FPGA has no bitstream (volatile config lost to a power cycle), or the link did not train | `pcie_helper.sh status` → `rescan` → if still absent, `sbr` (secondary bus reset) → if still absent, JTAG-reprogram (§2). `pcie_helper.sh debug` dumps endpoint + root-port config space and the dmesg tail |
| `lsusb` shows no FTDI (`0403:xxxx`) so JTAG cannot program | the micro-USB JTAG cable/header | physical: reseat the cable (`docs/SNOKE_REBUILD.md` §0). Ask the user — Claude cannot do this |
| the sequencer halted with an error | `S_STATUS[31:24]` is `err_code` | decode it: `python3 -c "import sys; sys.path.insert(0,'sw'); import hwmap; print(hwmap.seq_err_name(0x12))"`. The full table is `sw/hwmap.py:SEQ_ERR` (mirrors `rtl/seq_unit.sv:40-51` + `rtl/seq_movers.sv:115-118`). `0x0C` is your own ABORT; `0x10/0x11` are layer_chan; `0x20-0x23` are matvec/mover |
| `of_ovf` sticky bit set in `S_STATUS[23]` | the OUT FIFO (depth 64) overflowed — **a token was DROPPED**, not stalled. Sticky until reset | every later token of that session is suspect; restart the session |
| a second tool "works" but results are garbage | one of the legacy no-lock tools ran against a live session (§5) | `pgrep` first; read `sw/.seq.lock` |
| SSH to snoke resets before the banner (kex reset) | historical infra wedge (NVIDIA driver / disk), not this project | the user reboots snoke; then §1 |
| a chat reply is a quiz continuation that never stops | `--raw` (template off) | drop `--raw`; the chat template is the default (`docs/INSTRUCT_SPEC.md` T4) |
| multi-turn answers degrade | turn 1 was cut at the token budget before EOS | `--ntok >= 24` (§3) |
