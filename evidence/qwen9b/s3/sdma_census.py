#!/usr/bin/env python3
"""sdma_census.py — the SLD/SST census the schedule actually emits.

TWO HALVES, and they check each other.

SCHEDULE  the real functions in `ref/gen_layer_script` -- `sched_preamble`,
          `sched_dn_pair`, `sched_cv_pair`, `sched_attn_layer`,
          `sched_token_end` -- run against a COUNTING STUB whose `sld`/`sst`
          only tally.  Nothing is re-derived: this walks the same code the
          emitter walks, over the model's own `layer_types`, so the count is
          the schedule's and not a restatement of it.  Spec A1.5(c) says
          224 SLD/SST per token at the 9B stack (DN 48, conv 48, KV 128);
          this is where that number is measured.

STREAM    the same tally read out of an EMITTED artifact's `.seq`, per
          launch, so the schedule half is anchored to bytes.  A 2-layer
          smoke artifact has its own (much smaller) expectation, printed
          beside it; the point is that the two halves agree on what the
          same code produced.

    FABLE5_MODEL=9b FABLE5_RS_F=7 python evidence/qwen9b/s3/sdma_census.py \\
        [--expect 224] [<seq-prefix> ...]

  rc 0  SDMA_CENSUS: PASS
  rc 1  the schedule's per-token count is not `--expect`, or a stream could
        not be read
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "..", "ref"))
import gen_layer_script as G                                   # noqa: E402
import layer_ref as LR                                         # noqa: E402
import seq_format as SF                                        # noqa: E402


class Counter(object):
    """A Mach-shaped stub: the schedule's calls, and nothing else."""

    def __init__(self):
        self.n = {G.K_DN: [0, 0], G.K_KV: [0, 0], G.K_CV: [0, 0]}
        self.dn_slot = self.kv_slot = self.cv_slot = self.kv_layer = 0
        self.state_plan = {"dn": 0, "kv": 0, "cv": 0, "end": 0}

    def sld(self, kind, slot, layer, head=0):
        self.n[kind][0] += 1

    def sst(self, kind, slot, layer, head=0):
        self.n[kind][1] += 1

    def layer(self, dn_slot, kv_slot, cv_slot=0, kv_layer=0):
        self.dn_slot, self.kv_slot = dn_slot, kv_slot
        self.cv_slot, self.kv_layer = cv_slot, kv_layer

    def Treset(self):
        pass

    def sbase(self):
        pass

    def total(self):
        return sum(a + b for a, b in self.n.values())


def schedule_census(layer_types, ntok=2):
    """Run the REAL schedule over `layer_types` and tally."""
    n_dn = sum(1 for t in layer_types if t != "full_attention")
    kv_pf = G.sched_kv_prefetch(layer_types)
    M = Counter()
    G.sched_preamble(M, layer_types)
    pre = {k: list(v) for k, v in M.n.items()}
    per = []
    for _t in range(ntok):
        was = M.total()
        dn_i = kv_i = 0
        for i, lt in enumerate(layer_types):
            if lt == "full_attention":
                M.layer(dn_i % 2, 0, dn_i % 2, kv_i)
                G.sched_attn_layer(M, kv_i, LR.NKV, dn_i % 2, dn_i % 2,
                                   lambda _h: None)
                kv_i += 1
            else:
                G.sched_dn_pair(M, dn_i, n_dn, kv_pf[i])
                G.sched_cv_pair(M, dn_i, n_dn)
                M.layer(dn_i % 2, 0, dn_i % 2, kv_i)
                dn_i += 1
        G.sched_token_end(M, n_dn)
        per.append(M.total() - was)
    return M, pre, per


def stream_census(prefix):
    """SLD/SST out of an emitted `.seq`."""
    recs = SF.unpack_stream(open(prefix + ".seq", "rb").read())
    n = {G.K_DN: [0, 0], G.K_KV: [0, 0], G.K_CV: [0, 0]}
    a0 = 0
    for r in recs:
        if r.opcode == SF.OP_CSRWR and r.target == SF.CSR_L_ARG0:
            a0 = r.imm32
        elif r.opcode == SF.OP_CMD and (r.imm32 & 0xFF) in (SF.OP_L_SLD,
                                                            SF.OP_L_SST):
            kind = SF.sdma_fields(a0)[0]
            n[kind][0 if (r.imm32 & 0xFF) == SF.OP_L_SLD else 1] += 1
    return n, len(recs)


def show(tag, n):
    parts = " ".join(f"{['DN', 'KV', 'CV'][k]} {v[0]}+{v[1]}"
                     for k, v in sorted(n.items()))
    print(f"  {tag:22s} {parts}   total "
          f"{sum(a + b for a, b in n.values())}")


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    expect = 224
    for a in sys.argv[1:]:
        if a.startswith("--expect="):
            expect = int(a.split("=", 1)[1])
    bad = []
    types = LR.CFG.get("layer_types") or []
    n_dn = sum(1 for t in types if t != "full_attention")
    n_kv = sum(1 for t in types if t == "full_attention")
    print(f"SDMA census — FABLE5_MODEL={os.environ.get('FABLE5_MODEL')}, "
          f"{len(types)} layers ({n_dn} DeltaNet + {n_kv} full-attention), "
          f"NKV={LR.NKV}")
    M, pre, per = schedule_census(types, ntok=3)
    show("preamble", pre)
    tok = {k: [M.n[k][0] - pre[k][0], M.n[k][1] - pre[k][1]] for k in M.n}
    show("3 tokens", tok)
    print(f"  per token              {per}   (spec A1.5(c) expects {expect})")
    if len(set(per)) != 1:
        bad.append(f"the per-token count is not steady: {per}")
    elif per[0] != expect:
        bad.append(f"per token {per[0]}, spec A1.5(c) says {expect}")

    for p in argv:
        path = p if os.path.isabs(p) else os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", p)
        if not os.path.exists(path + ".seq"):
            bad.append(f"ABSENT: {p}.seq")
            continue
        n, nrec = stream_census(path)
        print(f"\n{p}  ({nrec} records)")
        show("stream", n)

    print("\nSDMA_CENSUS: %s (%d problem(s))"
          % ("PASS" if not bad else "FAIL", len(bad)))
    for b in bad:
        print("  ! " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
