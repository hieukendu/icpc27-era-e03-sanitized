"""Decompose explanations into atomic, typed, slot-grounded claims (SDBI typology) with a cached LLM
extractor in JSON mode. A second extractor (different model) re-extracts a subset for a consistency check.

Claim record: {cid, fid, explainer, text, type, subtype, slots, sentence_idx}
"""
import json
import os
import sys
import time

from config import DATA, RESULTS, EXTRACTOR, EXTRACTOR_SECOND, SECOND_EXTRACTOR_N, SEED, CLAIM_TYPES
from llm import llm, parse_json, stats
from explain import shown_source, load_corpus

SYSTEM = "You are a meticulous annotator. You output only valid JSON."

INSTRUCTIONS = """Decompose the EXPLANATION below into atomic claims about the given code. One claim = one checkable
statement. Split sentences that make several statements. Keep the author's wording (minimal rephrasing). Do NOT
add claims the explanation does not make, and do not correct them, even if they look wrong.

Type each claim with exactly one of:
- "structural": what the code is made of. subtypes: "calls" (calls/uses/invokes function or method X),
  "parameter" (takes/accepts parameter X), "default" (parameter X defaults to V), "returns" (returns a value /
  returns nothing or None), "raises" (the code explicitly raises/throws exception type X), "imports" (uses
  module/import X), "decorator" (is decorated/annotated with X).
- "dataflow": a value flows from one place to another inside the function. subtype "flow". Examples: "the
  result of sorted() is stored in s", "n is passed to range", "the list is returned", "x is used to compute y".
- "behavioural": how the function behaves for inputs. subtypes: "output" (for input I the result is O),
  "exception" (for some input an exception of type E occurs), "side_effect" (prints, writes, mutates),
  "general" (any other statement about results/behaviour without a concrete input, e.g. "returns the largest
  element", "handles empty input by returning 0").
- "intent": purpose, rationale, design motivation, context, performance/quality judgements, comparisons,
  recommendations ("this is useful for...", "ensures robustness", "is efficient"). subtype "purpose",
  "rationale", "context" or "other".

Slots (fill from the claim text; use null when the claim does not state it):
- calls: {"callee": "name"}        - parameter: {"name": "x"}      - default: {"name": "x", "value": "literal"}
- returns: {"returns_value": true|false}   - raises: {"exception": "ExcType"}   - imports: {"module": "name"}
- decorator: {"name": "x"}
- flow: {"source": "variable or function name", "sink": "variable or function name or 'return'"}
- output: {"input": "a Python call expression with the concrete arguments, or null", "output": "a Python literal
  for the stated result, or null"}
- exception: {"input": "call expression or null", "exception": "ExcType"}
- side_effect/general/intent: {}

Output JSON: {"claims": [{"text": "...", "type": "...", "subtype": "...", "slots": {...}}, ...]}
"""


def extraction_prompt(rec, explanation_text):
    return (f"{INSTRUCTIONS}\nCODE ({rec['lang']}):\n```{rec['lang']}\n{shown_source(rec)}\n```\n\n"
            f"EXPLANATION:\n\"\"\"\n{explanation_text}\n\"\"\"\n\nJSON:")


STRUCT_SUBS = ("calls", "parameter", "default", "returns", "raises", "imports", "decorator")
BEH_SUBS = ("output", "exception", "side_effect", "general")


def infer_type(sub, slots):
    """Recover the claim type when the extractor omitted or garbled it, from subtype then slot keys."""
    if sub in STRUCT_SUBS:
        return "structural"
    if sub == "flow":
        return "dataflow"
    if sub in BEH_SUBS:
        return "behavioural"
    keys = set(slots)
    if {"source", "sink"} & keys:
        return "dataflow"
    if {"callee", "module", "returns_value"} & keys or ({"name"} & keys):
        return "structural"
    if "exception" in keys:
        return "behavioural" if "input" in keys else "structural"
    if {"input", "output"} & keys:
        return "behavioural"
    return "intent"


def infer_subtype(t, slots):
    keys = set(slots)
    if t == "structural":
        if "callee" in keys: return "calls"
        if "value" in keys: return "default"
        if "name" in keys: return "parameter"
        if "exception" in keys: return "raises"
        if "module" in keys: return "imports"
        if "returns_value" in keys: return "returns"
    if t == "dataflow":
        return "flow"
    if t == "behavioural":
        if "exception" in keys: return "exception"
        if "input" in keys or "output" in keys: return "output"
        return "general"
    return "other"


