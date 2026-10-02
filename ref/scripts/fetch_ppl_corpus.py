#!/usr/bin/env python3
"""One-off fetcher that PINS the perplexity corpus (committed for provenance).

    uv run --with huggingface_hub --with pandas --with pyarrow --with transformers \
        python ref/scripts/fetch_ppl_corpus.py
    # (system python3 already has all four on darthplagueis: just `python3 ...`)

What it does
------------
1. Downloads the two `Salesforce/wikitext` `wikitext-2-raw-v1` parquet shards
   (validation + train) from the Hub with `hf_hub_download(repo_type=...)`.
2. Concatenates the `text` column of each in row order (the raw split IS the
   article stream; rows already carry their newlines).
3. Tokenizes with the LOCAL Qwen3.5-2B snapshot tokenizer.  That tokenizer is
   byte-identical to the 0.8B one (verified in Task 2 of the 2B migration), so
   ONE pinned corpus serves both models and the token counts below are exact
   for both.
4. Truncates to the first N tokens (eval 24576 from validation, calib 32768
   from train — different splits, so the two are disjoint by construction),
   detokenizes back to text, and writes
       ref/ppl_corpus_eval.txt     ref/ppl_corpus_calib.txt
5. Prints the sha256 of every input and output file.

THE PIN IS THE COMMITTED .txt FILES, not this script: re-running it needs
network + the Hub, while every scoring run only needs the text.  The token
counts printed here are what `ref/perplexity_eval.py` re-derives from the text
(the decode->encode round trip is checked below and must be exact).
"""
import glob
import hashlib
import os
import sys

REPO_ID = "Salesforce/wikitext"
SUBSET = "wikitext-2-raw-v1"
SHARDS = {  # output stem -> (parquet inside the dataset repo, n tokens kept)
    "eval": (f"{SUBSET}/validation-00000-of-00001.parquet", 24576),
    "calib": (f"{SUBSET}/train-00000-of-00001.parquet", 32768),
}
CHARS_PER_TOKEN_BUDGET = 12     # wikitext runs ~4.5; 12 is a safe over-read
REF = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENIZER_REPO_DIR = "models--Qwen--Qwen3.5-2B"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_dir():
    """Local HF snapshot dir of the tokenizer (same search order as load_qwen35)."""
    roots = []
    for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
        if os.environ.get(env):
            roots.append(os.environ[env])
    if os.environ.get("HF_HOME"):
        roots.append(os.path.join(os.environ["HF_HOME"], "hub"))
    roots.append(os.path.expanduser("~/.cache/huggingface/hub"))
    for root in roots:
        hits = sorted(glob.glob(os.path.join(
            root, TOKENIZER_REPO_DIR, "snapshots", "*", "tokenizer.json")))
        if hits:
            return os.path.dirname(hits[0])
    raise FileNotFoundError(
        f"{TOKENIZER_REPO_DIR} snapshot with tokenizer.json not found under "
        + ", ".join(roots))


def main():
    from huggingface_hub import hf_hub_download
    import pyarrow.parquet as pq
    from transformers import AutoTokenizer

    snap = snapshot_dir()
    print(f"tokenizer snapshot: {snap}")
    print(f"  tokenizer.json sha256 {sha256_file(os.path.join(snap, 'tokenizer.json'))}")
    tok = AutoTokenizer.from_pretrained(snap)
    print(f"  {type(tok).__name__} vocab={tok.vocab_size}")

    for stem, (fname, ntok) in SHARDS.items():
        path = hf_hub_download(REPO_ID, fname, repo_type="dataset")
        real = os.path.realpath(path)
        print(f"\n{stem}: {fname}")
        print(f"  cached  {real}")
        print(f"  parquet sha256 {sha256_file(real)}")

        col = pq.read_table(real, columns=["text"]).column("text").to_pylist()
        text = "".join(col)
        print(f"  split: {len(col)} rows, {len(text)} chars")

        budget = ntok * CHARS_PER_TOKEN_BUDGET
        ids = tok(text[:budget], add_special_tokens=False)["input_ids"]
        if len(ids) < ntok + 1024:
            raise SystemExit(
                f"{stem}: char budget {budget} yielded only {len(ids)} tokens, "
                f"need {ntok} with margin — raise CHARS_PER_TOKEN_BUDGET")
        ids = ids[:ntok]
        out_text = tok.decode(ids, skip_special_tokens=False,
                              clean_up_tokenization_spaces=False)

        # the harness re-tokenizes the .txt file: that round trip must be exact,
        # otherwise the committed pin does not mean the token stream we scored.
        back = tok(out_text, add_special_tokens=False)["input_ids"]
        if back != ids:
            raise SystemExit(
                f"{stem}: decode->encode round trip changed the token stream "
                f"({len(back)} vs {len(ids)} tokens) — the .txt pin would not "
                f"reproduce the scored sequence")

        out_path = os.path.join(REF, f"ppl_corpus_{stem}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"  -> {out_path}")
        print(f"     {ntok} tokens, {len(out_text)} chars, "
              f"{os.path.getsize(out_path)} bytes")
        print(f"     sha256 {sha256_file(out_path)}")

    print("\nFETCH_PPL_CORPUS OK (commit the two .txt files — they are the pin)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
