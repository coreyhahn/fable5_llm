#!/usr/bin/env bash
# rung2_launch.sh — Task NV1 rung 2 (the 9B decision rows), rulings C11/C12.
# README: runs ON SNOKE only.  Every row goes through nvfp4_run.sh (provenance
# header, never overwrites).  Rails (brief): a 9B row running > 12 h is a STOP
# for the monitor (this script does not kill on it); snoke `free -g` available
# must stay > 40 GB with rows pending (checked before every launch below).
#
#   rung2_launch.sh cpu              # the 2 CPU provenance rows, detached, in parallel
#   rung2_launch.sh cpuq [QUEUE_LOG] # ruling C13: the CPU queue (n51-n59, n54 last) — the one launched
#   rung2_launch.sh p40 [QUEUE_LOG]  # the serial P40 queue, self-detaching (NOT launched, C13)
#                                    # (default queue log n48_rung2_queue.log;
#                                    #  a relaunch must name a NEW n## queue log)
# The P40 queue skips any row whose log already exists (the wrapper never
# overwrites), so a relaunch resumes at the first un-started row.  It refuses
# to start a row while any other process holds > 1 GiB of the P40.
#
# n## assignment (fixed up front, rung 2):
#   n46  CPU  bf16 anchor
#   n47  CPU  all:w4g128 --act a8 (shipped)
#   n48  P40  queue log
#   n49  P40  bf16 anchor
#   n50  P40  all:w4g128 --act a8 (shipped)
#   n51  P40  all:nvfp4 --act nvfp4:dyn (full NVFP4)
#   n52  P40  all:nvfp4h --act a8 --rht-seed 0
#   n53  P40  all:nvfp4 --act a8
#   n54  P40  all:w4g64gptq --act a8 --calib-stats ref/calib_stats_9b_h.npz (4 h json bound)
#   n55  P40  all:nvfp4 (weights only)
#   n56  P40  all:nvfp4h --rht-seed 0 (weights only)
#   n57  P40  bf16 + --act a8
#   n58  P40  bf16 + --act nvfp4:dyn
#   n59  P40  all:nvfp4h --act a8 --rht-seed 1
set -u
ROOT=/home/cah/r2d2/code/fpga/fable5_llm
EV=evidence/qwen_next/nvfp4
cd "$ROOT" || exit 1
[ "$(hostname)" = snoke ] || { echo "rung2_launch.sh: snoke only (this is $(hostname))" >&2; exit 1; }

SHIPPED_PY=/home/cah/.venv/bin/python
CUDA_PY=/home/cah/.venv_nvfp4_cuda/bin/python
SHA=6bf4f8677a3b3fff178c6915e2a55b7326e534f6e54650067e33b056e4c27876
COMMON="--corpus ref/ppl_corpus_eval.txt --expect-corpus-sha256 $SHA --window 512"
CPU_THREADS=12
GPU_THREADS=12
MEM_RAIL=40            # GB that must stay available
CPU_ROW_GB=50          # D: fp32 9B body 35.96 GiB + fp32 head copy 3.79 GiB + eval buffers
GPU_ROW_GB=50          # D: the model is BUILT in fp32 on the host, then .half().to(cuda)
GPTQ_ROW_GB=90         # D: + calib_stats_9b_h.npz 25.8 GB + GPTQ Hessian work
GPTQ_BOUND_S=14400     # 4 h: no json by then -> kill, log, move on

avail_gb() { free -g | awk '/^Mem:/{print $7}'; }
ts() { date -Is; }

# ----------------------------------------------------------------- CPU rows
cpu_row() {  # n## name inject-args...
  local nn="$1" name="$2"; shift 2
  local log="${nn}_${name}.log" json="$EV/${nn}_${name}.json"
  if [ -e "$EV/$log" ]; then echo "cpu: $log exists — not relaunching (use a new n##)"; return 1; fi
  setsid nohup "$EV/nvfp4_run.sh" "$log" env FABLE5_MODEL=9b "$SHIPPED_PY" \
      ref/perplexity_eval.py $COMMON --threads $CPU_THREADS "$@" \
      --json-out "$json" > /dev/null 2>&1 < /dev/null &
  echo "cpu: launched $log (setsid pid $!) at $(ts)"
}

