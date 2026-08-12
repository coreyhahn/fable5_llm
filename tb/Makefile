# Testbench Makefile — Verilator sims for fable5_llm
# Usage: make tb_csr   (or just `make`)
# Each TB gets its own --Mdir to allow parallel builds.

VERILATOR ?= verilator
JOBS ?= 4
THREADS ?= 4

RTL := ../rtl

.PHONY: all tb_csr lint clean lint_seq_unit seq_unit_vectors tb_seq_build tb_seq tb_seq_lat tb_seq_sideband tb_seq_all \
        v2_vectors ng_vectors tb_matvec_build tb_matvec_g64 tb_matvec_ng

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

tb_matvec:
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s1 101 64 1024
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s2 202 32 3584
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s3 303 128 256
	$(VECPY) ../ref/gen_matvec_vectors.py vec_s4 404 16 2048
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_matvec -o tb_matvec \
	  --top-module tb_matvec \
	  $(RTL)/matvec_engine.sv tb_matvec.sv
	obj_dir_tb_matvec/tb_matvec --seed 1 +vecdir=vec_s1
	obj_dir_tb_matvec/tb_matvec --seed 2 +vecdir=vec_s2
	obj_dir_tb_matvec/tb_matvec --seed 3 +vecdir=vec_s3
	obj_dir_tb_matvec/tb_matvec --seed 4 +vecdir=vec_s4

lint_matvec:
	$(VERILATOR) --lint-only -Wall --timing $(RTL)/matvec_engine.sv

# ======================================================================
# v2 row format (W4 group size 64) — matvec_engine cfg_g64 / SHAPE bit 28
# ======================================================================
# Vectors come from tb/scripts/gen_matvec_v2_vectors.py (ref/w4a8_ref.py is
# still the numerics; ref/gen_matvec_vectors.py stays frozen at g=128 and
# its 5-field params.txt).  Shape spec: name:NROWS:K:seedbase — one dir per
# (shape, seed, mode) as vecv2/<name><seed>_g<128|64>, so every g64 case has
# a same-shape g128 twin for the throughput comparison.
#
#   a  K=1024 NG=8   NG64=16  1 scale beat
#   b  K=3584 NG=28  NG64=56  2 scale beats, ODD nrows (37)
#   c  K=4096 NG=32  NG64=64  2 scale beats, FULL scale buffer, odd nrows
#   d  K=2048 NG=16  NG64=32  1 scale beat (the NG=16 boundary)
#   e  K=128  NG=1   NG64=2   minimum NG (tightest drain tree-flush margin)
V2SHAPES := a:64:1024:1100 b:37:3584:2200 c:13:4096:3300 \
            d:16:2048:4400 e:9:128:5500
V2SEEDS  := 1 2 3 4

# RUNG 4 S2 — the SMALL-NG directed set: NG = 1,2,3,4 is the regime where a
# row is shorter than the retire pipeline, so the scale-beat stall guard (a
# sanctioned 1-2 cyc/row) is the only thing that can show up.  Enough rows in
# each case that the steady state, not the first/last row, dominates.
NGSHAPES := n1:23:128:6100 n2:24:256:6200 n3:17:384:6300 n4:31:512:6400

