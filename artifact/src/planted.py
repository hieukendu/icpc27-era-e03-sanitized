"""Planted-falsification set: ground truth without humans.

From claims Attest discharged as TRUE in the real explanations (local explainers), build minimally perturbed
FALSE twins whose label is known by construction:
  structural/calls      swap the callee for a sibling callee from the same repository that this function never calls
  structural/parameter  rename the parameter to a sibling parameter name that does not occur in the function
  dataflow/flow         replace the sink (or source) by a def-use node that is NOT reachable from the source
  behavioural (Corpus B) alter the claimed output literal, or flip a comparison word (largest<->smallest, ...)
Both versions then go END-TO-END through Attest: the claim texts of one function (true and false twins, mixed
in a seeded order) form a pseudo-explanation that the same LLM extractor decomposes; extracted claims are
matched back to planted items by text similarity; structural/dataflow claims are discharged against facts and
behavioural claims through probe synthesis + sandboxed execution. Output: results/planted.jsonl.
Caveat (stated in the paper): the TRUE side inherits Attest's own verdict on the original claim.
"""
import difflib
import hashlib
import json
import os
import random
import re

from config import RESULTS, SEED
from explain import load_corpus
from extract import claims_for
from discharge import _resolve, apply_entity_check
from facts import reachable

CAPS = {"calls": 50, "parameter": 30, "flow": 60, "behavioural": 60}
ANTONYMS = [("largest", "smallest"), ("maximum", "minimum"), ("max", "min"), ("greater", "less"),
            ("ascending", "descending"), ("even", "odd"), ("first", "last"), ("True", "False"),
            ("increasing", "decreasing"), ("longest", "shortest"), ("highest", "lowest"),
            ("positive", "negative"), ("uppercase", "lowercase"), ("before", "after")]
KEYWORDS = {"if", "for", "while", "return", "print", "len", "str", "int", "list", "dict", "set", "self",
            "super", "isinstance", "range", "None", "True", "False"}


def _rng(key):
    return random.Random(int(hashlib.sha256(f"{SEED}|{key}".encode()).hexdigest()[:12], 16))


def _word_re(tok):
    return re.compile(r"(?<![\w.])" + re.escape(tok) + r"(?![\w])")


def _replace(text, old, new):
    r = _word_re(old)
    if not r.search(text):
        return None
    return r.sub(new, text)


def _mutate_literal(lit):
    s = lit.strip()
    if s in ("True", "False"):
        return "False" if s == "True" else "True"
    if re.fullmatch(r"-?\d+", s):
        return str(int(s) + 1)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return repr(float(s) + 1.0)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[0] + s[1:-1] + "x" + s[0]
    if s.startswith("[") and s.endswith("]"):
        return "[]" if s != "[]" else "[0]"
    return None