if [ "${1:-}" = cpu ]; then
  a=$(avail_gb); need=$((2 * CPU_ROW_GB + MEM_RAIL))
  echo "cpu: available ${a} GB; 2 rows x ${CPU_ROW_GB} + rail ${MEM_RAIL} = ${need} GB"
  [ "$a" -ge "$need" ] || { echo "cpu: STOP — memory rail"; exit 3; }
  cpu_row n46 ppl_9b_bf16_cpu
  cpu_row n47 ppl_9b_w4g128_a8_cpu --inject all:w4g128 --act a8
  exit 0
fi

# ------------------------------------------------- CPU queue (ruling C13)
# 2026-09-23 ruling C13: the P40 is held by the user's Ollama llama-server
# (not touched), and n46 measured a 9B CPU row at ~20 min incl. build, so every
# remaining row runs on CPU in the shipped venv.  n49/n50 DROPPED (they were
# the P40 duplicates of n46/n47).  At most 3 rows at once, counting n46/n47;
# a row starts only when `free -g` available >= 100 GB (40 GB rail + n46's
# measured 53.6 GB RSS with margin), else wait and re-check every 60 s.
# n54 (GPTQ) runs ALONE at the end with its 4 h json bound.
#   rung2_launch.sh cpuq [QUEUE_LOG]   # self-detaching; default n48_rung2_queue.log
CPUQ_MAX=3
CPUQ_MIN_AVAIL=100
if [ "${1:-}" = cpuq ]; then
  QLOG="${2:-n48_rung2_queue.log}"
  if [ -e "$EV/$QLOG" ]; then echo "cpuq: queue log $QLOG exists — name a new n##" >&2; exit 2; fi
  setsid nohup "$0" _cpuq "$QLOG" > /dev/null 2>&1 < /dev/null &
  echo "cpuq: queue launched (setsid pid $!), log $EV/$QLOG"
  exit 0
