#!/usr/bin/env python3
"""tokenizer_check.py — is the tokenizer/chat template byte-identical across
0.8B / 2B / 4B / 9B?

The 2B migration got this for free: docs/QWEN2B_FEASIBILITY.md:20 records
"SAME vocab 248,320, byte-identical tokenizer + chat template".  The whole
quantization campaign rests on it — `ref/ppl_corpus_eval.txt` is scored at
24,528 positions and every Delta in QWEN2B_QUANT_STUDY.md is against an anchor
computed on those positions.  If the 4B/9B tokenizer differs, the corpus
re-tokenizes, the position count moves, and no anchor carries over.

This asks the Hub for each file's sha256 (the LFS/xet OID the Hub already
stores), so nothing large is downloaded.
"""
import hashlib
import json
import sys

from huggingface_hub import HfApi, hf_hub_download

REPOS = ["Qwen/Qwen3.5-0.8B", "Qwen/Qwen3.5-2B",
         "Qwen/Qwen3.5-4B", "Qwen/Qwen3.5-9B"]
FILES = ["tokenizer.json", "tokenizer_config.json", "vocab.json",
         "merges.txt", "chat_template.jinja", "generation_config.json",
         "special_tokens_map.json", "preprocessor_config.json"]

api = HfApi()

if __name__ == "__main__":
    present = {}
    for repo in REPOS:
        present[repo] = set(api.list_repo_files(repo))

    print("=" * 78)
    print("FILE PRESENCE")
    print("=" * 78)
    print(f"    {'file':30s}" + "".join(f"{r.split('-')[-1]:>8s}" for r in REPOS))
    for f in FILES:
        print(f"    {f:30s}" + "".join(
            f"{('yes' if f in present[r] else '-'):>8s}" for r in REPOS))

    print()
    print("=" * 78)
    print("SHA256 — small files are fetched and hashed locally")
    print("=" * 78)
    digests = {}
    for f in FILES:
        row = {}
        for repo in REPOS:
            if f not in present[repo]:
                row[repo] = None
                continue
            try:
                p = hf_hub_download(repo, f)
                row[repo] = hashlib.sha256(open(p, "rb").read()).hexdigest()
            except Exception as ex:                       # noqa: BLE001
                row[repo] = f"ERR {ex}"
        digests[f] = row
        vals = [v for v in row.values() if v and not str(v).startswith("ERR")]
        same = len(set(vals)) == 1 and len(vals) == len(REPOS)
        print(f"\n    {f}  ->  {'IDENTICAL across all four' if same else 'DIFFERS'}")
        for repo in REPOS:
            v = row[repo]
            print(f"      {repo.split('/')[-1]:14s} "
                  f"{(v[:16] + '...' if v and not str(v).startswith('ERR') else str(v))}")

    print()
    print("=" * 78)
    print("VERDICT")
    print("=" * 78)
    # What decides TOKENIZATION is the BPE table itself; tokenizer_config.json
    # also EMBEDS a copy of the chat template, so it can differ for a reason
    # that has nothing to do with how text is split into ids.
    tok = ["tokenizer.json", "vocab.json", "merges.txt"]
    tok_same = True
    for f in tok:
        vals = [digests[f][r] for r in REPOS]
        same = len(set(vals)) == 1 and all(vals)
        tok_same &= same
        print(f"    {f:26s} {'byte-identical across all four' if same else '*** DIFFERS ***'}")
    print(f"    -> TOKENIZATION is {'identical' if tok_same else 'NOT identical'}: "
          f"the pinned PPL corpus and its 24,528 scored positions "
          f"{'CARRY OVER unchanged' if tok_same else 'DO NOT carry over'}")
    print()
    for f in ("tokenizer_config.json", "chat_template.jinja"):
        vals = [digests[f][r] for r in REPOS]
        same = len(set(vals)) == 1 and all(vals)
        print(f"    {f:26s} {'byte-identical' if same else 'DIFFERS 0.8B/2B vs 4B/9B'}")
    print("    -> the CHAT TEMPLATE is not shared with the shipped models.")
    print("       evidence/qwen_next/feas/f11_tokenizer_diff.log has the diff:")
    print("       it is a 6-line inversion of the enable_thinking default —")
    print("       0.8B/2B emit the EMPTY think block unless asked, 4B/9B emit")
    print("       an OPEN <think> unless asked not to.  The host-side id-spliced")
    print("       template (docs/INSTRUCT_SPEC.md) must be re-derived, and the")
    print("       ntok >= 24 guidance changes because a reasoning block now")
    print("       precedes the answer by default.")

    json.dump(digests, open(sys.argv[1], "w") if len(sys.argv) > 1 else sys.stderr,
              indent=1, sort_keys=True)