def build_items():
    disc = [json.loads(l) for l in open(os.path.join(RESULTS, "discharge.jsonl"))]
    disc = [c for c in disc if c["explainer"] != "frontier"]
    facts = {json.loads(l)["fid"]: json.loads(l) for l in open(os.path.join(RESULTS, "facts.jsonl"))}
    corpus = {r["fid"]: r for r in load_corpus()}
    probes = {}
    pp = os.path.join(RESULTS, "probe_runs.jsonl")
    if os.path.exists(pp):
        probes = {json.loads(l)["cid"]: json.loads(l) for l in open(pp)}
    repo_calls, repo_params = {}, {}
    for fid, f in facts.items():
        repo = corpus[fid]["repo"]
        repo_calls.setdefault(repo, set()).update(c for c in f["calls"] if c.isidentifier())
        repo_params.setdefault(repo, set()).update(p.lstrip("*") for p in f["params"])
    items = {k: [] for k in CAPS}
    seen = set()
    for c in sorted(disc, key=lambda c: hashlib.sha256((str(SEED) + c["cid"]).encode()).hexdigest()):
        if c["outcome"] != "true" or (c["fid"], c["text"]) in seen:
            continue
        f, rec, r = facts[c["fid"]], corpus[c["fid"]], _rng(c["cid"])
        repo, text, slots = rec["repo"], c["text"], c["slots"] or {}
        new = None
        if c["type"] == "structural" and c["subtype"] == "calls" and len(items["calls"]) < CAPS["calls"]:
            old = str(slots.get("callee") or "").strip("`'\" ").split("(")[0].split(".")[-1]
            own = {x.lower() for x in f["calls"]}
            cands = sorted(x for x in repo_calls[repo] if x.lower() not in own and len(x) >= 3
                           and x not in KEYWORDS and x not in rec["source"])
            if old and cands and _word_re(old).search(text):
                rep = r.choice(cands)
                new, kind = _replace(text, old, rep), "calls"
        elif c["type"] == "structural" and c["subtype"] == "parameter" and len(items["parameter"]) < CAPS["parameter"]:
            old = str(slots.get("name") or "").strip("`'\"* ")
            cands = sorted(x for x in repo_params[repo] if x not in rec["source"] and len(x) >= 2 and x != "self")
            if old and cands and _word_re(old).search(text):
                rep = r.choice(cands)
                new, kind = _replace(text, old, rep), "parameter"
        elif c["type"] == "dataflow" and len(items["flow"]) < CAPS["flow"] and f.get("dataflow"):
            g = f["dataflow"]
            src, dst = _resolve(slots.get("source"), g, g["params"]), _resolve(slots.get("sink"), g, g["params"])
            if src and dst:
                plain = lambda n: n[5:] if n.startswith("call:") else n
                nodes = sorted(n for n in g["nodes"] if n not in ("return", "raise") and "." not in n
                               and len(plain(n)) >= 2 and plain(n) not in KEYWORDS)
                sink_txt = str(slots.get("sink") or "").strip("`'\" ").split("(")[0]
                src_txt = str(slots.get("source") or "").strip("`'\" ").split("(")[0]
                c_sink = [n for n in nodes if n != src and n != dst and not reachable(g, src, n)]
                c_src = [n for n in nodes if n != src and n != dst and not reachable(g, n, dst)]
                if dst != "return" and sink_txt and c_sink and _word_re(sink_txt.split(".")[-1]).search(text):
                    new = _replace(text, sink_txt.split(".")[-1], plain(r.choice(c_sink)))
                elif src_txt and c_src and _word_re(src_txt.split(".")[-1]).search(text):
                    new = _replace(text, src_txt.split(".")[-1], plain(r.choice(c_src)))
                kind = "flow"
        elif c["type"] == "behavioural" and c["corpus"] == "B" and len(items["behavioural"]) < CAPS["behavioural"]:
            p = (probes.get(c["cid"]) or {}).get("probe") or {}
            exp = p.get("expect")
            if isinstance(exp, str) and exp.strip() and exp.strip() in text and _mutate_literal(exp):
                new = text.replace(exp.strip(), _mutate_literal(exp), 1)
            else:
                for a, b in ANTONYMS:
                    for x, y in ((a, b), (b, a)):
                        if _word_re(x).search(text):
                            new = _replace(text, x, y)
                            break
                    if new:
                        break
            kind = "behavioural"
        if new and new != text:
            seen.add((c["fid"], text))
            items[kind].append({"orig_cid": c["cid"], "fid": c["fid"], "type": c["type"], "kind": kind,
                                "true_text": text, "false_text": new})
    out = []
    for k in CAPS:
        out += items[k]
    return out


def _swap_tokens(a, b):
    """(original token, substituted token) of a minimally perturbed sentence pair (word-level diff)."""
    wa, wb = re.findall(r"[\w.]+|\S", a), re.findall(r"[\w.]+|\S", b)
    sm = difflib.SequenceMatcher(None, wa, wb)
    olds, news = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            olds += wa[i1:i2]
            news += wb[j1:j2]
    return " ".join(olds), " ".join(news)


def _mentions(slots, tok):
    if not tok:
        return False
    blob = json.dumps(slots or {})
    parts = [p for p in re.findall(r"[A-Za-z_][\w]*|-?\d+(?:\.\d+)?", tok) if p not in ("the", "a", "an")]
    return bool(parts) and all(re.search(r"(?<![\w])" + re.escape(p) + r"(?![\w])", blob) for p in parts)


