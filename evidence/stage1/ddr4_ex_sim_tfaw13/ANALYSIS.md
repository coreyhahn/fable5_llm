# DDR4 example-design sim, run 1 (upstream CSV, tFAW=13ns) — 2026-06-11

Result: calibration DONE @3.03us (sim-fast mode); AXI traffic generator
completed ALL transactions, "TEST PASSED" — data path bit-correct.
BUT the Micron DDR4 model logged 248 `cmdACT` tFAW VIOLATIONs (no other
check fired). Root cause: upstream community CSV carries tFAW=13000 ps,
which is the JEDEC x4 (1/2KB page) value; our DIMMs are 4Gb x8 (1KB page),
JEDEC tFAW=21000 ps. The MIG, configured from the CSV, legally schedules
4-ACT windows that violate the x8 part spec. Data passed in sim because the
behavioral model flags but does not corrupt; on silicon this is a latent
instability risk under ACT-heavy (short-stride random) traffic.
Fix: local CSV deviation 13000->21000 ps (synth/constraints/PROVENANCE.md);
re-sim (run 2) must show zero VIOLATION lines; bitstream rebuilt as
build_005. build_004 (tFAW=13ns) is DO-NOT-PROGRAM.
