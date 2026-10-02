#!/usr/bin/env python3
"""G4b Step 2 — the OBSERVED maximum |p_acc| over the REAL 9B stream.

`p_acc` is `rtl/matvec_engine.sv:561` `logic signed [47:0] p_acc`, the row
accumulator, accumulated at `rtl/matvec_engine.sv:675` and consumed by the
single `rshift_round` at R1/R2.  Its reference twin is the local `p` of
`ref/w4a8_ref.py`'s `matvec_y32` -- the SAME quantity, by construction:
that function's docstring is explicit that the RTL is built to its accumulate
order and that nothing truncates before `sh`, and G4a section 5.3 replayed
the whole 9B model through both bit-exactly.

So the measurement is: replay `<prefix>.e4` through `ref/seq_model.SeqExec`
-- the SAME executor `tb/scripts/gen_seq_chip_vectors.py` uses to build the
`.chip` golden the RTL is checked against -- with `rshift_round` SPIED ON
for the duration of each matvec.  Spying on `rshift_round` rather than
recomputing `p` is deliberate: it captures the accumulator the reference
actually formed, so this file re-derives no arithmetic and cannot drift from
`matvec_y32`.

Reported against the 48-bit container, beside the two MODELLED bounds:
  * the RTL header's own worst case (`rtl/matvec_engine.sv:72-77`)
    MAX_NG * 65535 * 131072 = 8.25e11 at MAX_NG = 96 -> 41 magnitude bits,
    7 spare;
  * the study's arithmetic quoted by the Task 12 brief, ~45 of 48 at
    K = 12288.
Neither is a measurement.  This is.

Usage (on snoke, with numpy):
  python3 evidence/qwen9b/g4/g4b_pacc_probe.py tb/scripts/w9/model_9b_s1.e4 \\
      --base tb/scripts/w9/model_9b_s1
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ref"))
sys.path.insert(0, os.path.join(ROOT, "tb", "scripts"))

import seq_format as SF                                        # noqa: E402
import seq_model as SM                                         # noqa: E402
import w4a8_ref as W4                                          # noqa: E402
import hwmap as HW                                             # noqa: E402


class PaccSpy:
    """Wraps w4a8_ref.rshift_round for the duration of one matvec call."""

    def __init__(self):
        self.max_abs = 0
        self.n_rows = 0
        self.n_calls = 0
        self.worst = None          # (wid, nrows, K, NG, sh, max|p|)

    def install(self, mod, name, tag_fn):
        orig = getattr(mod, name)
        real_rr = W4.rshift_round

        def wrapper(*a, **kw):
            seen = {"mx": 0, "n": 0}

            def spy(p, sh):
                # p is int64 and bounded by 8.25e11, so int64 abs cannot
                # overflow; no object dtype needed.
                seen["mx"] = max(seen["mx"], int(np.abs(p).max()))
                seen["n"] += int(np.size(p))
                return real_rr(p, sh)

            W4.rshift_round = spy
            try:
                out = orig(*a, **kw)
            finally:
                W4.rshift_round = real_rr
            self.n_calls += 1
            self.n_rows += seen["n"]
            if seen["mx"] > self.max_abs:
                self.max_abs = seen["mx"]
                self.worst = tag_fn(a, kw, seen["mx"])
            return out

        setattr(mod, name, wrapper)


def mag_bits(v):
    return int(v).bit_length()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--base", default=None)
    a = ap.parse_args()
    base = a.base or a.prefix

    meta = json.load(open(a.prefix + ".seq.json"))
    stream = open(a.prefix + ".seq", "rb").read()
    blob = open(a.prefix + ".seqdata.bin", "rb").read()
    recs = SF.unpack_stream(stream)
    SF.validate_stream(recs, shape_isa=meta.get("shape_isa"))

    emb = None
    emb_row_bytes = HW.load_weights_manifest(base)[1]["emb_row_bytes"]
    embf = base + ".emb.bin"
    if os.path.exists(embf):
        nrow = os.path.getsize(embf) // emb_row_bytes
        emb = np.memmap(embf, dtype="<i2", mode="r").reshape(
            nrow, emb_row_bytes // 2)

    W = SM.DDRWeights.from_files(base, meta["weights"], meta)

    spy = PaccSpy()

    def tag(args, kw, mx):
        w = args[0]
        m = args[1]
        sh = args[2]
        N, K = w.shape
        return dict(N=int(N), K=int(K), NG=int(m.shape[1]), sh=int(sh),
                    max_abs=int(mx))

    # seq_model imported the two entry points by name, so BOTH are patched
    # there.  (matvec_y32_w8 delegates to w4a8_ref.matvec_y32, whose inner
    # rshift_round is the module global the spy replaces, so the w8 path is
    # covered either way; the 9B stream is W4 only.)
    spy.install(SM, "matvec_y32", tag)
    spy.install(SM, "matvec_y32_w8", tag)

    print(f"PACC replaying {a.prefix}: {len(recs)} records")
    ex = SM.SeqExec(recs, blob, W, emb=emb).run(max_steps=50 * len(recs))
    print(f"PACC seq_model stats: {ex.stats}")

    mx = spy.max_abs
    bits = mag_bits(mx)
    # the two MODELLED bounds, restated here so the log carries what the
    # measurement is being judged against
    rtl_bound = 96 * 65535 * 131072
    print(f"PACC matvec calls          : {spy.n_calls}")
    print(f"PACC rows accumulated      : {spy.n_rows}")
    print(f"PACC OBSERVED max |p_acc|  : {mx}")
    # Say this unambiguously: `bits` is the MAGNITUDE width, the container is
    # signed 48-bit, so the occupancy is bits + 1 of 48 and the headroom is
    # 47 - bits magnitude bits.  An earlier revision printed "{bits} of 48
    # (sign + {bits}, ...)", which read as if {bits} already included the sign.
    print(f"PACC OBSERVED magnitude bits: {bits}  ->  occupancy "
          f"{bits} + 1 sign = {bits + 1} of 48, headroom {47 - bits} "
          f"of 47 magnitude bits")
    print(f"PACC worst matvec          : {spy.worst}")
    print(f"PACC RTL header bound      : {rtl_bound} "
          f"= {mag_bits(rtl_bound)} magnitude bits "
          f"(rtl/matvec_engine.sv:72-77, MODELLED)")
    print(f"PACC study arithmetic      : ~45 of 48 at K=12288 (MODELLED, "
          f"Task 12 brief)")
    print(f"PACC observed / RTL bound  : {mx / rtl_bound:.3e}")
    if mx >= (1 << 47):
        print("PACC VERDICT: OVERFLOW — |p_acc| does not fit the signed 48-bit container")
        return 1
    print(f"PACC VERDICT: FITS — {bits} magnitude bits used, "
          f"{47 - bits} of 47 spare")
    return 0


if __name__ == "__main__":
    sys.exit(main())
