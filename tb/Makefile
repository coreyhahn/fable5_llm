# Testbench Makefile — Verilator sims for fable5_llm
# Usage: make tb_csr   (or just `make`)
# Each TB gets its own --Mdir to allow parallel builds.

VERILATOR ?= verilator
JOBS ?= 4
THREADS ?= 4

RTL := ../rtl

.PHONY: all tb_csr lint clean lint_seq_unit seq_unit_vectors tb_seq_build tb_seq tb_seq_guard tb_seq_lat tb_seq_sideband tb_seq_all \
        tb_dn_step_pipe tb_dn_step_pipe_ii tb_layer_env \
        ng_vectors q9_vectors tb_matvec_build tb_matvec_ng tb_streamer_engine

all: tb_csr

tb_csr:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_csr -o tb_csr \
	  --top-module tb_csr \
	  $(RTL)/csr_block.sv tb_csr.sv
	obj_dir_tb_csr/tb_csr --seed 1 +verilator+rand+reset+2
	obj_dir_tb_csr/tb_csr --seed 2 +verilator+rand+reset+2
	obj_dir_tb_csr/tb_csr --seed 3 +verilator+rand+reset+2
	obj_dir_tb_csr/tb_csr --seed 4 +verilator+rand+reset+2

lint:
	$(VERILATOR) --lint-only -Wall --timing $(RTL)/csr_block.sv

clean:
	rm -rf obj_dir_*

VECPY := $(shell command -v python3 >/dev/null && python3 -c "import numpy" 2>/dev/null && echo python3 || echo ../ref/.venv/bin/python)

# SR12 (SEQ_ISA v2.3 B17.2): task-private builds and the RED run.
#   MV1DIR   tb_matvec's obj_dir        CHANDIR  tb_matvec_chan's obj_dir
#   MV_RTL   the dir matvec_engine.sv / matvec_chan.sv are read from (a
#            `git show` extract of a base commit for the RED run)
#   MV_DEFS  e.g. +define+SR12_NO_BANK_PORTS: tb_matvec against an engine
#            with no cfg_xbank / cfg_rbank ports (the pre-SR12 RTL)
# The defaults are the historical names and ../rtl, so nothing else moves.
MV1DIR  ?= obj_dir_tb_matvec
CHANDIR ?= obj_dir_tb_chan
MV_RTL  ?= $(RTL)
MV_DEFS ?=

# SR12: the R2 banks.  The four frozen runs above them are unchanged; the
# bank runs follow, 4 seeds each: every case in XBANK+RBANK (x at word
# 1536 with bank 0 poisoned, rows tagged 2048+r), then +pingpong (case i in
# bank i%2, case i+1's x loaded into the other bank WHILE case i streams),
# whole and in 3-row chunks.  Then the bank-legality self-test: the engine's
# sim-only twin of the validator rule (XBANK ng 49, RBANK nrows 2049) must
# trip with its own message and a non-zero exit.
tb_matvec:
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s1 101 64 1024
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s2 202 32 3584
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s3 303 128 256
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s4 404 16 2048
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(MV_DEFS) \
	  --Mdir $(MV1DIR) -o tb_matvec \
	  --top-module tb_matvec \
	  $(MV_RTL)/matvec_engine.sv tb_matvec.sv
	$(MV1DIR)/tb_matvec --seed 1 +vecdir=vec_s1
	$(MV1DIR)/tb_matvec --seed 2 +vecdir=vec_s2
	$(MV1DIR)/tb_matvec --seed 3 +vecdir=vec_s3
	$(MV1DIR)/tb_matvec --seed 4 +vecdir=vec_s4
	@echo "-- SR12 (B17.2): XBANK+RBANK, pingpong, pingpong chunk=3 x 4 seeds --"
	for s in 1 2 3 4; do \
	  $(MV1DIR)/tb_matvec --seed $$s +verilator+seed+$$s +xbank +rbank \
	    +vecdirs=vec_s1,vec_s2,vec_s3,vec_s4 || exit 1; \
	  $(MV1DIR)/tb_matvec --seed $$s +verilator+seed+$$s +pingpong \
	    +vecdirs=vec_s2,vec_s1,vec_s4,vec_s3 || exit 1; \
	  $(MV1DIR)/tb_matvec --seed $$s +verilator+seed+$$s +pingpong +chunk=3 \
	    +vecdirs=vec_s2,vec_s1,vec_s4,vec_s3 || exit 1; \
	done
	@echo "-- SR12 self-test: the engine's sim-only bank guard MUST trip --"
	@for g in x:XBANK r:RBANK; do \
	  a=$${g%%:*}; m=$${g#*:}; \
	  out=`$(MV1DIR)/tb_matvec +bankguard=$$a 2>&1`; rc=$$?; \
	  case "$$out" in \
	    *"matvec_engine: $$m"*) ;; \
	    *) echo "SELFTEST FAIL: +bankguard=$$a did NOT trip the $$m guard (rc=$$rc)"; \
	       echo "$$out" | tail -3; exit 1;; \
	  esac; \
	  if [ $$rc -eq 0 ]; then \
	    echo "SELFTEST FAIL: $$m guard message seen but the run exited 0"; exit 1; \
	  fi; \
	  echo "OK: +bankguard=$$a tripped the $$m guard (rc=$$rc)"; \
	done
	@echo "TB_MATVEC OK: 4 frozen seeds + SR12 banks (XBANK+RBANK, pingpong, chunked pingpong) x 4 seeds + the bank-guard self-test"

lint_matvec:
	$(VERILATOR) --lint-only -Wall --timing $(RTL)/matvec_engine.sv

# ======================================================================
# Parameterized W4 shape sweeps — matvec_engine at G = 128
# ======================================================================
# Vectors come from tb/scripts/gen_matvec_v2_vectors.py (ref/w4a8_ref.py is
# still the numerics; ref/gen_matvec_vectors.py stays frozen at its four
# stage-2 shapes).  Shape spec: name:NROWS:K:seedbase — one dir per (shape,
# seed) as vecv2/<name><seed>_g128.
#
# G3.3 RETIRED the g64 and W8 halves of this sweep with the modes they
# drove (spec 5.1 S5 / 5.2 S6).  What went, and why, is recorded in
# evidence/qwen9b/g3/G3_3_MATVEC.md 2:
#   * V2SHAPES a..f and `v2_vectors` — the (g128, g64) TWIN family whose
#     only consumer was tb_matvec_g64 / tb_matvec_chan_g64.  Its distinct
#     W4 coverage (NG = 32, the exact one-scale-beat boundary) is carried
#     forward by the 9B shape q1 below; NG 8/28/16 are the frozen
#     tb_matvec shapes and NG 1/48 are n1/n5.
#   * W8SHAPES w1..w4, the DIRECTED w5 max-magnitude case and
#     `w8_vectors` — vectors for an engine mode this bitstream no longer
#     has.
#
# RUNG 4 S2 — the SMALL-NG directed set: NG = 1,2,3,4 is the regime where a
# row is shorter than the retire pipeline, so the scale-beat stall guard (a
# sanctioned 1-2 cyc/row) is the only thing that can show up.  Enough rows in
# each case that the steady state, not the first/last row, dominates.
# n5/n6 are the OTHER end of the old NG range (R-b, MAX_NG 32 -> 48): n5 is
# the K=6144 ceiling (NG=48) and n6 is a mid point above the old 32-group
# wall (NG=36).  Same grammar, same gates.
NGSHAPES := n1:23:128:6100 n2:24:256:6200 n3:17:384:6300 n4:31:512:6400 \
            n5:9:6144:6500 n6:21:4608:6600
V2SEEDS  := 1 2 3 4

# G3.3 — THE 9B ROW GEOMETRY (spec 4.5 W5).  K in {4096, 8192, 12288} is
# every row shape Qwen3.5-9B asks a matvec for, so ng in {32, 64, 96} and
# the scale-beat count in {1, 2, 3}:
#
#   q1  K=4096  NG=32  33 beats/row  1 scale beat  — the EXACT ceil(NG/32)
#                                    boundary (32 scales fill one beat with
#                                    no tail), and the NG the retired
#                                    V2SHAPES `c` used to cover
#   q2  K=8192  NG=64  66 beats/row  2 scale beats
#   q3  K=12288 NG=96  99 beats/row  3 scale beats — `down_proj` at
#                                    K = FFN, THE row that moves MAX_NG
#                                    48 -> 96, the full 3072-word XWIN and
#                                    the first shape ever to need a THIRD
#                                    scale beat at the g128 cadence
# Odd nrows throughout so a chunked run always has an uneven last chunk.
Q9SHAPES := q1:13:4096:9100 q2:7:8192:9200 q3:5:12288:9300

