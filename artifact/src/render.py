"""Render results/*.csv + summary.json into manuscript/generated/{macros,tab_*,fig_*}.tex (paper == artifact)."""
import csv
import json
import os

from config import RESULTS, GENERATED

TYPES = ["structural", "dataflow", "behavioural", "purpose", "rationale"]
TLAB = {"structural": "Structural", "dataflow": "Data-flow", "behavioural": "Behavioural",
        "purpose": "Purpose", "rationale": "Rationale"}
EVID = {"structural": "tree-sitter facts", "dataflow": "reaching defs (may)", "behavioural": "blind probe",
        "purpose": "probe / class facts", "rationale": "outside $E$"}
KLAB = {"calls": "Calls", "parameter": "Parameter", "flow": "Data-flow", "behavioural": "Behavioural (B)",
        "all": "All (primary)", "all+E": "All (+E, ablation)"}


def rd(name):
    with open(os.path.join(RESULTS, name), newline="") as f:
        return list(csv.DictReader(f))


def pct(x, d=0):
    if x in (None, "", "None"):
        return "--"
    return f"{100 * float(x):.{d}f}"


def num(x, d=2):
    return "--" if x in (None, "", "None") else f"{float(x):.{d}f}"


def w(name, text):
    with open(os.path.join(GENERATED, name), "w") as f:
        f.write(text)


def macro_name(s):
    s = s.replace("coder14b", "coder").replace("general14b", "general").replace("frontier", "haiku")
    out, up = "", True
    for ch in s:
        if ch.isalpha():
            out += ch.upper() if up else ch
            up = False
        else:
            up = True
            if ch.isdigit():
                out += "ABCDEFGHIJ"[int(ch)]
    return out


