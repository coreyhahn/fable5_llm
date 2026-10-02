# NV1 rung 2 — the 9B rows (plan, rulings C11/C12)

Launcher: `evidence/qwen_next/nvfp4/rung2_launch.sh` (`cpu` = the two CPU rows,
detached in parallel; `p40 [QUEUE_LOG]` = the serial P40 queue, self-detaching).
Every row runs on snoke through `nvfp4_run.sh`, with `FABLE5_MODEL=9b`,
`--corpus ref/ppl_corpus_eval.txt --expect-corpus-sha256 6bf4f867…4c27876 --window 512`
(batch at the harness default 4, as in rung 1), `--json-out` beside its log.
CPU rows: `/home/cah/.venv/bin/python`, `--threads 12`. P40 rows:
`/home/cah/.venv_nvfp4_cuda/bin/python --device cuda --threads 12`.

| n## | host | row | extra args | expected wall (S) |
|---|---|---|---|---|
| n46 | CPU | bf16 anchor | — | 1–3 h |
| n47 | CPU | shipped | `--inject all:w4g128 --act a8` | 2–5 h |
| n48 | P40 | queue log (start/end/rc per row, the 4 h bound) | — | — |
| n49 | P40 | bf16 anchor | — | < 30 min |
| n50 | P40 | shipped | `--inject all:w4g128 --act a8` | 1–2 h |
| n51 | P40 | full NVFP4 | `--inject all:nvfp4 --act nvfp4:dyn` | 1–3 h |
| n52 | P40 | NVFP4+RHT + A8 | `--inject all:nvfp4h --act a8 --rht-seed 0` | 1–2 h |
| n53 | P40 | NVFP4 + A8 | `--inject all:nvfp4 --act a8` | 1–2 h |
| n54 | P40 | W4 g64 GPTQ + A8 | `--inject all:w4g64gptq --calib-stats ref/calib_stats_9b_h.npz --act a8` | 4 h bound (killed if no json) |
| n55 | P40 | weights only NVFP4 | `--inject all:nvfp4` | < 1 h |
| n56 | P40 | weights only NVFP4+RHT | `--inject all:nvfp4h --rht-seed 0` | < 1 h |
| n57 | P40 | acts only A8 | `--act a8` | 1 h |
| n58 | P40 | acts only NVFP4 dyn | `--act nvfp4:dyn` | 1–2 h |
| n59 | P40 | RHT seed 1 | `--inject all:nvfp4h --act a8 --rht-seed 1` | 1–2 h |

Wall times are scaled from the rung-1 2B jsons (6 threads: build 44–750 s,
eval 387–1662 s, GPTQ build 3376 s) by ≈ 4–5× for the 9B; the act hooks and
the weight quantizers run in numpy on the CPU even on P40 rows, so the P40
speeds up only the float matmuls. The brief's "≈ 7 h each on CPU" is the
2026-09-09 estimate; these rows measure it.

## Memory (D; snoke 247 GB, 239 GB available at launch time)
- The harness builds the model in **float32** on the host (`text_config`
  sets `cfg.dtype = "float32"`): 17.98 GiB bf16 → 35.96 GiB fp32 body + a
  3.79 GiB fp32 head copy + eval buffers → **≈ 50 GB per CPU row**.
- P40 rows build the same fp32 model on the host, then `.half().to(cuda)`:
  **≈ 50 GB host peak**; ≈ 18 GiB fp16 + buffers on the 23 GiB GPU.
- n54 adds `calib_stats_9b_h.npz` (25.8 GB) and GPTQ work: **≈ 90 GB**.
- Worst concurrent peak: 2 × 50 + 90 = 190 GB → 239 − 190 = **49 GB left > 40 GB rail**.
  The launcher re-checks `free -g` available ≥ row + 40 before every launch
  and STOPs the queue otherwise.

## Rails
- A 9B row running over **12 h** is a STOP for the monitor (not auto-killed).
- snoke available memory must stay **> 40 GB** with rows pending.
- The queue refuses to start a row while another process holds > 1 GiB of the
  P40, and logs a STOP line.
- n## numbers are never reused: a relaunch of the queue names a new queue log;
  rows whose log exists are skipped.

## Amendment 2026-09-23 (evening) — ruling C13: every row on CPU

- **Ollama holds the P40.** At the 18:43 check, pid 489137
  `/usr/local/lib/ollama/llama-server` (root, a child of `ollama serve`
  pid 2982) held 12,668 of 23,040 MiB at 0 % utilization. The 9B in fp16
  does not fit beside it. It is the user's service and was not touched.
- **Measured CPU rate (n46).** n46 is the 9B bf16 anchor at 12 threads,
  started 18:45:46. It reached `window 4/48 … 59.3s` and `window 8/48 …
  119.1s` (`n46_ppl_9b_bf16_cpu.log`), so the eval takes about 15 min.
  Including the build, a row takes about 20 min. The brief's "≈ 7 h" was
  wrong.
- **Measured RSS.** At 4 min, n46's RSS was 53.6 GB (in eval) and n47's was
  34.7 GB (still building).
- **Ruling C13.** Every remaining rung-2 row runs on CPU in the shipped venv,
  `/home/cah/.venv/bin/python`, at `--threads 12` with the device left at its
  cpu default. The P40 is not used, Ollama is not touched, and the `p40`
  mode of the launcher stays in place but is never launched.
- **Dropped rows.** n49 and n50 were the P40 duplicates of n46 and n47. Their
  numbers are retired and never used.
- **Host for the rest.** n51, n52, n53, n55, n56, n57, n58 and n59 keep the
  row assignments in the table above, with the host changed to CPU. n54
  (GPTQ, `ref/calib_stats_9b_h.npz`) runs **alone, last**, with its 4 h json
  bound.
- **Queue.** `rung2_launch.sh cpuq`, detached, logging to
  `n48_rung2_queue.log`; the header records the host change and the reason.
- **Concurrency.** At most 3 rung-2 rows run at once, and n46 and n47 count
  while they are alive. Running rows are counted by the python processes whose
  `--json-out` is `n46`–`n59`.
- **Memory gate.** A row starts only when `free -g` shows available
  ≥ 100 GB: the 40 GB rail plus one row's measured 53.6 GB, with margin. If it
  doesn't, the queue waits and re-checks every 60 s.
- **Worst case.** 3 rows × about 54 GB = about 162 GB of the 247 GB host.
- **Rails unchanged.** A row running over 12 h is a STOP for the monitor, and
  available memory must stay above 40 GB while rows are pending.