v2_vectors:
	@for sp in $(V2SHAPES); do \
	  nm=$${sp%%:*}; r=$${sp#*:}; n=$${r%%:*}; r=$${r#*:}; \
	  k=$${r%%:*}; sb=$${r#*:}; \
	  for s in $(V2SEEDS); do for g in 128 64; do \
	    $(VECPY) scripts/gen_matvec_v2_vectors.py \
	      vecv2/$${nm}$${s}_g$${g} $$(($$sb + $$s)) $$n $$k $$g || exit 1; \
	  done; done; \
	done

ng_vectors:
	@for sp in $(NGSHAPES); do \
	  nm=$${sp%%:*}; r=$${sp#*:}; n=$${r%%:*}; r=$${r#*:}; \
	  k=$${r%%:*}; sb=$${r#*:}; \
	  for s in $(V2SEEDS); do for g in 128 64; do \
	    $(VECPY) scripts/gen_matvec_v2_vectors.py \
	      vecv2/$${nm}$${s}_g$${g} $$(($$sb + $$s)) $$n $$k $$g || exit 1; \
	  done; done; \
	done

# Own --Mdir / binary name so concurrent workstreams never race on NFS:
#   make tb_matvec_g64 MVDIR=obj_dir_tb_matvec_d MVBIN=tb_matvec_d
MVDIR ?= obj_dir_tb_matvec
MVBIN ?= tb_matvec

tb_matvec_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir $(MVDIR) -o $(MVBIN) \
	  --top-module tb_matvec \
	  $(RTL)/matvec_engine.sv tb_matvec.sv

# g64 unit gate.  Every run puts SEVERAL cases through ONE engine instance
# with no reset between them, so each is also a quasi-static-reconfig test.
#   1. correctness, all 5 shapes, 4 seeds, random gaps + result backpressure
#   2. MIXED: mode 0 and mode 1 matvecs alternating on the same instance
#   3. chunked rows: chunk=5 against nrows 37/13/9 (uneven last chunk)
#   4. throughput: g128/g64 pairs, no gaps, no backpressure.  +pairs asserts
#      the g64 run costs no more than the g128 run plus its extra scale
#      beats (i.e. the drain never becomes the bottleneck).
#
#      RUNG 4 (S1 tagged retire pipeline): the bound is now +maxstall=0 for
#      NG > 4 and a row-PERIOD floor of +ngfloor=6 for the small-NG shape e
#      (NG=1), which is the S2 single-scale-bank guard.  It was
#      +maxstall=9 in rung 3 (the "NG+10" row period) — the measured rung-3
#      numbers this replaced are evidence/rung4/mv_baseline_rung3.log.
tb_matvec_g64: v2_vectors tb_matvec_build
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/a$${s}_g64,vecv2/b$${s}_g64,vecv2/c$${s}_g64,vecv2/d$${s}_g64,vecv2/e$${s}_g64 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/a$${s}_g128,vecv2/a$${s}_g64,vecv2/b$${s}_g64,vecv2/b$${s}_g128,vecv2/e$${s}_g64,vecv2/c$${s}_g128,vecv2/c$${s}_g64,vecv2/d$${s}_g64,vecv2/e$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=5 \
	    +vecdirs=vecv2/b$${s}_g64,vecv2/c$${s}_g64,vecv2/e$${s}_g64,vecv2/a$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +nogap +pairs \
	    +maxstall=$(MVMAXSTALL) +ngfloor=$(MVNGFLOOR) \
	    +vecdirs=vecv2/a$${s}_g128,vecv2/a$${s}_g64,vecv2/b$${s}_g128,vecv2/b$${s}_g64,vecv2/c$${s}_g128,vecv2/c$${s}_g64,vecv2/d$${s}_g128,vecv2/d$${s}_g64,vecv2/e$${s}_g128,vecv2/e$${s}_g64 || exit 1; \
	done

# RUNG 4 gate bounds (overridable so the rung-3 baseline can be re-measured
# on the same TB:  make tb_matvec_g64 MVMAXSTALL=9 MVNGFLOOR=99).
#   MVMAXSTALL  stall cycles/row allowed when NG > 4.  ZERO: agent A's
#               retire pipeline has no exposed bubble at all on any shape
#               with NG >= 5, and every production shape is NG in {8,16,28}
#               (K = 1024/2048/3584).  Measured on all 4 seeds x both modes.
#   MVNGFLOOR   row-period floor allowed when NG <= 4.  The S2
#               single-scale-bank guard floors the period at 6 cycles, so
#               the sanctioned bubble is exactly 6-BPR = 5-NG (4/3/2/1 for
#               NG=1/2/3/4) — matvec_engine.sv's own law, checked per shape
#               rather than as a flat count, so NG=4 is still held to 1.
MVMAXSTALL ?= 0
MVNGFLOOR  ?= 6

# RUNG 4 S2 directed small-NG gate: NG = 1,2,3,4 in BOTH modes, correctness
# with random gaps + backpressure first, then the same shapes with no gaps
# so the scale-beat stall guard is measured in isolation.  Chunked-row runs
# too: at NG<=4 a chunk boundary lands every few beats, which is where a
# retire pipeline that mis-tags `first`/`last` breaks.
tb_matvec_ng: ng_vectors tb_matvec_build
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n1$${s}_g64,vecv2/n2$${s}_g128,vecv2/n2$${s}_g64,vecv2/n3$${s}_g128,vecv2/n3$${s}_g64,vecv2/n4$${s}_g128,vecv2/n4$${s}_g64 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=1 \
	    +vecdirs=vecv2/n1$${s}_g64,vecv2/n2$${s}_g128,vecv2/n3$${s}_g64,vecv2/n4$${s}_g128 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +chunk=3 \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n2$${s}_g64,vecv2/n3$${s}_g128,vecv2/n4$${s}_g64 || exit 1; \
	done
	for s in $(V2SEEDS); do \
	  $(MVDIR)/$(MVBIN) --seed $$s +nogap +pairs \
	    +maxstall=$(MVMAXSTALL) +ngfloor=$(MVNGFLOOR) \
	    +vecdirs=vecv2/n1$${s}_g128,vecv2/n1$${s}_g64,vecv2/n2$${s}_g128,vecv2/n2$${s}_g64,vecv2/n3$${s}_g128,vecv2/n3$${s}_g64,vecv2/n4$${s}_g128,vecv2/n4$${s}_g64 || exit 1; \
	done
	@echo "TB_MATVEC_NG OK: NG 1..4 x {g128,g64} x 4 seeds — random, chunk=1, chunk=3, nogap+pairs"

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
	  --Mdir obj_dir_tb_chan -o tb_chan \
	  --top-module tb_matvec_chan \
	  ../rtl/matvec_engine.sv ../rtl/ddr_rd_streamer.sv ../rtl/matvec_chan.sv tb_matvec_chan.sv
	obj_dir_tb_chan/tb_chan --seed 1 +vecdir=vec_s1
	obj_dir_tb_chan/tb_chan --seed 2 +vecdir=vec_s2
	obj_dir_tb_chan/tb_chan --seed 3 +vecdir=vec_s3
	obj_dir_tb_chan/tb_chan --seed 4 +vecdir=vec_s4

# same full CSR/DMA chain, driving SHAPE bit 28 from the vector dir's 6th
# params field (the tb reads it back to prove the bit round-trips).
tb_matvec_chan_build:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall $(XLIB) \
	  --Mdir obj_dir_tb_chan -o tb_chan \
	  --top-module tb_matvec_chan \
	  ../rtl/matvec_engine.sv ../rtl/ddr_rd_streamer.sv ../rtl/matvec_chan.sv tb_matvec_chan.sv

tb_matvec_chan_g64: v2_vectors tb_matvec_chan_build
	for s in $(V2SEEDS); do \
	  for nm in a b c d e; do \
	    obj_dir_tb_chan/tb_chan --seed $$s +vecdir=vecv2/$${nm}$${s}_g64 || exit 1; \
	  done; \
	done

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
# NOTE the "_c_" in the generator name: tb/scripts/gen_seq_vectors.py and
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
  $(RTL)/gate_unit.sv $(RTL)/vec_alu.sv $(RTL)/layer_chan.sv

# Python used by the script generators, evaluated AFTER `cd ../ref`:
#   darthplagueis  .venv/bin/python           (default)
#   snoke          /home/cah/.venv/bin/python (ref/.venv's interpreter
#                  lives under ~/.local/share/uv, which is not NFS-shared)
GENPY ?= .venv/bin/python

# ---- FROZEN back-compat sets ------------------------------------------
# tb/scripts/layer_s* and token_s* are COMMITTED stage-3/4 evidence built by
# the pre-Phase-1A generator.  The generator has since moved to the Phase-1A
# datapath, so `layer_scripts` / `token_scripts` would NOT reproduce the
# committed bytes.  They stay as the LAYER=0 back-compat regression set and
# must keep passing UNMODIFIED (nothing in the RTL changed) — run
# `make tb_layer_chan` / `make tb_token` against the committed files, do not
# regenerate.  The recipes below are deliberately fenced off.
layer_scripts token_scripts:
	@echo "REFUSED: $@ would overwrite committed pre-Phase-1A evidence."; \
	 echo "  They are the frozen back-compat set (see evidence/stage3,"; \
	 echo "  evidence/stage4). Regenerate only from git history 229c033."; \
	 false

tb_layer_chan:
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_layer -o tb_layer \
	  --top-module tb_layer_chan \
	  $(LAYER_RTL) tb_layer_chan.sv
	obj_dir_tb_layer/tb_layer +script=scripts/layer_s1.txt
	obj_dir_tb_layer/tb_layer +script=scripts/layer_s2.txt
	obj_dir_tb_layer/tb_layer +script=scripts/layer_s3.txt
	obj_dir_tb_layer/tb_layer +script=scripts/layer_s4.txt

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
SEQ_ERRS  := op ind chan jmp xopsgn csrsp rsvd
SEQ_MICRO := csrwr cmd movx movy16 movy32 ldc

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
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_seq -o tb_seq \
	  --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC)

tb_seq: seq_unit_vectors tb_seq_build
	for s in $(SEQ_SEEDS); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; done
	for e in $(SEQ_ERRS); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_e_$$e || exit 1; done
	for m in $(SEQ_MICRO); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_m_$$m || exit 1; done

tb_seq_lat: seq_unit_vectors
	for L in 0 8; do \
	  $(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	    --Mdir obj_dir_tb_seq_l$$L -o tb_seq_l$$L -GLAT=$$L \
	    --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC) || exit 1; \
	  for s in $(SEQ_SEEDS); do \
	    obj_dir_tb_seq_l$$L/tb_seq_l$$L +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; \
	  done; \
	  for m in $(SEQ_MICRO); do \
	    obj_dir_tb_seq_l$$L/tb_seq_l$$L +vec=$(SEQ_VEC)/seq_m_$$m || exit 1; \
	  done; \
	done

tb_seq_sideband: seq_unit_vectors
	$(VERILATOR) --binary --timing -j $(JOBS) -Wall \
	  --Mdir obj_dir_tb_seq_sb -o tb_seq_sb "-GSIDEBAND=1'b1" \
	  --top-module tb_seq_unit $(SEQ_RTL) $(SEQ_TBSRC)
	for s in $(SEQ_SEEDS); do \
	  obj_dir_tb_seq_sb/tb_seq_sb +vec=$(SEQ_VEC)/seq_u_s$$s || exit 1; done

tb_seq_all: lint_seq_unit tb_seq tb_seq_lat tb_seq_sideband

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

OF_N      := 24 64 80
OF_PHASES := 0 1 2 3 4 5 6 7

tb_seq_offifo: seq_unit_vectors tb_seq_build
	@echo "-- depth 64 + sticky of_ovf, no concurrent pops --"
	for n in $(OF_N); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n || exit 1; done
	@echo "-- the SAME streams over the burst fabric at blat 0/8 --"
	for L in 0 8; do for n in $(OF_N); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n +blat=$$L || exit 1; \
	done; done
	@echo "-- directed push/pop race: 8 pop phases x 3 streams --"
	@echo "   (FAILS on rtl/seq_unit.sv as of 2026-08-11: a read of OUT_FIFO"
	@echo "    that reports EMPTY still pops one cycle later if an AMAXL push"
	@echo "    landed on the read's accept edge.  PRE-EXISTING, also present"
	@echo "    at HEAD.  Fix + evidence: evidence/rung4/S6_out_fifo_pop_race.patch,"
	@echo "    evidence/rung4/gate_seq_offifo.log section F.)"
	for p in $(OF_PHASES); do for n in $(OF_N); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_f_of$$n +ofrace +ofphase=$$p \
	    || exit 1; \
	done; done
	@echo "-- race on the normal streams too (their AMAXLs sit mid-stream) --"
	for p in 0 3; do for s in $(SEQ_SEEDS); do \
	  obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_u_s$$s +ofrace +ofphase=$$p \
	    || exit 1; \
	done; done
	@echo "-- self-test: the depth check MUST trip if the TB is told 16 --"
	@if obj_dir_tb_seq/tb_seq +vec=$(SEQ_VEC)/seq_f_of24 +ofdepth=16 \
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
