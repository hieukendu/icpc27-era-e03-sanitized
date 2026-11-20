"""Aggregate Attest (round-2 engine) outputs into CSVs + summary.json for the manuscript.

Statistics: 95% percentile CIs from a cluster bootstrap over FUNCTIONS (B = 2000, seeded) for every rate,
including the planted-set metrics and the H2 correlation; permutation p-values for H2; Cohen's kappa for
typing agreement. Decided = true + false. H1 decision rule (coded before round 1): the CI upper bound of the
decided share must be < 60%.
"""
import csv
import difflib
import json
import os
from collections import Counter, defaultdict

import numpy as np
from scipy import stats as sps

from config import DATA, RESULTS, SEED, EXPLAINERS, FRONTIER, EXTRACTOR, EXTRACTOR_SECOND, JUDGE, JUDGE_V1
from selection import selection, work_order
from discharge import discharge_claim, type2_of, load_retype

B = 2000
TYPES = ["structural", "dataflow", "behavioural", "purpose", "rationale"]
OUTC = ["true", "false", "consistent", "unverifiable", "undischargeable"]
COND_ORDER = ["coder14b", "general14b", "frontier"]
H1_THRESHOLD = 0.60
TUNING_ROUNDS = 2          # rounds 1-2 were inspected while the round-1 engine was tuned (RUNLOG cycles 2, 4)


def load(name):
    p = os.path.join(RESULTS, name)
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def write_csv(name, rows, cols):
    with open(os.path.join(RESULTS, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in cols})


def r4(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)


def clusters(items, key="fid"):
    by = defaultdict(list)
    for c in items:
        by[c[key]].append(c)
    return [by[k] for k in sorted(by)]


DROPS = {}


def boot(items, stat, rng, key="fid", tag=None):
    """Percentile CI; resamples where the statistic is undefined are counted. If more than 5% are undefined the
    interval is not reported (round 3, R2-3: silently dropping no-variance resamples biased an H2 interval)."""
    cl = clusters(items, key)
    if not cl:
        return None, None
    vals, dropped = [], 0
    for _ in range(B):
        samp = []
        for i in rng.choice(len(cl), len(cl)):
            samp += cl[i]
        v = stat(samp)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            vals.append(v)
        else:
            dropped += 1
    if tag:
        DROPS[tag] = dropped
    if not vals or dropped > 0.05 * B:
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def share(pred):
    return lambda cs: (sum(1 for c in cs if pred(c)) / len(cs)) if cs else None


def ratio(num, den):
    def f(cs):
        d = [c for c in cs if den(c)]
        return (sum(1 for c in d if num(c)) / len(d)) if d else None
    return f


def kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    labs = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[l] * cb[l] for l in labs) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


decided = lambda c: c["outcome"] in ("true", "false")


def est(items, stat, rng):
    lo, hi = boot(items, stat, rng)
    return {"v": r4(stat(items)), "lo": r4(lo), "hi": r4(hi), "n": len(items)}


