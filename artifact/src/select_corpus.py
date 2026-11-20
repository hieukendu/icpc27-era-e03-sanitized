"""Freeze the analysed corpus as the first N complete rounds of the work order (see selection.py)."""
import json
import os
import sys

from config import DATA
from selection import work_order

if __name__ == "__main__":
    n = int(sys.argv[1])
    rounds = work_order()[:n]
    fids = [f for r in rounds for f in r]
    json.dump({"n_rounds": n, "fids": fids}, open(os.path.join(DATA, "selection.json"), "w"), indent=1)
    print(f"selection: {n} rounds, {len(fids)} functions")
