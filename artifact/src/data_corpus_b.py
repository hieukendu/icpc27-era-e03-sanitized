"""Corpus B: functions with executable ground truth from EvalPlus (HumanEval+, MBPP+).

The *canonical solution* is the explained function. The docstring (which contains worked examples) is
stripped so that behavioural claims are the explainer's own inferences, not copied oracle text.
`exec_source` is the runnable module (imports + function) used ONLY inside the probe sandbox.
"""
import ast
import json
import os
import random

from datasets import load_dataset

from config import DATA, SEED, N_HUMANEVAL, N_MBPP, MAX_LINES


def _strip_docstring(module_src, entry_point):
    try:
        mod = ast.parse(module_src)
    except SyntaxError:
        return None
    lines = module_src.splitlines()
    for node in ast.walk(mod):
        if isinstance(node, ast.FunctionDef) and node.name == entry_point and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                del lines[first.lineno - 1:first.end_lineno]
                break
    out = "\n".join(lines)
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out


def _function_only(module_src, entry_point):
    mod = ast.parse(module_src)
    lines = module_src.splitlines()
    for node in mod.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry_point:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    return None


def _examples_from_doctest(prompt):
    """(call, expected) pairs from `>>> f(...)` lines of the original docstring."""
    out, lines = [], prompt.splitlines()
    for i, l in enumerate(lines):
        st = l.strip()
        if st.startswith(">>> ") and i + 1 < len(lines):
            exp = lines[i + 1].strip()
            if exp and not exp.startswith(">>>") and not exp.startswith('"""'):
                out.append([st[4:].strip(), exp])
    return out


def _examples_from_asserts(test_list):
    import re
    out = []
    for t in test_list:
        m = re.match(r"assert\s+(.+?)\s*==\s*(.+)$", t.strip())
        if m and "(" in m.group(1) and not m.group(1).startswith(("set(", "sorted(", "str(", "round(", "math.")):
            out.append([m.group(1).strip(), m.group(2).strip()])
    return out


def main():
    rng = random.Random(SEED)
    rows = []
    he = load_dataset("evalplus/humanevalplus", split="test")
    cands = []
    for r in he:
        full = r["prompt"].rstrip() + "\n" + r["canonical_solution"]
        stripped = _strip_docstring(full, r["entry_point"])
        if stripped is None:
            continue
        fn = _function_only(stripped, r["entry_point"])
        if fn is None or fn.count("\n") + 1 > MAX_LINES or fn.count("\n") + 1 < 3:
            continue
        imports = "\n".join(l for l in stripped.splitlines() if l.startswith(("import ", "from ")))
        cands.append({"task_id": r["task_id"], "name": r["entry_point"], "source": fn,
                      "context_imports": imports, "exec_source": stripped, "lang": "python",
                      "dataset": "humanevalplus", "lines": fn.count("\n") + 1,
                      "examples": _examples_from_doctest(r["prompt"])})
    cands.sort(key=lambda r: r["task_id"])
    rows += sorted(rng.sample(cands, N_HUMANEVAL), key=lambda r: r["task_id"])
    print(f"HumanEval+: {len(cands)} candidates, sampled {N_HUMANEVAL}")

    mb = load_dataset("evalplus/mbppplus", split="test")
    cands = []
    for r in mb:
        code = r["code"].strip("\n")
        try:
            mod = ast.parse(code)
        except SyntaxError:
            continue
        funcs = [n for n in mod.body if isinstance(n, ast.FunctionDef)]
        if len(funcs) != 1:   # single-function programs only (so the explained unit is unambiguous)
            continue
        imports = "\n".join(l for l in code.splitlines() if l.startswith(("import ", "from ")))
        fn = _function_only(code, funcs[0].name)
        if fn is None or fn.count("\n") + 1 > MAX_LINES or fn.count("\n") + 1 < 3:
            continue
        cands.append({"task_id": f"Mbpp/{r['task_id']}", "name": funcs[0].name, "source": fn,
                      "context_imports": imports, "exec_source": code, "lang": "python",
                      "dataset": "mbppplus", "lines": fn.count("\n") + 1,
                      "examples": _examples_from_asserts(r["test_list"])})
    cands.sort(key=lambda r: int(r["task_id"].split("/")[1]))
    rows += sorted(rng.sample(cands, N_MBPP), key=lambda r: int(r["task_id"].split("/")[1]))
    print(f"MBPP+: {len(cands)} candidates, sampled {N_MBPP}")

    for i, r in enumerate(rows):
        r["fid"] = f"B{i:03d}"
        r["corpus"] = "B"
        r["repo"] = r["dataset"]
        r["path"] = r["task_id"]
        r["cls"] = None
    with open(os.path.join(DATA, "corpus_b.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    print(f"Corpus B: {len(rows)} functions")


if __name__ == "__main__":
    main()
