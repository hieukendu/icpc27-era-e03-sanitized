"""Warm-up driver: walks the deterministic WORK ORDER function by function and fills the LLM cache for every
LLM stage (explanations x2, extraction x2, second extraction / judge on the designated subsets, probe
synthesis for Corpus B). The analysis scripts later replay exactly the same prompts from the cache.
Progress (completed rounds) is logged so the corpus can be frozen at a complete round boundary.

usage: python warm.py [max_rounds]      (local explainers, all LLM stages)
       python warm.py --frontier K     (frontier explainer + extraction for the first K rounds only)
"""
import json
import os
import sys
import time

from config import EXPLAINERS
from explain import load_corpus, explain_one
from extract import claims_for
from judge import judge
from probe import synthesise
from selection import work_order, in_second, in_judge
from llm import stats


def do_function(rec, conds):
    for cond in conds:
        e = explain_one(rec, cond)
        claims, _ = claims_for(rec, e, "first")
        if cond == "frontier":
            continue
        if in_second(rec["fid"]):
            claims_for(rec, e, "second")
        if in_judge(rec["fid"]):
            judge(rec, sorted(claims, key=lambda c: c["cid"]))
        if rec["corpus"] == "B":
            beh = [c for c in claims if c["type"] == "behavioural"]
            if beh:
                synthesise(rec, beh)


def main():
    args = sys.argv[1:]
    frontier_k = 0
    if "--frontier" in args:
        i = args.index("--frontier")
        frontier_k = int(args[i + 1])
        del args[i:i + 2]
    max_rounds = int(args[0]) if args else 10 ** 6
    corpus = {r["fid"]: r for r in load_corpus()}
    t0 = time.time()
    if frontier_k:
        max_rounds = frontier_k
    for r, rnd in enumerate(work_order()[:max_rounds]):
        for fid in rnd:
            conds = ["frontier"] if frontier_k else list(EXPLAINERS)
            do_function(corpus[fid], conds)
        print(f"[warm] round {r+1} complete ({sum(len(x) for x in work_order()[:r+1])} functions), "
              f"{time.time()-t0:.0f}s, {stats()}", flush=True)


if __name__ == "__main__":
    main()