ng_vectors:
	@for sp in $(NGSHAPES); do \
	  nm=$${sp%%:*}; r=$${sp#*:}; n=$${r%%:*}; r=$${r#*:}; \
	  k=$${r%%:*}; sb=$${r#*:}; \
	  for s in $(V2SEEDS); do \
	    $(VECPY) scripts/gen_matvec_v2_vectors.py \
	      vecv2/$${nm}$${s}_g128 $$(($$sb + $$s)) $$n $$k || exit 1; \
	  done; \
	done

q9_vectors:
	@for sp in $(Q9SHAPES); do \
	  nm=$${sp%%:*}; r=$${sp#*:}; n=$${r%%:*}; r=$${r#*:}; \
	  k=$${r%%:*}; sb=$${r#*:}; \
	  for s in $(V2SEEDS); do \
	    $(VECPY) scripts/gen_matvec_v2_vectors.py \
	      vecv2/$${nm}$${s}_g128 $$(($$sb + $$s)) $$n $$k || exit 1; \
	  done; \
	done

# Own --Mdir / binary name so concurrent workstreams never race on NFS:
#   make tb_matvec_ng MVDIR=obj_dir_tb_matvec_d MVBIN=tb_matvec_d
MVDIR ?= obj_dir_tb_matvec
MVBIN ?= tb_matvec

tb_matvec_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(MV_DEFS) \
	  --Mdir $(MVDIR) -o $(MVBIN) \
	  --top-module tb_matvec \
	  $(MV_RTL)/matvec_engine.sv tb_matvec.sv

# RUNG 4 gate bounds (overridable so the rung-3 baseline can be re-measured
# on the same TB:  make tb_matvec_ng MVMAXSTALL=9 MVNGFLOOR=99).
#   MVMAXSTALL  stall cycles/row allowed when NG > 4.  ZERO: agent A's
#               retire pipeline has no exposed bubble at all on any shape
#               with NG >= 5, and every production shape is NG in {8,16,28}
#               (K = 1024/2048/3584).  Measured on all 4 seeds.
#   MVNGFLOOR   row-period floor allowed when NG <= 4.  The S2
#               single-scale-bank guard floors the period at 6 cycles, so
#               the sanctioned bubble is exactly 6-BPR = 5-NG (4/3/2/1 for
#               NG=1/2/3/4) — matvec_engine.sv's own law, checked per shape
#               rather than as a flat count, so NG=4 is still held to 1.
MVMAXSTALL ?= 0
MVNGFLOOR  ?= 6

# RUNG 4 S2 directed small-NG gate: NG = 1,2,3,4, correctness with random
# gaps + backpressure first, then the same shapes with no gaps so the
# scale-beat stall guard is measured in isolation.  Chunked-row runs too: at
# NG<=4 a chunk boundary lands every few beats, which is where a retire
# pipeline that mis-tags `first`/`last` breaks.
#
# R-b extends the same gate to the LARGE-NG end (n5 = NG 48, n6 = NG 36):
# above NG 32 a row grows a SECOND scale beat for the first time, so this is
# where the generalized scale-beat count is proven — including under
# chunk=1/chunk=3 row splitting.
#
# G3.3: the +pairs run is RETIRED with the g64 mode it compared against (it
# asserted a (g128, g64) shape pair cost no more than the extra scale
# beats).  The +nogap run keeps +maxstall/+ngfloor, which are the bounds
# that were doing the work on the g128 half.
tb_matvec_ng: ng_vectors q9_vectors tb_matvec_build
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g128,vecv2/n3$${s}_g128,vecv2/n4$${s}_g128,vecv2/n5$${s}_g128,vecv2/n6$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=1 \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g128,vecv2/n3$${s}_g128,vecv2/n4$${s}_g128,vecv2/n5$${s}_g128,vecv2/n6$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=3 \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g128,vecv2/n3$${s}_g128,vecv2/n4$${s}_g128,vecv2/n5$${s}_g128,vecv2/n6$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +nogap \
	    +maxstall=$(MVMAXSTALL) +ngfloor=$(MVNGFLOOR) \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g128,vecv2/n3$${s}_g128,vecv2/n4$${s}_g128,vecv2/n5$${s}_g128,vecv2/n6$${s}_g128 || exit 1; \
	done
	@echo "-- the 9B row geometry: NG 32/64/96 (K 4096/8192/12288) --"
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/q1$${s}_g128,vecv2/q2$${s}_g128,vecv2/q3$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=2 \
	    +vecdirs=vecv2/q3$${s}_g128,vecv2/q1$${s}_g128,vecv2/q2$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +nogap \
	    +maxstall=$(MVMAXSTALL) +ngfloor=$(MVNGFLOOR) \
	    +vecdirs=vecv2/q1$${s}_g128,vecv2/q2$${s}_g128,vecv2/q3$${s}_g128 || exit 1; \
	done
	@echo "-- MIXED, one engine instance, no reset: 9B and small-NG shapes interleaved --"
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/q3$${s}_g128,vecv2/n1$${s}_g128,vecv2/q1$${s}_g128,vecv2/n5$${s}_g128,vecv2/q2$${s}_g128,vecv2/q3$${s}_g128 || exit 1; \
	done
	@echo "-- SR12 (B17.2): XBANK+RBANK over NG 1..4/36/48 (n5 = NG 48 ends at x line 95) --"
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +verilator+seed+$$s +xbank +rbank \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g128,vecv2/n3$${s}_g128,vecv2/n4$${s}_g128,vecv2/n5$${s}_g128,vecv2/n6$${s}_g128 || exit 1; \
	done
	@echo "-- self-test: matvec_engine's cfg_ng > MAX_NG envelope guard MUST trip --"
	@# a non-zero exit alone is NOT proof: any other $$fatal (e.g. a missing
	@# +vecdir) also exits non-zero.  Require the guard's OWN message AND a
	@# non-zero exit.
	@out=`$(MVDIR)/$(MVBIN) +guardtest 2>&1`; rc=$$?; \
	 case "$$out" in \
	   *"cfg_ng 97 unsupported"*) ;; \
	   *) echo "SELFTEST FAIL: cfg_ng=97 did NOT trip matvec_engine's guard (rc=$$rc)"; \
	      echo "$$out" | tail -3; exit 1;; \
	 esac; \
	 if [ $$rc -eq 0 ]; then \
	   echo "SELFTEST FAIL: guard message seen but the run exited 0"; exit 1; \
	 fi
	@echo "TB_MATVEC_NG OK: NG 1..4 + 36 + 48 + the 9B 32/64/96 x 4 seeds — random, chunk=1/2/3, nogap, mixed-shape, + the cfg_ng=97 envelope self-test"

tb_streamer_engine:
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s1 101 64 1024
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s2 202 32 3584
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s3 303 128 256
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s4 404 16 2048
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_se -o tb_se \
	  --top-module tb_streamer_engine \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv tb_streamer_engine.sv
	obj_dir_tb_se/tb_se --seed 1 +vecdir=vec_s1
	obj_dir_tb_se/tb_se --seed 2 +vecdir=vec_s2
	obj_dir_tb_se/tb_se --seed 3 +vecdir=vec_s3
	obj_dir_tb_se/tb_se --seed 4 +vecdir=vec_s4

XLIB := -f /home/cah/r2d2/code/verilator_lib/verilator_lib.f /home/cah/r2d2/code/verilator_lib/verilator_xilinx.vlt

tb_matvec_chan:
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s1 101 64 1024
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s2 202 32 3584
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s3 303 128 256
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s4 404 16 2048
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir $(CHANDIR) -o tb_chan \
	  --top-module tb_matvec_chan \
	  $(MV_RTL)/matvec_engine.sv ../rtl/ddr_rd_streamer.sv $(MV_RTL)/matvec_chan.sv tb_matvec_chan.sv
	$(CHANDIR)/tb_chan --seed 1 +vecdir=vec_s1
	$(CHANDIR)/tb_chan --seed 2 +vecdir=vec_s2
	$(CHANDIR)/tb_chan --seed 3 +vecdir=vec_s3
	$(CHANDIR)/tb_chan --seed 4 +vecdir=vec_s4
	@echo "-- self-test: sw/hwmap.shape_word, BOTH layouts + the VERSION gate --"
	@# G3.3 fix round 1: this invocation used to hang off tb_matvec_w8, which
	@# G3.3 retired -- the selftest's own docstring named a gate that no
	@# longer ran it.  tb_matvec_chan is the right home: it is the target
	@# that drives a SHAPE word through the real CSR.
	$(VECPY) ../sw/hwmap.py
	@echo "-- G3.3: the 9B row geometry through the FULL CSR/DMA chain --"
	@# +shapeback adds a SHAPE read-back, which shifts the AXI model's
	@# $$urandom stream -- so it is passed ONLY here, and the four frozen
	@# runs above stay cycle-reproducible against the stage-2 evidence.
	@# q3 is K = 12288, i.e. 3072 XWIN words: the full widened aperture
	@# and the 12-bit XPTR, pushed one AXI-Lite word at a time.
	$(MAKE) q9_vectors
	for s in $(V2SEEDS); do \
	  for nm in q1 q2 q3; do \
	    $(CHANDIR)/tb_chan --seed $$s +shapeback +vecdir=vecv2/$${nm}$${s}_g128 || exit 1; \
	  done; \
	done
	@echo "-- SR12 (B17.2): the R2 banks through the real CSR, 4 seeds --"
	@# +xbank +rbank: SHAPE bits 29/30 (+shapeback: still read back 0), x at
	@# XPTR 1536 over a poisoned bank 0, rows read from RES_PTR 2048; q1 is
	@# the 9B K = 4096 row in a bank.  +overlap: A in bank 0 and, WHILE it
	@# streams, B's x into XWIN bank 1; then B on XBANK|RBANK -- B's rows at
	@# 2048 and A's at 0 both bit-exact.  SR12 fix 1: +rbank alone at q2/q3
	@# (ng 64/96, K = 8192/12288 -- rows XBANK cannot take) lands at 2048.
	for s in $(V2SEEDS); do \
	  n=$$(( $$s % 4 + 1 )); \
	  $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +xbank +rbank +shapeback +vecdir=vec_s$$s || exit 1; \
	  $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +xbank +rbank +shapeback +vecdir=vecv2/q1$${s}_g128 || exit 1; \
	  $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +overlap=vec_s$$n +vecdir=vec_s$$s || exit 1; \
	  for nm in q2 q3; do \
	    $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +rbank +shapeback +vecdir=vecv2/$${nm}$${s}_g128 || exit 1; \
	  done; \
	done
	for s in $(V2SEEDS); do n=$$(( $$s % 4 + 1 )); $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +push +vecdir=vec_s$$s || exit 1; $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +push +xbank +rbank +pushstall=40 +vecdir=vec_s$$s || exit 1; $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +push +pushcoll +pushburst +pushstall=100 +vecdir=vec_s$$n || exit 1; $(CHANDIR)/tb_chan --seed $$s +verilator+seed+$$s +pushthenburst +xbank +vecdir=vec_s$$s || exit 1; done; echo "TB_MATVEC_CHAN OK: the 4 frozen stage-2 shapes + the 9B NG 32/64/96 x 4 seeds with the SHAPE round-trip + SR12 banks (XBANK+RBANK, q1 in a bank, bank-1 load during a bank-0 run, RBANK at q2/q3) x 4 seeds + R3-8 the x-push leg (bank 0 / bank 1, ui stalled until room drops, the forced AXI-Lite collision one slot from full, burst contention, broadcast-then-burst) x 4 seeds"

# The same full CSR/DMA chain as tb_matvec_chan, built once so several
# vector families can be run through it.
tb_matvec_chan_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir $(CHANDIR) -o tb_chan \
	  --top-module tb_matvec_chan \
	  $(MV_RTL)/matvec_engine.sv ../rtl/ddr_rd_streamer.sv $(MV_RTL)/matvec_chan.sv tb_matvec_chan.sv

tb_fx_rsqrt:
	$(VECPY) ../ref/gen_rsqrt_cases.py rsqrt_cases_s1.txt 1
	$(VECPY) ../ref/gen_rsqrt_cases.py rsqrt_cases_s2.txt 2
	$(VECPY) ../ref/gen_rsqrt_cases.py rsqrt_cases_s3.txt 3
	$(VECPY) ../ref/gen_rsqrt_cases.py rsqrt_cases_s4.txt 4
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_rsqrt -o tb_rsqrt \
	  --top-module tb_fx_rsqrt \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_rsqrt.sv tb_fx_rsqrt.sv
	obj_dir_tb_rsqrt/tb_rsqrt --seed 1 +cases=rsqrt_cases_s1.txt
	obj_dir_tb_rsqrt/tb_rsqrt --seed 2 +cases=rsqrt_cases_s2.txt
	obj_dir_tb_rsqrt/tb_rsqrt --seed 3 +cases=rsqrt_cases_s3.txt
	obj_dir_tb_rsqrt/tb_rsqrt --seed 4 +cases=rsqrt_cases_s4.txt

# ======================================================================
# sequencer rung-1 compute ops (docs/SEQ_ISA.md): vec_alu op 12 DYNQ16,
# vec_alu op 8 probe, vecnorm EPS-NORM.  Goldens come from
# tb/scripts/gen_seq_c_vectors.py (ref/layer_fixed.py is the numerics) and
# land in their OWN tree — tb/vectors/ stays frozen, so every pre-existing
# unit case replays byte-identical inputs.
# NOTE the "_c_": tb/scripts/gen_seq_vectors.py (DELETED at b2f1223) and
# gen_seq_unit_vectors.py belong to the SEQ-unit workstream (tb_seq_unit
# record streams) and are unrelated to these compute-op goldens.
# ======================================================================
SEQSEEDS := 1 2 3 4

seq_c_vectors:
	@for s in $(SEQSEEDS); do \
	  $(VECPY) scripts/gen_seq_c_vectors.py vecseq/s$$s $$s || exit 1; \
	done

tb_vecnorm: seq_c_vectors
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_vecnorm -o tb_vecnorm \
	  --top-module tb_vecnorm \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_rsqrt.sv $(RTL)/vecnorm_unit.sv tb_vecnorm.sv
	obj_dir_tb_vecnorm/tb_vecnorm --seed 1 +vecdir=vectors/s1 +seqdir=vecseq/s1
	obj_dir_tb_vecnorm/tb_vecnorm --seed 2 +vecdir=vectors/s2 +seqdir=vecseq/s2
	obj_dir_tb_vecnorm/tb_vecnorm --seed 3 +vecdir=vectors/s3 +seqdir=vecseq/s3
	obj_dir_tb_vecnorm/tb_vecnorm --seed 4 +vecdir=vectors/s4 +seqdir=vecseq/s4
	@echo "-- self-test: vecnorm_unit's cfg_nlog2 >= 13 envelope guard MUST trip --"
	@# a non-zero exit alone is NOT proof: any other $$fatal (e.g. a missing
	@# +vecdir) also exits non-zero.  Require the guard's OWN message AND a
	@# non-zero exit.
	@out=`obj_dir_tb_vecnorm/tb_vecnorm +guardtest 2>&1`; rc=$$?; \
	 case "$$out" in \
	   *"cfg_nlog2 13 unsupported"*) ;; \
	   *) echo "SELFTEST FAIL: cfg_nlog2=13 did NOT trip vecnorm_unit's guard (rc=$$rc)"; \
	      echo "$$out" | tail -3; exit 1;; \
	 esac; \
	 if [ $$rc -eq 0 ]; then \
	   echo "SELFTEST FAIL: guard message seen but the run exited 0"; exit 1; \
	 fi
	@echo "TB_VECNORM OK: 4 seeds (rmsnorm 1024, l2norm 128, EPS-NORM, N=2048 nlog2=11 x2, N=4096 nlog2=12 x2) + envelope self-test"

tb_rope:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_rope -o tb_rope \
	  --top-module tb_rope \
	  $(RTL)/fx_pkg.sv $(RTL)/rope_unit.sv tb_rope.sv
	obj_dir_tb_rope/tb_rope +vecdir=vectors/s1
	obj_dir_tb_rope/tb_rope +vecdir=vectors/s2
	obj_dir_tb_rope/tb_rope +vecdir=vectors/s3
	obj_dir_tb_rope/tb_rope +vecdir=vectors/s4

tb_fx_silu:
	$(VECPY) ../ref/gen_silu_cases.py silu_cases_s1.txt 1
	$(VECPY) ../ref/gen_silu_cases.py silu_cases_s2.txt 2
	$(VECPY) ../ref/gen_silu_cases.py silu_cases_s3.txt 3
	$(VECPY) ../ref/gen_silu_cases.py silu_cases_s4.txt 4
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_silu -o tb_silu \
	  --top-module tb_fx_silu \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_silu.sv tb_fx_silu.sv
	obj_dir_tb_silu/tb_silu +cases=silu_cases_s1.txt
	obj_dir_tb_silu/tb_silu +cases=silu_cases_s2.txt
	obj_dir_tb_silu/tb_silu +cases=silu_cases_s3.txt
	obj_dir_tb_silu/tb_silu +cases=silu_cases_s4.txt

tb_conv4_silu:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_conv -o tb_conv \
	  --top-module tb_conv4_silu \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_silu.sv $(RTL)/conv4_silu.sv tb_conv4_silu.sv
	obj_dir_tb_conv/tb_conv +vecdir=vectors/s1
	obj_dir_tb_conv/tb_conv +vecdir=vectors/s2
	obj_dir_tb_conv/tb_conv +vecdir=vectors/s3
	obj_dir_tb_conv/tb_conv +vecdir=vectors/s4

tb_dn_step:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_dn -o tb_dn \
	  --top-module tb_dn_step \
	  $(RTL)/fx_pkg.sv $(RTL)/dn_step.sv tb_dn_step.sv
	obj_dir_tb_dn/tb_dn +vecdir=vectors/s1
	obj_dir_tb_dn/tb_dn +vecdir=vectors/s2
	obj_dir_tb_dn/tb_dn +vecdir=vectors/s3
	obj_dir_tb_dn/tb_dn +vecdir=vectors/s4

# G3.4 Step 1' (spec 4.1 W1'(a)) — the SAME four vector cases replayed at
# the SHIPPED read latency, RLAT = 2 + 2*DN_PIPE = 6, with option (i)'s
# pass-2 wait state.  Bit-exactness against the same goldens is what proves
# the address lead is right; DN_CYCLES is the price, measured not modelled.
# Own --Mdir: obj_dir_tb_dn is the RLAT=2 control and the two must not race.
tb_dn_step_pipe:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_dn6 -o tb_dn6 \
	  -GRLAT=6 -GP2W=1 \
	  --top-module tb_dn_step \
	  $(RTL)/fx_pkg.sv $(RTL)/dn_step.sv tb_dn_step.sv
	obj_dir_tb_dn6/tb_dn6 +vecdir=vectors/s1
	obj_dir_tb_dn6/tb_dn6 +vecdir=vectors/s2
	obj_dir_tb_dn6/tb_dn6 +vecdir=vectors/s3
	obj_dir_tb_dn6/tb_dn6 +vecdir=vectors/s4

# The SAME latency with NO wait state: option (ii), two reads outstanding.
# NOT SHIPPED — this target exists only so the Step 1' decision can be
# priced against a measurement instead of Track P's bound.  Read
# evidence/qwen9b/g3/G3_4_LAYER.md section 4 before acting on it.
tb_dn_step_pipe_ii:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_dn6b -o tb_dn6b \
	  -GRLAT=6 -GP2W=0 \
	  --top-module tb_dn_step \
	  $(RTL)/fx_pkg.sv $(RTL)/dn_step.sv tb_dn_step.sv
	obj_dir_tb_dn6b/tb_dn6b +vecdir=vectors/s1
	obj_dir_tb_dn6b/tb_dn6b +vecdir=vectors/s2
	obj_dir_tb_dn6b/tb_dn6b +vecdir=vectors/s3
	obj_dir_tb_dn6b/tb_dn6b +vecdir=vectors/s4

tb_attn_core:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_attn -o tb_attn \
	  --top-module tb_attn_core \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_recip.sv $(RTL)/attn_core.sv tb_attn_core.sv
	obj_dir_tb_attn/tb_attn +vecdir=vectors/s1
	obj_dir_tb_attn/tb_attn +vecdir=vectors/s2
	obj_dir_tb_attn/tb_attn +vecdir=vectors/s3
	obj_dir_tb_attn/tb_attn +vecdir=vectors/s4

tb_gate_unit:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_gate -o tb_gate \
	  --top-module tb_gate_unit \
	  $(RTL)/fx_pkg.sv $(RTL)/gate_unit.sv tb_gate_unit.sv
	obj_dir_tb_gate/tb_gate +vecdir=vectors/s1
	obj_dir_tb_gate/tb_gate +vecdir=vectors/s2
	obj_dir_tb_gate/tb_gate +vecdir=vectors/s3
	obj_dir_tb_gate/tb_gate +vecdir=vectors/s4

