#!/usr/bin/env python3
"""Derive every number in evidence/qwen2b/q2/sensitivity/SENSITIVITY.md.

Reads only committed artifacts — the Task-7 scan jsons, the bf16 anchor, the
V1/V2 jsons, and the per-family W4 error table of `ref/audit_ranges_2b_report.md`
section 2 — and prints the ranked table, the rank correlations (with exact
permutation p-values), the bytes/token table, the sum-vs-joint cross-check and
the re-run agreement.  Nothing is hardcoded except the family->class map.

    python3 ref/scripts/rank_sensitivity.py
"""
import itertools
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCAN = os.path.join(REPO, "evidence/qwen2b/q2/sensitivity")
W4 = ["qkv", "o_proj", "gate_up", "down", "dn_in", "dn_out", "lm_head"]
ALL = W4 + ["emb"]
# audit section-2 matrix family -> injection class
FAMILY = {"dn.in_qkv": "dn_in", "dn.in_z": "dn_in", "dn.in_b": "dn_in",
          "dn.in_a": "dn_in", "dn.out": "dn_out", "mlp.gate": "gate_up",
          "mlp.up": "gate_up", "mlp.down": "down", "attn.q_proj": "qkv",
          "attn.k_proj": "qkv", "attn.v_proj": "qkv", "attn.o_proj": "o_proj",
          "lm_head": "lm_head"}
W8_IDEAL_BPW = 8 + 16 / 128        # FLOOR only; Task 9 owns the packed rate


def load(p):
    with open(p) as f:
        return json.load(f)


def rank(vals):
    """Descending midranks (rank 1 = largest).  Ties share the mean rank —
    `lm_head` and `emb` are two images of the SAME tied matrix and so have
    byte-identical parameter counts; arbitrary tie-breaking there would
    manufacture a correlation."""
    order = sorted(vals, key=lambda c: -vals[c])
    out, i = {}, 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = mid
        i = j + 1
    return out


def spearman(a, b):
    """Pearson correlation of the (mid)ranks — the tie-correct definition.
    Reduces to 1 - 6*sum(d^2)/(n^3-n) when no ranks are tied."""
    keys = list(a)
    n = len(keys)
    ma, mb = sum(a[c] for c in keys) / n, sum(b[c] for c in keys) / n
    num = sum((a[c] - ma) * (b[c] - mb) for c in keys)
    den = (sum((a[c] - ma) ** 2 for c in keys)
           * sum((b[c] - mb) ** 2 for c in keys)) ** 0.5
    return num / den if den else 0.0


def perm_p(a, b):
    """Exact two-tailed permutation p for Spearman (n<=8 -> <=40320 perms)."""
    keys = list(a)
    obs = abs(spearman(a, b))
    av = [a[c] for c in keys]
    hit = tot = 0
    for perm in itertools.permutations([b[c] for c in keys]):
        r = dict(zip(keys, perm))
        if abs(spearman(dict(zip(keys, av)), r)) >= obs - 1e-12:
            hit += 1
        tot += 1
    return hit / tot


def crit(n, alpha=0.05):
    """Smallest |rho| whose exact two-tailed permutation p <= alpha."""
    ids = list(range(n))
    base = {i: i + 1 for i in ids}
    rhos = sorted({round(spearman(base, dict(zip(ids, p))), 12)
                   for p in itertools.permutations(range(1, n + 1))})
    n_tot = len(list(itertools.permutations(range(n))))
    for r in rhos:
        if r <= 0:
            continue
        p = sum(1 for pm in itertools.permutations(range(1, n + 1))
                if abs(spearman(base, dict(zip(ids, pm)))) >= r - 1e-12) / n_tot
        if p <= alpha:
            return r, p
    return None, None


