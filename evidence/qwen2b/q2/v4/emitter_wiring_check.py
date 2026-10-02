#!/usr/bin/env python3
"""Does the DDR image generator's calibration wiring actually RESOLVE?

Task 8b's review found the emitters unwired: `gen_model_script` called
`quant_layer` with no `layer_idx` (a hard SystemExit with the plumb on) and
quantized the LM head with no calibration arguments at all (a *silently*
unweighted head under a calibrated name).  Both are now wired.  This checks
the wiring against the REAL 2B calibration file, which is the part inspection
cannot do: that every argument the emitter now passes resolves to real data,
for every layer index it will use, with the right length.

It deliberately does NOT emit an image (that is ~30 min and gigabytes at 2B);
what it proves is that the lookups the emitter performs succeed and are the
same objects the scored quantizer consumed.  The quantizer behind them is the
one `fidelity_check` ran end to end for 1 h 50 m (`fixed_v4gptq_g64_S4.log`).

    FABLE5_MODEL=2b FABLE5_CALIB_STATS=ref/calib_stats_2b_h.npz \\
      FABLE5_CALIB_MODE=gptq python3 evidence/qwen2b/q2/v4/emitter_wiring_check.py
"""
import json
import os
import socket
import sys

REF = "/home/cah/r2d2/code/fpga/fable5_llm/ref"
sys.path.insert(0, REF)

import numpy as np                                              # noqa: E402
import calib_stats as CS                                        # noqa: E402
import layer_fixed as LF                                        # noqa: E402
import load_qwen35 as LQ                                        # noqa: E402


def main():
    print(f"host {socket.gethostname()}  mode={LF.CALIB_MODE}  "
          f"stats={LF.CALIB_STATS or '<unset>'}")
    if not LF.CALIB_STATS:
        raise SystemExit("set FABLE5_CALIB_STATS (and FABLE5_CALIB_MODE) — "
                         "this checks the CALIBRATED path")
    cfg = dict(LQ.load_config())
    cfg = cfg.get("text_config", cfg)
    types = list(cfg["layer_types"])
    n = len(types)
    print(f"geometry: {n} layers "
          f"({sum(t != 'full_attention' for t in types)} DN / "
          f"{sum(t == 'full_attention' for t in types)} GQA), H={cfg['hidden_size']}")

    # exactly what gen_model_script's loop now asks for, per layer
    ok = nsal = nhess = 0
    for i, lt in enumerate(types):
        sub = "attn" if lt == "full_attention" else "dn"
        for s in (sub, "mlp"):
            for wk in CS.SUFFIX[s]:
                sal, hess = LF._calib_for(s, wk, i)
                assert (sal is None) != (hess is None), (s, wk, i)
                if sal is not None:
                    nsal += 1
                    assert sal.ndim == 1 and np.all(np.isfinite(sal)), (s, wk, i)
                else:
                    nhess += 1
                    assert hess.U.shape == (hess.K, hess.K), (s, wk, i)
                    assert hess.diag.shape == (hess.K,), (s, wk, i)
                ok += 1
    print(f"layer weights: {ok} lookups over layers 0..{n - 1} all resolved "
          f"({nsal} salience vectors, {nhess} Hessian factors)")

    # and what the head path now asks for
    hs, hh = LF.calib_salience("lm_head"), LF.calib_hess("lm_head")
    assert (hs is None) != (hh is None)
    K = int(cfg["hidden_size"])
    got = hs.shape[0] if hs is not None else hh.K
    assert got == K, (got, K)
    print(f"lm_head: {'salience' if hs is not None else 'Hessian'} resolved, "
          f"K={got} == hidden_size")

    # the emitter must be reading the same file the scored runs read
    sha = CS.meta(LF.CALIB_STATS)
    print(f"npz provenance: model_tag={sha.get('model_tag')} "
          f"tokens={sha.get('n_tokens_hooked')} sites={sha.get('n_sites')} "
          f"hessian={sha.get('hessian')} host={sha.get('host')}")
    print(json.dumps({"layer_lookups": ok, "salience": nsal, "hessian": nhess,
                      "head": "ok"}, sort_keys=True))
    print("\nEMITTER_WIRING_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
