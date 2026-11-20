"""Generate one explanation per (function, explainer). Neutral prompt (no steering towards claim types) so
the claim-type distribution reflects what current assistants volunteer. Temperature 0, cached."""
import json
import os
import re
import time

from config import DATA, RESULTS, EXPLAINERS, FRONTIER, FRONTIER_CAP
from llm import llm, stats

SYSTEM = ("You are a coding assistant helping a developer understand unfamiliar code. "
          "Answer in plain prose: 5 to 8 sentences, one paragraph, no bullet lists, no code blocks, no headings.")


def shown_source(rec):
    if rec["corpus"] == "B":
        return rec["exec_source"]
    head = f"# repository: {rec['repo']}, file: {rec['path']}"
    if rec.get("cls"):
        head += f", method of class {rec['cls']}"
    imps = "\n".join(rec.get("context_imports", "").splitlines()[:12])
    if rec["lang"] == "java":
        return f"// repository: {rec['repo']}, file: {rec['path']}, method of class {rec['cls']}\n{imps}\n\n{rec['source']}"
    return f"{head}\n{imps}\n\n{rec['source']}"


def prompt_for(rec):
    lang = "Java method" if rec["lang"] == "java" else "Python function"
    return (f"Explain what the following {lang} `{rec['name']}` does and how it works.\n\n"
            f"```{rec['lang']}\n{shown_source(rec)}\n```")


def load_corpus():
    rows = []
    for name in ("corpus_a.jsonl", "corpus_b.jsonl"):
        rows += [json.loads(l) for l in open(os.path.join(DATA, name))]
    return sorted(rows, key=lambda r: r["fid"])


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`\"'(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


def explain_one(rec, cond):
    backend, model = FRONTIER if cond == "frontier" else EXPLAINERS[cond]
    text = llm(prompt_for(rec), backend=backend, model=model, system=SYSTEM, num_predict=450)
    sents = split_sentences(text)
    return {"fid": rec["fid"], "corpus": rec["corpus"], "lang": rec["lang"], "explainer": cond,
            "model": model, "text": text, "n_sentences": len(sents), "n_words": len(text.split())}


def main():
    """Replay (from cache) / generate explanations for the selected corpus. The frontier condition covers
    the functions listed in data/frontier_subset.json (if present)."""
    from selection import selection
    sel = selection()["fids"]
    rows = [r for r in load_corpus() if r["fid"] in set(sel)]
    fp = os.path.join(DATA, "frontier_subset.json")
    frontier = set(json.load(open(fp))) if os.path.exists(fp) else set()
    out = os.path.join(RESULTS, "explanations.jsonl")
    t0, n = time.time(), 0
    with open(out, "w") as fo:
        for cond in list(EXPLAINERS) + ["frontier"]:
            for rec in rows:
                if cond == "frontier" and rec["fid"] not in frontier:
                    continue
                fo.write(json.dumps(explain_one(rec, cond), sort_keys=True) + "\n")
                n += 1
                if n % 50 == 0:
                    print(f"[explain] {n} done, {time.time()-t0:.0f}s, {stats()}", flush=True)
    print(f"explanations: {n} -> {os.path.basename(out)}; llm stats {stats()}")


if __name__ == "__main__":
    main()