def main():
    S = json.load(open(os.path.join(RESULTS, "summary.json")))
    M = {}

    def m(k, v):
        M[macro_name(k)] = v

    def mest(k, e, d=1):
        m(k, pct(e["v"], d)); m(k + " lo", pct(e["lo"], d)); m(k + " hi", pct(e["hi"], d))

    for k in ("n_functions", "n_rounds", "n_func_apy", "n_func_ajava", "n_func_b", "n_explanations",
              "n_explanations_local", "n_explanations_frontier", "n_cache"):
        m(k.replace("_", " "), S[k])
    m("n extra cached", S.get("n_extra_cached_coder", 0))
    m("n claims", f"{S['n_claims']:,}".replace(",", "{,}")); m("n claims local", f"{S['n_claims_local']:,}".replace(",", "{,}"))
    for c, v in S["claims_per_expl"].items():
        m(f"cpe {c}", f"{v:.1f}")
    h1 = S["H1"]
    rt_ = S["retype"]
    mest("hone full", h1["full"]); mest("hone held", h1["heldout"])
    m("hone held n", h1["heldout"]["n"])
    for r, v in h1["per_round"].items():
        m(f"hone round {r}", pct(v, 1))
    for s, k in (("A-python", "apy"), ("A-java", "ajava"), ("B", "b")):
        mest(f"slice {k}", h1["slice"][s], 0); mest(f"slice held {k}", h1["slice_heldout"][s], 0)
        m(f"slice held {k} n", h1["slice_heldout"][s]["n"]); m(f"slice {k} one", pct(h1["slice"][s]["v"], 1))
    mest("hone consistent", h1["consistent_share"]); mest("hone decons", h1["decided_or_consistent"])
    mest("resid rationale", h1["rationale_in_residue"], 0); mest("resid policy", h1["policy_in_residue"], 0)
    mest("resid consistent", h1["consistent_in_residue"], 0); mest("rationale all", h1["rationale_share_all"], 0)
    m("rationale all one", pct(h1["rationale_share_all"]["v"], 1)); m("rt ratall second one", pct(rt_["rationale_share_all_second"], 1))
    m("intent all ext", pct(h1["intent_share_all_extractor"])); mest("dbp decided", h1["dbp_decided"], 0)
    mest("bp b decided", h1["beh_purpose_B_decided"], 0)
    for t in S["typology"]:
        m(f"typ {t['type']} n", t["n"]); m(f"typ {t['type']} share", pct(t["share"]))
        m(f"typ {t['type']} dec", pct(t["decided_share"]))
    rt = S["retype"]
    m("rt n", rt["n_intent"]); m("rt func", pct(rt["functional_primary"])); m("rt func second", pct(rt["functional_second"]))
    m("rt agree", pct(rt["agree_primary_second"])); m("rt kappa", num(rt["kappa_primary_second"]))
    m("rt kappa ext", num(rt["kappa_primary_extractor_subtype"])); m("rt ratall second", pct(rt["rationale_share_all_second"]))
    for p in S["profile"]:
        k = p["key"].replace("-", " ")
        m(f"prof {k} dec", pct(p["decided"], 1)); m(f"prof {k} falsedec", pct(p["false_dec"], 1))
        m(f"prof {k} falsedec lo", pct(p["false_dec_lo"], 1)); m(f"prof {k} falsedec hi", pct(p["false_dec_hi"], 1))
        m(f"prof {k} falsenoinst", pct(p["false_dec_no_inst"], 1)); m(f"prof {k} cons", pct(p["consistent"], 1))
    mc = S["matched_haiku_minus_local"]
    for k in ("decided", "false_dec"):
        m(f"mc {k}", pct(mc[k]["v"], 1)); m(f"mc {k} lo", pct(mc[k]["lo"], 1)); m(f"mc {k} hi", pct(mc[k]["hi"], 1))
    pr = S["probes"]
    m("probe n", pr["n"]); m("probe pre", pr["invalid_pre"]); m("probe nondisc", pr["nondiscriminating"])
    m("probe raised", pr["raised"]); m("probe err", pr["errors"]); m("probe noprobe", pr["no_probe"])
    for conc in ("stated", "instantiated"):
        d = pr["by_conc"].get(conc, {})
        for o in ("true", "false", "consistent", "unverifiable"):
            m(f"probe {conc[:4]} {o}", d.get(o, 0))
        m(f"probe {conc[:4]} n", sum(d.values()))
    m("probe none n", sum(pr["by_conc"].get("none", {}).values()))
    m("probe disagree", pr.get("instance_disagreement", 0))
    pa = S.get("probe_audit", {})
    m("paudit n", sum(pa.values())); m("paudit synth", pa.get("synthesiser_error", 0))
    m("paudit claimfalse", pa.get("claim_false", 0)); m("paudit ambig", pa.get("ambiguous", 0))
    v1t = pr.get("v1_true_now", {})
    m("probe vone true n", sum(v1t.values())); m("probe vone true still", v1t.get("true", 0))
    fl = S["flips"]
    m("flip vone true", fl["v1_true_local"]); m("flip total", fl["v1_true_to_other"])
    m("flip vone decided", pct(fl["v1_decided"], 1))
    for fam, v in fl["by_family"].items():
        m(f"flip fam {fam.replace('/', ' ')}", v)
    for k, v in fl["by_rule"].items():
        m("flip " + k.replace("->", " to ").replace("-", " "), v)
    for k, v in fl.get("into_true_from", {}).items():
        m(f"flip into true from {k}", v)
    m("flip into true", sum(fl.get("into_true_from", {}).values()))
    f23 = S.get("flips_v2_v3", {})
    m("vtwo decided", pct(f23.get("v2_decided_local"), 1))
    for k, v in f23.get("transitions", {}).items():
        m("vthree " + k.replace("->", " to "), v)
    m("vthree member", f23.get("rules", {}).get("member=>member-compound", 0))
    m("vthree total", sum(f23.get("transitions", {}).values()))
    fp = S.get("flips_prev", {})
    m("vthree decided", pct(fp.get("v3_decided_local"), 1)); m("prev total", fp.get("total", 0))
    for k, v in fp.get("transitions", {}).items():
        m("prev " + k.replace("->", " to "), v)
    fa = S.get("false_audit", {})
    m("fa n", fa.get("n_false_all", 0)); m("fa local", fa.get("n_false_local", 0)); m("fa correct", fa.get("correct", 0))
    m("fa prev local", fa.get("prev_false_local", 0)); m("fa prev all", fa.get("prev_false_all", 0))
    ex = S.get("extractor", {})
    sv4 = S.get("false_audit_v3", {}).get("second_v4", {})
    m("ext second false", ex.get("n_second_false", 0)); m("ext second false vfour", sv4.get("n", 0))
    m("ext second false vfour correct", sv4.get("correct", 0))
    m("ext sd decided second", ex.get("sd_decided_second", 0))
    fa_ids = {r["cid"] for r in csv.DictReader(open(os.path.join(os.path.dirname(RESULTS), "data", "false_audit.csv")))}
    un2 = [c for c in ex.get("second_false", []) if c not in fa_ids]
    if un2:
        raise SystemExit(f"render: unaudited second-extraction FALSE verdicts {un2}")
    f3 = S.get("false_audit_v3", {})
    for grp in ("corpus", "corpus_local", "planted"):
        for k, v in f3.get(grp, {}).items():
            m(f"fathree {grp.replace('_', ' ')} {k.replace('_', ' ')}", v)
    m("fathree local true", sum(v for k, v in f3.get("corpus_local", {}).items() if k != "correct_refutation"))
    m("fathree all true", sum(v for k, v in f3.get("corpus", {}).items() if k != "correct_refutation"))
    ta = S.get("true_audit", {})
    m("ta n", ta.get("n", 0)); m("ta more", ta.get("asserts_more", 0)); m("ta pure", ta.get("pure", 0)); m("ta unrel", ta.get("slot_unrelated", 0))
    import math as _mth

    def _wilson(k, n, z=1.96):
        if n == 0:
            return 0, 0
        p_ = k / n
        d = 1 + z * z / n
        c = (p_ + z * z / (2 * n)) / d
        h = z * _mth.sqrt(p_ * (1 - p_) / n + z * z / (4 * n * n)) / d
        return c - h, c + h
    kpart = ta.get("asserts_more", 0) + ta.get("slot_unrelated", 0)
    nta = max(1, ta.get("n", 1))
    m("ta morepct", pct(kpart / nta)); lo_, hi_ = _wilson(kpart, nta)
    m("ta morepct lo", pct(lo_)); m("ta morepct hi", pct(hi_)); m("ta partial n", kpart)
    m("ta purepct", pct(ta.get("pure", 0) / nta)); lo_, hi_ = _wilson(ta.get("pure", 0), nta)
    m("ta purepct lo", pct(lo_)); m("ta purepct hi", pct(hi_))
    # Full-scope estimate and finite-population interval: revision_analysis.py.
    m("text any", pct(h1.get("text_any_decided"), 1)); m("text all", pct(h1.get("text_all_decided"), 1))
    m("n texts", h1.get("n_texts", 0)); m("dec true share", pct(h1.get("decided_true_share"), 1))
    f45 = S.get("flips_v4_v5", {})
    m("vfour decided", pct(f45.get("v4_decided_local"), 1)); m("vfive total", f45.get("total", 0))
    for k, v in f45.get("transitions", {}).items():
        m("vfive " + k.replace("->", " to "), v)
    if fa.get("unaudited"):
        raise SystemExit(f"render: unaudited FALSE verdicts {fa['unaudited']} -- audit them in data/false_audit.csv")
    mest("hone held noprule", h1["heldout_without_probe_rule"]); mest("hone full noprule", h1["full_without_probe_rule"])
    m("hone ndisagree local", h1["n_disagree_local"])
    for k, v in S.get("probe_audit_split", {}).items():
        m("pasplit " + k.replace(":", " ").replace("_", " "), v)
    for k, v in S.get("probe_partition", {}).items():
        m("ppart " + k.replace("_", " "), v)
    m("ppart sum", S.get("probe_partition_sum", 0))
    m("probe vtwo cons", pr.get("v2_consistent_n", 0)); m("probe vtwo cons pretrue", pr.get("v2_consistent_pre_true", 0))
    m("probe cons pretrue", pr.get("consistent_pre_true", 0)); m("probe cons n", pr.get("consistent_n", 0))
    if "extractor" in S:
        e = S["extractor"]
        m("ext n", e["n_expl"]); m("ext nfunc", e["n_func"]); m("ext matched", pct(e["matched_frac"]))
        m("ext kappa", num(e["kappa_matched"])); mest("ext agree", e["type_agree_incl_unmatched"], 0)
        m("ext false first", pct(e["sd_false_first"], 1)); m("ext false second", pct(e["sd_false_second"], 1))
    if "H2" in S:
        h = S["H2"]
        m("htwo judge", h["judge"]); m("htwo n", h["n_points"]); m("htwo nfunc", h["n_func"]); m("htwo judged", h["n_expl_judged"])
        for k in ("same_claims", "coder_only", "rest_claims"):
            d = h.get(k, {})
            kk = {"same_claims": "s", "coder_only": "c", "rest_claims": "r"}[k]
            m(f"htwo {kk} n", d.get("n", 0)); m(f"htwo {kk} rho", num(d.get("rho"))); m(f"htwo {kk} tau", num(d.get("tau_b")))
            m(f"htwo {kk} p", num(d.get("p_boot"), 3)); m(f"htwo {kk} pperm", num(d.get("p_perm"), 3))
            m(f"htwo {kk} lo", num(d.get("lo"))); m(f"htwo {kk} hi", num(d.get("hi")))
            m(f"htwo {kk} yone", d.get("y_eq_1", 0)); m(f"htwo {kk} dropped", d.get("boot_dropped") or 0)
            m(f"htwo {kk} xone", d.get("x_eq_1", 0))
        cf = h.get("conf", {})
        m("htwo true F", cf.get("true/F", 0)); m("htwo true judged", cf.get("true/F", 0) + cf.get("true/T", 0))
        m("htwo rest T", pct(h.get("rest_judge_T_share"))); m("htwo rest judged", h.get("rest_judged_n", 0))
        m("htwo agree", pct(h["agree"])); m("htwo kappa", num(h["kappa"])); m("htwo pairs", h["claim_pairs"])
        m("htwo ef n", h["engine_false_n"]); m("htwo ef jf", h["engine_false_judge_F"])
        m("htwo jf n", h["judge_F_n"]); m("htwo jf ef", h["judge_F_engine_false"])
    if "planted" in S:
        a = S["planted_audit"]
        m("pl frozen", a["pairs_frozen"]); m("pl orignottrue", a["orig_not_true_v2"]); m("pl audited", a["audited"])
        m("pl labelerr", a["label_error"]); m("pl valid", a["pairs_valid"])
        sd = S.get("planted_audit_sides", {})
        m("pl audited false", sd.get("false_twins", 0)); m("pl audited true", sd.get("true_twins", 0))
        for r in S["planted"]:
            k = r["kind"].replace("+E", " e")
            m(f"pl {k} pairs", r["pairs"])
            for nm in ("lost", "true_kept", "true_to_false", "caught", "f_to_t", "prec_false"):
                m(f"pl {k} {nm.replace('_', ' ')}", pct(r[nm]))
                m(f"pl {k} {nm.replace('_', ' ')} lo", pct(r[nm + "_lo"])); m(f"pl {k} {nm.replace('_', ' ')} hi", pct(r[nm + "_hi"]))
        pm = S["planted_miss"]
        for k, v in pm.items():
            m(f"miss {k.replace('_', ' ')}", v)
    # Actual crossed-model results are rendered by render_revision.py.
    tl = os.path.join(RESULTS, "test_engine.log")
    if not os.path.exists(tl):
        raise SystemExit("render: results/test_engine.log missing -- run tests/test_engine.py (make render does)")
    tags = [line[:3] for line in open(tl)]
    if tags.count("BUG"):
        raise SystemExit("render: regression test has failing cases")
    m("suite total", sum(tags.count(t) for t in ("OK ", "LIM", "FIX"))); m("suite lim", tags.count("LIM"))
    m("suite fixed", tags.count("FIX")); m("suite pass", tags.count("OK "))
    w("macros.tex", "% generated by artifact/src/render.py -- do not edit\n" +
      "".join(f"\\newcommand{{\\{k}}}{{{v}}}\n" for k, v in sorted(M.items())))

    # ---------------- Table 1: typology
    rows = rd("tab_typology.csv")
    body = [f"{TLAB[r['type']]} & {EVID[r['type']]} & {r['n']} ({pct(r['share'])}) & {r['true']} & {r['false']} & "
            f"{r['consistent']} & {r['unverifiable']} & {r['undischargeable']} \\\\" for r in rows]
    w("tab_typology.tex", "\\begin{table}[t]\n\\centering\n\\caption{SDBPR claim types after re-typing, their evidence "
      "kind, and \\attest{} outcomes for the local explainers' claims (T true, F false, C consistent, Unv unverifiable, "
      "Und undischargeable).}\n\\label{tab:typology}\n\\footnotesize\\setlength{\\tabcolsep}{2.4pt}\n"
      "\\begin{tabular}{@{}llrrrrrr@{}}\n\\toprule\nType & Evidence & Claims (\\%) & T & F & C & Unv & Und \\\\\n\\midrule\n" +
      "\n".join(body) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")

    # ---------------- Table 2: profile
    rows = rd("tab_profile.csv")
    body = []
    for r in rows:
        if r["key"] in ("local", "A-python"):
            body.append("\\midrule")
        body.append(f"{r['label']} & {r['n_func']} & {r['n_claims']} & {pct(r['decided'], 1)} [{pct(r['decided_lo'], 1)}, "
                    f"{pct(r['decided_hi'], 1)}] & {pct(r['consistent'], 0)} & "
                    + (f"{pct(r['false_dec'], 1)} [{pct(r['false_dec_lo'], 1)}, {pct(r['false_dec_hi'], 1)}]"
                       if float(r['false_dec'] or 0) > 0 else "0 (none)") + " \\\\")
    w("tab_profile.tex", "\\begin{table}[t]\n\\centering\n\\caption{Decided share (true+false) with 95\\% cluster-bootstrap "
      "CIs over functions, consistent share, and false share among decided claims (Haiku: rounds 1--3 only).}\n\\label{tab:profile}\n"
      "\\footnotesize\\setlength{\\tabcolsep}{1.6pt}\n\\begin{tabular}{@{}lrrrrr@{}}\n\\toprule\n"
      "Explainer / slice & Fn & Claims & Decided \\% & C \\% & False \\% \\\\\n\\midrule\n" + "\n".join(body) +
      "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")

    # ---------------- Table 3: planted
    if os.path.exists(os.path.join(RESULTS, "tab_planted.csv")):
        rows = rd("tab_planted.csv")
        total = next(int(r["pairs"]) for r in rows if r["kind"] == "all")
        shown = sum(int(r["pairs"]) for r in rows if r["kind"] not in ("all", "all+E") and int(r["pairs"]) >= 5)
        body = []
        for r in rows:
            if int(r["pairs"]) < 5:
                continue            # too few audited pairs to report (behavioural: see text)
            if r["kind"] == "all":
                body.append("\\midrule")
            ci = lambda k: f"{pct(r[k])} [{pct(r[k + '_lo'])}, {pct(r[k + '_hi'])}]"
            body.append(f"{KLAB[r['kind']]} & {r['pairs']} & {pct(r['lost'])} & {pct(r['true_kept'])} & {ci('caught')} & "
                        f"{ci('f_to_t')} & {pct(r['prec_false'])} \\\\")
        w("tab_planted.tex", "\\begin{table}[t]\n\\centering\n\\caption{\\attest{} end-to-end on planted pairs (\\%; 95\\% CIs clustered by function; columns defined in "
          f"Sec.~\\ref{{sec:eval}}). Per-kind rows cover {shown} of {total} pairs; kinds with $<$5 pairs "
          "(behavioural) omitted.}\n\\label{tab:planted}\n\\footnotesize\\setlength{\\tabcolsep}{2pt}\n"
          "\\begin{tabular}{@{}lrrrrrr@{}}\n\\toprule\nPerturbation & Pairs & Lost & Kept & Caught & F$\\to$T & Prec \\\\\n"
          "\\midrule\n" + "\n".join(body) + "\n\\bottomrule\n\\end{tabular}\n\\end{table}\n")

    # ---------------- Figure 1: stacked bars per type x explainer
    rows = rd("fig_outcomes.csv")
    conds = []
    for r in rows:
        if r["cond"] not in conds:
            conds.append(r["cond"])
    short = {"coder14b": "Coder", "general14b": "Qwen", "frontier": "Haiku"}
    tshort = {"structural": "S", "dataflow": "D", "behavioural": "B", "purpose": "P", "rationale": "R"}
    ylabels = [f"{short[c]}-{tshort[t]}" for c in conds for t in TYPES]
    series = [("true", "true", "teal!70"), ("false", "false", "red!70"), ("consistent", "consistent", "teal!25"),
              ("unverifiable", "unverifiable", "gray!45"), ("undischargeable", "undischargeable", "orange!45")]
    plots = []
    for key, lab, col in series:
        coords = " ".join(f"({100 * float(r[key]):.1f},{short[r['cond']]}-{tshort[r['type']]})" for r in rows)
        plots.append(f"\\addplot[xbar,draw=none,fill={col},area legend] coordinates {{{coords}}};\\addlegendentry{{{lab}}}")
    w("fig_outcomes.tex", "\\begin{figure}[t]\n\\centering\n\\begin{tikzpicture}\n\\begin{axis}[xbar stacked, "
      "width=0.74\\columnwidth, height=5.2cm, bar width=3.0pt, xmin=0, xlabel={\\% of the explainer's claims}, "
      f"symbolic y coords={{{','.join(reversed(ylabels))}}}, ytick=data, "
      "yticklabel style={font=\\scriptsize}, xticklabel style={font=\\scriptsize}, label style={font=\\scriptsize}, "
      "legend style={font=\\scriptsize, at={(1.02,0.5)}, anchor=west, legend columns=1, draw=none}, "
      "xmajorgrids, grid style={dashed,gray!30}, enlarge y limits=0.04]\n" + "\n".join(plots) +
      "\n\\end{axis}\n\\end{tikzpicture}\n\\caption{\\attest{} outcomes by claim type (S/D/B/P/R) and explainer, as a "
      "share of all claims of that explainer.}\n\\label{fig:outcomes}\n\\end{figure}\n")
    print(f"render: {len(M)} macros -> {os.path.basename(GENERATED)}")


if __name__ == "__main__":
    main()