tb_vec_alu: seq_c_vectors
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_alu -o tb_alu \
	  --top-module tb_vec_alu \
	  $(RTL)/fx_pkg.sv $(RTL)/vec_alu.sv tb_vec_alu.sv
	obj_dir_tb_alu/tb_alu --seed 1 +vecdir=vectors/s1 +seqdir=vecseq/s1
	obj_dir_tb_alu/tb_alu --seed 2 +vecdir=vectors/s2 +seqdir=vecseq/s2
	obj_dir_tb_alu/tb_alu --seed 3 +vecdir=vectors/s3 +seqdir=vecseq/s3
	obj_dir_tb_alu/tb_alu --seed 4 +vecdir=vectors/s4 +seqdir=vecseq/s4
	@echo "-- RUNG4 S5: the >2^18 element chain (am_g wrap) on one seed --"
	obj_dir_tb_alu/tb_alu --seed 1 +vecdir=vectors/s1 +seqdir=vecseq/s1 +amaxlong

# layer-level integration for the rung-1 ops: DYNQ16 -> XRF -> EPS-NORM
# and the op-8 probe -> XRF[2], replayed by the UNMODIFIED tb_layer_chan
# (W/C/R records only).  Its own --Mdir so it never races the frozen
# tb_layer_chan / tb_token / tb_chain runs.
seq_layer_scripts:
	@for s in $(SEQSEEDS); do \
	  $(VECPY) scripts/gen_seq_layer_script.py scripts/seqlayer_s$$s.txt $$s \
	    || exit 1; \
	done

# ======================================================================
# G3.4 (spec 4.1 W1', 4.6 W6, 5.4 S9) — the DIRECTED banking + envelope
# gates on the REAL layer_chan.  No reference model and no golden file:
# both modes assert that stores which MUST be independent behave
# identically from identical inputs, and that every envelope check
# refuses.  Own --Mdir so they never race obj_dir_tb_layer.
# tb_layer_dnbank is RETIRED by S3 (SEQ_ISA v2.1 B15.2, spec
# 2026-09-04-qwen35-9b-state-spill-design.md 3).  It proved that the 24 DN
# banks, the 8 KV banks and the 24 conv banks were INDEPENDENT and that
# every one of them really stored; the layer now holds TWO CACHE SLOTS per
# kind and the layer identity lives in the SLD/SST commands, so there is no
# bank array left to prove independent.  The property moved to the DDR
# image, where ref/seq_model.StateRegion and the SEQ gate's STATE
# comparison hold it, and to tb_layer_sdma (S2), which round-trips a block
# of every kind through the real DMA.  `run_dnbank` went with it
# (tb/tb_layer_chan.sv).

# Own --Mdir, never shared with the tb_layer_chan family (obj_dir_tb_layer*):
# two targets that build the same top module must not write one directory --
# the collision hazard the G3.4 brief called out.
tb_layer_env:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_layerenv -o tb_layerenv \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) seq_mem_file.sv tb_layer_chan.sv
	@for s in 1 2 3 4; do \
	  obj_dir_tb_layerenv/tb_layerenv +envtest --seed $$s \
	    +watchdog_ms=4000 || exit 1; \
	done

# ======================================================================
# S2 (spec 2026-09-04 state-spill §3-§5, SEQ_ISA v2.1 B15) — the layer's
# STATE DMA gate.  tb_layer_sdma drives layer_chan directly over AXI-Lite
# against tb/axi_ram_bfm.sv (a RAM-backed 512-bit AXI4 slave), so it needs
# NO generated command stream: the emitter learns the SLD/SST schedule at
# S3, where tb_layer_chan / tb_layer_env are re-run.  Own --Mdir, never
# shared with the tb_layer_chan family (obj_dir_tb_layer*).
#
#   make tb_layer_sdma            the gate, SDMA_SEEDS seeds
#   make tb_layer_sdma_nofence    the F1 RED CONTROL: the same TB built with
#                                 -GSDMA_NOFENCE=1 (the fence bypassed) MUST
#                                 FAIL case 4's golden compare.  The target
#                                 succeeds only when the run FAILS.
# ======================================================================
.PHONY: tb_layer_sdma tb_layer_sdma_nofence lint_state_dma lint_layer_chan

SDMA_SEEDS ?= 1 2 3 4

tb_layer_sdma:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layersdma -o tb_layersdma \
	  --top-module tb_layer_sdma \
	  $(LAYER_RTL) axi_ram_bfm.sv tb_layer_sdma.sv
	@for s in $(SDMA_SEEDS); do \
	  echo "-- tb_layer_sdma seed $$s --"; \
	  obj_dir_tb_layersdma/tb_layersdma +vecdir=vectors/s$$s +seed=$$s \
	    || exit 1; \
	done

tb_layer_sdma_nofence:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  -GSDMA_NOFENCE=1 \
	  --Mdir obj_dir_tb_layersdma_nf -o tb_layersdma_nf \
	  --top-module tb_layer_sdma \
	  $(LAYER_RTL) axi_ram_bfm.sv tb_layer_sdma.sv
	@for s in $(SDMA_SEEDS); do \
	  echo "-- tb_layer_sdma_nofence seed $$s (MUST FAIL) --"; \
	  if obj_dir_tb_layersdma_nf/tb_layersdma_nf +vecdir=vectors/s$$s \
	       +seed=$$s; then \
	    echo "CONTROL FAILED: -GSDMA_NOFENCE=1 PASSED at seed $$s"; exit 1; \
	  else \
	    echo "OK: the F1 bypass reads stale state and FAILS at seed $$s"; \
	  fi; \
	done

lint_state_dma:
	$(VERILATOR) --lint-only -Wall --timing $(RTL)/state_dma.sv \
	  --top-module state_dma

# The `lint` target at the top of this file lints rtl/csr_block.sv ONLY.
# This is the layer's own -Wall lint, over the whole LAYER_RTL list, plus
# the two S2 testbench sources.
lint_layer_chan:
	$(VERILATOR) --lint-only -Wall --timing $(LAYER_RTL) \
	  --top-module layer_chan
	$(VERILATOR) --lint-only -Wall --timing axi_ram_bfm.sv \
	  --top-module axi_ram_bfm

tb_seq_layer: seq_layer_scripts
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_seqlayer -o tb_seqlayer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv
	obj_dir_tb_seqlayer/tb_seqlayer +script=scripts/seqlayer_s1.txt
	obj_dir_tb_seqlayer/tb_seqlayer +script=scripts/seqlayer_s2.txt
	obj_dir_tb_seqlayer/tb_seqlayer +script=scripts/seqlayer_s3.txt
	obj_dir_tb_seqlayer/tb_seqlayer +script=scripts/seqlayer_s4.txt

# ======================================================================
# rung 3 (docs/RUNG3_SPEC.md S6) — the layer_chan burst window (agent C).
# Standalone unit gate on the REAL layer_chan: burst<->SWIN equality both
# directions, SLVERR-while-busy against a LIVE vec_alu command, the
# SWIN/burst write collision, and zero-strobe beats.  Own --Mdir so it
# never races tb_layer_chan (obj_dir_tb_layer).
# ======================================================================
.PHONY: lint_layershim_c tb_layershim_c

LAYSHIM_SEEDS := 1 2 3 4

lint_layershim_c:
	$(VERILATOR) --lint-only -Wall --timing $(LAYER_RTL) \
	  --top-module layer_chan
	$(VERILATOR) --lint-only -Wall --timing $(LAYER_RTL) tb_layershim_c.sv \
	  --top-module tb_layershim_c

tb_layershim_c:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layershim_c -o tb_layershim_c \
	  --top-module tb_layershim_c \
	  $(LAYER_RTL) tb_layershim_c.sv
	@for s in $(LAYSHIM_SEEDS); do \
	  obj_dir_tb_layershim_c/tb_layershim_c +seed=$$s \
	    +verilator+rand+reset+2 || exit 1; \
	done

# ======================================================================
# RUNG 4 / S5 — TOPK-32 unit gate (docs/RUNG4_SPEC.md, agent D namespace).
#
# The DUT is the REAL layer_chan: the TOPK block is fed by vec_alu's 51-bit
# bundle and read only through the layer CSR map, so the only honest
# stimulus is a real ALU AMAX32 command over the real scratchpad.  Golden =
# tb/scripts/gen_topk_cases.py (numpy).  ~550k elements per seed, the
# heaviest single case being 270,336 elements (> 2^18, the am_g wrap).
#
#   make topk_cases          goldens for 4 seeds -> tb/vectopk/s<n>/
#   make tb_topk             build + 4 seeds + 5 comparator self-tests
#   make tb_topk TOPK_RTL_DIR=<dir>   build against an alternative RTL tree
# ======================================================================
.PHONY: topk_cases tb_topk_build tb_topk lint_topk

TOPK_SEEDS   ?= 1 2 3 4
TOPK_RTL_DIR ?= $(RTL)
TOPK_RTL     := $(TOPK_RTL_DIR)/fx_pkg.sv $(TOPK_RTL_DIR)/fx_rsqrt.sv \
  $(TOPK_RTL_DIR)/fx_recip.sv $(TOPK_RTL_DIR)/fx_silu.sv \
  $(TOPK_RTL_DIR)/vecnorm_unit.sv $(TOPK_RTL_DIR)/rope_unit.sv \
  $(TOPK_RTL_DIR)/conv4_silu.sv $(TOPK_RTL_DIR)/dn_step.sv \
  $(TOPK_RTL_DIR)/attn_core.sv $(TOPK_RTL_DIR)/gate_unit.sv \
  $(TOPK_RTL_DIR)/vec_alu.sv $(TOPK_RTL_DIR)/layer_chan.sv
TOPK_MDIR    ?= obj_dir_tb_topk

topk_cases:
	@for s in $(TOPK_SEEDS); do \
	  $(VECPY) scripts/gen_topk_cases.py vectopk/s$$s $$s || exit 1; done

lint_topk:
	$(VERILATOR) --lint-only -Wall --timing $(TOPK_RTL) tb_topk.sv \
	  --top-module tb_topk

tb_topk_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir $(TOPK_MDIR) -o tb_topk \
	  --top-module tb_topk \
	  $(TOPK_RTL) tb_topk.sv

tb_topk: topk_cases tb_topk_build
	@for s in $(TOPK_SEEDS); do \
	  $(TOPK_MDIR)/tb_topk +cases=vectopk/s$$s/topk_cases.txt || exit 1; \
	done
	@echo "-- comparator self-test: every check MUST trip under sabotage --"
	@for k in 1 2 3 4 5; do \
	  if $(TOPK_MDIR)/tb_topk +cases=vectopk/s1/topk_cases.txt \
	       +sabotage=$$k +quiet >/dev/null 2>&1; then \
	    echo "SELFTEST FAIL: +sabotage=$$k did NOT trip the comparator"; \
	    exit 1; \
	  fi; \
	done
	@echo "TB_TOPK OK: 4 seeds + 5 comparator self-tests"

lint_seq:
	$(VERILATOR) --lint-only -Wall --timing \
	  $(RTL)/fx_pkg.sv $(RTL)/vec_alu.sv --top-module vec_alu
	$(VERILATOR) --lint-only -Wall --timing \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_rsqrt.sv $(RTL)/vecnorm_unit.sv \
	  --top-module vecnorm_unit
	$(VERILATOR) --lint-only -Wall --timing $(LAYER_RTL) \
	  --top-module layer_chan

# integration: full layer command-script replay vs layer_decode_fx golden.
LAYER_RTL = $(RTL)/fx_pkg.sv $(RTL)/fx_rsqrt.sv $(RTL)/fx_recip.sv \
  $(RTL)/fx_silu.sv $(RTL)/vecnorm_unit.sv $(RTL)/rope_unit.sv \
  $(RTL)/conv4_silu.sv $(RTL)/dn_step.sv $(RTL)/attn_core.sv \
  $(RTL)/gate_unit.sv $(RTL)/vec_alu.sv $(RTL)/state_dma.sv \
  $(RTL)/layer_chan.sv

# Python used by the script generators, evaluated AFTER `cd ../ref`:
#   darthplagueis  .venv/bin/python           (default)
#   snoke          /home/cah/.venv/bin/python (ref/.venv's interpreter
#                  lives under ~/.local/share/uv, which is not NFS-shared)
GENPY ?= .venv/bin/python

# ---- FROZEN back-compat sets ------------------------------------------
# tb/scripts/layer_s* and token_s* are COMMITTED stage-3/4 evidence built by
# the pre-Phase-1A generator.  The generator has since moved to the Phase-1A
# datapath, so `layer_scripts` / `token_scripts` would NOT reproduce the
# committed bytes.  The recipes below are deliberately fenced off.
#
# G3.1 (2026-09-01) RETIRED THEM AS REPLAYABLE STREAMS, and this is where
# the byte-lock is spent (spec 8 G3).  Their C records carry SEQ_ISA v1.7
# (in fact pre-R-b) ARG words: `C 5 4000000 ...` means nch = 2048 under
# v1.7's `nch = arg0[27:15]` and nch = 1024 under v2.0's `arg0[29:16]`, so
# the RTL now decodes them as DIFFERENT COMMANDS.  The old note here said
# they "must keep passing UNMODIFIED (nothing in the RTL changed)"; the RTL
# ISA has now changed, so that sentence is false and the files stay as the
# RECORD of what stage 3/4 ran, not as a live gate.
#
#   * `tb_layer_chan` is re-based onto `layerv2_s*.txt`, GENERATED by the
#     current gen_layer_script.py (random weights, no checkpoint, ~10 s a
#     seed) and gitignored — see `layer_v2_scripts` below.  It is the only
#     TB that drives CONV/CONVW/KVAP/ATTN/ROPE against the real layer_chan,
#     which is exactly what G3.1's widened channel fields need.
#   * `tb_token`, `tb_chain`, `tb_model_*` and `tb_seq_chip` replay
#     committed v1.7 artifacts the same way and are retired with them.
#     Re-basing those needs the real checkpoint and belongs to the task
#     that regenerates the 9B artifact chain, not to G3.1.
#
# +------------------------------------------------------------------+
# | G4a (Task 11) DISPOSITION of `tb_token` and `tb_chain`:           |
# | RETIRED FOR GOOD, and here is the reason rather than a shrug.     |
# +------------------------------------------------------------------+
# The task that regenerates the 9B artifact chain is G4a, and it looked at
# both.  Neither is re-based, and neither is a loss:
#
#   `tb_token` replays `scripts/token_s*.txt`, which are COMMITTED
#   pre-Phase-1A evidence — `token_scripts` above REFUSES to regenerate
#   them on purpose.  Re-basing would mean either overwriting committed
#   evidence (refused by design) or inventing a new artifact family, which
#   is what `token24_scripts` / `tb_token24` already are: the SAME
#   generator (`gen_token_script.py`), gitignored and regenerable at
#   whatever FABLE5_MODEL selects.
#
#   `tb_chain` replays `scripts/chain_s*.txt`, which ARE regenerable
#   (`chain_scripts`, gitignored), so re-basing it is mechanical in the
#   Makefile sense — which is exactly why the decision needs a reason and
#   not an excuse.  The reason is that it would buy nothing new: `tb_chain`
#   drives N layers of `layer_chan` back to back from a host BFM, and BOTH
#   halves of that are covered at 9B already — the single-layer direct drive by
#   `tb_layer_chan` on `layerv2_s*` (G3.4 ran it at FABLE5_MODEL=9b, 4
#   seeds, 1,438 commands / 261,357 checks bit-exact:
#   `evidence/qwen9b/g3/G3_4_LAYER.md`), and the many-layers-in-sequence
#   case by `tb_seq_chip_9b` below, which runs THIRTY-TWO real layers on
#   real weights through `seq_unit` and the movers.
#
# So both stay as the record of how stage 3/4 was gated.  Neither target is
# deleted and neither is claimed to pass; `evidence/qwen9b/g4/G4A_REPLAY.md`
# carries the same disposition.
layer_scripts token_scripts:
	@echo "REFUSED: $@ would overwrite committed pre-Phase-1A evidence."; \
	 echo "  They are the frozen back-compat set (see evidence/stage3,"; \
	 echo "  evidence/stage4). Regenerate only from git history 229c033."; \
	 false

