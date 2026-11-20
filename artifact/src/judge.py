"""H2 PROXY (no humans): an independent model (qwen2.5:14b, not the extractor) reads the code and labels
every extracted claim of an explanation as T (the code supports it), F (the code contradicts it) or U (cannot
be decided from the code alone). Per explanation we later correlate Attest's discharged-true rate with the
judge-confirmed rate. This is a proxy for faithfulness; the human correlation is pending."""
import json
import os
import time

from config import RESULTS, JUDGE
from llm import llm, parse_json, stats
from explain import shown_source, load_corpus

SYSTEM = "You are a careful senior code reviewer. You output only valid JSON."

INSTRUCTIONS = """Below is a piece of code and a numbered list of claims that someone made about it.
For EACH claim decide, by reading the code carefully, whether it is:
- "T": correct -- the code supports the claim,
- "F": incorrect -- the code contradicts the claim,
- "U": cannot be decided from the code alone (e.g. purpose, motivation, quality judgements, external context).
Judge each claim independently. Output JSON: {"verdicts": [{"i": <claim number>, "v": "T"|"F"|"U"}, ...]}
"""


def judge_prompt(rec, claims):
    lines = "\n".join(f"{i+1}. {c['text']}" for i, c in enumerate(claims))
    return f"{INSTRUCTIONS}\nCODE ({rec['lang']}):\n```{rec['lang']}\n{shown_source(rec)}\n```\n\nCLAIMS:\n{lines}\n\nJSON:"


def judge(rec, claims):
    """Return list of verdicts aligned with claims ('T','F','U' or None when missing)."""
    if not claims:
        return []
    raw = llm(judge_prompt(rec, claims), backend=JUDGE[0], model=JUDGE[1], system=SYSTEM,
              num_predict=60 + 14 * len(claims), json_mode=True)
    js = parse_json(raw)
    out = [None] * len(claims)
    if isinstance(js, dict) and isinstance(js.get("verdicts"), list):
        for v in js["verdicts"]:
            if not isinstance(v, dict):
                continue
            try:
                i = int(v.get("i")) - 1
            except (TypeError, ValueError):
                continue
            lab = str(v.get("v", "")).strip().upper()[:1]
            if 0 <= i < len(claims) and lab in ("T", "F", "U"):
                out[i] = lab
    return out


def main():
    from selection import selected_fids
    sel = selected_fids()
    corpus = {r["fid"]: r for r in load_corpus()}
    by_expl = {}
    for l in open(os.path.join(RESULTS, "claims.jsonl")):
        c = json.loads(l)
        by_expl.setdefault((c["explainer"], c["fid"]), []).append(c)
    keys = sorted(k for k in by_expl if k[1] in sel and k[0] != "frontier")   # round 2: all local explanations
    t0 = time.time()
    with open(os.path.join(RESULTS, "judge.jsonl"), "w") as fo:
        for n, k in enumerate(keys, 1):
            cl = sorted(by_expl[k], key=lambda c: c["cid"])
            for c, v in zip(cl, judge(corpus[k[1]], cl)):
                fo.write(json.dumps({"cid": c["cid"], "fid": c["fid"], "explainer": c["explainer"],
                                     "judge": v, "judge_model": JUDGE[1]}, sort_keys=True) + "\n")
            if n % 20 == 0:
                print(f"[judge] {n}/{len(keys)} {time.time()-t0:.0f}s {stats()}", flush=True)
    print(f"judge: {len(keys)} explanations -> judge.jsonl")


if __name__ == "__main__":
    main()
