# SAMPLING — FROZEN SPEC (2026-08-11): host-f32 head, path D

## USER RULING (2026-08-11, supersedes S1/S2 as the SHIPPED path)

"Keep on the chip." Model compute stays on the FPGA: the shipped
sampling design is a chip TOP-K capture unit (k=32 {value,index}
pairs maintained during the existing on-chip LM-head AMAX scan,
CSR-readable post-halt) delivered by the NEXT RTL RUNG together with
the row-bubble fix and argmax-combine. The host's only role is the
dice roll among chip-provided scores (dequant + softmax + seeded RNG
over k values — microseconds, no model compute). Path D (host-f32
head) is DEMOTED to a verification-only utility (--verify-head).
Est. sampled step = full launch 63.2 ms + ~0.3 ms readout+math.
This project's software half ships now (sampler math, flags, serve
fields, fixture-tested, refusal until the TOPK bitstream); the RTL
half rides the rung-4 build. S3-S7 remain in force where applicable.

Investigation verdict (measured on the real head image): host BLAS f32
LM head from a resident copy = 9.10 ms GEMV; sampled step = lite 45.0
+ x8 readback 1.75 + GEMV 9.10 + sample 0.92 = **56.8 ms/token — 6.4 ms
FASTER than greedy** (63.2). Fidelity: argmax identical, top-100 SET
identical, top-50 ORDER identical vs the chip's exact integers (max rel
err 2.86e-6; 570x smaller than the 49-50th logit gap). Paths A/B/C are
dead by measurement/RTL fact (RES_DATA is a single MMIO CSR; no
RES/scratch->DDR record exists; only ONE global AMAX winner exists and
AMAXV is unreachable from any record).

CHARTER NOTE (user-visible): in sampling mode the LM head (~1/24 of
the FLOPs) runs on the HOST. Greedy remains 100% on-chip, bit-exact,
and the default. --verify-head cross-checks host-vs-chip per step.

## Frozen decisions S1-S8

S1 Sampled decode = lite launch EVERY step + host head. Greedy = full
   launch, on-chip AMAX, untouched. Mode folds into the existing lite
   decision (chat_seq.py ~:1331, serve.py ~:1015); _launch unchanged;
   token patch already accepts any id (seq_chat.py:604-611); the
   greedy token still comes from the SEQ OUT FIFO, never AMAXI.
S2 Host head: f32 dense built ONCE per session from the committed DDR
   head image (w186, 1017 MB f32, 12.65 s build; cache to LOCAL disk
   e.g. /tmp or ~/.cache — NOT the NFS share). OPENBLAS_NUM_THREADS
   pinned to 16.
S3 DETERMINISM: BLAS reduction order is thread-unstable -> take
   top-(k+8) by f32, RESCORE those rows in exact integer arithmetic
   (~0.14 ms), then softmax/sample on the rescored values. Seeded
   np.random.default_rng; seed recorded in stats and --out reports.
S4 Dequant: logit = y32 * 2^(e_x - 22) for the head (e=-4, sh=5,
   RS_F=8; gen_layer_script.py:566 shift_for). e_x read from L_EOUT
   [3:0] post-halt; x8 = scratch[0x800..0xBFF], one int8 per 16b word,
   read via SPTR/SWIN post-halt ONLY (never while SEQ busy), BEFORE
   issuing the next launch.
S5 Sampler: --temp T (default off => greedy), --top-k (default 50),
   --top-p via top-512 prefilter (0.62 ms; never the 7 ms full
   argsort). Flags in chat_seq; temperature/top_k/top_p/seed request
   fields in serve.
S6 --verify-head: full launches + host head in parallel; host argmax
   MUST equal the chip FIFO token every step (the continuous
   chip-vs-host cross-check; +11.8 ms/step).
S7 x8 survives full launches (head writes STG 0x1000+) — S6 relies on
   this; assert the invariant in a selftest against the body layout.
S8 No RTL, no stream changes, no new artifacts. On-chip sampling
   enablers (AMAXL pushing {AMAXV,AMAXI}, deeper OUT FIFO, of_cnt race
   fix) are logged for the next RTL rung, not this project.

## Gates

G1 selftests (board-free): sampler math vs numpy references
   (temperature/top-k/top-p distributions), seed determinism, integer
   rescore == w4a8_ref exact scores on synthetic vectors, greedy path
   byte-identical with no flags, f32-build correctness vs the image
   (spot rows), S7 layout assert.
G2 model-only: sampled trajectory with fixed seed reproduced twice
   (host math only, seq_model provides the hidden states? — if too
   slow, gate on the sampler consuming a canned x8/e_x fixture with
   provenance).
G3 HW (integrator, WHEN THE BOARD RETURNS): --verify-head over a
   2-turn session (every host argmax == chip token); sampled 2-run
   fixed-seed determinism; greedy canned regression unchanged;
   qualitative repetition-prompt transcript greedy vs sampled;
   measured ms/token vs the 56.8 projection. Evidence ->
   evidence/sampling/.

## File ownership (one Opus agent)

sw/chat_seq.py + sw/serve.py only (import-shared sampler class in
chat_seq). Head-cache builder may be a small standalone
sw/head_cache.py if cleaner. No ref/, no rtl/, no tb/.