# G3.1: the SEQ_ISA v2.0 layer_chan regression set.  Same generator, same
# seeds, same coverage (CONVW/CONVZ/CONV/VN/VNW/ROPE/ROPET/GATE/DNST/DNZ/
# KVAP/ATTN/ALU end to end against the real RTL) — regenerated because the
# committed layer_s* set encodes an ISA this RTL no longer decodes.  The
# artifacts are gitignored: they are reproducible from the seed in ~10 s.
LAYERV2_SEEDS ?= 1 2 3 4
layer_v2_scripts:
	@for s in $(LAYERV2_SEEDS); do \
	  cd ../ref && $(GENPY) gen_layer_script.py \
	    ../tb/scripts/layerv2_s$$s.txt $$s || exit 1; cd ../tb; \
	done

# S3: the script's own `S` record programs SB_DN/SB_KV/SB_CV and tells the
# TB's DDR model where the state region is, so the run needs only the
# artifact prefix: `+state=<prefix>` names `<prefix>.state.bin`, the INITIAL
# region image `ref/gen_layer_script`'s dump_state writes beside the script.
tb_layer_chan: layer_v2_scripts
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) seq_mem_file.sv tb_layer_chan.sv
	for s in $(LAYERV2_SEEDS); do \
	  obj_dir_tb_layer/tb_layer +script=scripts/layerv2_s$$s.txt \
	    +state=scripts/layerv2_s$$s || exit 1; \
	done

tb_token:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv
	obj_dir_tb_layer/tb_layer +script=scripts/token_s1.txt +emb=scripts/token_s1.emb.bin
	obj_dir_tb_layer/tb_layer +script=scripts/token_s2.txt +emb=scripts/token_s2.emb.bin
	obj_dir_tb_layer/tb_layer +script=scripts/token_s3.txt +emb=scripts/token_s3.emb.bin
	obj_dir_tb_layer/tb_layer +script=scripts/token_s4.txt +emb=scripts/token_s4.emb.bin

# 8-layer chain: ntok=3, nlayers=8 per seed (gen_chain_script.py)
chain_scripts:
	cd ../ref && $(GENPY) gen_chain_script.py ../tb/scripts/chain_s1.txt 1 3 8
	cd ../ref && $(GENPY) gen_chain_script.py ../tb/scripts/chain_s2.txt 2 3 8
	cd ../ref && $(GENPY) gen_chain_script.py ../tb/scripts/chain_s3.txt 3 3 8
	cd ../ref && $(GENPY) gen_chain_script.py ../tb/scripts/chain_s4.txt 4 3 8

tb_chain:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv
	obj_dir_tb_layer/tb_layer +script=scripts/chain_s1.txt +watchdog_ms=4000
	obj_dir_tb_layer/tb_layer +script=scripts/chain_s2.txt +watchdog_ms=4000
	obj_dir_tb_layer/tb_layer +script=scripts/chain_s3.txt +watchdog_ms=4000
	obj_dir_tb_layer/tb_layer +script=scripts/chain_s4.txt +watchdog_ms=4000

# full 24-layer autoregressive token gate: ntok=3, vocab=8192, nlayers=24
token24_scripts:
	cd ../ref && $(GENPY) gen_token_script.py ../tb/scripts/token24_s1.txt 1 3 8192 24
	cd ../ref && $(GENPY) gen_token_script.py ../tb/scripts/token24_s2.txt 2 3 8192 24
	cd ../ref && $(GENPY) gen_token_script.py ../tb/scripts/token24_s3.txt 3 3 8192 24
	cd ../ref && $(GENPY) gen_token_script.py ../tb/scripts/token24_s4.txt 4 3 8192 24

tb_token24:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv
	obj_dir_tb_layer/tb_layer +script=scripts/token24_s1.txt +emb=scripts/token24_s1.emb.bin +watchdog_ms=20000
	obj_dir_tb_layer/tb_layer +script=scripts/token24_s2.txt +emb=scripts/token24_s2.emb.bin +watchdog_ms=20000
	obj_dir_tb_layer/tb_layer +script=scripts/token24_s3.txt +emb=scripts/token24_s3.emb.bin +watchdog_ms=20000
	obj_dir_tb_layer/tb_layer +script=scripts/token24_s4.txt +emb=scripts/token24_s4.emb.bin +watchdog_ms=20000

# ======================================================================
# stage 5 increment (3): REAL Qwen3.5-0.8B weights, full 248,320 vocab.
#
# One target per prompt seed — a single seed is ~950 MB of artifacts and a
# long sim, so `model_script_s1` / `tb_model_s1` are the gate; s2..s4 exist
# for a full 4-seed sweep when there is time for it (they are NOT part of
# the default `model_scripts` fan-out for that reason: ask for them).
#
# PYTHON: MODELPY must be a numpy-capable interpreter on the machine you
# are on AND the machine must have the HF cache.  ref/.venv works on
# darthplagueis only (its interpreter lives under ~/.local/share/uv, which
# is not NFS-shared); on snoke use MODELPY=/home/cah/.venv/bin/python.
# ======================================================================
# The generator runs a RUNTIME RANGE AUDIT and refuses to bless a script
# whose fixed-point formats saturate.  On the real weights S_F=13 does
# saturate and S_F is frozen in the RTL, so the audit must be overridden
# DELIBERATELY:
#     make model_v2_script_s1 MODEL_FLAGS=--allow-clip
# Leaving MODEL_FLAGS empty is the honest default: it fails loudly.
MODELPY ?= $(GENPY)
MODEL_NTOK ?= 3
MODEL_FLAGS ?=

# ---- model_s* / model_rs8_s*: FROZEN pre-Phase-1A artifacts ------------
# These prefixes belong to the committed stage-5 (3) evidence
# (evidence/stage5/model_s1_artifacts.sha256, model_rs8_artifacts.sha256,
# STAGE5_INC3_GATE.md) and were built by the pre-Phase-1A generator.  The
# generator has since moved to the Phase-1A datapath, so regenerating them
# here would NOT reproduce those hashes.  They have no make target any
# more on purpose: use git history (229c033) if you need them.

# ---- model_v2_s*: the Phase-1A production model scripts ---------------
# res_scale=8 is the production residual scale (gen_model_script header).
MODEL_V2_FLAGS ?= --res-scale=8 --allow-clip

model_v2_script_s1:
	cd ../ref && $(MODELPY) gen_model_script.py ../tb/scripts/model_v2_s1.txt 1 $(MODEL_NTOK) $(MODEL_V2_FLAGS)
model_v2_script_s2:
	cd ../ref && $(MODELPY) gen_model_script.py ../tb/scripts/model_v2_s2.txt 2 $(MODEL_NTOK) $(MODEL_V2_FLAGS)
model_v2_script_s3:
	cd ../ref && $(MODELPY) gen_model_script.py ../tb/scripts/model_v2_s3.txt 3 $(MODEL_NTOK) $(MODEL_V2_FLAGS)
model_v2_script_s4:
	cd ../ref && $(MODELPY) gen_model_script.py ../tb/scripts/model_v2_s4.txt 4 $(MODEL_NTOK) $(MODEL_V2_FLAGS)

model_v2_scripts: model_v2_script_s1
model_v2_scripts_all: model_v2_script_s1 model_v2_script_s2 \
                      model_v2_script_s3 model_v2_script_s4

tb_model_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv

MODEL_WD ?= 200000

tb_model_v2_s1: tb_model_build
	obj_dir_tb_layer/tb_layer +script=scripts/model_v2_s1.txt +emb=scripts/model_v2_s1.emb.bin +watchdog_ms=$(MODEL_WD)
tb_model_v2_s2: tb_model_build
	obj_dir_tb_layer/tb_layer +script=scripts/model_v2_s2.txt +emb=scripts/model_v2_s2.emb.bin +watchdog_ms=$(MODEL_WD)
tb_model_v2_s3: tb_model_build
	obj_dir_tb_layer/tb_layer +script=scripts/model_v2_s3.txt +emb=scripts/model_v2_s3.emb.bin +watchdog_ms=$(MODEL_WD)
tb_model_v2_s4: tb_model_build
	obj_dir_tb_layer/tb_layer +script=scripts/model_v2_s4.txt +emb=scripts/model_v2_s4.emb.bin +watchdog_ms=$(MODEL_WD)

tb_model_v2: tb_model_v2_s1
tb_model_v2_all: tb_model_v2_s1 tb_model_v2_s2 tb_model_v2_s3 tb_model_v2_s4

# ======================================================================
# rung 1: the on-chip command sequencer (rtl/seq_unit.sv + seq_movers.sv)
#
# The DUT is driven against BEHAVIOURAL stubs of the layer_chan / matvec_chan
# CSR maps (tb/seq_stub_*.sv) through a latency-modelling AXI-Lite fabric
# (tb/seq_fabric_model.sv) and a DDR read model (tb/seq_ddr_model.sv).
# Golden = tb/scripts/gen_seq_unit_vectors.py, which builds the streams with
# ref/seq_format.py and emits the exact AXI-Lite transaction lists.
#
#   make tb_seq            4 seeds + 7 error paths + 6 micro-benchmarks
#   make tb_seq_lat        the same at fabric latency 0 and 8 (sensitivity)
#   make tb_seq_sideband   USE_XRF_SIDEBAND=1 (the XRF-refresh alternative)
#   make tb_seq_all        all of the above
# ======================================================================
SEQ_RTL   := $(RTL)/seq_unit.sv $(RTL)/seq_movers.sv
SEQ_TBSRC := seq_fabric_model.sv seq_burst_fabric.sv seq_ddr_model.sv \
             seq_stub_layer.sv seq_stub_mvchan.sv tb_seq_unit.sv
SEQ_VEC   ?= scripts/seqvec
SEQ_SEEDS := 1 2 3 4
# G3.4 fix round 1: env0 / env97 are S9's MVGO SHAPE envelope, the two
# sides of 1 <= ng <= 96, each preceded by a LEGAL MVGO in the same
# stream so the refusal cannot be confused with an early halt.
# SR3 (SEQ_ISA v2.3 B17.1): fmrsvd = FENCE target[15:4] != 0, fmimm = a
# legal mask with imm32 != 0, haltmask = HALT target != 0 — each after legal
# records, and the TB checks the faulting PC.
# SR12 (B17.2, err 0x06 each, after legal records and the legal edge):
# mxrsvd = MOVX target[15:12] != 0, mxstart = MOVX start word 3072,
# mxrange = MOVX start + ceil(len/4) = 3073, myrange = MOVY start row + len
# = 4097.
SEQ_ERRS  := op ind chan jmp xopsgn csrsp rsvd env0 env97 fmrsvd fmimm haltmask \
             mxrsvd mxstart mxrange myrange bcast_mvgo movx_chan5 bcast_range
SEQ_MICRO := csrwr cmd movx movy16 movy32 ldc
# R-b directed: LDC/EMB/MOVX/MOVY through scratch words > 16383 and a
# 1536-word XWIN MOVX (the R4 follow-on); `embrow` is the runtime EMB row
# size (EMBLOG2 = 12 -> 4096 B rows).  R-c adds `repack1..4`: MVGO WBASEs
# from a PER-CHANNEL weight pack, ONE CONFIGURATION PER SEED (nch 2/4/3/4,
# both layouts, an interleaved image in each) — the addressing the V5 W8
# fit needs.  hiaddr/embrow stay seed-1 only, like the micros.
# SR3: `fmask` is the FENCE channel mask (SEQ_ISA v2.3 B17.1); fmask2..4 are
# the same stream under a channel permutation per seed (seed 1 = identity).
# SR12: `bank` is the R2 bank fields (SEQ_ISA v2.3 B17.2: MOVX start word,
# MOVY start row, SHAPE bits 29/30, the running-range overlap); bank2..4 are
# the same stream under the fmask permutations.
SEQ_DIRECTED := hiaddr embrow repack1 repack2 repack3 repack4 \
                fmask fmask2 fmask3 fmask4 bank bank2 bank3 bank4 bcast bcast2 bcast3 bcast4
# SR3: the obj_dir stem of the tb_seq_all family (tb_seq, _syn, _l0/_l8,
# _sb), overridable so a task can build its OWN dirs (one host per
# obj_dir): `make tb_seq_all SEQ_OBJ=obj_dir_seq_unit_sr3 SEQ_VEC=...`.
# The default is the historical name, so every other target is unchanged.
SEQ_OBJ ?= obj_dir_tb_seq

lint_seq_unit:
	$(VERILATOR) --lint-only -Wall --timing $(SEQ_RTL) --top-module seq_unit
	$(VERILATOR) --lint-only -Wall --timing seq_fabric_model.sv
	$(VERILATOR) --lint-only -Wall --timing seq_burst_fabric.sv
	$(VERILATOR) --lint-only -Wall --timing seq_ddr_model.sv
	$(VERILATOR) --lint-only -Wall --timing seq_stub_layer.sv
	$(VERILATOR) --lint-only -Wall --timing seq_stub_mvchan.sv

seq_unit_vectors:
	mkdir -p $(SEQ_VEC)
	for s in $(SEQ_SEEDS); do \
	  $(VECPY) scripts/gen_seq_unit_vectors.py $(SEQ_VEC) $$s || exit 1; done

tb_seq_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(SEQ_DEFS) \
	  --Mdir $(SEQ_OBJ) -o tb_seq \
	  --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC)