def _is_template_echo(text):
    """RUNLOG cycle 2: the extractor occasionally echoes an instruction line ("The code explicitly raises/throws
    exception type X") as a claim. Such claims are not in the explanation and are dropped."""
    t = text.strip().lower()
    return ("type x" in t or "function or method x" in t or "parameter x" in t or "module/import x" in t
            or t in INSTRUCTIONS.lower() and len(t) > 25 or "concrete arguments" in t)


def normalise(claims_json):
    out = []
    if not isinstance(claims_json, dict):
        return out
    items = claims_json.get("claims")
    if not isinstance(items, list):
        return out
    for c in items:
        if not isinstance(c, dict) or not isinstance(c.get("text"), str) or not c["text"].strip():
            continue
        t = str(c.get("type", "")).strip().lower()
        if t in ("behavioral",):
            t = "behavioural"
        if t in ("data-flow", "data_flow", "data flow"):
            t = "dataflow"
        sub = str(c.get("subtype", "") or "").strip().lower().replace("-", "_").replace(" ", "_")
        slots = c.get("slots") if isinstance(c.get("slots"), dict) else {}
        if t not in CLAIM_TYPES:
            t = infer_type(sub, slots)
        if not sub:
            sub = infer_subtype(t, slots)
        if _is_template_echo(c["text"]):
            continue
        out.append({"text": c["text"].strip(), "type": t, "subtype": sub, "slots": slots})
    return out


def salvage_claims(raw):
    """RUNLOG cycle 8: JSON mode occasionally degenerates into a whitespace run inside the last string, which
    truncates the document. Recover every *complete* claim object that precedes the truncation."""
    i = raw.find("[")
    if i == -1:
        return None
    dec, items, j = json.JSONDecoder(), [], i + 1
    while True:
        while j < len(raw) and raw[j] in " \n\r\t,":
            j += 1
        if j >= len(raw) or raw[j] != "{":
            break
        try:
            obj, j = dec.raw_decode(raw, j)
        except json.JSONDecodeError:
            break
        items.append(obj)
    return {"claims": items, "_salvaged": True} if items else None


def extract(rec, expl, backend, model):
    raw = llm(extraction_prompt(rec, expl["text"]), backend=backend, model=model, system=SYSTEM,
              num_predict=1800, json_mode=True)
    js = parse_json(raw)
    if js is None:
        js = salvage_claims(raw)
    claims = normalise(js)
    return claims, js is not None


def claims_for(rec, expl, which="first"):
    """Typed claims (with cids) for one explanation; shared by extract.main and the warm-up driver."""
    backend, model = EXTRACTOR if which == "first" else EXTRACTOR_SECOND
    claims, ok = extract(rec, expl, backend, model)
    for i, c in enumerate(claims):
        c.update({"cid": f"{expl['explainer']}:{expl['fid']}:{i:02d}", "fid": expl["fid"],
                  "explainer": expl["explainer"], "corpus": expl["corpus"], "lang": expl["lang"],
                  "extractor": model})
    return claims, ok


def main(which="first"):
    from selection import selected_fids, in_second
    sel = selected_fids()
    corpus = {r["fid"]: r for r in load_corpus()}
    expls = [json.loads(l) for l in open(os.path.join(RESULTS, "explanations.jsonl"))]
    expls = [e for e in expls if e["fid"] in sel]
    expls.sort(key=lambda e: (e["explainer"], e["fid"]))
    if which == "first":
        out = os.path.join(RESULTS, "claims.jsonl")
        todo = expls
    else:
        out = os.path.join(RESULTS, "claims_second.jsonl")
        todo = [e for e in expls if in_second(e["fid"]) and e["explainer"] != "frontier"]
    t0, n, bad = time.time(), 0, 0
    with open(out, "w") as fo:
        for e in todo:
            claims, ok = claims_for(corpus[e["fid"]], e, which)
            bad += 0 if ok else 1
            for c in claims:
                fo.write(json.dumps(c, sort_keys=True) + "\n")
            fo.flush()
            n += 1
            if n % 20 == 0:
                print(f"[extract-{which}] {n}/{len(todo)} expl, {time.time()-t0:.0f}s, json-fail={bad}, {stats()}",
                      flush=True)
    print(f"extract-{which}: {n} explanations, {bad} unparsable -> {os.path.basename(out)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "first")
