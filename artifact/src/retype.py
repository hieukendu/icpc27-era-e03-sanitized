"""Second-pass re-typing of extractor-'intent' claims (round-2 revision, R1-1/R3-M6).

The first-pass extractor puts purpose statements, functional summaries and rationale into one Intent type.
Two classifiers from model families different from the extractor (Qwen) -- gemma2:9b (primary) and
llama3.1:8b (agreement check) -- label every intent claim, from its text and the function name only, as
  FUNCTIONAL : states what the code computes, returns or does, or where it lives (class / module) -- a statement
               about behaviour or structure that could in principle be checked against the code or by running it
  RATIONALE  : why it is designed so, who it is for, context of use, quality / performance judgements, advice.
The prompt was fixed before any re-typing output was inspected. FUNCTIONAL claims become type 'purpose' (P) and
are routed to behavioural / structural evidence; RATIONALE claims stay outside the evidence set (undischargeable).
Output: results/retype.jsonl  {cid, retype_primary, retype_second}
"""
import json
import os
import time

from config import RESULTS
from llm import llm, parse_json, stats

RETYPERS = [("ollama", "gemma2:9b"), ("ollama", "llama3.1:8b")]
SYSTEM = "You are a careful software-engineering annotator. You output only valid JSON."
INSTRUCTIONS = """Each numbered sentence below was said about the function `{name}`. Label every sentence:
- "FUNCTIONAL": it states what the function computes, returns or does, what it operates on, or where it is defined
  (its class or module) -- something that could in principle be checked by reading or running the code.
- "RATIONALE": it states why the code is written this way, who or what it is for, the context in which it is used,
  a judgement of quality or performance, or a recommendation.
If a sentence mixes both, choose the label of its main assertion.
Output JSON: {{"labels": [{{"i": <number>, "label": "FUNCTIONAL" | "RATIONALE"}}, ...]}}

SENTENCES:
{lines}

JSON:"""


def classify(name, claims, model):
    lines = "\n".join(f"{i+1}. {c['text']}" for i, c in enumerate(claims))
    raw = llm(INSTRUCTIONS.format(name=name, lines=lines), backend=model[0], model=model[1], system=SYSTEM,
              num_predict=40 + 18 * len(claims), json_mode=True)
    js = parse_json(raw)
    out = [None] * len(claims)
    if isinstance(js, dict) and isinstance(js.get("labels"), list):
        for v in js["labels"]:
            try:
                i = int(v.get("i")) - 1
            except (TypeError, ValueError, AttributeError):
                continue
            lab = str(v.get("label", "")).strip().upper()
            if 0 <= i < len(claims) and lab in ("FUNCTIONAL", "RATIONALE"):
                out[i] = lab
    return out


def main():
    from explain import load_corpus
    corpus = {r["fid"]: r for r in load_corpus()}
    by_fid = {}
    for l in open(os.path.join(RESULTS, "claims.jsonl")):
        c = json.loads(l)
        if c["type"] == "intent":
            by_fid.setdefault(c["fid"], []).append(c)
    t0 = time.time()
    rows = {}
    for mi, model in enumerate(RETYPERS):
        for n, fid in enumerate(sorted(by_fid), 1):
            cl = sorted(by_fid[fid], key=lambda c: c["cid"])
            for c, lab in zip(cl, classify(corpus[fid]["name"], cl, model)):
                rows.setdefault(c["cid"], {"cid": c["cid"]})["retype_primary" if mi == 0 else "retype_second"] = lab
            if n % 20 == 0:
                print(f"[retype {model[1]}] {n}/{len(by_fid)} {time.time()-t0:.0f}s {stats()}", flush=True)
    with open(os.path.join(RESULTS, "retype.jsonl"), "w") as fo:
        for cid in sorted(rows):
            fo.write(json.dumps(rows[cid], sort_keys=True) + "\n")
    print(f"retype: {len(rows)} intent claims over {len(by_fid)} functions")


if __name__ == "__main__":
    main()