tb_seq: seq_unit_vectors tb_seq_build
	for s in $(SEQ_SEEDS); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; done
	for e in $(SEQ_ERRS); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_e_$$e || exit 1; done
	for m in $(SEQ_MICRO); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_m_$$m || exit 1; done
	for d in $(SEQ_DIRECTED); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_h_$$d || exit 1; done; for h in $(SEQ_XPHOLD); do $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_h_$${h%%:*} +xp_lowroom=$${h#*:} || exit 1; done

# R-b guard control: prove the EMBLOG2 range check keeps the OLD value.
# It needs an AS-SYNTHESIZED build (+define+SYNTHESIS) because the sim-only
# $error would otherwise $stop the run before the readback — so this target
# checks BOTH halves: loud in a normal build, harmless in hardware.
# -Wno-UNUSEDPARAM: compiling out the sim-only checks orphans the window-size
# localparams they read (seq_movers RES_WORDS/XWIN_WORDS/SCR_WORDS) — an
# artifact of the define, not a lint finding.  The -Wall build is tb_seq.
tb_seq_guard: seq_unit_vectors tb_seq_build
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall -Wno-UNUSEDPARAM \
	  +define+SYNTHESIS \
	  --Mdir $(SEQ_OBJ)_syn -o tb_seq_syn \
	  --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC)
	$(SEQ_OBJ)_syn/tb_seq_syn +vec=$(SEQ_VEC)/seq_h_embrow \
	  +emblog2bad=7
	$(SEQ_OBJ)_syn/tb_seq_syn +vec=$(SEQ_VEC)/seq_h_embrow \
	  +emblog2bad=14
	@echo "--- and the same write in a NORMAL build must raise \$$error:"
	@if $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_h_embrow +emblog2bad=7 \
	    >/dev/null 2>&1; then \
	  echo "FAIL: an illegal EMBLOG2 write did not \$$error in sim"; exit 1; \
	else echo "OK: illegal EMBLOG2 write is loud in simulation"; fi

tb_seq_lat: seq_unit_vectors
	for L in 0 8; do \
	  $(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	    --Mdir $(SEQ_OBJ)_l$$L -o tb_seq_l$$L -GLAT=$$L \
	    --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC) || exit 1; \
	  for s in $(SEQ_SEEDS); do \
	    $(SEQ_OBJ)_l$$L/tb_seq_l$$L +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; \
	  done; \
	  for m in $(SEQ_MICRO); do \
	    $(SEQ_OBJ)_l$$L/tb_seq_l$$L +vec=$(SEQ_VEC)/seq_m_$$m || exit 1; \
	  done; \
	done

tb_seq_sideband: seq_unit_vectors
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir $(SEQ_OBJ)_sb -o tb_seq_sb "-GSIDEBAND=1'b1" \
	  --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC)
	for s in $(SEQ_SEEDS); do \
	  $(SEQ_OBJ)_sb/tb_seq_sb +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; done

tb_seq_all: lint_seq_unit tb_seq tb_seq_guard tb_seq_lat tb_seq_sideband

# ======================================================================
# RUNG 4 / S6 — the seq_unit OUT FIFO (docs/RUNG4_SPEC.md, agent D).
#
# Three dedicated streams (gen_seq_unit_vectors.py build_offifo) of N
# back-to-back (AMAX32 command, AMAXL) pairs, N = 24 / 64 / 80:
#   24  proves the OLD depth-16 silently dropped tokens 17..24
#   64  fills the new depth EXACTLY — of_ovf must stay 0
#   80  overflows it — of_ovf sticky 1, out_cnt saturates at 64, the FIRST
#       64 tokens intact
# then the DIRECTED RACE: the host pops the OUT FIFO interleaved with its
# STATUS polls while the sequencer pushes.  +ofphase slides the pop across
# the push and the TB counts, through a hierarchical reference on
# of_wp/of_rp, the cycles in which BOTH moved — so "a push and a pop landed
# together and nothing desynced" is measured, not assumed.
# ======================================================================
.PHONY: tb_seq_offifo
# SR13a: the runs use $(SEQ_OBJ) (default obj_dir_tb_seq, unchanged), the
# obj_dir tb_seq_build just built, so a task can run this target on its
# OWN build: `make tb_seq_offifo SEQ_OBJ=obj_dir_... SEQ_VEC=...`.

OF_N      := 24 64 80
OF_PHASES := 0 1 2 3 4 5 6 7

tb_seq_offifo: seq_unit_vectors tb_seq_build
	@echo "-- depth 64 + sticky of_ovf, no concurrent pops --"
	for n in $(OF_N); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n || exit 1; done
	@echo "-- the SAME streams over the burst fabric at blat 0/8 --"
	for L in 0 8; do for n in $(OF_N); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n +blat=$$L || exit 1; \
	done; done
	@echo "-- directed push/pop race: 8 pop phases x 3 streams --"
	@#  G3.1 (2026-09-01): the warning that used to print here said the race
	@#  "FAILS on rtl/seq_unit.sv as of 2026-08-11 ... PRE-EXISTING, also
	@#  present at HEAD".  IT IS NOT PRESENT AT HEAD and has not been for a
	@#  while: the recorded fix's AFTER side is in the tree (the
	@#  unconditional `of_rp` advance and the conditional `csr_of_pop`
	@#  strobe both match evidence/rung4/S6_out_fifo_pop_race.patch), and
	@#  `git log ec4216d..HEAD -- rtl/seq_unit.sv` is ZERO commits, ec4216d
	@#  being the R-b full-sim-gate commit.  The target was RUN BY NAME and
	@#  is green (evidence/qwen9b/g3/G3_1_ISA.md), so the stale echo is
	@#  deleted rather than the patch re-applied — force-applying it would
	@#  revert the conditional strobe and REINTRODUCE the token-loss race.
	for p in $(OF_PHASES); do for n in $(OF_N); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n +ofrace +ofphase=$$p \
	    || exit 1; \
	done; done
	@echo "-- race on the normal streams too (their AMAXLs sit mid-stream) --"
	for p in 0 3; do for s in $(SEQ_SEEDS); do \
	  $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_u_s$$s +ofrace +ofphase=$$p \
	    || exit 1; \
	done; done
	@echo "-- self-test: the depth check MUST trip if the TB is told 16 --"
	@if $(SEQ_OBJ)/tb_seq +vec=$(SEQ_VEC)/seq_f_of24 +ofdepth=16 \
	     >/dev/null 2>&1; then \
	  echo "SELFTEST FAIL: +ofdepth=16 did NOT trip on a 24-token stream"; \
	  exit 1; \
	fi
	@echo "TB_SEQ_OFFIFO OK: 3 depths x {axil, blat 0, blat 8} + 24 race runs + 8 stream races + depth self-test"

# ======================================================================
# wave 3: FULL-CHIP, SEQ-DRIVEN simulation (tb/tb_seq_chip.sv)
#
# seq_unit + seq_movers driving the REAL layer_chan and the REAL
# matvec_chan(s) — no behavioural stubs anywhere in the datapath.  The
# record stream, the LDC constant blob, the embedding table and the packed
# W4 weight images are the ACTUAL emitted/committed binaries, served beat by
# beat out of the files by tb/seq_mem_file.sv.
#
#   make seq_chip_vectors SEQP=scripts/w3/tok2_s1.e SEQBASE=scripts/w3/tok2_s1
#   make tb_seq_chip_build
#   make tb_seq_chip      SEQP=... SEQBASE=...
#
# CHIP_NMV = how many REAL matvec_chan instances to elaborate (1 is enough
# for every stream the emitter produces today: all MVGO records target
# channel 0).  Raising it costs one xpm_memory_tdpram + one ddr_rd_streamer
# + one matvec_engine each.
# ======================================================================
CHIP_RTL   := $(SEQ_RTL) $(LAYER_RTL) \
              $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv \
              $(RTL)/matvec_chan.sv
CHIP_TBSRC := seq_fabric_model.sv seq_burst_fabric.sv seq_mem_file.sv \
              tb_seq_chip.sv
CHIP_NMV   ?= 1
CHIP_WD    ?= 600000
CHIP_DIR   ?= scripts/w3
SEQP       ?= $(CHIP_DIR)/tok2_s1.e
SEQBASE    ?= $(CHIP_DIR)/tok2_s1

# The two fast gate scripts, emitted with profile=epsnorm + dyn_ka (the
# combination whose decode loop closes).  lay_s1 is the short DN+ATTN
# synthetic for iteration; tok2_s1 is the 3-step decode loop.
seq_chip_scripts:
	mkdir -p $(CHIP_DIR)
	cd ../ref && SEQ_EMIT=$(CURDIR)/$(CHIP_DIR)/lay_s1.e SEQ_PROFILE=epsnorm \
	  $(GENPY) gen_layer_script.py $(CURDIR)/$(CHIP_DIR)/lay_s1.txt 1 2
	cd ../ref && SEQ_EMIT=$(CURDIR)/$(CHIP_DIR)/tok2_s1.e SEQ_PROFILE=epsnorm \
	  $(GENPY) gen_token_script.py $(CURDIR)/$(CHIP_DIR)/tok2_s1.txt 1 3 8192 2
	$(VECPY) scripts/gen_seq_chip_vectors.py $(CHIP_DIR)/lay_s1.e  --base $(CHIP_DIR)/lay_s1
	$(VECPY) scripts/gen_seq_chip_vectors.py $(CHIP_DIR)/tok2_s1.e --base $(CHIP_DIR)/tok2_s1

lint_seq_chip:
	$(VERILATOR) --lint-only -Wall --timing seq_mem_file.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

seq_chip_vectors:
	$(VECPY) scripts/gen_seq_chip_vectors.py $(SEQP) --base $(SEQBASE)

tb_seq_chip_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_seq_chip -o tb_seq_chip -GNMV=$(CHIP_NMV) \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chip: tb_seq_chip_build
	obj_dir_tb_seq_chip/tb_seq_chip +seq=$(SEQP) +base=$(SEQBASE) \
	  +watchdog_ms=$(CHIP_WD)

# the two fast gates end to end (~30 s and ~50 s of sim each)
tb_seq_chip_fast: seq_chip_scripts tb_seq_chip_build
	obj_dir_tb_seq_chip/tb_seq_chip +seq=$(CHIP_DIR)/lay_s1.e \
	  +base=$(CHIP_DIR)/lay_s1  +watchdog_ms=$(CHIP_WD)
	obj_dir_tb_seq_chip/tb_seq_chip +seq=$(CHIP_DIR)/tok2_s1.e \
	  +base=$(CHIP_DIR)/tok2_s1 +watchdog_ms=$(CHIP_WD)

# ======================================================================
# R-c / V5: the 2B W8 (SHAPE bit 29) chain, per-channel repacked.
#
# Everything here is 2B (FABLE5_MODEL=2b) + `--wq=w8` + `SEQ_NCH=4
# SEQ_REPACK=1`, which is the ONLY combination that fits: the 2B W8 pack is
# 1,847 MiB in one span and 464.8 MiB on the busiest channel
# (evidence/qwen2b/rc/T3_REPACK.md §4).  A repacked stream needs one weight
# REGION FILE PER CHANNEL, so these build tb_seq_chip with
# -GWIMGPC=1 -GNMV=4 into their OWN obj_dir — never reuse obj_dir_tb_seq_chip,
# whose NMV=1/WIMGPC=0 elaboration is what the frozen 0.8B gates use.
#
#   make w8_2b_smoke_scripts MODELPY=/home/cah/.venv/bin/python   # 4 seeds
#   make tb_seq_chip_w8_build
#   make tb_seq_chip_w8_smoke          # the cheap fail-fast (1 layer x 4)
#   make w8_2b_model_script            # the FULL 2B artifact set (~30-60 min)
#   make seq_chip_vectors_w8           # + the .chip golden and 4x .wimg<c>
#   make tb_seq_chip_w8                # the full-2B chip replay (hours)
#
# S=4 is the standing 2B ruling (Q5 / audit_ranges_2b_report.md §6.6);
# --allow-clip is the same deliberate S_F=13 override the 0.8B recipe needs.
#
# +------------------------------------------------------------------+
# | RETIRED FOR THIS BITSTREAM — dated note 2026-09-02 (G3.3, Task 9) |
# +------------------------------------------------------------------+
# G3.3 stripped the W8 engine mode out of rtl/matvec_engine.sv and SHAPE
# bit 29 out of rtl/matvec_chan.sv (spec 5.1 S5), so THIS TREE CANNOT
# REPLAY A W8 STREAM: the elaboration below still builds, but a W8 SHAPE
# word now decodes as a W4 one and the chip would silently disagree with
# its .chip golden.  G3.1 had already made the family unrunnable from a
# post-G3 checkout for a second, independent reason — the pinned 2B
# artifacts are SEQ_ISA v1.7 streams and the emitter here is v2.0.
# The targets are KEPT, not deleted, because they are the record of how
# build_035's chain was gated and they are the recipe a pre-G3 checkout
# still runs.  The two RUN targets refuse rather than mis-verify; the
# script/vector targets are left alone because they only produce files.
# Disposition and reasoning: evidence/qwen9b/g3/G3_3_MATVEC.md 2.
# ======================================================================
.PHONY: w8_2b_smoke_scripts w8_2b_model_script seq_chip_vectors_w8 \
        tb_seq_chip_w8_build tb_seq_chip_w8_smoke tb_seq_chip_w8 \
        lint_seq_chip_w8 w8_2b_tok_smoke_scripts tb_seq_chip_w8_tok_smoke

W8_DIR    ?= scripts/w5
W8_BASE   ?= $(W8_DIR)/model_w8_2b_s1
W8_NCH    ?= 4
W8_NTOK   ?= 3
W8_SEED   ?= 1
W8_FLAGS  ?= --res-scale=4 --allow-clip --wq=w8
W8_SMOKE_NTOK ?= 2
W8_SEEDS  ?= 1 2 3 4
W8_WD     ?= 172800000

# --- the cheap fail-fast: ONE DN + ONE ATTN layer at the 2B geometry, W8,
# repacked over 4 channels, 4 seeds.  Random weights, so no checkpoint and
# no HF cache needed; ~130 MB of images per seed.
w8_2b_smoke_scripts:
	mkdir -p $(W8_DIR)
	for s in $(W8_SEEDS); do \
	  ( cd ../ref && FABLE5_MODEL=2b SEQ_PROFILE=epsnorm SEQ_NCH=$(W8_NCH) \
	      SEQ_REPACK=1 SEQ_EMIT=$(CURDIR)/$(W8_DIR)/lay2b_w8_s$$s.e \
	      $(MODELPY) gen_layer_script.py \
	      $(CURDIR)/$(W8_DIR)/lay2b_w8_s$$s.txt $$s $(W8_SMOKE_NTOK) \
	      --wq=w8 ) || exit 1; \
	  FABLE5_MODEL=2b $(VECPY) scripts/gen_seq_chip_vectors.py \
	    $(W8_DIR)/lay2b_w8_s$$s.e --base $(W8_DIR)/lay2b_w8_s$$s || exit 1; \
	done