def run_items(items):
    """Round 2: the frozen round-1 item set (results/planted_items.json) is replayed through the round-2 engine.
    The pseudo-explanations are byte-identical to round 1, so their extractions come from the cache; behavioural
    claims go through blind, mutant-validated probes."""
    from discharge import discharge_claim
    from probe import synthesise, evaluate
    corpus = {r["fid"]: r for r in load_corpus()}
    facts = {json.loads(l)["fid"]: json.loads(l) for l in open(os.path.join(RESULTS, "facts.jsonl"))}
    by_fid = {}
    for i, it in enumerate(items):
        it["pid"] = i
        by_fid.setdefault(it["fid"], []).append(it)
    rows = []
    for fid in sorted(by_fid):
        rec, f = corpus[fid], facts[fid]
        planted = []
        for it in by_fid[fid]:
            planted.append((it, True, it["true_text"]))
            planted.append((it, False, it["false_text"]))
        planted.sort(key=lambda x: hashlib.sha256(f"{SEED}|{x[2]}".encode()).hexdigest())
        text = " ".join(t if t.rstrip().endswith((".", "!", "?")) else t.rstrip() + "." for _, _, t in planted)
        pseudo = {"fid": fid, "explainer": "planted", "corpus": rec["corpus"], "lang": rec["lang"], "text": text}
        claims, _ = claims_for(rec, pseudo, "first")
        for c in claims:
            c["type2"] = "rationale" if c["type"] == "intent" else c["type"]
        pairs = []
        for pi, (_, _, t) in enumerate(planted):
            for ci, c in enumerate(claims):
                pairs.append((difflib.SequenceMatcher(None, t, c["text"]).ratio(), pi, ci))
        pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
        match, used = {}, set()
        for ratio, pi, ci in pairs:
            if ratio < 0.5 or pi in match or ci in used:
                continue
            match[pi] = (ci, ratio)
            used.add(ci)
        beh = [claims[match[pi][0]] for pi in sorted(match) if claims[match[pi][0]]["type2"] == "behavioural"
               and rec["corpus"] == "B"]
        probes = {}
        if beh:
            texts = {c["cid"]: c["text"] for c in beh}
            for cid, p in synthesise(rec, beh).items():
                oc, ev, det = evaluate(rec, p, texts.get(cid))
                probes[cid] = {"outcome": oc, "evidence": ev, "concreteness": p.get("concreteness")}
        for pi, (it, label, t) in enumerate(planted):
            old_tok, new_tok = _swap_tokens(it["true_text"], it["false_text"])
            row = {"pid": it["pid"], "fid": fid, "kind": it["kind"], "orig_type": it["type"], "label": label,
                   "orig_cid": it["orig_cid"], "text": t, "old_tok": old_tok, "new_tok": new_tok}
            if pi not in match:
                row.update({"matched": False, "ext_type": None, "outcome": "lost", "evidence": "no extracted claim matched",
                            "outcome_e": "lost", "evidence_e": "no extracted claim matched", "rule": "lost"})
            else:
                c = claims[match[pi][0]]
                oc, ev, _, rule = discharge_claim(c, f, rec, probes)
                oce, eve = apply_entity_check(c, rec, oc, ev)
                row.update({"matched": True, "match_ratio": round(match[pi][1], 3), "ext_type": c["type"],
                            "ext_subtype": c["subtype"], "slots": c["slots"], "outcome": oc, "evidence": ev,
                            "rule": rule, "outcome_e": oce, "evidence_e": eve,
                            "slot_has_old": _mentions(c["slots"], old_tok), "slot_has_new": _mentions(c["slots"], new_tok)})
            rows.append(row)
    return rows


def main():
    items = json.load(open(os.path.join(RESULTS, "planted_items.json")))
    rows = run_items(items)
    with open(os.path.join(RESULTS, "planted.jsonl"), "w") as fo:
        for r in rows:
            fo.write(json.dumps(r, sort_keys=True) + "\n")
    from collections import Counter
    print("planted items by kind:", dict(Counter(i["kind"] for i in items)))
    print("planted outcomes:", dict(Counter((r["kind"], r["label"], r["outcome"]) for r in rows)))


if __name__ == "__main__":
    main()
