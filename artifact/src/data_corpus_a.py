"""Corpus A: real functions/methods from open-source repositories (shallow clones under data/repos/).

The repositories are untrusted input: we only parse them with tree-sitter; nothing is imported or executed.
Deterministic sampling (SEED) of PY_PER_REPO functions per Python repo and JAVA_PER_REPO methods per Java repo.
"""
import json
import os
import random
import subprocess
import textwrap

from tree_sitter import Language, Parser
import tree_sitter_java
import tree_sitter_python

from config import (DATA, REPOS, SEED, PY_REPOS, JAVA_REPOS, PY_PER_REPO, JAVA_PER_REPO, MIN_LINES,
                    MAX_LINES)

PY_PARSER = Parser(Language(tree_sitter_python.language()))
JAVA_PARSER = Parser(Language(tree_sitter_java.language()))
SKIP_DIRS = ("test", "tests", "testing", "docs", "doc", "examples", "example", "_vendor", "vendor",
             "benchmarks", "bench", "scripts", "conftest", ".git", "site-packages", "src/test")


def _skip(path):
    parts = path.replace("\\", "/").split("/")
    return any(p in SKIP_DIRS for p in parts) or any(p.startswith("test_") for p in parts) or "/src/test/" in path


def _txt(n, src):
    return src[n.start_byte:n.end_byte].decode("utf8", "replace")


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def py_candidates(repo):
    root = os.path.join(REPOS, repo)
    out = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            path = os.path.join(dp, fn)
            rel = os.path.relpath(path, root)
            if not fn.endswith(".py") or _skip(rel) or fn in ("setup.py", "conftest.py", "__main__.py"):
                continue
            try:
                src = open(path, "rb").read()
            except OSError:
                continue
            tree = PY_PARSER.parse(src)
            if tree.root_node.has_error:
                continue
            imports = [_txt(n, src) for n in tree.root_node.children
                       if n.type in ("import_statement", "import_from_statement")]
            for n in _walk(tree.root_node):
                if n.type != "function_definition":
                    continue
                name = _txt(n.child_by_field_name("name"), src)
                if name.startswith("test") or name in ("__init__", "__repr__", "__str__", "__eq__", "__hash__"):
                    continue
                lines = n.end_point[0] - n.start_point[0] + 1
                if not (MIN_LINES <= lines <= MAX_LINES):
                    continue
                if not any(c.type == "call" for c in _walk(n)):
                    continue
                # nested functions excluded (parent must be module or class body)
                par = n.parent
                if par is not None and par.type == "decorated_definition":
                    par = par.parent
                if par is None or par.type not in ("module", "block"):
                    continue
                cls = None
                if par.type == "block" and par.parent is not None and par.parent.type == "class_definition":
                    cls = _txt(par.parent.child_by_field_name("name"), src)
                elif par.type == "block":
                    continue  # nested in a function or other block
                # include decorators
                start = n.start_byte
                if n.parent is not None and n.parent.type == "decorated_definition":
                    start = n.parent.start_byte
                col = n.parent.start_point[1] if (n.parent is not None and n.parent.type == "decorated_definition") else n.start_point[1]
                text = textwrap.dedent(" " * col + src[start:n.end_byte].decode("utf8", "replace"))
                out.append({"repo": repo, "path": rel, "cls": cls, "name": name,
                            "start_line": n.start_point[0] + 1, "end_line": n.end_point[0] + 1,
                            "lines": lines, "source": text,
                            "context_imports": "\n".join(imports[:25]), "lang": "python"})
    out.sort(key=lambda r: (r["path"], r["start_line"]))
    return out


def java_candidates(repo):
    root = os.path.join(REPOS, repo)
    out = []
    for dp, dns, fns in os.walk(root):
        dns.sort()
        for fn in sorted(fns):
            path = os.path.join(dp, fn)
            rel = os.path.relpath(path, root)
            if not fn.endswith(".java") or _skip(rel) or "/test/" in rel or fn.endswith("Test.java"):
                continue
            try:
                src = open(path, "rb").read()
            except OSError:
                continue
            tree = JAVA_PARSER.parse(src)
            if tree.root_node.has_error:
                continue
            imports = [_txt(n, src) for n in tree.root_node.children if n.type == "import_declaration"]
            for n in _walk(tree.root_node):
                if n.type != "method_declaration":
                    continue
                body = n.child_by_field_name("body")
                if body is None:
                    continue
                name = _txt(n.child_by_field_name("name"), src)
                lines = n.end_point[0] - n.start_point[0] + 1
                if not (MIN_LINES <= lines <= MAX_LINES):
                    continue
                if not any(c.type in ("method_invocation", "object_creation_expression") for c in _walk(n)):
                    continue
                cls_node = n.parent.parent if n.parent is not None else None
                cls = None
                if cls_node is not None and cls_node.type in ("class_declaration", "enum_declaration", "interface_declaration"):
                    cls = _txt(cls_node.child_by_field_name("name"), src)
                else:
                    continue  # anonymous/inner-nested methods skipped
                text = textwrap.dedent(" " * n.start_point[1] + src[n.start_byte:n.end_byte].decode("utf8", "replace"))
                out.append({"repo": repo, "path": rel, "cls": cls, "name": name,
                            "start_line": n.start_point[0] + 1, "end_line": n.end_point[0] + 1,
                            "lines": lines, "source": text,
                            "context_imports": "\n".join(imports[:25]), "lang": "java"})
    out.sort(key=lambda r: (r["path"], r["start_line"]))
    return out


def main():
    rng = random.Random(SEED)
    rows, meta = [], {}
    for repo, k, fn in [(r, PY_PER_REPO, py_candidates) for r in PY_REPOS] + \
                       [(r, JAVA_PER_REPO, java_candidates) for r in JAVA_REPOS]:
        cands = fn(repo)
        try:
            commit = subprocess.run(["git", "-C", os.path.join(REPOS, repo), "rev-parse", "HEAD"],
                                    capture_output=True, text=True).stdout.strip()
        except OSError:
            commit = "unknown"
        picked = rng.sample(cands, min(k, len(cands)))
        picked.sort(key=lambda r: (r["path"], r["start_line"]))
        meta[repo] = {"commit": commit, "candidates": len(cands), "sampled": len(picked),
                      "lang": picked[0]["lang"] if picked else None}
        rows.extend(picked)
        print(f"{repo:15s} commit={commit[:10]} candidates={len(cands):5d} sampled={len(picked)}")
    for i, r in enumerate(rows):
        r["fid"] = f"A{i:03d}"
        r["corpus"] = "A"
    with open(os.path.join(DATA, "corpus_a.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    with open(os.path.join(DATA, "corpus_a_meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    print(f"Corpus A: {len(rows)} functions")


if __name__ == "__main__":
    main()