# --- the full 2B W8 model artifact set (the R-c chain).  MODELPY must be a
# torch+HF-cache interpreter: on snoke /home/cah/.venv/bin/python.
w8_2b_model_script:
	mkdir -p $(W8_DIR)
	cd ../ref && FABLE5_MODEL=2b SEQ_PROFILE=epsnorm SEQ_NCH=$(W8_NCH) \
	  SEQ_REPACK=1 SEQ_EMIT=$(CURDIR)/$(W8_BASE).e \
	  $(MODELPY) gen_model_script.py $(CURDIR)/$(W8_BASE).txt \
	  $(W8_SEED) $(W8_NTOK) $(W8_FLAGS)

seq_chip_vectors_w8:
	FABLE5_MODEL=2b $(VECPY) scripts/gen_seq_chip_vectors.py \
	  $(W8_BASE).e --base $(W8_BASE)

lint_seq_chip_w8:
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) \
	  -GNMV=$(W8_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chip_w8_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_seq_chip_w8 -o tb_seq_chip_w8 \
	  -GNMV=$(W8_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

# --- TOKEN coverage for the fail-fast (R-c wall 8's follow-on).  The
# 1-layer smoke above emits EMB = AMAXL = JMP = 0 — it generates no tokens
# at all — so it is blind to the embed / argmax / decode-loop path, which is
# exactly where wall 8 lived (the TB never programmed EMBLOG2, so a 2B
# artifact's 4096 B embedding rows were fetched as 2048 B ones).  This one
# runs the real token loop over a small vocab: minutes, not the 66 the full
# model costs, and it carries EMB + AMAXL + JMP.
W8_TOK_VOCAB ?= 8192
W8_TOK_NTOK  ?= 2
W8_TOK_LAYERS ?= 2

w8_2b_tok_smoke_scripts:
	mkdir -p $(W8_DIR)
	for s in $(W8_SEEDS); do \
	  ( cd ../ref && FABLE5_MODEL=2b SEQ_PROFILE=epsnorm SEQ_NCH=$(W8_NCH) \
	      SEQ_REPACK=1 SEQ_EMIT=$(CURDIR)/$(W8_DIR)/tok2b_w8_s$$s.e \
	      $(MODELPY) gen_token_script.py \
	      $(CURDIR)/$(W8_DIR)/tok2b_w8_s$$s.txt $$s $(W8_TOK_NTOK) \
	      $(W8_TOK_VOCAB) $(W8_TOK_LAYERS) --wq=w8 ) || exit 1; \
	  FABLE5_MODEL=2b $(VECPY) scripts/gen_seq_chip_vectors.py \
	    $(W8_DIR)/tok2b_w8_s$$s.e --base $(W8_DIR)/tok2b_w8_s$$s || exit 1; \
	done

tb_seq_chip_w8_tok_smoke: tb_seq_chip_w8_build
	for s in $(W8_SEEDS); do \
	  obj_dir_tb_seq_chip_w8/tb_seq_chip_w8 \
	    +seq=$(W8_DIR)/tok2b_w8_s$$s.e +base=$(W8_DIR)/tok2b_w8_s$$s \
	    +watchdog_ms=$(CHIP_WD) || exit 1; \
	done

tb_seq_chip_w8_smoke: tb_seq_chip_w8_build
	@echo "RETIRED (G3.3): this bitstream has no W8 engine mode — a W8 SHAPE"; \
	 echo "word decodes as W4 and the replay would silently disagree with its"; \
	 echo "golden.  Run this family from a pre-G3 checkout.  See tb/Makefile's"; \
	 echo "R-c / V5 banner and evidence/qwen9b/g3/G3_3_MATVEC.md 2."; exit 1
	for s in $(W8_SEEDS); do \
	  obj_dir_tb_seq_chip_w8/tb_seq_chip_w8 \
	    +seq=$(W8_DIR)/lay2b_w8_s$$s.e +base=$(W8_DIR)/lay2b_w8_s$$s \
	    +watchdog_ms=$(CHIP_WD) || exit 1; \
	done

# The FIRST full-2B-model simulation.  Budget hours of wall time and give it
# a generous watchdog (W8_WD is 48 h of simulated ms by default).
tb_seq_chip_w8: tb_seq_chip_w8_build
	@echo "RETIRED (G3.3): this bitstream has no W8 engine mode — a W8 SHAPE"; \
	 echo "word decodes as W4 and the replay would silently disagree with its"; \
	 echo "golden.  Run this family from a pre-G3 checkout.  See tb/Makefile's"; \
	 echo "R-c / V5 banner and evidence/qwen9b/g3/G3_3_MATVEC.md 2."; exit 1
	obj_dir_tb_seq_chip_w8/tb_seq_chip_w8 +seq=$(W8_BASE).e \
	  +base=$(W8_BASE) +watchdog_ms=$(W8_WD)

# ======================================================================
# G4a: the 9B W4 g128 chain, per-channel repacked (FABLE5_MODEL=9b).
#
# Everything here is 9B + W4 g128 + GPTQ + `SEQ_NCH=4 SEQ_REPACK=1`, which
# is the ONLY combination that fits: the nch-INDEPENDENT 9B pack is
# 3,902.3 MiB in one span against a 1,280 MiB window and
# `sw/hwmap.plan_weights` REFUSES it, while the nch=4 repack lands the
# busiest channel at 978.6 MiB = 76.5 % of the window
# (evidence/qwen9b/g2/G2C_CHAIN.md section 5.2).  So there is no 1-channel
# `.e` 9B stream to emit and the artifacts are named `.e4`, exactly as the
# 0.8B four-channel set is.
#
# A repacked stream needs one weight REGION FILE PER CHANNEL, so these build
# tb_seq_chip with -GWIMGPC=1 -GNMV=4 into their OWN obj_dir —
# obj_dir_tb_seq_chip_9b, a THIRD one.  obj_dir_tb_seq_chip is the
# NMV=1/WIMGPC=0 elaboration the frozen 0.8B gates use and
# obj_dir_tb_seq_chip_w8 is the 2B W8 twin; never reuse either.
#
#   make w9_9b_smoke_scripts MODELPY=/home/cah/.venv/bin/python  # 4 seeds
#   make tb_seq_chip_9b_build
#   make tb_seq_chip_9b_smoke        # the cheap fail-fast (1 DN + 1 ATTN x4)
#   make w9_9b_tok_smoke_scripts     # + the token loop (EMB / AMAXL / JMP)
#   make tb_seq_chip_9b_tok_smoke
#   make w9_9b_model_script          # the FULL 9B artifact set (hours)
#   make seq_chip_vectors_9b         # + the .chip golden and 4x .wimg<c>
#   make tb_seq_chip_9b              # the full-9B chip replay (hours)
#
# THE OPERATING POINT, spelled out so a run is never a guess (plan A1/A2):
#   FABLE5_MODEL=9b         H=4096 FFN=12288, 32 layers (24 DN / 8 GQA)
#   FABLE5_RS_F=7           A2, adopted by user ruling 2026-09-01.
#                           rtl/conv4_silu.sv:54 bakes the matching shift,
#                           so the RTL and the artifact must agree; an
#                           artifact emitted at 8 would replay WRONG here.
#   --res-scale=1           spec 4.4: at H=4096 the raw residual reaches the
#                           Q7.8 rail with no rescale applied at all
#   --w4-group=128          D1 (the g64 strip is ratified O2)
#   FABLE5_CALIB_STATS/MODE the GPTQ pair, ref/calib_stats_9b_h.npz
#   FABLE5_DN_STATE unset   = int16, the ratified container (A1)
#
# NOT passed: --allow-clip.  The 0.8B/2B recipes need it for the S_F=13
# DeltaNet-state soak; whether 9B does is a MEASUREMENT this chain makes
# rather than an assumption it bakes in, and the artifacts are written on
# both paths (`ref/seq_format._finalize` is an atexit hook), so a tripped
# audit costs a non-zero rc and a recorded report, not a re-run.
#
# W9_WD matches W8_WD, the largest watchdog in the tree.  At 250 MHz one
# simulated ms is 250,000 cycles, so both are far past any real bound:
# the operative limit on these runs is bounded wall-clock polling by the
# operator, and the numbers are budget documentation, not a live guard.
# ======================================================================
.PHONY: w9_9b_smoke_emit_x2 w9_9b_model_emit_x2 w9_9b_emit2_red \
        w9_9b_smoke_scripts w9_9b_tok_smoke_scripts w9_9b_model_script \
        seq_chip_vectors_9b tb_seq_chip_9b_build tb_seq_chip_9b_smoke \
        tb_seq_chip_9b_tok_smoke tb_seq_chip_9b lint_seq_chip_9b

W9_DIR    ?= scripts/w9
W9_BASE   ?= $(W9_DIR)/model_9b_s1
W9_SEQ    ?= $(W9_BASE).e4
W9_NCH    ?= 4
W9_NTOK   ?= 3
W9_SEED   ?= 1
W9_FLAGS  ?= --w4-group=128 --res-scale=1
W9_SMOKE_NTOK ?= 2
W9_SEEDS  ?= 1 2 3 4
W9_WD     ?= 172800000
# ABSOLUTE: every recipe below `cd ../ref`, so a repo-relative Hessian path
# would not resolve and the run would die on a FileNotFoundError — which is
# exactly how G2c's first emit attempt failed
# (evidence/qwen9b/g2/run_g2c_emit.sh:70-75).
W9_HESS   ?= $(abspath $(CURDIR)/../ref/calib_stats_9b_h.npz)
# THE MODEL SELECTION, and it belongs on EVERY recipe here, not only the
# generators.  `ref/layer_fixed.RS_F` is a process-global constant fixed at
# import (`ref/layer_fixed.py:134`): since #26 it is DERIVED from FABLE5_MODEL
# (9b => 7) and FABLE5_RS_F is an override that must AGREE or is refused, so
# the pair below is CHECKED rather than remembered -- but it must still be on
# every recipe, because FABLE5_MODEL is what carries the value.
# THE ONE LEGITIMATE DISAGREEMENT is a deliberate rider sweep,
# `FABLE5_RS_F_RIDER=1`, which is a MEASUREMENT knob (the two G1 fidelity
# scripts) and NEVER a vector recipe: nothing in this Makefile sets it, and
# an artifact emitted under it is not the shipping operating point.  Since
# 2026-09-10 a run that sets it prints one FABLE5_RS_F_RIDER line on stderr.
# `tb/scripts/gen_seq_chip_vectors.py` runs
# the reference executor to build the .chip golden -- so a vector recipe
# without it would compute the golden at RS_F = 8 against a stream emitted
# at 7 and the chip replay would disagree with its own golden for a reason
# no error message names.  A2.5's rule -- CLOSED 2026-09-10 by #26, and now
# ENFORCED rather than advised -- WAS the converse and still holds: never
# export FABLE5_RS_F process-wide across a byte-locked emit.
W9_MODEL   = FABLE5_MODEL=9b FABLE5_RS_F=7
W9_ENV     = $(W9_MODEL) SEQ_PROFILE=epsnorm \
             SEQ_NCH=$(W9_NCH) SEQ_REPACK=1
W9_GPTQ    = FABLE5_CALIB_STATS=$(W9_HESS) FABLE5_CALIB_MODE=gptq

# --- the cheap fail-fast: ONE DN + ONE ATTN layer at the 9B geometry,
# repacked over 4 channels, 4 seeds.  Random weights, so no checkpoint, no
# HF cache and no GPTQ Hessian are needed.
# S3 fix round 2 (C1 part 3): the artifact is EMITTED TWICE and the second
# emission must reproduce the first byte for byte before the artifact is
# accepted.  `W9_EMIT2=0` turns it off; nothing in this repo should.
W9_EMIT2   ?= 1
EMIT2_SH    = ../evidence/qwen9b/s3/emit_repeat.sh
# S4 fix round 1 (I1a): where `w9_9b_model_script` KEEPS the emitter's own
# output and its exit status, so the recipe can apply the rc contract
# instead of being abandoned by make on a by-design non-zero rc.  Both live
# under $(EMIT2_DIR) (defined below; make expands lazily) and are named
# after the artifact's basename, so emission A and emission B — which differ
# only in W9_BASE — cannot collide.
W9_EMIT_OUT = $(EMIT2_DIR)/$(notdir $(W9_BASE)).emit.out
W9_EMIT_RC  = $(EMIT2_DIR)/$(notdir $(W9_BASE)).emit.rc
# `n = 1` plus REF_PREFIX IS "emit twice and compare": the kept emission is
# the first, this is the second.  EMIT_SEQ_ENV is each target's OWN W9_ENV,
# so the two emissions cannot differ by an environment variable.

w9_9b_smoke_scripts:
	mkdir -p $(W9_DIR) $(EMIT2_DIR)
	for s in $(W9_SEEDS); do \
	  ( cd ../ref && $(W9_ENV) \
	      SEQ_EMIT=$(CURDIR)/$(W9_DIR)/lay9b_s$$s.e4 \
	      $(MODELPY) gen_layer_script.py \
	      $(CURDIR)/$(W9_DIR)/lay9b_s$$s.txt $$s $(W9_SMOKE_NTOK) ) \
	    || exit 1; \
	  if [ "$(W9_EMIT2)" = 1 ]; then \
	    EMIT_GEN=gen_layer_script.py \
	    EMIT_ARGS="$$s $(W9_SMOKE_NTOK)" MODELPY=$(MODELPY) \
	    EMIT_SEQ_ENV="$(W9_ENV)" \
	    REF_PREFIX=$(CURDIR)/$(W9_DIR)/lay9b_s$$s \
	      sh $(EMIT2_SH) 1 $(CURDIR)/$(EMIT2_DIR)/lay9b_s$$s || exit 1; \
	  fi; \
	  $(W9_MODEL) $(VECPY) scripts/gen_seq_chip_vectors.py \
	    $(W9_DIR)/lay9b_s$$s.e4 --base $(W9_DIR)/lay9b_s$$s || exit 1; \
	done

# --- TOKEN coverage for the fail-fast (R-c wall 8's follow-on).  The
# 1-layer smoke above emits EMB = AMAXL = JMP = 0 — it generates no tokens
# at all — so it is blind to the embed / argmax / decode-loop path.  At 9B
# that path carries EMBLOG2 = 13, which is EXACTLY SEQ_EMBLOG2_MAX with no
# headroom (G2C_CHAIN.md section 5.2a), so it is worth its own rung.
W9_TOK_VOCAB  ?= 8192
W9_TOK_NTOK   ?= 2
W9_TOK_LAYERS ?= 2

w9_9b_tok_smoke_scripts:
	mkdir -p $(W9_DIR) $(EMIT2_DIR)
	for s in $(W9_SEEDS); do \
	  ( cd ../ref && $(W9_ENV) \
	      SEQ_EMIT=$(CURDIR)/$(W9_DIR)/tok9b_s$$s.e4 \
	      $(MODELPY) gen_token_script.py \
	      $(CURDIR)/$(W9_DIR)/tok9b_s$$s.txt $$s $(W9_TOK_NTOK) \
	      $(W9_TOK_VOCAB) $(W9_TOK_LAYERS) ) || exit 1; \
	  if [ "$(W9_EMIT2)" = 1 ]; then \
	    EMIT_GEN=gen_token_script.py \
	    EMIT_ARGS="$$s $(W9_TOK_NTOK) $(W9_TOK_VOCAB) $(W9_TOK_LAYERS)" \
	    MODELPY=$(MODELPY) EMIT_SEQ_ENV="$(W9_ENV)" \
	    REF_PREFIX=$(CURDIR)/$(W9_DIR)/tok9b_s$$s \
	      sh $(EMIT2_SH) 1 $(CURDIR)/$(EMIT2_DIR)/tok9b_s$$s || exit 1; \
	  fi; \
	  $(W9_MODEL) $(VECPY) scripts/gen_seq_chip_vectors.py \
	    $(W9_DIR)/tok9b_s$$s.e4 --base $(W9_DIR)/tok9b_s$$s || exit 1; \
	done

# --- the full 9B model artifact set.  MODELPY must be a torch+HF-cache
# interpreter: on snoke /home/cah/.venv/bin/python, or the uv invocation
# evidence/qwen9b/g2/run_g2c_emit.sh:89 uses.  Budget HOURS: the GPTQ pass
# alone was measured at 2 h 55 min (G2C_CHAIN.md section 4.2).
#
# S4 FIX ROUND 1 (review I1): THE EMITTER'S rc IS CAPTURED, NOT ABANDONED.
# `ref/gen_model_script.py:711-721` does `raise SystemExit(` when the
# runtime range audit fails and `--allow-clip` is not passed, so at 9B the
# emitter exits 1 BY DESIGN with `RANGE AUDIT FAILED: ...` as the message
# and the artifacts already written by `ref/seq_format._finalize`'s atexit
# hook.  This used to be a plain recipe line, so make abandoned the recipe
# there and the W9_EMIT2 block below WAS NEVER REACHED on this target --
# the campaign's emit-twice gate was inert on its most expensive artifact
# (S4's own evidence/qwen9b/s4/001_emit_9b_s1.log shows `Error 1` reported
# against the emitter's line).  The rc contract below is the one
# `evidence/qwen9b/s4/emit_model_gated.sh:82-102` already implements:
#
#   rc 0                              -> run the block
#   rc != 0 AND `RANGE AUDIT FAILED`  -> run the block
#           AND the finalizer's `SEQ: ... records ... -> ` line
#           AND no Traceback / AssertionError
#   anything else                     -> ABORT BEFORE the block
#
# and the TARGET still exits with the EMITTER's rc afterwards, so `rc 2`
# (make's translation of a recipe that returned 1) keeps meaning what
# Task 11's and S4's emission logs say it means.  A failure of the block
# itself exits non-zero whatever the emitter's rc was.
#
# S3 fix round 2 (C1 part 3), unchanged in intent: the model artifact is
# accepted only if a SECOND emission reproduces it.  Budget twice the emit
# -- the GPTQ pass alone was 2 h 55 min (G2C_CHAIN.md 4.2) -- and that is
# the price of keeping an artifact a bit-exact replay depends on.
w9_9b_model_script:
	mkdir -p $(W9_DIR) $(EMIT2_DIR)
	@# ONE recipe line from here on: `rc` has to survive to the block.
	rm -f $(CURDIR)/$(W9_EMIT_RC); \
	( cd ../ref && $(W9_ENV) $(W9_GPTQ) \
	    SEQ_EMIT=$(CURDIR)/$(W9_SEQ) \
	    $(MODELPY) gen_model_script.py $(CURDIR)/$(W9_BASE).txt \
	    $(W9_SEED) $(W9_NTOK) $(W9_FLAGS) 2>&1; \
	  echo $$? > $(CURDIR)/$(W9_EMIT_RC) ) \
	  | tee $(CURDIR)/$(W9_EMIT_OUT); \
	rc=`cat $(CURDIR)/$(W9_EMIT_RC) 2>/dev/null || echo 127`; \
	echo "W9_EMIT2 GATE: emitter rc=$$rc, output kept in $(W9_EMIT_OUT)"; \
	if [ "$$rc" != 0 ]; then \
	  if grep -q '^RANGE AUDIT FAILED' $(CURDIR)/$(W9_EMIT_OUT) \
	     && grep -q '^SEQ: .* records .* -> ' $(CURDIR)/$(W9_EMIT_OUT) \
	     && ! grep -qE 'Traceback \(most recent call last\)|AssertionError' \
	          $(CURDIR)/$(W9_EMIT_OUT); then \
	    echo "W9_EMIT2 GATE: rc $$rc is the KNOWN deliberate range-audit failure (no --allow-clip); the artifacts were written"; \
	  else \
	    echo "W9_EMIT2 GATE: ABORT -- rc $$rc is NOT the known range-audit failure; the emit-twice block is SKIPPED"; \
	    grep -nE 'Traceback \(most recent call last\)|AssertionError' \
	      $(CURDIR)/$(W9_EMIT_OUT) | tail -20; \
	    exit $$rc; \
	  fi; \
	fi; \
	if [ "$(W9_EMIT2)" = 1 ]; then \
	  EMIT_GEN=gen_model_script.py \
	  EMIT_ARGS="$(W9_SEED) $(W9_NTOK) $(W9_FLAGS)" \
	  EMIT_ENV="$(W9_GPTQ)" MODELPY=$(MODELPY) \
	  EMIT_SEQ_ENV="$(W9_ENV)" REF_PREFIX=$(CURDIR)/$(W9_BASE) \
	    sh $(EMIT2_SH) 1 $(CURDIR)/$(EMIT2_DIR)/$(notdir $(W9_BASE)) \
	    || exit 1; \
	fi; \
	exit $$rc

# S3 fix round 1 (C1): EMIT TWICE AND COMPARE.  Three emitter runs on
# darthplagueis -- the host the Global Constraints ban from numeric compute
# -- aborted inside w4a8_ref.matvec_y32's overflow assert with an
# arithmetically impossible value, and the reviewer reproduced it 3 times in
# 9 on that host from a clean tree.  An assert that FIRES is the lucky case;
# the same corruption below its threshold is a silently wrong artifact.  So
# every emission this project KEEPS is emitted twice under different
# prefixes and refused unless the .txt, the .seq, the .seqdata.bin and the
# state image all agree byte for byte.  `evidence/qwen9b/s3/emit_repeat.sh`
# is the gate; these are its two entry points.
EMIT2_DIR ?= $(W9_DIR)/emit2

# The standalone forms: N emissions with no kept artifact, for a soak or a
# host comparison.  The KEPT-ARTIFACT gate is wired into
# w9_9b_smoke_scripts / w9_9b_tok_smoke_scripts / w9_9b_model_script above.
w9_9b_smoke_emit_x2:
	EMIT_SEQ_ENV="$(W9_ENV)" MODELPY=$(MODELPY) \
	  sh $(EMIT2_SH) 2 $(CURDIR)/$(EMIT2_DIR)/smoke \
	  $(W9_SEED) $(W9_SMOKE_NTOK)

# The gate's own RED: the second emission is perturbed (seed + 1) and the
# comparison MUST refuse it.  A check that has never failed is a check
# nobody has seen work.
w9_9b_emit2_red:
	@echo "RED: the second emission is perturbed; EMIT_REPEAT must FAIL"
	EMIT2_FORCE_FAIL=1 EMIT_SEQ_ENV="$(W9_ENV)" MODELPY=$(MODELPY) \
	REF_PREFIX=$(CURDIR)/$(W9_DIR)/lay9b_s$(W9_SEED) \
	  sh $(EMIT2_SH) 1 $(CURDIR)/$(EMIT2_DIR)/red \
	  $(W9_SEED) $(W9_SMOKE_NTOK) \
	  && { echo "EMIT2_RED: NOT CAUGHT — the gate is blind"; exit 1; } \
	  || echo "EMIT2_RED: CAUGHT (the gate refused a perturbed emission)"

# S4's four model emits run under THIS one.  Budget twice the emit: the
# GPTQ pass alone was 2 h 55 min (G2C_CHAIN.md 4.2), so this is a whole day
# for four seeds and it is the price of keeping the artifacts.
w9_9b_model_emit_x2:
	EMIT_GEN=gen_model_script.py \
	EMIT_ARGS="$(W9_SEED) $(W9_NTOK) $(W9_FLAGS)" \
	EMIT_ENV="$(W9_GPTQ)" MODELPY=$(MODELPY) EMIT_SEQ_ENV="$(W9_ENV)" \
	  sh $(EMIT2_SH) 2 \
	  $(CURDIR)/$(EMIT2_DIR)/model $(W9_SEED) $(W9_NTOK)

seq_chip_vectors_9b:
	$(W9_MODEL) $(VECPY) scripts/gen_seq_chip_vectors.py \
	  $(W9_SEQ) --base $(W9_BASE)

lint_seq_chip_9b:
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chip_9b_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_seq_chip_9b -o tb_seq_chip_9b \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chip_9b_smoke: tb_seq_chip_9b_build
	for s in $(W9_SEEDS); do \
	  obj_dir_tb_seq_chip_9b/tb_seq_chip_9b \
	    +seq=$(W9_DIR)/lay9b_s$$s.e4 +base=$(W9_DIR)/lay9b_s$$s \
	    +watchdog_ms=$(CHIP_WD) || exit 1; \
	done

tb_seq_chip_9b_tok_smoke: tb_seq_chip_9b_build
	for s in $(W9_SEEDS); do \
	  obj_dir_tb_seq_chip_9b/tb_seq_chip_9b \
	    +seq=$(W9_DIR)/tok9b_s$$s.e4 +base=$(W9_DIR)/tok9b_s$$s \
	    +watchdog_ms=$(CHIP_WD) || exit 1; \
	done

# The FIRST full-9B-model simulation — the first time the whole model runs
# anywhere.  Budget hours of wall time.
tb_seq_chip_9b: tb_seq_chip_9b_build
	obj_dir_tb_seq_chip_9b/tb_seq_chip_9b +seq=$(W9_SEQ) \
	  +base=$(W9_BASE) +watchdog_ms=$(W9_WD)

# ----------------------------------------------------------------------
# BN1: the TIMELINE-CENSUS elaboration.  Same sources, same parameters,
# its OWN obj_dir — `obj_dir_seq_chip_tl`, a FOURTH one — because the house
# rule is one obj_dir per build and the three above carry frozen gates
# (obj_dir_tb_seq_chip is the 0.8B NMV=1 elaboration, _w8 the 2B twin,
# _9b the shipped 9B replay whose binary S4's 031 ran).
#
# The instrument itself is `tb/seq_timeline.svh`, `include`d by
# tb/tb_seq_chip.sv and GATED by `+timeline=<csv>`: this binary with the
# plusarg ABSENT must reproduce 031's cycle count and tokens exactly, which
# is BN1's control, so BOTH of BN1's runs use THIS binary.  `-I$(CURDIR)`
# is what lets the `include resolve from tb/.
# ----------------------------------------------------------------------
.PHONY: tb_seq_chip_9b_tl_build tb_seq_chip_9b_tl lint_seq_chip_9b_tl

lint_seq_chip_9b_tl:
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) -I$(CURDIR) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

# SV1 (2026-09-24): the Mdir and binary name are variables so a second,
# independently-built copy of THIS elaboration can live beside the census
# binary (`make tb_seq_chip_9b_tl_build TL_MDIR=obj_dir_seq_chip_sv1
# TL_BIN=tb_seq_chip_9b_sv1`).  The defaults are the census binary, byte
# for byte the recipe it was built with.
TL_MDIR ?= obj_dir_seq_chip_tl
TL_BIN  ?= tb_seq_chip_9b_tl
tb_seq_chip_9b_tl_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) -I$(CURDIR) \
	  --Mdir $(TL_MDIR) -o $(TL_BIN) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