def main():
    rng = np.random.default_rng(SEED)
    sel = selection()
    rounds = work_order()
    round_of = {f: i + 1 for i, r in enumerate(rounds) for f in r}
    expls = load("explanations.jsonl")
    claims = load("discharge.jsonl")
    for c in claims:
        c["round"] = round_of[c["fid"]]
    local = [c for c in claims if c["explainer"] != "frontier"]
    S = {"n_rounds": sel["n_rounds"], "n_functions": len(sel["fids"]),
         "planned": {"functions": 270, "second_extraction": 100, "judge": 120}}
    sl = Counter("A-python" if e["corpus"] == "A" and e["lang"] == "python" else "A-java" if e["corpus"] == "A" else "B"
                 for e in expls if e["explainer"] == "coder14b")
    S.update({"n_func_apy": sl["A-python"], "n_func_ajava": sl["A-java"], "n_func_b": sl["B"],
              "n_explanations": len(expls), "n_explanations_local": sum(e["explainer"] != "frontier" for e in expls),
              "n_explanations_frontier": sum(e["explainer"] == "frontier" for e in expls),
              "n_claims": len(claims), "n_claims_local": len(local)})
    S["models"] = {"coder14b": EXPLAINERS["coder14b"][1], "general14b": EXPLAINERS["general14b"][1],
                   "frontier": FRONTIER[1], "extractor": EXTRACTOR[1], "extractor_second": EXTRACTOR_SECOND[1],
                   "judge": JUDGE[1], "judge_v1": JUDGE_V1[1], "retypers": ["gemma2:9b", "llama3.1:8b"]}
    S["mean_words"] = {c: r4(np.mean([e["n_words"] for e in expls if e["explainer"] == c])) for c in COND_ORDER}
    per = Counter((c["explainer"], c["fid"]) for c in claims)
    S["claims_per_expl"] = {c: r4(np.mean([per.get((c, e["fid"]), 0) for e in expls if e["explainer"] == c])) for c in COND_ORDER}
    cache = set(os.listdir(os.path.join(RESULTS, "llm_cache")))
    S["n_cache"] = len(cache)
    from explain import load_corpus, prompt_for, SYSTEM as EXPL_SYSTEM
    from llm import _key
    extra = 0
    for r in load_corpus():
        if r["fid"] not in set(sel["fids"]):
            k = _key("ollama", EXPLAINERS["coder14b"][1], EXPL_SYSTEM, prompt_for(r), False, 450)
            extra += (k + ".json") in cache
    S["n_extra_cached_coder"] = extra

    # ---------------- Table 1: typology x outcome (local)
    typ = []
    for t in TYPES:
        cs = [c for c in local if c["type2"] == t]
        oc = Counter(c["outcome"] for c in cs)
        typ.append({"type": t, "n": len(cs), "share": r4(len(cs) / len(local)), **{o: oc[o] for o in OUTC},
                    "decided_share": r4((oc["true"] + oc["false"]) / len(cs)) if cs else None})
    write_csv("tab_typology.csv", typ, ["type", "n", "share"] + OUTC + ["decided_share"])
    S["typology"] = typ

    # ---------------- H1 (local): full corpus, held-out rounds 3-5, per round, per slice
    held = [c for c in local if c["round"] > TUNING_ROUNDS]
    h1 = {"full": est(local, share(decided), rng), "heldout": est(held, share(decided), rng)}
    for k in ("full", "heldout"):
        h1[k]["supported"] = bool(h1[k]["hi"] is not None and h1[k]["hi"] < H1_THRESHOLD)
    h1["per_round"] = {r: r4(share(decided)([c for c in local if c["round"] == r])) for r in range(1, sel["n_rounds"] + 1)}
    sl_of = lambda c: "B" if c["corpus"] == "B" else ("A-java" if c["lang"] == "java" else "A-python")
    h1["slice"] = {s: est([c for c in local if sl_of(c) == s], share(decided), rng) for s in ("A-python", "A-java", "B")}
    h1["slice_heldout"] = {s: est([c for c in held if sl_of(c) == s], share(decided), rng) for s in ("A-python", "A-java", "B")}
    h1["consistent_share"] = est(local, share(lambda c: c["outcome"] == "consistent"), rng)
    h1["decided_or_consistent"] = est(local, share(lambda c: c["outcome"] in ("true", "false", "consistent")), rng)
    resid = lambda c: not decided(c)
    h1["residue_n"] = sum(1 for c in local if resid(c))
    h1["rationale_in_residue"] = est([c for c in local], ratio(lambda c: c["type2"] == "rationale", resid), rng)
    h1["policy_in_residue"] = est(local, ratio(lambda c: c["rule"] == "policy", resid), rng)
    h1["consistent_in_residue"] = est(local, ratio(lambda c: c["outcome"] == "consistent", resid), rng)
    h1["rationale_share_all"] = est(local, share(lambda c: c["type2"] == "rationale"), rng)
    h1["intent_share_all_extractor"] = r4(share(lambda c: c["type"] == "intent")(local))
    # reader-relevant coverage: data-flow + behavioural + purpose claims only
    dbp = [c for c in local if c["type2"] in ("dataflow", "behavioural", "purpose")]
    h1["dbp_decided"] = est(dbp, share(decided), rng)
    h1["beh_purpose_B_decided"] = est([c for c in local if c["type2"] in ("behavioural", "purpose") and c["corpus"] == "B"],
                                      share(decided), rng)
    dis = lambda c: decided(c) or "instance disagreement" in c["evidence"]
    h1["heldout_without_probe_rule"] = est(held, share(dis), rng)
    h1["full_without_probe_rule"] = est(local, share(dis), rng)
    h1["n_disagree_local"] = sum(1 for c in local if "instance disagreement" in c["evidence"])
    # sentence-level view (claim texts are not always atomic: one text can carry several slots)
    by_text = defaultdict(list)
    for c in local:
        by_text[(c["explainer"], c["fid"], c["text"])].append(c)
    h1["n_texts"] = len(by_text)
    h1["text_any_decided"] = r4(sum(1 for v in by_text.values() if any(decided(c) for c in v)) / len(by_text))
    h1["text_all_decided"] = r4(sum(1 for v in by_text.values() if all(decided(c) for c in v)) / len(by_text))
    h1["decided_true_share"] = r4(sum(1 for c in local if c["outcome"] == "true") / max(1, sum(1 for c in local if decided(c))))
    S["H1"] = h1

    # ---------------- re-typing agreement (all claims typed intent by the extractor, all explainers)
    rt = load_retype()
    ints = [c for c in claims if c["type"] == "intent"]
    a = [rt.get(c["cid"], {}).get("retype_primary") for c in ints]
    b = [rt.get(c["cid"], {}).get("retype_second") for c in ints]
    both = [(x, y) for x, y in zip(a, b) if x and y]
    ext = ["FUNCTIONAL" if c["subtype"] == "purpose" else "RATIONALE" for c in ints]
    pe = [(x, y) for x, y in zip(a, ext) if x]
    S["retype"] = {"n_intent": len(ints), "n_labelled_primary": sum(1 for x in a if x),
                   "n_labelled_second": sum(1 for x in b if x),
                   "functional_primary": r4(sum(1 for x in a if x == "FUNCTIONAL") / max(1, sum(1 for x in a if x))),
                   "functional_second": r4(sum(1 for x in b if x == "FUNCTIONAL") / max(1, sum(1 for x in b if x))),
                   "agree_primary_second": r4(sum(1 for x, y in both if x == y) / len(both)) if both else None,
                   "kappa_primary_second": r4(kappa([x for x, _ in both], [y for _, y in both])),
                   "n_both": len(both),
                   "kappa_primary_extractor_subtype": r4(kappa([x for x, _ in pe], [y for _, y in pe])),
                   "agree_primary_extractor_subtype": r4(sum(1 for x, y in pe if x == y) / len(pe)) if pe else None}
    # sensitivity: rationale share of residue if the second re-typer's labels were used
    alt = []
    for c in local:
        t2 = c["type2"]
        if c["type"] == "intent":
            lab = rt.get(c["cid"], {}).get("retype_second") or rt.get(c["cid"], {}).get("retype_primary")
            t2 = "purpose" if lab == "FUNCTIONAL" else "rationale"
        alt.append(t2)
    resid_alt = [t for c, t in zip(local, alt) if not decided(c) or (c["type2"] != t)]
    S["retype"]["rationale_share_all_second"] = r4(sum(1 for t in alt if t == "rationale") / len(alt))

    # ---------------- Table 2: profile by explainer + pooled views
    prof = []

    def prow(label, cs, key, dec_est=None):
        dd = [c for c in cs if decided(c)]
        row = {"key": key, "label": label, "n_claims": len(cs), "n_func": len({c["fid"] for c in cs})}
        for t in TYPES:
            row["share_" + t] = r4(share(lambda c, t=t: c["type2"] == t)(cs))
        e = dec_est or est(cs, share(decided), rng)
        row.update({"decided": e["v"], "decided_lo": e["lo"], "decided_hi": e["hi"],
                    "consistent": r4(share(lambda c: c["outcome"] == "consistent")(cs))})
        e = est(cs, ratio(lambda c: c["outcome"] == "false", decided), rng)
        row.update({"false_dec": e["v"], "false_dec_lo": e["lo"], "false_dec_hi": e["hi"]})
        row["false_dec_no_inst"] = r4(ratio(lambda c: c["outcome"] == "false",
                                            lambda c: decided(c) and "instance counterexample" not in c["evidence"])(cs))
        prof.append(row)
    for cond in COND_ORDER:
        cs = [c for c in claims if c["explainer"] == cond]
        if cs:
            prow({"coder14b": "Qwen2.5-Coder-14B", "general14b": "Qwen2.5-14B",
                  "frontier": "Claude Haiku 5.5 (r1--3)"}[cond], cs, cond)
    prow("Local, all rounds", local, "local", h1["full"])
    prow("Local, held-out r3--5", held, "heldout", h1["heldout"])
    for s, lab in (("A-python", "Python repos"), ("A-java", "Java repos"), ("B", "EvalPlus")):
        prow(lab, [c for c in local if sl_of(c) == s], s, h1["slice"][s])
    write_csv("tab_profile.csv", prof, list(prof[0].keys()))
    S["profile"] = prof

    # matched-round contrast Haiku vs local (rounds 1-3), paired by function
    m_local = [c for c in local if c["round"] <= 3]
    m_hk = [c for c in claims if c["explainer"] == "frontier"]
    fids = sorted({c["fid"] for c in m_hk})
    def diff_stat(stat):
        def f(sample_fids):
            hk = [c for fid in sample_fids for c in by_hk.get(fid, [])]
            lo_ = [c for fid in sample_fids for c in by_lo.get(fid, [])]
            a_, b_ = stat(hk), stat(lo_)
            return None if a_ is None or b_ is None else a_ - b_
        return f
    by_hk, by_lo = defaultdict(list), defaultdict(list)
    for c in m_hk:
        by_hk[c["fid"]].append(c)
    for c in m_local:
        by_lo[c["fid"]].append(c)
    mc = {}
    for nm, stat in (("decided", share(decided)), ("false_dec", ratio(lambda c: c["outcome"] == "false", decided))):
        f = diff_stat(stat)
        vals = [f([fids[i] for i in rng.choice(len(fids), len(fids))]) for _ in range(B)]
        vals = [v for v in vals if v is not None]
        mc[nm] = {"v": r4(f(fids)), "lo": r4(np.percentile(vals, 2.5)), "hi": r4(np.percentile(vals, 97.5))}
    S["matched_haiku_minus_local"] = mc

    # ---------------- probes
    pr = [p for p in load("probe_runs.jsonl") if p["fid"] in set(sel["fids"])]
    S["probes"] = {"n": len(pr),
                   "by_conc": {k: dict(Counter(p["outcome"] for p in pr if (p.get("probe") or {}).get("concreteness") == k))
                               for k in ("stated", "instantiated", "none")},
                   "invalid_pre": sum(1 for p in pr if "precondition" in p["evidence"]),
                   "nondiscriminating": sum(1 for p in pr if "non-discriminating" in p["evidence"]),
                   "raised": sum(1 for p in pr if "probe call raised" in p["evidence"]),
                   "errors": sum(1 for p in pr if p["evidence"].startswith("probe ")),
                   "no_probe": sum(1 for p in pr if p["evidence"].startswith("no ")),
                   "local_n": sum(1 for p in pr if p["explainer"] != "frontier")}
    S["probes"]["instance_disagreement"] = sum(1 for p in pr if "instance disagreement" in p["evidence"])
    pa = os.path.join(DATA, "probe_audit.csv")
    if os.path.exists(pa):
        rows_pa = list(csv.DictReader(open(pa)))
        S["probe_audit"] = dict(Counter(r["decision"] for r in rows_pa))
        split = Counter()
        for r in rows_pa:
            ex, fid = r["cid"].split(":")[0], r["cid"].split(":")[1]
            grp = "haiku" if ex == "frontier" else ("heldout" if round_of[fid] > TUNING_ROUNDS else "tuning")
            split[f"{grp}:{r['decision']}"] += 1
        S["probe_audit_split"] = dict(split)
    # exact partition of probe-routed claims
    part = Counter()
    for p in pr:
        conc = (p.get("probe") or {}).get("concreteness")
        ev = p["evidence"]
        if p.get("probe") is None:
            k = "no_probe_returned"
        elif conc == "stated":
            k = "stated_" + p["outcome"]
        elif conc == "instantiated":
            k = ("inst_consistent" if p["outcome"] == "consistent" else
                 "inst_disagreement" if "instance disagreement" in ev else
                 "inst_nondiscriminating" if "non-discriminating" in ev else
                 "inst_vacuous_pre" if "vacuous precondition" in ev else
                 "inst_invalid_pre" if "precondition" in ev else
                 "inst_error" if (ev.startswith("probe ") or "raised" in ev) else
                 "inst_no_call" if ev.startswith("no executable") else "inst_other")
        else:
            k = "no_executable_probe"
        part[k] += 1
    S["probe_partition"] = dict(sorted(part.items()))
    S["probe_partition_sum"] = sum(part.values())
    S["probes"]["consistent_pre_true"] = sum(1 for p in pr if p["outcome"] == "consistent"
                                             and ((p.get("probe") or {}).get("precondition") or "True").strip() == "True")
    S["probes"]["consistent_n"] = sum(1 for p in pr if p["outcome"] == "consistent")
    pv2 = [p for p in load("v2/probe_runs.jsonl") if p["fid"] in set(sel["fids"])]
    S["probes"]["v2_consistent_n"] = sum(1 for p in pv2 if p["outcome"] == "consistent")
    S["probes"]["v2_consistent_pre_true"] = sum(1 for p in pv2 if p["outcome"] == "consistent"
                                                and ((p.get("probe") or {}).get("precondition") or "True").strip() == "True")
    v1p = {p["cid"]: p for p in load("v1/probe_runs.jsonl")}
    S["probes"]["v1_true_now"] = dict(Counter(p["outcome"] for p in pr if v1p.get(p["cid"], {}).get("outcome") == "true"))

    # ---------------- v1 -> v2 flips
    v1 = {c["cid"]: c for c in load("v1/discharge.jsonl")}
    fl = Counter()
    trans = Counter()
    for c in local:
        o1 = v1.get(c["cid"], {}).get("outcome")
        if o1 is None:
            continue
        trans[(o1, c["outcome"])] += 1
        if o1 == "true" and c["outcome"] != "true":
            fl[(c["rule"], c["outcome"])] += 1
    S["flips"] = {"v1_true_local": sum(1 for c in local if v1.get(c["cid"], {}).get("outcome") == "true"),
                  "v1_true_to_other": sum(fl.values()),
                  "by_rule": {f"{k[0]}->{k[1]}": v for k, v in sorted(fl.items(), key=lambda x: -x[1])},
                  "transitions": {f"{a}->{b}": v for (a, b), v in sorted(trans.items())},
                  "v1_decided": r4(sum(1 for c in local if v1.get(c["cid"], {}).get("outcome") in ("true", "false")) / len(local))}
    fr = defaultdict(int)
    for (rule, oc), v in fl.items():
        fam = ("returns" if rule.startswith("returns") else "flow" if rule.startswith("flow") else
               "probe" if rule.startswith("probe") else "calls/imports" if rule.startswith(("calls", "imports")) else
               "retype" if rule in ("member",) else "other")
        fr[fam] += v
    S["flips"]["by_family"] = dict(fr)
    S["flips"]["into_true_from"] = {k.split("->")[0]: v for k, v in S["flips"]["transitions"].items()
                                    if k.endswith("->true") and not k.startswith("true")}
    # real-corpus FALSE audit (all explainers; AI-assistant audit in data/false_audit.csv)
    fa = {r["cid"]: r for r in csv.DictReader(open(os.path.join(DATA, "false_audit.csv")))} \
        if os.path.exists(os.path.join(DATA, "false_audit.csv")) else {}
    fals = [c for c in claims if c["outcome"] == "false"]
    S["false_audit"] = {"n_false_all": len(fals), "n_false_local": sum(1 for c in fals if c["explainer"] != "frontier"),
                        "audited": sum(1 for c in fals if c["cid"] in fa),
                        "correct": sum(1 for c in fals if fa.get(c["cid"], {}).get("decision") == "correct_refutation"),
                        "unaudited": [c["cid"] for c in fals if c["cid"] not in fa]}
    # earlier-FALSE audit (v3 engine + planted true twins) and TRUE audit (random sample; AI assistant)
    p3 = os.path.join(DATA, "false_audit_v3.csv")
    if os.path.exists(p3):
        r3_ = list(csv.DictReader(open(p3)))
        sv4 = [r for r in r3_ if r["id"].startswith("second_v4:")]
        second_v4 = {"n": len(sv4), "correct": sum(1 for r in sv4 if r["decision"] == "correct_refutation")}
        r3_ = [r for r in r3_ if not r["id"].startswith("second_v4:")]
        S["false_audit_v3"] = {"corpus": dict(Counter(r["decision"] for r in r3_ if not r["id"].startswith("planted"))),
                               "corpus_local": dict(Counter(r["decision"] for r in r3_ if not r["id"].startswith(("planted", "frontier")))),
                               "planted": dict(Counter(r["decision"] for r in r3_ if r["id"].startswith("planted"))),
                               "second_v4": second_v4}
    pt = os.path.join(DATA, "true_audit.csv")
    if os.path.exists(pt):
        rt_ = list(csv.DictReader(open(pt)))
        S["true_audit"] = {"n": len(rt_), **dict(Counter(r["decision"] for r in rt_))}
    v3 = {c["cid"]: c for c in load("v3/discharge.jsonl")}
    S["false_audit"]["prev_false_local"] = sum(1 for c in v3.values() if c["outcome"] == "false" and c["explainer"] != "frontier")
    S["false_audit"]["prev_false_all"] = sum(1 for c in v3.values() if c["outcome"] == "false")
    tp = Counter()
    for c in claims:
        o3 = v3.get(c["cid"], {}).get("outcome")
        if o3 is not None and o3 != c["outcome"]:
            tp[f"{o3}->{c['outcome']}"] += 1
    S["flips_prev"] = {"transitions": dict(sorted(tp.items())), "total": sum(tp.values()),
                       "v3_decided_local": r4(sum(1 for c in local if v3.get(c["cid"], {}).get("outcome") in ("true", "false")) / len(local))}
    v4 = {c["cid"]: c for c in load("v4/discharge.jsonl")}
    t45 = Counter()
    for c in claims:
        o4 = v4.get(c["cid"], {}).get("outcome")
        if o4 is not None and o4 != c["outcome"]:
            t45[f"{o4}->{c['outcome']}"] += 1
    S["flips_v4_v5"] = {"transitions": dict(sorted(t45.items())), "total": sum(t45.values()),
                        "v4_decided_local": r4(sum(1 for c in local if v4.get(c["cid"], {}).get("outcome") in ("true", "false")) / len(local))}
    v2 = {c["cid"]: c for c in load("v2/discharge.jsonl")}
    t23 = Counter()
    r23 = Counter()
    for c in local:
        o2 = v2.get(c["cid"], {}).get("outcome")
        if o2 is not None and o2 != c["outcome"]:
            t23[f"{o2}->{c['outcome']}"] += 1
            r23[f"{v2[c['cid']].get('rule')}=>{c['rule']}"] += 1
    S["flips_v2_v3"] = {"transitions": dict(sorted(t23.items())), "rules": dict(sorted(r23.items(), key=lambda x: -x[1])),
                        "v2_decided_local": r4(sum(1 for c in local if v2.get(c["cid"], {}).get("outcome") in ("true", "false")) / len(local))}

    # ---------------- Figure 1: outcome shares by type x explainer
    fig = []
    for cond in COND_ORDER:
        n_all = sum(1 for c in claims if c["explainer"] == cond)
        for t in TYPES:
            cs = [c for c in claims if c["explainer"] == cond and c["type2"] == t]
            oc = Counter(c["outcome"] for c in cs)
            fig.append({"cond": cond, "type": t, "n": len(cs), **{o: r4(oc[o] / n_all) if n_all else 0 for o in OUTC}})
    write_csv("fig_outcomes.csv", fig, ["cond", "type", "n"] + OUTC)

    # ---------------- extractor consistency (S/D re-discharge under the second extractor's slots)
    sec = load("claims_second.jsonl")
    facts = {json.loads(l)["fid"]: json.loads(l) for l in open(os.path.join(RESULTS, "facts.jsonl"))}
    if sec:
        first_by, sec_by = defaultdict(list), defaultdict(list)
        for c in local:
            first_by[(c["explainer"], c["fid"])].append(c)
        for c in sec:
            sec_by[(c["explainer"], c["fid"])].append(c)
        keys = sorted(sec_by.keys() | {k for k in first_by if k in sec_by})
        rows = []
        for k in keys:
            a_, b_ = first_by[k], sec_by[k]
            pairs = sorted(((difflib.SequenceMatcher(None, x["text"], y["text"]).ratio(), i, j)
                            for i, x in enumerate(a_) for j, y in enumerate(b_)), key=lambda p: (-p[0], p[1], p[2]))
            ua, ub = {}, set()
            for r_, i, j in pairs:
                if r_ < 0.6 or i in ua or j in ub:
                    continue
                ua[i] = j
                ub.add(j)
            for i, x in enumerate(a_):
                rows.append({"fid": k[1], "matched": i in ua, "t1": x["type"],
                             "t2": b_[ua[i]]["type"] if i in ua else None})
        m = [r for r in rows if r["matched"]]
        from explain import load_corpus as _lc
        _corp = {r["fid"]: r for r in _lc()}
        second_false = []

        def sd_rate(cs, record=False):
            out = []
            for c in cs:
                if c["type"] in ("structural", "dataflow"):
                    c2 = dict(c)
                    c2["type2"] = c["type"]
                    oc = discharge_claim(c2, facts.get(c["fid"]), _corp.get(c["fid"]), {})[0]
                    out.append(oc)
                    if record and oc == "false":
                        second_false.append("second:" + c["cid"])
            d = [o for o in out if o in ("true", "false")]
            return (sum(1 for o in d if o == "false") / len(d)) if d else None, len(d)
        s1 = [c for k in keys for c in first_by[k]]
        s2 = [c for k in keys for c in sec_by[k]]
        f1, n1 = sd_rate(s1)
        f2, n2 = sd_rate(s2, record=True)
        e_tm = est(rows, share(lambda r: r["matched"] and r["t1"] == r["t2"]), rng)
        S["extractor"] = {"n_expl": len(keys), "n_func": len({k[1] for k in keys}), "claims_first": len(s1),
                          "claims_second": len(s2), "matched_frac": r4(len(m) / len(rows)) if rows else None,
                          "kappa_matched": r4(kappa([r["t1"] for r in m], [r["t2"] for r in m])),
                          "type_agree_incl_unmatched": e_tm,
                          "sd_false_first": r4(f1), "sd_false_second": r4(f2), "sd_decided_first": n1, "sd_decided_second": n2,
                          "second_false": sorted(second_false), "n_second_false": len(second_false),
                          }

    # ---------------- H2 proxy (round 2: gemma2:9b judge, different family; same claim set for x and y)
    jd = {j["cid"]: j for j in load("judge.jsonl")}
    if jd:
        by = defaultdict(list)
        for c in local:
            if c["cid"] in jd:
                by[(c["explainer"], c["fid"])].append(c)
        pts = []
        for k in sorted(by):
            cs = [c for c in by[k] if decided(c) and jd[c["cid"]]["judge"] in ("T", "F")]
            rest = [c for c in by[k] if not decided(c) and jd[c["cid"]]["judge"] in ("T", "F")]
            if len(cs) >= 2:
                pts.append({"fid": k[1], "explainer": k[0],
                            "x": sum(c["outcome"] == "true" for c in cs) / len(cs),
                            "y": sum(jd[c["cid"]]["judge"] == "T" for c in cs) / len(cs),
                            "y_rest": (sum(jd[c["cid"]]["judge"] == "T" for c in rest) / len(rest)) if len(rest) >= 2 else None,
                            "n": len(cs)})
        h2 = {"judge": JUDGE[1], "n_expl_judged": len(by), "n_points": len(pts), "n_func": len({p["fid"] for p in pts})}

        def corr(ps, ykey="y"):
            ps = [p for p in ps if p[ykey] is not None]
            if len(ps) < 5 or len({p["x"] for p in ps}) < 2 or len({p[ykey] for p in ps}) < 2:
                return {"n": len(ps)}
            x = np.array([p["x"] for p in ps])
            y = np.array([p[ykey] for p in ps])
            rho = sps.spearmanr(x, y).statistic
            tau = sps.kendalltau(x, y).statistic
            prng = np.random.default_rng(SEED + 7)
            perm = [sps.spearmanr(x, prng.permutation(y)).statistic for _ in range(B)]
            perm = np.nan_to_num(np.array(perm))
            pval = float((np.sum(np.abs(perm) >= abs(rho)) + 1) / (B + 1))
            # function-clustered bootstrap; the p-value is derived from the SAME bootstrap distribution
            # (two-sided, share of resamples on the other side of 0), so CI and p agree by construction
            cl = clusters(ps)
            vals, dropped = [], 0
            for _ in range(B):
                samp = [p for i in rng.choice(len(cl), len(cl)) for p in cl[i]]
                xs_, ys_ = [p["x"] for p in samp], [p[ykey] for p in samp]
                if len(set(xs_)) > 1 and len(set(ys_)) > 1:
                    vals.append(sps.spearmanr(xs_, ys_).statistic)
                else:
                    dropped += 1
            DROPS["h2_" + ykey + str(len(ps))] = dropped
            if vals and dropped <= 0.05 * B:
                lo, hi = float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))
                v_ = np.array(vals)
                p_boot = float(min(1.0, 2 * min(np.mean(v_ <= 0), np.mean(v_ >= 0))))
            else:
                lo = hi = p_boot = None
            return {"n": len(ps), "rho": r4(rho), "tau_b": r4(tau), "p_perm": r4(pval), "p_boot": r4(p_boot),
                    "lo": r4(lo), "hi": r4(hi),
                    "x_eq_1": int(np.sum(x == 1.0)), "y_eq_1": int(np.sum(y == 1.0)),
                    "boot_dropped": DROPS.get("h2_" + ykey + str(len(ps)))}
        h2["same_claims"] = corr(pts)
        h2["coder_only"] = corr([p for p in pts if p["explainer"] == "coder14b"])
        h2["rest_claims"] = corr(pts, "y_rest")
        pairs = [(c["outcome"], jd[c["cid"]]["judge"]) for k in by for c in by[k] if decided(c)]
        conf = Counter(pairs)
        dec = [(o, j) for o, j in pairs if j in ("T", "F")]
        rest_lab = [jd[c["cid"]]["judge"] for k in by for c in by[k] if not decided(c) and jd[c["cid"]]["judge"] in ("T", "F")]
        h2["rest_judge_T_share"] = r4(sum(1 for j in rest_lab if j == "T") / len(rest_lab)) if rest_lab else None
        h2["rest_judged_n"] = len(rest_lab)
        h2.update({"claim_pairs": len(pairs),
                   "conf": {f"{o}/{j}": v for (o, j), v in sorted(conf.items())},
                   "agree": r4(sum(1 for o, j in dec if (o == "true") == (j == "T")) / len(dec)) if dec else None,
                   "kappa": r4(kappa(["T" if o == "true" else "F" for o, _ in dec], [j for _, j in dec])),
                   "engine_false_n": sum(1 for o, j in dec if o == "false"),
                   "engine_false_judge_F": sum(1 for o, j in dec if o == "false" and j == "F"),
                   "judge_F_n": sum(1 for o, j in dec if j == "F"),
                   "judge_F_engine_false": sum(1 for o, j in dec if j == "F" and o == "false")})
        S["H2"] = h2
        write_csv("h2_points.csv", [{"x": r4(p["x"]), "y": r4(p["y"]), "n": p["n"], "explainer": p["explainer"]} for p in pts],
                  ["x", "y", "n", "explainer"])

    # ---------------- planted set (round-2 engine, audited labels)
    pl = load("planted.jsonl")
    if pl:
        v2o = {c["cid"]: c["outcome"] for c in claims}
        audit = {}
        ap = os.path.join(DATA, "planted_audit.csv")
        if os.path.exists(ap):
            for r in csv.DictReader(open(ap)):
                audit[int(r["pid"])] = r
        pids = sorted({r["pid"] for r in pl})
        orig = {r["pid"]: r["orig_cid"] for r in pl}
        valid = {p for p in pids if v2o.get(orig[p]) == "true" and audit.get(p, {}).get("decision") != "label_error"}
        n_true_side = sum(1 for r in audit.values() if "TRUE twin" in (r.get("note") or ""))
        S["planted_audit_sides"] = {"false_twins": len(audit) - n_true_side, "true_twins": n_true_side}
        S["planted_audit"] = {"pairs_frozen": len(pids),
                              "orig_not_true_v2": sum(1 for p in pids if v2o.get(orig[p]) != "true"),
                              "audited": len(audit),
                              "label_error": sum(1 for p in pids if audit.get(p, {}).get("decision") == "label_error"
                                                 and v2o.get(orig[p]) == "true"),
                              "label_ok": sum(1 for p in pids if audit.get(p, {}).get("decision") == "label_ok"
                                              and v2o.get(orig[p]) == "true"),
                              "pairs_valid": len(valid)}
        rows_v = [r for r in pl if r["pid"] in valid]

        def pmet(oc_key):
            return {"lost": share(lambda r: r[oc_key] == "lost"),
                    "true_kept": ratio(lambda r: r[oc_key] == "true", lambda r: r["label"]),
                    "true_to_false": ratio(lambda r: r[oc_key] == "false", lambda r: r["label"]),
                    "caught": ratio(lambda r: r[oc_key] == "false", lambda r: not r["label"]),
                    "f_to_t": ratio(lambda r: r[oc_key] == "true", lambda r: not r["label"]),
                    "prec_false": ratio(lambda r: not r["label"], lambda r: r[oc_key] == "false")}
        tab = []
        for kind in ["calls", "parameter", "flow", "behavioural", "all", "all+E"]:
            oc_key = "outcome_e" if kind == "all+E" else "outcome"
            rs = [r for r in rows_v if kind.startswith("all") or r["kind"] == kind]
            if not rs:
                continue
            row = {"kind": kind, "pairs": sum(1 for r in rs if r["label"]), "n_func": len({r["fid"] for r in rs})}
            for nm, fn in pmet(oc_key).items():
                e = est(rs, fn, rng)
                row[nm], row[nm + "_lo"], row[nm + "_hi"] = e["v"], e["lo"], e["hi"]
            tab.append(row)
        write_csv("tab_planted.csv", tab, list(tab[0].keys()))
        S["planted"] = tab
        # breakdown of missed false twins (primary engine)
        F = [r for r in rows_v if not r["label"]]
        miss = [r for r in F if r["outcome"] != "false"]
        cat = Counter()
        for r in miss:
            if r["outcome"] == "lost":
                cat["lost"] += 1
            elif r["outcome"] == "undischargeable":
                cat["typed_rationale"] += 1
            elif r["outcome"] == "unverifiable":
                cat["unverifiable"] += 1
            elif r["outcome"] == "consistent":
                cat["consistent"] += 1
            elif r.get("slot_has_new"):
                cat["true_grounded_on_false_token"] += 1
            elif r.get("slot_has_old"):
                cat["true_silent_correction"] += 1
            else:
                cat["true_regrounded_elsewhere"] += 1
        S["planted_miss"] = {"n_false": len(F), "n_missed": len(miss), **dict(cat)}

    from llm import cache_digest
    S["llm_cache"] = cache_digest()
    with open(os.path.join(RESULTS, "summary.json"), "w") as f:
        json.dump(S, f, indent=1, sort_keys=True)
    print(json.dumps({"H1_full": S["H1"]["full"], "H1_heldout": S["H1"]["heldout"], "flips": S["flips"]["by_family"]}, indent=1))


if __name__ == "__main__":
    main()
