"""Deterministic work order and corpus selection.

GPU time is shared with three sibling projects, so the LLM stages run function-by-function along a fixed,
stratified round-robin WORK ORDER (each round = 6 Python functions, one per repository; 2 Java methods, one
per repository; 4 EvalPlus problems, two per source). Within a stratum, functions keep their fid order (fids
were assigned after a seeded random sample, see data_corpus_*.py). The analysed corpus is the first
N_ROUNDS complete rounds (data/selection.json), so any truncation is deterministic and balanced.
Subsets: second extraction on functions at order positions p % SECOND_EVERY == 0, H2-proxy judge on
p % JUDGE_EVERY == 0 (both explanations of each such function).
"""
import json
import os

from config import DATA

SECOND_EVERY = 4
JUDGE_EVERY = 3
STRATA = [("A", "click"), ("A", "requests"), ("A", "tqdm"), ("A", "more-itertools"), ("A", "attrs"),
          ("A", "boltons"), ("A", "gson"), ("A", "commons-lang"),
          ("B", "humanevalplus"), ("B", "humanevalplus"), ("B", "mbppplus"), ("B", "mbppplus")]


def _rows():
    rows = []
    for name in ("corpus_a.jsonl", "corpus_b.jsonl"):
        rows += [json.loads(l) for l in open(os.path.join(DATA, name))]
    return rows


def work_order():
    """List of rounds; each round is a list of fids."""
    pools = {}
    for r in sorted(_rows(), key=lambda r: r["fid"]):
        pools.setdefault((r["corpus"], r["repo"]), []).append(r["fid"])
    ptr = {k: 0 for k in pools}
    rounds = []
    while True:
        rnd = []
        for s in STRATA:
            if ptr[s] < len(pools[s]):
                rnd.append(pools[s][ptr[s]])
                ptr[s] += 1
        if not rnd:
            break
        rounds.append(rnd)
    return rounds


def flat_order():
    return [f for rnd in work_order() for f in rnd]


def selection():
    """{'n_rounds': k, 'fids': [...]} -- the analysed corpus."""
    p = os.path.join(DATA, "selection.json")
    if not os.path.exists(p):
        raise SystemExit("data/selection.json missing: run `python select_corpus.py <n_rounds>`")
    return json.load(open(p))


def selected_fids():
    return set(selection()["fids"])


def position(fid):
    return flat_order().index(fid)


def in_second(fid):
    return position(fid) % SECOND_EVERY == 0


def in_judge(fid):
    return position(fid) % JUDGE_EVERY == 0
