# sw/Makefile — host-side hardware tools (run on snoke, board already
# programmed).  Nothing in here ever programs the FPGA or touches flash.
#
#   make smoke_lcyc     probe the layer_chan LCYC busy-cycle counter
#   make tok_meter      stage-5 inc-4 tok/s, 1 DDR channel
#   make tok_meter4     stage-5 inc-4 tok/s, 4 DDR channels (row-split)
#   make tok_meter_all  both, into evidence/stage5/
#   make regress_hwmap  layer_s1 x1 — proves the hwmap.py refactor is a no-op
#   make chat           interactive live inference REPL (sw/infer.py)
#   make chat_verify    same, full layer_fixed lockstep on every token
#   make infer_gate     the infer.py acceptance gate: the model_v2_s1 prompt
#                       reproduced token-for-token, then two free demos
#   make seq_selftest   sw/seq_run.py pure-python unit tests (NO board)
#   make seq_dry_run    upload + readback-verify the SEQ images (NO SEQ CSRs;
#                       safe on a bitstream that has no sequencer)
#   make seq_run        the real sequencer run (needs build_029 +
#                       EXPECTED_SEQ_VERSION filled in in sw/seq_run.py)
#   make seq_dry_run4   rung 1b: row-split weights over DDR chans 0..3 +
#                       per-channel readback (needs a meta nch>1 stream;
#                       NO SEQ CSRs, safe on any resident bitstream)
#   make seq_run4       rung 1b real 4-chan run (needs build_030 resident)

PY      ?= .venv/bin/python
SCRIPT  ?= ../tb/scripts/model_s1.txt
RUNS    ?= 1
EVID    ?= ../evidence/stage5
TAG     ?= build026
NTOK    ?= 8
INFER_FLAGS ?=

# --- sequencer (rung 1) ------------------------------------------------
# SEQ_PREFIX is the emitter prefix: <prefix>.seq / .seqdata.bin / .seq.json.
# Regenerate it with the documented SEQ_EMIT flow, e.g.
#   cd ../ref && SEQ_EMIT=$(PWD)/../tb/scripts/w4/model_v2_s1.e \
#     SEQ_PROFILE=epsnorm .venv/bin/python gen_model_script.py \
#     ../tb/scripts/w4/model_v2_s1.txt 1 3 --res-scale=8 --allow-clip
SEQ_PREFIX ?= ../tb/scripts/w4/model_v2_s1.e
# rung 4 S4: the OPT-IN 4-chan stream.  Same .txt / weight images / const
# blob as SEQ_PREFIX — only the matvec encoding differs (row-split MVGOs,
# and the LM head's 122 chunks INTERLEAVED chunk j -> engine j%4).
# Regenerate with the same flow plus SEQ_NCH=4:
#   cd ../ref && SEQ_EMIT=$(PWD)/../tb/scripts/w4/model_v2_s1.e4 \
#     SEQ_PROFILE=epsnorm SEQ_NCH=4 /home/cah/.venv/bin/python \
#     gen_model_script.py <outdir>/model_v2_s1.txt 1 3 --res-scale=8 \
#     --allow-clip
SEQ_PREFIX4 ?= ../tb/scripts/w4/model_v2_s1.e4
SEQ_FLAGS  ?=

.PHONY: smoke_lcyc tok_meter tok_meter4 tok_meter_all regress_hwmap \
        chat chat_verify infer_gate seq_selftest seq_dry_run seq_run \
        seq_dry_run4 seq_run4 chat4 chat4_canned

smoke_lcyc:
	$(PY) tok_meter.py --smoke-only

tok_meter:
	$(PY) tok_meter.py --script $(SCRIPT) --runs $(RUNS) --smoke-lcyc \
	  --out $(EVID)/tokmeter_1chan_$(TAG).json

tok_meter4:
	$(PY) tok_meter.py --script $(SCRIPT) --runs $(RUNS) --four-chan \
	  --out $(EVID)/tokmeter_4chan_$(TAG).json