fi
if [ "${1:-}" = _cpuq ]; then
  QLOG="$EV/$2"
  q() { echo "$(ts) $*" >> "$QLOG"; }
  # python processes of this rung (n46/n47 and the queue's rows) — the concurrency count
  running9b() { pgrep -f "^$SHIPPED_PY ref/perplexity_eval.py .*--json-out $EV/n(4[67]|5[0-9])_" | wc -l; }
  CROWS=(
    "n51|ppl_9b_nvfp4_actdyn_cpu|0|--inject all:nvfp4 --act nvfp4:dyn"
    "n52|ppl_9b_nvfp4h_a8_seed0_cpu|0|--inject all:nvfp4h --act a8 --rht-seed 0"
    "n53|ppl_9b_nvfp4_a8_cpu|0|--inject all:nvfp4 --act a8"
    "n55|ppl_9b_nvfp4_cpu|0|--inject all:nvfp4"
    "n56|ppl_9b_nvfp4h_seed0_cpu|0|--inject all:nvfp4h --rht-seed 0"
    "n57|ppl_9b_bf16_a8_cpu|0|--act a8"
    "n58|ppl_9b_bf16_actnvfp4dyn_cpu|0|--act nvfp4:dyn"
    "n59|ppl_9b_nvfp4h_a8_seed1_cpu|0|--inject all:nvfp4h --act a8 --rht-seed 1"
    "n54|ppl_9b_w4g64gptq_a8_cpu|$GPTQ_BOUND_S|--inject all:w4g64gptq --calib-stats ref/calib_stats_9b_h.npz --act a8"
  )
  {
    echo "=== NV1 rung 2 CPU queue  host: $(hostname)  tree: $(git rev-parse --short HEAD)"
    echo "=== HOST CHANGE (ruling C13, 2026-09-23): P40 held by the user's Ollama llama-server (pid 489137, 12,668 MiB; not touched);"
    echo "===   n46 measured 4/48 windows in 59 s at 12 threads (~20 min/row incl. build) -> every row on CPU, shipped venv."
    echo "===   n49/n50 DROPPED (P40 duplicates of n46/n47). The p40 mode of this script is kept but never launched."
    echo "=== FABLE5_MODEL=9b $SHIPPED_PY --threads $CPU_THREADS (device cpu), $COMMON"
    echo "=== gates: <= $CPUQ_MAX rows at once (n46/n47 counted); start only if free -g available >= $CPUQ_MIN_AVAIL GB, else re-check every 60 s"
    echo "=== n54 runs ALONE last; json bound ${GPTQ_BOUND_S}s (4 h) -> kill + log. A row > 12 h is a STOP for the monitor (not enforced)."
    echo "=== n## assignment: n46 CPU bf16 | n47 CPU w4g128+a8 | n48 this log | n49,n50 dropped"
    for r in "${CROWS[@]}"; do IFS='|' read -r nn name bound args <<< "$r"
      echo "===   $nn  $name  [${args}]  bound=${bound}"; done
  } >> "$QLOG"
  declare -A PG_OF=() T0_OF=() LOG_OF=() JSON_OF=() BOUND_OF=()
  reap() {  # log END for finished rows, enforce the n54 bound
    local nn
    for nn in "${!PG_OF[@]}"; do
      local pg=${PG_OF[$nn]} killed=0
      if kill -0 "$pg" 2>/dev/null; then
        if [ "${BOUND_OF[$nn]}" -gt 0 ] && [ ! -e "${JSON_OF[$nn]}" ] \
           && [ $(( $(date +%s) - ${T0_OF[$nn]} )) -ge "${BOUND_OF[$nn]}" ]; then
          kill -TERM -- "-$pg" 2>/dev/null; sleep 30; kill -KILL -- "-$pg" 2>/dev/null
          q "KILLED $nn at the ${BOUND_OF[$nn]}s bound (no json)"; killed=1
        else continue; fi
      fi
      wait "$pg" 2>/dev/null
      local rc; rc=$(grep -m1 '^=== rc' "$EV/${LOG_OF[$nn]}" 2>/dev/null | awk '{print $NF}')
      q "END $nn rc=${rc:-none} json=$([ -e "${JSON_OF[$nn]}" ] && echo yes || echo no) killed=$killed wall=$(( $(date +%s) - ${T0_OF[$nn]} ))s"
      unset "PG_OF[$nn]"
    done
  }
  for r in "${CROWS[@]}"; do
    IFS='|' read -r nn name bound args <<< "$r"
    log="${nn}_${name}.log"; json="$EV/${nn}_${name}.json"
    if [ -e "$EV/$log" ]; then q "SKIP $nn: $log exists"; continue; fi
    maxrun=$CPUQ_MAX; [ "$nn" = n54 ] && maxrun=1   # n54 alone
    waited=0
    while :; do
      reap
      n=$(running9b); a=$(avail_gb)
      if [ "$n" -lt "$maxrun" ] && [ "$a" -ge "$CPUQ_MIN_AVAIL" ]; then break; fi
      [ $((waited % 30)) -eq 0 ] && q "WAIT $nn: running=$n (max $maxrun) available=${a}GB (min $CPUQ_MIN_AVAIL)"
      waited=$((waited + 1)); sleep 60
    done
    # shellcheck disable=SC2086
    setsid "$EV/nvfp4_run.sh" "$log" env FABLE5_MODEL=9b "$SHIPPED_PY" ref/perplexity_eval.py \
        $COMMON --threads $CPU_THREADS $args --json-out "$json" > /dev/null 2>&1 < /dev/null &
    PG_OF[$nn]=$!; T0_OF[$nn]=$(date +%s); LOG_OF[$nn]=$log; JSON_OF[$nn]=$json; BOUND_OF[$nn]=$bound
    q "START $nn $log pgid $! running_before=$n available=${a}GB"
    sleep 20   # let the new row register before the next count
  done
  while [ "${#PG_OF[@]}" -gt 0 ]; do reap; [ "${#PG_OF[@]}" -gt 0 ] && sleep 60; done
  q "QUEUE DONE"
  exit 0
fi

# ------------------------------------------------------------ P40 queue
if [ "${1:-}" = p40 ]; then
  QLOG="${2:-n48_rung2_queue.log}"
  if [ -e "$EV/$QLOG" ]; then echo "p40: queue log $QLOG exists — name a new n##" >&2; exit 2; fi
  setsid nohup "$0" _queue "$QLOG" > /dev/null 2>&1 < /dev/null &
  echo "p40: queue launched (setsid pid $!), log $EV/$QLOG"
  exit 0
fi

[ "${1:-}" = _queue ] || { echo "usage: $0 cpu | cpuq [QUEUE_LOG] | p40 [QUEUE_LOG]" >&2; exit 1; }
QLOG="$EV/$2"
q() { echo "$(ts) $*" >> "$QLOG"; }

