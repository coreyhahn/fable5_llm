import json, difflib
from huggingface_hub import hf_hub_download
for f in ("tokenizer_config.json", "chat_template.jinja"):
    a = open(hf_hub_download("Qwen/Qwen3.5-2B", f)).read()
    b = open(hf_hub_download("Qwen/Qwen3.5-4B", f)).read()
    c = open(hf_hub_download("Qwen/Qwen3.5-9B", f)).read()
    print("="*70); print(f, " 4B == 9B:", b == c, " len 2B/4B:", len(a), len(b))
    if f.endswith(".json"):
        ja, jb = json.loads(a), json.loads(b)
        ka, kb = set(ja), set(jb)
        print("  keys only in 2B:", sorted(ka-kb))
        print("  keys only in 4B:", sorted(kb-ka))
        for k in sorted(ka & kb):
            if ja[k] != jb[k]:
                sa, sb = str(ja[k]), str(jb[k])
                print(f"  {k}: 2B={sa[:150]}  ->  4B={sb[:150]}")
    else:
        d = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                      "2B", "4B", lineterm="", n=1))
        print(f"  unified diff, {len(d)} lines:")
        for ln in d[:80]:
            print("   ", ln[:160])