tok_meter_all: tok_meter tok_meter4

regress_hwmap:
	$(PY) layer_test.py --scripts ../tb/scripts/layer_s1.txt --runs 1

# --- live inference (sw/infer.py) --------------------------------------
# Never programs the board; refuses to DMA unless MAGIC/VERSION/CALIB and
# every IDENT read back exactly.  Add --skip-upload once the model_v2_s1
# images are resident.
chat:
	$(PY) infer.py --ntok $(NTOK) $(INFER_FLAGS)

chat_verify:
	$(PY) infer.py --verify --ntok $(NTOK) $(INFER_FLAGS)

infer_gate:
	$(PY) -u infer.py --verify --check-images --ntok 3 \
	  --prompt "The capital of France" $(INFER_FLAGS)

# --- sequencer runner (sw/seq_run.py) ----------------------------------
# seq_selftest needs no board at all.  seq_dry_run uploads the weights, the
# embedding table, the LDC blob and the RELOCATED record stream and reads
# every byte back — it never touches the 0x6000 SEQ CSR window, so it is
# runnable on the currently resident (sequencer-less) bitstream.
seq_selftest:
	$(PY) -u seq_run.py --selftest

seq_dry_run:
	$(PY) -u seq_run.py --prefix $(SEQ_PREFIX) --dry-run \
	  --out $(EVID)/seq_dry_run_$(TAG).json $(SEQ_FLAGS)

seq_run:
	$(PY) -u seq_run.py --prefix $(SEQ_PREFIX) \
	  --out $(EVID)/seq_run_$(TAG).json $(SEQ_FLAGS)

# --- rung 1b: 4-channel weight-split flow -----------------------------
# --four-chan requires a row-split stream (meta nch>1) from the 4-chan
# emitter (ref/seq_format SEQ_NCH=4); otherwise seq_run.py aborts.  The
# weight images are row-split across DDR chans 0..3 and each quarter is
# readback-verified where its matvec_chan reads it.  seq_dry_run4 touches
# no SEQ CSRs (safe today); seq_run4 needs build_030 resident.
seq_dry_run4:
	$(PY) -u seq_run.py --prefix $(SEQ_PREFIX4) --four-chan --dry-run \
	  --out $(EVID)/seq_dry_run4_$(TAG).json $(SEQ_FLAGS)

seq_run4:
	$(PY) -u seq_run.py --prefix $(SEQ_PREFIX4) --four-chan \
	  --out $(EVID)/seq_run4_$(TAG).json $(SEQ_FLAGS)

# --- rung 4 S4: 4-chan CHAT session ------------------------------------
# --nch 4 selects SEQ_PREFIX4 and the interleaved weight placement.  The
# FIRST run re-uploads every weight image (the residency probe misses on
# channels the 1-chan layout never wrote) — ~900 MiB, minutes; after that
# it is a witness-only probe like any other session.  Flipping back to
# --nch 1 re-uploads again.
chat4:
	$(PY) -u chat_seq.py --nch 4 --ntok $(NTOK) $(INFER_FLAGS)

chat4_canned:
	$(PY) -u chat_seq.py --nch 4 --canned \
	  --out $(EVID)/chat4_canned_$(TAG).json $(INFER_FLAGS)

# ---- chat-seq / serving convenience targets (docs pass, 2026-08-12) ----
chat_seq:        ; $(PY) -u chat_seq.py --ntok $(NTOK) $(CHAT_FLAGS)
serve:           ; $(PY) -u serve.py --port $(SERVE_PORT) $(SERVE_FLAGS)
serve_mock:      ; $(PY) -u serve.py --mock --mock-realtime --port $(SERVE_PORT)
serve_test:      ; $(PY) -u serve.py --selftest
chat_client:     ; $(PY) -u chat_client.py --port $(SERVE_PORT) $(CLIENT_FLAGS)
SERVE_PORT ?= 8137