# The full replay WITH the census on.  TL_CSV names the per-record CSV;
# leaving it empty runs the control (no plusarg, no CSV, no instrument).
TL_CSV ?=
tb_seq_chip_9b_tl: tb_seq_chip_9b_tl_build
	obj_dir_seq_chip_tl/tb_seq_chip_9b_tl +seq=$(W9_SEQ) \
	  +base=$(W9_BASE) +watchdog_ms=$(W9_WD) \
	  $(if $(TL_CSV),+timeline=$(TL_CSV),)

# ======================================================================
# CHAT-SEQ gate I1 (docs/CHAT_SEQ_SPEC.md) — launch-per-step chat flow on
# the REAL RTL: (a) a second START preserves the KV / DeltaNet / conv /
# TCNT banks, (b) one pos_mode="ldc" launch at pos > 85 loads the CORRECT
# RoPE table (the XRF[4] sign-extension hazard is invisible to
# ref/seq_model.py, so it can only be shown here).
#
#   make chat_i1_gate CHAT_PY=/home/cah/.venv/bin/python     # THE gate
#
# or piecewise:
#   make chat_i1_vectors        # golden: 4 launch images + multi-launch .chip
#   make tb_seq_chat_i1         # build (own obj_dir) + run one scenario
#   make chat_i1_vectors tb_seq_chat_i1 CHAT_OUT=scripts/w4/chat_i1b \
#        CHAT_TOK0=314          # the variant (different launch-1 token)
#
# Heavy: ~54M simulated cycles / ~25 min per run.  Run it on snoke.
# ======================================================================
.PHONY: chat_i1_vectors lint_seq_chat_i1 tb_seq_chat_i1_build tb_seq_chat_i1 \
        chat_i1_gate

CHAT_DIR  ?= scripts/w4
CHAT_PY   ?= $(VECPY)
CHAT_OUT  ?= $(CHAT_DIR)/chat_i1
CHAT_BASE ?= $(CHAT_DIR)/model_v2_s1
CHAT_TMAX ?= 128
CHAT_TOK0 ?= 760
CHAT_TOK1 ?= 6511
CHAT_POS  ?= 86
CHAT_WD   ?= 600000

chat_i1_vectors:
	$(CHAT_PY) scripts/gen_chat_i1_vectors.py $(CHAT_OUT) \
	  --base $(CHAT_BASE) --t-max $(CHAT_TMAX) --tok0 $(CHAT_TOK0) \
	  --tok1 $(CHAT_TOK1) --far-pos $(CHAT_POS)

lint_seq_chat_i1:
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chat_i1_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_seq_chat_i1 -o tb_seq_chat_i1 -GNMV=$(CHIP_NMV) \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