# row table: n## | name | mem GB | bound s (0 = none) | args
ROWS=(
  "n49|ppl_9b_bf16_cuda|$GPU_ROW_GB|0|"
  "n50|ppl_9b_w4g128_a8_cuda|$GPU_ROW_GB|0|--inject all:w4g128 --act a8"
  "n51|ppl_9b_nvfp4_actdyn_cuda|$GPU_ROW_GB|0|--inject all:nvfp4 --act nvfp4:dyn"
  "n52|ppl_9b_nvfp4h_a8_seed0_cuda|$GPU_ROW_GB|0|--inject all:nvfp4h --act a8 --rht-seed 0"
  "n53|ppl_9b_nvfp4_a8_cuda|$GPU_ROW_GB|0|--inject all:nvfp4 --act a8"
  "n54|ppl_9b_w4g64gptq_a8_cuda|$GPTQ_ROW_GB|$GPTQ_BOUND_S|--inject all:w4g64gptq --calib-stats ref/calib_stats_9b_h.npz --act a8"
  "n55|ppl_9b_nvfp4_cuda|$GPU_ROW_GB|0|--inject all:nvfp4"
  "n56|ppl_9b_nvfp4h_seed0_cuda|$GPU_ROW_GB|0|--inject all:nvfp4h --rht-seed 0"
  "n57|ppl_9b_bf16_a8_cuda|$GPU_ROW_GB|0|--act a8"
  "n58|ppl_9b_bf16_actnvfp4dyn_cuda|$GPU_ROW_GB|0|--act nvfp4:dyn"
  "n59|ppl_9b_nvfp4h_a8_seed1_cuda|$GPU_ROW_GB|0|--inject all:nvfp4h --act a8 --rht-seed 1"
)
{
  echo "=== NV1 rung 2 P40 queue (rulings C11/C12)  host: $(hostname)  tree: $(git rev-parse --short HEAD)"
  echo "=== serial, FABLE5_MODEL=9b, $CUDA_PY --device cuda --threads $GPU_THREADS, $COMMON"
  echo "=== rails: available memory > ${MEM_RAIL} GB before each row; n54 json bound ${GPTQ_BOUND_S}s (4 h) -> kill + move on;"
  echo "===        a 9B row > 12 h is a STOP for the monitor (not enforced here)"
  echo "=== n## assignment: n46 CPU bf16 | n47 CPU w4g128+a8 | n48 this queue log"
  for r in "${ROWS[@]}"; do IFS='|' read -r nn name mem bound args <<< "$r"
    echo "===   $nn  $name  [${args:-bf16}]  mem~${mem}GB  bound=${bound}"; done
} >> "$QLOG"

for r in "${ROWS[@]}"; do
  IFS='|' read -r nn name mem bound args <<< "$r"
  log="${nn}_${name}.log"; json="$EV/${nn}_${name}.json"
  if [ -e "$EV/$log" ]; then q "SKIP $nn: $log exists"; continue; fi
  a=$(avail_gb)
  if [ "$a" -lt $((mem + MEM_RAIL)) ]; then
    q "STOP before $nn: available ${a} GB < ${mem} + ${MEM_RAIL} (memory rail); queue ends"; exit 3; fi
  held=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits \
         | awk -F', *' '$2>1024{print $1":"$2"MiB"}' | tr '\n' ' ')
  if [ -n "$held" ]; then
    q "STOP before $nn: P40 held by another process: $held; queue ends"; exit 4; fi
  t0=$(date +%s)
  # shellcheck disable=SC2086
  setsid "$EV/nvfp4_run.sh" "$log" env FABLE5_MODEL=9b "$CUDA_PY" ref/perplexity_eval.py \
      $COMMON --threads $GPU_THREADS --device cuda $args --json-out "$json" \
      > /dev/null 2>&1 < /dev/null &
  pg=$!
  q "START $nn $log pgid $pg avail ${a}GB"
  killed=0
  while kill -0 "$pg" 2>/dev/null; do
    sleep 60
    if [ "$bound" -gt 0 ] && [ ! -e "$json" ] && [ $(( $(date +%s) - t0 )) -ge "$bound" ]; then
      kill -TERM -- "-$pg" 2>/dev/null; sleep 30; kill -KILL -- "-$pg" 2>/dev/null
      killed=1; q "KILLED $nn at the ${bound}s bound (no json); moving on"; break
    fi
  done
  wait "$pg" 2>/dev/null
  rc=$(grep -m1 '^=== rc' "$EV/$log" 2>/dev/null | awk '{print $NF}')
  q "END $nn rc=${rc:-none} json=$([ -e "$json" ] && echo yes || echo no) killed=$killed wall=$(( $(date +%s) - t0 ))s"
done
q "QUEUE DONE"
