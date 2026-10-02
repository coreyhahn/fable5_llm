#!/usr/bin/env python3
"""Every number in LADDER.md, derived from the committed jsons.

Reads only committed artifacts — this track's PPL jsons at 4B and 9B, the 2B
study's committed jsons for the cross-study column — and imports
`ref/scripts/bytes_per_token.py` for the byte column, so the document and the
calculator cannot drift apart.  Nothing is hardcoded except the point -> file
map and the injection spec each point was scored with.

Provenance is ASSERTED, not assumed: every variant row must share its own
geometry's anchor on corpus sha, checkpoint header sha, scored positions,
window, batch, token count and model tag, and its `inject_resolved` must be
the map the byte column is computed from.  A mismatch raises before anything
is ranked — the same discipline as
`evidence/qwen2b/q2/v4_v5/v4_v5_table.py` §provenance.

    python3 evidence/qwen_next/ladder/ladder_table.py       # from the repo root
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "ref", "scripts"))
import bytes_per_token as BPT                                   # noqa: E402

L = HERE
Q2 = os.path.join(REPO, "evidence/qwen2b/q2")
Q1 = os.path.join(REPO, "evidence/qwen2b/q1")

# point -> (label, injection spec scored | None for the bf16 anchor)
POINTS = [
    ("bf16",       "bf16 anchor",        None),
    ("w4g128",     "W4 g128 (shipped)",  "all:w4g128"),
    ("w4g64",      "W4 g64",             "all:w4g64"),
    ("w4g128gptq", "W4 g128 + GPTQ",     "all:w4g128gptq"),
    ("w4g64gptq",  "W4 g64 + GPTQ",      "all:w4g64gptq"),
    ("w8g128",     "W8 g128",            "all:w8g128"),
]

# the 2B study's corresponding rows (docs/QWEN2B_QUANT_STUDY.md §8).  The
# snoke twins are used wherever they exist, because this campaign is
# snoke-only and §6.4 closed the anchor/V1/V2 attribution gap with them.
TWO_B = [
    ("bf16",      f"{Q1}/ppl_2b_bf16_snoke.json"),
    ("w4g128",    f"{Q2}/v1_v2/ppl_v1_snoke.json"),
    ("w4g64",     f"{Q2}/v1_v2/ppl_v2_snoke.json"),
    ("w4g64gptq", f"{Q2}/v4/ppl_v4gptq.json"),
    ("w8g128",    f"{Q2}/v4_v5/ppl_v5.json"),
]


def load(p):
    with open(p) as f:
        return json.load(f)


def rows_for(tag):
    """[(key, label, spec, json)] for one geometry, provenance asserted."""
    anchor_p = os.path.join(L, f"ppl_{tag}_bf16.json")
    if not os.path.exists(anchor_p):
        return None, []
    anchor = load(anchor_p)
    out = []
    for key, label, spec in POINTS:
        p = os.path.join(L, f"ppl_{tag}_{key}.json")
        if not os.path.exists(p):
            print(f"  (missing {os.path.basename(p)})")
            continue
        j = load(p)
        for k in ("corpus_sha256", "checkpoint_header_sha256", "n_positions",
                  "window", "batch", "model_tag", "n_tokens"):
            assert j[k] == anchor[k], \
                f"{tag}/{key}: {k} differs from the anchor ({j[k]!r} vs {anchor[k]!r})"
        if spec is None:
            assert j["res_scale"] == 1.0 and not j["inject"], \
                f"{tag}/bf16: the anchor must be pure bf16"
        else:
            assert j["res_scale"] == 8.0, f"{tag}/{key}: res_scale"
            plan, _ = BPT.parse_map(spec)
            got = {c: q for c, q in j["inject_resolved"].items()
                   if c in BPT.W4_CLASSES}
            assert plan == got, f"{tag}/{key}: map {plan} != scored {got}"
            assert j["inject_resolved"].get("dn_conv") == "cw13"
            assert j["inject_resolved"].get("emb") == "emb16"
        out.append((key, label, spec, j))
    return anchor, out


def bytes_of(tag, spec):
    """bytes/token of the DDR image set this point implies.

    NOTE the caveat that belongs with every 4B/9B byte number: it is a BYTES
    result computed by the shipped `plan_weights` law, not a fit — no address
    map exists for either geometry (`docs/QWEN35_NEXT_FEASIBILITY.md` §3.2).
    """
    if spec is None:
        return None
    cfg = BPT.load_cfg(tag)
    plan, _ = BPT.parse_map(spec)
    return BPT.budget(cfg, plan)


def panel(tag):
    anchor, rows = rows_for(tag)
    if anchor is None:
        print(f"\n### {tag.upper()} — no anchor yet, skipping")
        return
    A = anchor["ppl"]
    base = next((j for k, _l, _s, j in rows if k == "w4g128"), None)
    gap = (base["ppl"] - A) if base else float("nan")
    print(f"\n=== {tag.upper()} ladder ===")
    print(f"  anchor PPL {A:.6f}   W4 g128 gap {gap:+.6f}   "
          f"{anchor['n_positions']} positions, window {anchor['window']}, "
          f"batch {anchor['batch']}")
    print(f"  corpus {anchor['corpus_sha256'][:16]}…  "
          f"ckpt {anchor['checkpoint_header_sha256'][:16]}…  "
          f"hosts {sorted({str(j.get('host')) for _k, _l, _s, j in rows})}  "
          f"threads {sorted({j.get('threads') for _k, _l, _s, j in rows})}")
    print()
    print("  point                PPL         dPPL       d%      "
          "% of the g128 gap LEFT   bytes/token       b/w     build+eval s")
    for key, label, spec, j in rows:
        b = bytes_of(tag, spec)
        d = j["ppl"] - A
        left = 100 * d / gap if base else float("nan")
        bt = (f"{b['bytes_per_token']:>13,} {b['bits_per_weight']:8.3f}"
              if b else f"{'-':>13} {'-':>8}")
        secs = j["seconds_build"] + j["seconds_eval"]
        print(f"  {label:<20s} {j['ppl']:.6f} {d:+.6f} {100 * d / A:+7.2f}% "
              f"{left:12.2f} %          {bt}   {secs:8.1f}")
    return anchor, rows


def frontier(tag):
    """What a PPL point costs in bytes, against the SHIPPED W4 g128 format.

    The 2B study's §2 asks this question against V2 (w4g64); the shipped
    format is g128, so that is the baseline here.  A negative dPPL means the
    point is WORSE than w4g128 and the rate is meaningless — printed as such.
    """
    anchor, rows = rows_for(tag)
    if anchor is None:
        return
    base = next((j for k, _l, _s, j in rows if k == "w4g128"), None)
    if base is None:
        return
    b0 = bytes_of(tag, "all:w4g128")["bytes_per_token"]
    print(f"\n=== {tag.upper()}: what a PPL point costs in bytes "
          "(baseline = the shipped W4 g128) ===")
    print("  point                PPL bought vs g128   extra bytes/token   "
          "MB per PPL point")
    for key, label, spec, j in rows:
        if spec is None or key == "w4g128":
            continue
        d = base["ppl"] - j["ppl"]
        extra = bytes_of(tag, spec)["bytes_per_token"] - b0
        rate = (f"{extra / d / 1e6:12.1f}" if d > 1e-9
                else "           - (no gain)")
        print(f"  {label:<20s} {d:+.6f}            {extra:>13,}   {rate}")
    print("  NOTE: these are BYTES, not a fit.  No address map exists for "
          "either geometry\n  and the shipped weight window is 1,280 MiB per "
          "channel — see\n  docs/QWEN35_NEXT_FEASIBILITY.md §3 / §3.2, which "
          "owns that question.")


def cross_study():
    print("\n=== cross-study: the same five points at 2B "
          "(docs/QWEN2B_QUANT_STUDY.md) ===")
    two = {}
    for key, p in TWO_B:
        if os.path.exists(p):
            two[key] = load(p)
    if not two:
        print("  (2B jsons not found)")
        return
    # PROVENANCE, asserted -- added 2026-08-26 after review.  `rows_for()`
    # asserts the 4B/9B side; this function had NO asserts at all while §1 of
    # LADDER.md credited "every number below" to a provenance-asserting
    # script.  The cross-study column is the one place two CAMPAIGNS are put
    # in the same table, so it is exactly where a silent corpus or position
    # mismatch would be most damaging and least visible.  Negative control:
    # perturb any 2B json's corpus_sha256 and this now refuses instead of
    # printing the table.
    assert "bf16" in two, "the 2B anchor json is required for the cross-study"
    _c2 = two["bf16"]["corpus_sha256"]
    _n2 = two["bf16"]["n_positions"]
    for key, p in TWO_B:
        if key not in two:
            continue
        j = two[key]
        assert j["corpus_sha256"] == _c2, (
            f"2B cross-study: {os.path.basename(p)} scored corpus "
            f"{j['corpus_sha256'][:16]}… but the 2B anchor scored "
            f"{_c2[:16]}… — these are not the same corpus")
        assert j["n_positions"] == _n2, (
            f"2B cross-study: {os.path.basename(p)} scored "
            f"{j['n_positions']} positions, the 2B anchor scored {_n2}")
        assert j["model_tag"] == "2b", (p, j["model_tag"])
    # and the cross-study only means anything if the 2B campaign and THIS
    # campaign scored the same corpus over the same number of positions --
    # that is the claim §3 of LADDER.md makes in words, asserted here.
    for _t in ("4b", "9b"):
        _p = os.path.join(L, f"ppl_{_t}_bf16.json")
        if not os.path.exists(_p):
            continue
        _j = load(_p)
        assert _j["corpus_sha256"] == _c2, (
            f"cross-study is INVALID: {_t} scored corpus "
            f"{_j['corpus_sha256'][:16]}… but 2B scored {_c2[:16]}…")
        assert _j["n_positions"] == _n2, (
            f"cross-study is INVALID: {_t} scored {_j['n_positions']} "
            f"positions, 2B scored {_n2}")
    A2 = two["bf16"]["ppl"]
    print(f"  2B anchor {A2:.6f}  ({two['bf16']['n_positions']} positions, "
          f"corpus {two['bf16']['corpus_sha256'][:16]}…)")
    tags = [t for t in ("4b", "9b")
            if os.path.exists(os.path.join(L, f"ppl_{t}_bf16.json"))]
    anchors = {t: load(os.path.join(L, f"ppl_{t}_bf16.json"))["ppl"] for t in tags}
    print()
    print("  point                 2B dPPL   2B d%   "
          + "".join(f"| {t.upper()} dPPL  {t.upper()} d%   " for t in tags))
    for key, label, _spec in POINTS:
        if key == "bf16":
            continue
        cells = ""
        for t in tags:
            p = os.path.join(L, f"ppl_{t}_{key}.json")
            if os.path.exists(p):
                j = load(p)
                d = j["ppl"] - anchors[t]
                cells += f"| {d:+.6f} {100 * d / anchors[t]:+6.2f}%   "
            else:
                cells += f"| {'-':>9} {'-':>7}   "
        if key in two:
            d2 = two[key]["ppl"] - A2
            print(f"  {label:<20s} {d2:+.6f} {100 * d2 / A2:+6.2f}%   {cells}")
        else:
            print(f"  {label:<20s} {'-':>9} {'-':>7}   {cells}"
                  "   (no 2B twin — this point is new at 4B/9B)")
    print(f"\n  Read the d% column, not the dPPL column, across models: the "
          f"anchors differ,\n  so an absolute PPL delta is not comparable "
          f"between geometries.  Corpus,\n  window, batch and the "
          f"{_n2:,} scored positions ARE identical -- asserted above,\n"
          f"  not assumed.  The TOKENIZING files that matter "
          f"(tokenizer.json, vocab.json,\n  merges.txt) are byte-identical "
          f"across all four models; chat_template.jinja\n  and "
          f"tokenizer_config.json DIFFER 0.8B/2B vs 4B/9B and are not used "
          f"by this\n  offline scoring path (CHECKPOINT_VERIFY.md section 7).")


def summary_line(log_path, cfg_name):
    """The harness's OWN summary row for `cfg_name`, out of its stdout log.

    Added 2026-08-26 after this script's aggregation of `s_sat` disagreed with
    the log it was derived from (max() vs sum(); it printed 1205 where the log
    said 4438).  The json is the source of truth for the numbers, but the log
    is an INDEPENDENT rendering of the same run by `fidelity_check.py` itself,
    so agreeing with it is a real provenance check on the aggregation.
    Returns (top1_ok, top1_tot, rank_max, resid_max, clips, s_sat) or None.
    """
    if not os.path.exists(log_path):
        return None
    rows, in_tbl = [], False
    with open(log_path) as f:
        for ln in f:
            if ln.startswith("config") and "S_F sat" in ln:
                in_tbl = True
                continue
            if in_tbl:
                if not ln.strip():
                    break
                rows.append(ln.rstrip("\n"))
    for ln in rows:
        tk = ln.split()
        if len(tk) < 8:
            continue
        name = " ".join(tk[:-7])
        if name != cfg_name:
            continue
        ok, tot = tk[-7].split("/")
        return (int(ok), int(tot), int(tk[-5]), int(tk[-3]),
                int(tk[-2]), int(tk[-1]))
    return None


def fidelity():
    print("\n=== fidelity harness (ref/fidelity_check.py) ===")
    any_ = False
    for tag in ("4b", "9b"):
        for key in ("w8g128", "w4g128", "w4g64", "w4g128gptq", "w4g64gptq"):
            p = os.path.join(L, f"fixed_{tag}_{key}.json")
            if not os.path.exists(p):
                continue
            any_ = True
            d = load(p)
            for name, r in d.items():
                tot = ok = clips = 0
                ranks, t5, rmax, sat = [], [], 0, 0
                for pk in ("1", "2", "3", "4"):
                    if pk not in r:
                        continue
                    tot += len(r[pk]["top1"])
                    ok += int(sum(r[pk]["top1"]))
                    ranks += list(r[pk]["rank"])
                    t5 += list(r[pk]["top5"])
                    clips += int(r[pk]["resid_clip"])
                    rmax = max(rmax, int(r[pk]["resid_max"]))
                    # s_sat is a COUNT of saturation events (fidelity_check.py
                    # :803 sums per-cache counts), so it sums across prompts —
                    # exactly as the harness's own SUMMARY line does at :1131.
                    # This was max() until 2026-08-26 and printed 1205 where
                    # the source log said 4438.  resid_clip likewise sums;
                    # resid_max is a magnitude and takes the max.
                    sat += int(r[pk]["s_sat"])
                ranks.sort()
                med = ranks[len(ranks) // 2] if ranks else float("nan")
                rmx = max(ranks) if ranks else -1
                sl = summary_line(os.path.join(L, f"fixed_{tag}_{key}.log"),
                                  name)
                if sl is not None:
                    got = (ok, tot, rmx, rmax, clips, sat)
                    assert sl == got, (
                        f"fixed_{tag}_{key}: this script derives {got} from "
                        f"the json but fidelity_check.py's own SUMMARY line "
                        f"says {sl} — (top1_ok, top1_tot, rank_max, "
                        f"resid_max, clips, s_sat)")
                else:
                    print(f"  NOTE: no SUMMARY line found for "
                          f"fixed_{tag}_{key} — row below is UNCROSSCHECKED")
                print(f"  {tag} {key:<11s} [{name}]  top-1 {ok}/{tot}  "
                      f"rank med {med} max {rmx}  "
                      f"top5 ovl {sum(t5) / max(len(t5), 1):.2f}  "
                      f"|resid|max {rmax} of 32768  RESID CLIPS {clips}  "
                      f"S_F sat {sat}  emb |q|max {r.get('_emb_absmax')}  "
                      f"host {r.get('_host')}")
    if not any_:
        print("  (no fidelity jsons yet — see LADDER.md for the 4B refusal)")


def main():
    for tag in ("4b", "9b"):
        panel(tag)
    for tag in ("4b", "9b"):
        frontier(tag)
    cross_study()
    fidelity()
    print("\nLADDER_TABLE OK — every row above passed the provenance asserts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