tb_seq_chat_i1: tb_seq_chat_i1_build
	obj_dir_tb_seq_chat_i1/tb_seq_chat_i1 +seq=$(CHAT_OUT) \
	  +base=$(CHAT_BASE) +watchdog_ms=$(CHAT_WD)

# THE gate: golden + build + the deterministic scenario AND its variant
# (a different launch-1 prompt token = a second, independent stream).
CHAT_TOK0B ?= 314
CHAT_OUTB  ?= $(CHAT_DIR)/chat_i1b

chat_i1_gate:
	$(MAKE) chat_i1_vectors
	$(MAKE) chat_i1_vectors CHAT_OUT=$(CHAT_OUTB) CHAT_TOK0=$(CHAT_TOK0B)
	$(MAKE) tb_seq_chat_i1_build
	obj_dir_tb_seq_chat_i1/tb_seq_chat_i1 +seq=$(CHAT_OUT) \
	  +base=$(CHAT_BASE) +watchdog_ms=$(CHAT_WD)
	obj_dir_tb_seq_chat_i1/tb_seq_chat_i1 +seq=$(CHAT_OUTB) \
	  +base=$(CHAT_BASE) +watchdog_ms=$(CHAT_WD)

# ======================================================================
# rung 2 (docs/RUNG2_SPEC.md gate 1) — DIFFERENTIAL harnesses.
# One randomized stimulus stream drives the frozen HEAD copy in tb/legacy/
# AND the current rtl/ module, each with its own scratch / stream model;
# nothing assumes equal cycle counts.  Own --Mdir per target so these never
# race tb_vec_alu (obj_dir_tb_alu) or tb_vecnorm (obj_dir_tb_vecnorm).
# ======================================================================
.PHONY: tb_vecalu_diff tb_vecnorm_diff tb_ru2_diff

RU2SEEDS := 1 2 3 4

tb_vecalu_diff:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_vecalu_diff -o tb_vecalu_diff \
	  --top-module tb_vecalu_diff \
	  $(RTL)/fx_pkg.sv $(RTL)/vec_alu.sv legacy/vec_alu_legacy.sv \
	  tb_vecalu_diff.sv
	@for s in $(RU2SEEDS); do \
	  obj_dir_tb_vecalu_diff/tb_vecalu_diff +seed=$$s || exit 1; \
	done
	@echo "-- strict: overlap invariant fatal + write-first scratch + cfg-latch --"
	obj_dir_tb_vecalu_diff/tb_vecalu_diff +seed=1 +coll_fatal +wfirst +cfgscramble
	obj_dir_tb_vecalu_diff/tb_vecalu_diff +seed=3 +coll_fatal +wfirst +cfgscramble
	@echo "-- comparator self-test: every check MUST trip under sabotage --"
	@for k in 1 2 3 4; do \
	  if obj_dir_tb_vecalu_diff/tb_vecalu_diff +seed=1 +sabotage=$$k \
	       >/dev/null 2>&1; then \
	    echo "SELFTEST FAIL: +sabotage=$$k did NOT trip the comparator"; \
	    exit 1; \
	  fi; \
	done
	@echo "TB_VECALU_DIFF OK: 4 seeds + 2 strict + 4 comparator self-tests"

tb_vecnorm_diff:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_vecnorm_diff -o tb_vecnorm_diff \
	  --top-module tb_vecnorm_diff \
	  $(RTL)/fx_pkg.sv $(RTL)/fx_rsqrt.sv $(RTL)/vecnorm_unit.sv \
	  legacy/vecnorm_legacy.sv tb_vecnorm_diff.sv
	@for s in $(RU2SEEDS); do \
	  obj_dir_tb_vecnorm_diff/tb_vecnorm_diff +seed=$$s || exit 1; \
	done
	@echo "-- comparator self-test: every check MUST trip under sabotage --"
	@for k in 1 2 3; do \
	  if obj_dir_tb_vecnorm_diff/tb_vecnorm_diff +seed=1 +sabotage=$$k \
	       >/dev/null 2>&1; then \
	    echo "SELFTEST FAIL: +sabotage=$$k did NOT trip the comparator"; \
	    exit 1; \
	  fi; \
	done
	@echo "TB_VECNORM_DIFF OK: 4 seeds + 3 comparator self-tests"

tb_ru2_diff: tb_vecalu_diff tb_vecnorm_diff

# ======================================================================
# RUNG 3 / S5 — matvec_chan burst shim unit TB (agent B, own namespace)
# ======================================================================
# Real rtl/matvec_chan.sv (real xpm fifo + tdpram + shipped CSR file) with
# mvshim_b_stubs.sv standing in for matvec_engine / ddr_rd_streamer.
# Seeds 1-2 run ui_clk fast (300 MHz, async); seeds 3-4 run ui_clk SLOW
# (50 MHz) so the XWIN fifo genuinely fills and WREADY backpressure and the
# "never drop a burst word" rule are exercised.
.PHONY: lint_mvshim_b tb_mvshim_b_build tb_mvshim_b

lint_mvshim_b:
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan_ipi \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv \
	  $(RTL)/matvec_chan_ipi.v
	@echo "LINT_MVSHIM_B OK: -Wall clean (matvec_chan + matvec_chan_ipi)"

tb_mvshim_b_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_mvshim_b -o tb_mvshim_b \
	  --top-module tb_mvshim_b \
	  mvshim_b_stubs.sv $(RTL)/matvec_chan.sv tb_mvshim_b.sv

tb_mvshim_b: tb_mvshim_b_build
	obj_dir_tb_mvshim_b/tb_mvshim_b --seed 1 +seed=1 +verilator+rand+reset+2
	obj_dir_tb_mvshim_b/tb_mvshim_b --seed 2 +seed=2 +verilator+rand+reset+2
	obj_dir_tb_mvshim_b/tb_mvshim_b --seed 3 +seed=3 +verilator+rand+reset+2 +slowui
	obj_dir_tb_mvshim_b/tb_mvshim_b --seed 4 +seed=4 +verilator+rand+reset+2 +slowui
	@echo "-- self-test: the scoreboard MUST trip under +sabotage --"
	@if obj_dir_tb_mvshim_b/tb_mvshim_b --seed 1 +seed=1 +sabotage >/dev/null 2>&1; then \
	  echo "SELFTEST FAIL: +sabotage did NOT trip the scoreboard"; exit 1; \
	fi
	@echo "TB_MVSHIM_B OK: 4 seeds (2 fast ui_clk, 2 slow ui_clk) + sabotage self-test"

# ======================================================================
# RUNG 3 (docs/RUNG3_SPEC.md) — the BURST data plane.
#
# tb/seq_burst_fabric.sv is the AXI4 1x5 latency model standing in for
# burst_smc + its five register slices (S2), decoding the S4 map
# (mvchan_c at (c+1)<<16, layer_0 at 5<<16) onto 16-bit MI addresses.
# NB those are the BURST fabric's MI decode, not the AXI-Lite CSR map:
# docs/SEQ_ISA.md puts layer_chan at 0x5000 and mvchan c at 0x1000*(c+1).
# One binary covers the whole latency sweep: +blat=<n> overrides the LAT
# parameter at run time (0..LATMAX).  +binj_b=<n> / +binj_r=<n> turn the
# n'th write response / read beat into SLVERR, which is how the mover's
# E_AXI (0x12) path is gated.
#
#   make lint_seq_burst      -Wall lint of the fabric alone
#   make tb_bfab             fabric + S5/S6 window conformance, 4 seeds
#                            x blat 0/4/8 (routing, DECERR, SLVERR,
#                            geometry, pipelining) — no mover involved
#   make tb_seq_burst        tb_seq_unit over the burst path, every
#                            vector x blat 0/4/8, + the two E_AXI cases
# ======================================================================
.PHONY: lint_seq_burst tb_bfab_build tb_bfab tb_seq_burst

BFAB_SRC := seq_burst_fabric.sv seq_stub_mvchan.sv seq_stub_layer.sv \
            tb_burst_fabric.sv
BLATS    := 0 4 8

lint_seq_burst:
	$(VERILATOR) --lint-only -Wall --timing seq_burst_fabric.sv
	$(VERILATOR) --lint-only -Wall --timing $(BFAB_SRC) \
	  --top-module tb_burst_fabric

tb_bfab_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_bfab -o tb_bfab \
	  --top-module tb_burst_fabric $(BFAB_SRC)

tb_bfab: tb_bfab_build
	for L in $(BLATS); do for s in $(SEQ_SEEDS); do \
	  obj_dir_tb_bfab/tb_bfab +seed=$$s +blat=$$L || exit 1; done; done

tb_seq_burst: seq_unit_vectors tb_seq_build
	for L in $(BLATS); do \
	  for s in $(SEQ_SEEDS); do \
	    obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_u_s$$s +blat=$$L || exit 1; \
	  done; \
	  for e in $(SEQ_ERRS); do \
	    obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_e_$$e +blat=$$L || exit 1; \
	  done; \
	  for m in $(SEQ_MICRO); do \
	    obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_$$m +blat=$$L || exit 1; \
	  done; \
	done
	obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_movy16 +binj_r=37 +experr=18
	obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_movx   +binj_b=2  +experr=18
	obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_ldc    +binj_b=1  +experr=18
	obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_movx   +binj_r=5  +experr=18

# ======================================================================
# BM1-T1 (2026-09-24): the chip testbench carrying the BM1 idle counters
# (docs/superpowers/specs/2026-09-24-board-idle-counters-design.md §1-§3,
# docs/SEQ_ISA.md B16).  The SAME elaboration as tb_seq_chip_9b_tl_build
# (NMV=$(W9_NCH) WIMGPC=1, the census's) in its OWN obj_dir, so the census
# binary (obj_dir_seq_chip_tl) and SV1's (obj_dir_seq_chip_sv1) are never
# rebuilt by it.  Build and run ON SNOKE; one host per obj_dir.
#   make tb_seq_chip_9b_bm1_build
#   evidence/qwen9b/bm/run_bm1.sh <stem> <mode> ...     (the runner)
# lint_bm1: -Wall over every RTL file BM1 touches, alone and in the
# testbenches that instantiate them (tb_seq_unit, tb_matvec_chan,
# tb_mvshim_b), plus both IPI wrappers.
# ======================================================================
.PHONY: tb_seq_chip_9b_bm1_build lint_bm1
BM1_MDIR := obj_dir_seq_chip_bm1
tb_seq_chip_9b_bm1_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) -I$(CURDIR) \
	  --Mdir $(BM1_MDIR) -o tb_seq_chip_9b_bm1 \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 \
	  --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)

lint_bm1:
	$(VERILATOR) --lint-only -Wall --timing $(SEQ_RTL) --top-module seq_unit
	$(VERILATOR) --lint-only -Wall --timing $(SEQ_RTL) $(RTL)/seq_unit_ipi.v \
	  --top-module seq_unit_ipi
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan_ipi \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv \
	  $(RTL)/matvec_chan_ipi.v
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) -I$(CURDIR) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)
	$(VERILATOR) --lint-only -Wall --timing --top-module tb_seq_unit \
	  $(SEQ_RTL) $(SEQ_TBSRC)
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module tb_matvec_chan \
	  ../rtl/matvec_engine.sv ../rtl/ddr_rd_streamer.sv ../rtl/matvec_chan.sv tb_matvec_chan.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module tb_mvshim_b \
	  mvshim_b_stubs.sv $(RTL)/matvec_chan.sv tb_mvshim_b.sv
	@echo "LINT_BM1 OK: -Wall clean (seq_unit, seq_unit_ipi, matvec_chan, matvec_chan_ipi, tb_seq_chip NMV=$(W9_NCH), tb_seq_unit, tb_matvec_chan, tb_mvshim_b)"

# ======================================================================
# R3-8 (docs/SEQ_ISA.md v2.3 B17.3): the MOVX BROADCAST, form (a) — the
# x-push bus seq_0 -> mvchan_0..3.  Appended here so no cited line of this
# file moves; the runs themselves ride on the existing recipes:
#   * tb_seq: SEQ_ERRS gains bcast_mvgo / movx_chan5 / bcast_range,
#     SEQ_DIRECTED gains bcast bcast2..4 (tb/scripts/gen_seq_unit_vectors.py
#     build_bcast, one stream per seed), and the recipe's last line runs the
#     LOCKSTEP case SEQ_XPHOLD: <vector>:<chan>:<push #>:<cycles> — channel
#     <chan>'s stub drops room for <cycles> cycles from the <push #>-th push,
#     so every channel must stall (tb_seq_unit +xp_lowroom), one channel per
#     seed's stream;
#   * tb_matvec_chan: the push leg's runs ride on the recipe's closing line;
#   * SEQ_DEFS: `+define+R3_NO_XPUSH_PORTS` builds tb_seq_unit against a
#     seq_unit with no push ports (the RED run on the pre-R3 RTL).
# ======================================================================
SEQ_DEFS   ?=
SEQ_XPHOLD := bcast:0:16:40 bcast2:1:24:48 bcast3:2:32:40 bcast4:3:40:64

.PHONY: lint_r3
# lint_bm1's file set with the R3 top wiring: every module whose ports R3-8
# widened, both chip-TB elaborations and the three TBs that instantiate them.
lint_r3:
	$(VERILATOR) --lint-only -Wall --timing $(SEQ_RTL) --top-module seq_unit
	$(VERILATOR) --lint-only -Wall --timing $(SEQ_RTL) $(RTL)/seq_unit_ipi.v \
	  --top-module seq_unit_ipi
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module matvec_chan_ipi \
	  $(RTL)/matvec_engine.sv $(RTL)/ddr_rd_streamer.sv $(RTL)/matvec_chan.sv \
	  $(RTL)/matvec_chan_ipi.v
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) -I$(CURDIR) \
	  -GNMV=$(W9_NCH) -GWIMGPC=1 --top-module tb_seq_chip $(CHIP_RTL) $(CHIP_TBSRC)
	$(VERILATOR) --lint-only -Wall --timing --top-module tb_seq_unit \
	  $(SEQ_RTL) $(SEQ_TBSRC)
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module tb_matvec_chan \
	  ../rtl/matvec_engine.sv ../rtl/ddr_rd_streamer.sv ../rtl/matvec_chan.sv tb_matvec_chan.sv
	$(VERILATOR) --lint-only -Wall --timing $(XLIB) --top-module tb_mvshim_b \
	  mvshim_b_stubs.sv $(RTL)/matvec_chan.sv tb_mvshim_b.sv
	@echo "LINT_R3 OK: -Wall clean (seq_unit, seq_unit_ipi, matvec_chan, matvec_chan_ipi, tb_seq_chip NMV=$(W9_NCH) with and without -I, tb_seq_unit, tb_matvec_chan, tb_mvshim_b)"