def audit_err():
    """Per-class worst matrix rel err (%) from audit_ranges_2b_report.md §2."""
    path = os.path.join(REPO, "ref/audit_ranges_2b_report.md")
    out = {}
    with open(path) as f:
        for line in f:
            m = re.match(r"\s*\|\s*`([^`]+)`", line)
            if not m:
                continue
            fam = m.group(1).split(" = ")[0].strip()
            cls = FAMILY.get(fam)
            if cls is None:
                continue
            pcts = [float(x) for x in re.findall(r"(\d+\.\d+)%", line)]
            if not pcts:
                continue
            out[cls] = max(out.get(cls, 0.0), max(pcts))
    missing = [c for c in W4 if c not in out]
    assert not missing, f"audit table parse missed {missing}"
    return out


def main():
    anchor = load(os.path.join(REPO, "evidence/qwen2b/q1/ppl_2b_bf16.json"))
    A = anchor["ppl"]
    d, n, pt = {}, {}, {}
    for c in ALL:
        j = load(os.path.join(SCAN, f"scan_{c}.json"))
        for k in ("corpus_sha256", "checkpoint_header_sha256", "n_positions",
                  "window", "batch", "model_tag", "n_tokens"):
            assert j[k] == anchor[k], f"{c}: {k} differs from the anchor"
        assert list(j["inject_resolved"]) == [c], f"{c}: {j['inject_resolved']}"
        assert (j["res_scale"] == 8.0) == (c == "emb"), f"{c}: res_scale"
        d[c] = j["ppl"] - A
        n[c] = j["classes"][c]["n_weights"]
        pt[c] = j
    print(f"provenance OK: 8 points share the anchor's corpus/checkpoint/"
          f"window/batch/positions ({anchor['n_positions']})")
    print(f"bf16 anchor PPL {A:.6f}\n")

    order = sorted(W4, key=lambda c: -d[c])
    dl = sorted(d.values())
    med = 0.5 * (dl[3] + dl[4])
    print("| rank | class | quant | mats | params | PPL | ΔPPL | Δ% | ΔPPL/Mparam |")
    print("|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(sorted(ALL, key=lambda c: -d[c]), 1):
        q = pt[c]["inject_resolved"][c]
        q += " S=8" if c == "emb" else ""
        print(f"| {i} | `{c}` | {q} | {pt[c]['classes'][c]['n_matrices']} | "
              f"{n[c] / 1e6:.2f} M | {pt[c]['ppl']:.6f} | {d[c]:+.6f} | "
              f"{100 * d[c] / A:+.2f} % | {1e6 * d[c] / n[c]:+.5f} |")
    print(f"\nmedian ΔPPL {med:.6f}   10x median {10 * med:.6f}   "
          f"negative deltas: {sum(1 for c in ALL if d[c] < 0)}   "
          f"points > 10x median: {sum(1 for c in ALL if d[c] > 10 * med)}")

    # --- correlations -------------------------------------------------
    err = audit_err()
    print("\n--- rank correlations (audit §2 per-family worst rel err, g128) ---")
    print("  class    ΔPPL rank  size rank  errmax rank  errmax%")
    rp7, rn7, re7 = rank({c: d[c] for c in W4}), rank({c: n[c] for c in W4}), \
        rank({c: err[c] for c in W4})
    rpp7 = rank({c: d[c] / n[c] for c in W4})
    for c in order:
        print(f"  {c:8s} {rp7[c]:9g} {rn7[c]:10g} {re7[c]:12g}   {err[c]:.2f}")
    rc, rp_ = crit(7)
    print(f"\n  n=7, exact permutation critical |rho| at alpha=0.05 = "
          f"{rc:.3f} (p={rp_:.4f})")
    for lbl, a, b in (("ΔPPL vs params        ", rp7, rn7),
                      ("ΔPPL vs max rel err   ", rp7, re7),
                      ("ΔPPL/param vs rel err ", rpp7, re7)):
        rho = spearman(a, b)
        p = perm_p(a, b)
        print(f"  {lbl} rho = {rho:+.3f}   permutation p = {p:.4f}   "
              f"{'SIGNIFICANT' if p <= 0.05 else 'not significant at 0.05'}")
    rho8 = spearman(rank(d), rank(n))
    print(f"  [8 classes, emb included] ΔPPL vs params rho = {rho8:+.3f} "
          f"(midranks: emb and lm_head are the SAME tied matrix, {n['emb']:,} "
          f"weights each, so they share size rank {rank(n)['emb']})")
    print("      emb is joint-largest by size and least damaged of all, so "
          "including it cuts rho by more than a third — which is why the "
          "headline rho is the 7 W4 classes only.")

    # --- additivity ---------------------------------------------------
    v1 = load(os.path.join(REPO, "evidence/qwen2b/q2/v1_v2/ppl_v1.json"))
    v2 = load(os.path.join(REPO, "evidence/qwen2b/q2/v1_v2/ppl_v2.json"))
    s = sum(d.values())
    joint = v2["ppl"] - A
    print(f"\n--- additivity ---\n  sum of the 8 one-at-a-time deltas {s:.6f}")
    print(f"  V2 joint delta                    {joint:.6f}")
    print(f"  scan covers {100 * s / joint:.1f} % of the joint; "
          f"super-additive residual {joint - s:+.6f}")

    # --- bytes ---------------------------------------------------------
    def traffic(rec):
        return sum(rec["classes"][c]["total_bits"] for c in W4) / 8
    b1, b2 = traffic(v1), traffic(v2)
    print(f"\n--- bytes/token (7 W4 classes' packed rows; emb excluded) ---")
    print(f"  V1 g128 {int(b1):>15,}  (feasibility 996,282,368: "
          f"{'MATCH' if int(b1) == 996282368 else 'MISMATCH'})")
    print(f"  V2 g64  {int(b2):>15,}  ({100 * (b2 - b1) / b1:+.3f} % vs V1)")
    for c in order:
        cb = v2["classes"][c]["total_bits"] / 8
        print(f"    {c:8s} {int(cb):>13,}  {100 * cb / b2:5.2f} %")
    all7 = sum(n[c] for c in W4) * W8_IDEAL_BPW / 8
    print(f"\n  W8-on-all-seven at the {W8_IDEAL_BPW} b/w IDEAL FLOOR: "
          f"{int(all7):,} B/token = {all7 / b2:.3f}x V2")
    for k in (1, 2, 3):
        promo = order[:k]
        rm = sum(v2["classes"][c]["total_bits"] / 8 for c in promo)
        w8 = sum(n[c] for c in promo) * W8_IDEAL_BPW / 8
        rec = sum(d[c] for c in promo)
        print(f"  V4 top-{k} ({'+'.join(promo)}):")
        print(f"    W4 side {int(b2 - rm):>13,} B  (= {int(b2):,} − {int(rm):,})"
              f"  + W8 rows [Task 9]")
        print(f"    floor   {int(b2 - rm + w8):>13,} B = {(b2 - rm + w8) / b2:.3f}x V2"
              f" = {100 * (b2 - rm + w8) / all7:.1f} % of full-W8 traffic")
        print(f"    ΔPPL recoverable {rec:.6f} = {100 * rec / joint:.1f} % of the "
              f"joint / {100 * rec / s:.1f} % of the sum of parts; "
              f"est. PPL {v2['ppl'] - rec:.6f}")

    # --- re-runs --------------------------------------------------------
    print("\n--- re-run agreement (host-fault ruling) ---")
    for c in ALL:
        p = os.path.join(SCAN, f"scan_{c}_rerun.json")
        if not os.path.exists(p):
            continue
        r = load(p)
        same = f"{pt[c]['ppl']:.6f}" == f"{r['ppl']:.6f}"
        print(f"  {c:8s} {pt[c]['ppl']:.6f} vs {r['ppl']:.6f}  "
              f"{'AGREE' if same else 'DISAGREE'}  nll_sum bit-identical: "
              f"{pt[c]['nll_sum'] == r['nll_sum']} ({pt[c]['nll_sum']:.6f})")


if __name__ == "__main__":
    main()
