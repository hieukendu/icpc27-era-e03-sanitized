"""Behavioural discharge for Corpus B (round-2 revision, R3-M2/M7).

1. BLIND synthesis: an LLM (cached, JSON mode) turns each behavioural / functional-purpose claim into a probe
   from the function SIGNATURE and the claim text only -- the body is never shown.
   Probe = {call, expect | expect_raises, precondition, concreteness}; concreteness is "stated" (the claim names
   the input and the outcome), "instantiated" (the claim is general; the synthesiser chose an input and derived
   the expectation from the claim's wording), or "none".
2. VALIDATION: the probe's precondition (a self-contained boolean expression saying that the chosen input
   satisfies the claim's condition) must evaluate to True, else the probe is invalid; a probe that passes on
   the original function must FAIL on at least one first-order mutant of the function (operator / constant /
   boolean-connective swaps), else it cannot discriminate; a call that raises in a non-raise probe is a probe
   error, not a falsification. Invalid / non-discriminating probes -> UNVERIFIABLE.
3. VERDICT: stated probes give TRUE/FALSE; an instantiated probe that passes gives CONSISTENT (instance evidence
   for a general sentence); one that fails gives UNVERIFIABLE ("instance disagreement"), because an audit
   (data/probe_audit.csv) found most such failures to be synthesiser errors.
Isolation (what actually exists): each run is a fresh `python -I` subprocess in an empty temporary directory
with a minimal environment, a 5 s wall-clock timeout and a CPU-time rlimit, wrapped in macOS `sandbox-exec`
with a profile that denies all network access and all file writes outside the temporary directory. There is
NO memory limit (macOS does not let us lower RLIMIT_AS/RLIMIT_DATA). LLM-written call strings are executed as
given inside this wrapper.
"""
import ast
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

from config import RESULTS, PROBER, PROBE_TIMEOUT_S
from llm import llm, parse_json, stats
from explain import load_corpus

PY = sys.executable
SANDBOX = shutil.which("sandbox-exec")
N_MUTANTS = 8
SYSTEM = "You write minimal, deterministic Python test probes from specifications. Output only valid JSON."

INSTRUCTIONS = """You are given only the SIGNATURE of a Python function (its body is hidden) and some CLAIMS a
developer read about it. For each claim write an executable probe that tests whether the claim is true.
Rules:
- "call": one Python expression calling the function with concrete literal arguments.
- Exactly one of "expect" (a Python literal for the result the CLAIM implies) or "expect_raises" (the exception
  class name the CLAIM says is raised). Derive the expectation from the claim's wording only.
- "precondition": a self-contained Python boolean expression over your literal arguments that is True exactly
  when the chosen input satisfies the situation the claim talks about (e.g. for "if the two lists have different
  lengths it returns False" with call f([1],[2,3]) use "len([1]) != len([2,3])"); use "True" if the claim has no
  condition.
- "concreteness": "stated" if the claim itself names the input and the outcome; "instantiated" if the claim is
  general and you chose an input; "none" if no meaningful probe exists (purpose, performance, printing, mutation
  that a return value cannot show, or a claim about internal steps).
- Keep inputs small. For floats use values with exact representations.
Output JSON: {"probes": [{"id": <claim id>, "concreteness": "...", "call": "...", "expect": "..." or null,
"expect_raises": "..." or null, "precondition": "..."}, ...]}
"""

HARNESS = r'''
import json as __json, math as __math
def __approx__(a, b):
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return type(a) is type(b) and a == b
        if isinstance(a, float) or isinstance(b, float):
            return __math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return type(a) == type(b) and len(a) == len(b) and all(__approx__(x, y) for x, y in zip(a, b))
        return a == b
    except Exception:
        return False
def __run__():
    try:
        __pre = bool(__PRE__)
    except Exception as __e:
        return {"status": "probe_error", "error": "precondition: " + type(__e).__name__}
    if not __pre:
        return {"status": "pre_false"}
    try:
        __r = (__CALL__)
    except Exception as __e:
        return {"status": "raised", "raised": type(__e).__name__, "mro": [c.__name__ for c in type(__e).__mro__]}
    try:
        __exp = (__EXPECT__)
    except Exception as __e:
        return {"status": "probe_error", "error": "expect: " + type(__e).__name__ + ": " + str(__e)[:120]}
    return {"status": "returned", "match": bool(__approx__(__r, __exp)), "result": repr(__r)[:200],
            "expected": repr(__exp)[:200], "rtype": type(__r).__name__, "etype": type(__exp).__name__}
print("@@PROBE@@" + __json.dumps(__run__()))
'''


def _limits():
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (PROBE_TIMEOUT_S, PROBE_TIMEOUT_S + 1))
    except (ValueError, OSError):
        pass


def run_probe(exec_source, call, expect, expect_raises, precondition="True"):
    expect_expr = "None" if expect_raises else (expect if expect not in (None, "") else "None")
    script = exec_source + "\n" + HARNESS.replace("__PRE__", precondition or "True").replace("__CALL__", call) \
        .replace("__EXPECT__", expect_expr)
    with tempfile.TemporaryDirectory() as td:
        td = os.path.realpath(td)
        path = os.path.join(td, "probe.py")
        with open(path, "w") as f:
            f.write(script)
        cmd = [PY, "-I", path]
        if SANDBOX:
            prof = ("(version 1)(allow default)(deny network*)(deny file-write*)"
                    f'(allow file-write* (subpath "{td}") (literal "/dev/null"))')
            cmd = [SANDBOX, "-p", prof] + cmd
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "HOME": td, "TMPDIR": td,
               "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "no_proxy": ""}
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, cwd=td, env=env,
                               preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return {"status": "timeout"}
        for line in p.stdout.splitlines():
            if line.startswith("@@PROBE@@"):
                try:
                    return json.loads(line[len("@@PROBE@@"):])
                except json.JSONDecodeError:
                    break
        err = (p.stderr.strip().splitlines() or ["?"])[-1][:200]
        return {"status": "probe_error" if ("SyntaxError" in err or "NameError" in err) else "crash", "error": err}


# ----------------------------------------------------------------------------------------------- mutants
class _Mutator(ast.NodeTransformer):
    SWAP_CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
                ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
    SWAP_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult,
                ast.Div: ast.Mult, ast.Mod: ast.FloorDiv}

    def __init__(self, target):
        self.target, self.i = target, -1

    def _hit(self):
        self.i += 1
        return self.i == self.target

    def visit_Compare(self, node):
        self.generic_visit(node)
        if type(node.ops[0]) in self.SWAP_CMP and self._hit():
            node.ops[0] = self.SWAP_CMP[type(node.ops[0])]()
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if type(node.op) in self.SWAP_BIN and self._hit():
            node.op = self.SWAP_BIN[type(node.op)]()
        return node

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        if self._hit():
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, bool):
            if self._hit():
                return ast.copy_location(ast.Constant(not node.value), node)
        elif isinstance(node.value, int) and self._hit():
            return ast.copy_location(ast.Constant(node.value + 1), node)
        return node


def mutants(exec_source, name):
    """Deterministic first-order mutants of function `name` inside the module source (up to N_MUTANTS)."""
    try:
        mod = ast.parse(exec_source)
    except SyntaxError:
        return []
    out, seen = [], set()
    for k in range(60):
        m = ast.parse(exec_source)
        fn = next((n for n in m.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        if fn is None:
            return []
        mut = _Mutator(k)
        for stmt in fn.body:
            mut.visit(stmt)
        if mut.i < k:
            break
        try:
            src = ast.unparse(m)
        except Exception:
            continue
        if src not in seen and src != ast.unparse(mod):
            seen.add(src)
            out.append(src)
        if len(out) >= N_MUTANTS:
            break
    return out


# ----------------------------------------------------------------------------------------------- verdicts
def _passes(run, expect_raises):
    st = run.get("status")
    if expect_raises:
        return st == "raised" and expect_raises in run.get("mro", [run.get("raised")])
    return st == "returned" and bool(run.get("match"))


def _norm_pre(pre):
    """A precondition that is a constant expression (no names, no calls: `1 == 1`, `(True)`) is vacuous -> 'True'."""
    pre = (pre or "True").strip()
    try:
        tree = ast.parse(pre, mode="eval")
    except SyntaxError:
        return pre
    if not any(isinstance(n, (ast.Name, ast.Call, ast.Attribute)) and not (isinstance(n, ast.Name) and n.id in ("True", "False", "None"))
               for n in ast.walk(tree)):
        try:
            if bool(eval(compile(tree, "<pre>", "eval"), {"__builtins__": {}}, {})):
                return "True"
        except Exception:
            return pre
    return pre


_COND = re.compile(r"\b(if|when|whenever|unless|otherwise|ties?|tied|until|while|in case|only when)\b", re.I)
_NUM = {"int", "float", "bool"}


def evaluate(rec, p, text=None):
    """Run + validate one probe. Returns (outcome, evidence, details)."""
    conc = p.get("concreteness")
    if conc not in ("stated", "instantiated") or not p.get("call") or (p.get("expect") is None and not p.get("expect_raises")):
        return "unverifiable", "no executable probe (claim too abstract or synthesiser gap)", {}
    pre = _norm_pre(p.get("precondition"))
    if conc == "instantiated" and pre == "True" and text and _COND.search(text):
        # round 3 (R3-S1): a conditional claim needs a non-trivial precondition
        return "unverifiable", "vacuous precondition for a conditional claim", {"concreteness": conc}
    er = p.get("expect_raises")
    run = run_probe(rec["exec_source"], p["call"], p["expect"], er, p.get("precondition") or "True")
    st = run.get("status")
    det = {"run": run, "concreteness": conc}
    if st in ("timeout", "crash", "probe_error"):
        return "unverifiable", f"probe {st}: {run.get('error', '')}", det
    if st == "pre_false":
        return "unverifiable", "probe input violates the claim's precondition", det
    if not er and st == "raised":
        return "unverifiable", f"probe call raised {run.get('raised')} (probe error, not a falsification)", det
    if not _passes(run, er):
        ev = (f"returned {run.get('result')} instead of raising {er}" if er and st == "returned" else
              f"raised {run.get('raised')} (expected {er})" if er else
              f"result={run.get('result')} expected={run.get('expected')}")
        if conc == "stated" and st == "returned" and run.get("rtype") != run.get("etype") and \
                not ({run.get("rtype"), run.get("etype")} <= _NUM):
            # round 3 (R3-S8): result and expectation of different kinds -> the probe, not the claim, is wrong
            return "unverifiable", f"type mismatch between result ({run.get('rtype')}) and expectation ({run.get('etype')})", det
        if conc == "instantiated":
            # RUNLOG round-2 cycle R2: an audit of the first 20 probe FALSE verdicts found 16 synthesiser errors
            # (wrong expectation for a correct general claim), so a failing INSTANTIATED probe is not evidence.
            return "unverifiable", "instance disagreement (synthesiser expectation unverified): " + ev, det
        return "false", ev, det
    # passes on the original: it must fail on at least one mutant to count as evidence
    muts = mutants(rec["exec_source"], rec["name"])
    killed = 0
    for msrc in muts:
        mr = run_probe(msrc, p["call"], p["expect"], er, p.get("precondition") or "True")
        if mr.get("status") in ("returned", "raised") and not _passes(mr, er):
            killed += 1
    det.update({"mutants": len(muts), "killed": killed})
    if killed == 0:
        return "unverifiable", f"non-discriminating probe (0/{len(muts)} mutants killed)", det
    if conc == "instantiated":
        return "consistent", f"instance evidence ({killed}/{len(muts)} mutants killed): {run.get('result')}", det
    return "true", f"stated probe passed ({killed}/{len(muts)} mutants killed): {run.get('result')}", det


def signature(rec):
    try:
        mod = ast.parse(rec["source"])
        fn = next(n for n in ast.walk(mod) if isinstance(n, ast.FunctionDef))
        fn.body = [ast.Expr(ast.Constant(Ellipsis))]
        fn.decorator_list = []
        return ast.unparse(fn)
    except Exception:
        return rec["source"].splitlines()[0] + "\n    ..."


def synthesise(rec, claims):
    """One LLM call per explanation: blind probes for all its behavioural / purpose claims."""
    lines = "\n".join(f"- id={c['cid']} {c['text']}" for c in claims)
    prompt = f"{INSTRUCTIONS}\nSIGNATURE (body hidden):\n```python\n{signature(rec)}\n```\n\nCLAIMS:\n{lines}\n\nJSON:"
    raw = llm(prompt, backend=PROBER[0], model=PROBER[1], system=SYSTEM, num_predict=1800, json_mode=True)
    js = parse_json(raw)
    out = {}
    if isinstance(js, dict) and isinstance(js.get("probes"), list):
        for p in js["probes"]:
            if not isinstance(p, dict):
                continue
            exp = p.get("expect")
            if exp is not None and not isinstance(exp, str):
                exp = repr(exp) if not isinstance(exp, (list, dict)) else json.dumps(exp)
            out[str(p.get("id", ""))] = {
                "concreteness": str(p.get("concreteness", "none")).lower(),
                "call": p.get("call") if isinstance(p.get("call"), str) else None,
                "expect": _repair_expect(exp),
                "expect_raises": p.get("expect_raises") if isinstance(p.get("expect_raises"), str) else None,
                "precondition": p.get("precondition") if isinstance(p.get("precondition"), str) else "True"}
    return out


def _repair_expect(e):
    """JSON mode often yields a bare string value (`racecar`); quote text that is not a Python literal."""
    if not isinstance(e, str):
        return e
    try:
        ast.literal_eval(e)
        return e
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        pass
    try:
        tree = ast.parse(e, mode="eval")
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        if names <= {"True", "False", "None", "float", "int", "str", "list", "tuple", "set", "dict", "frozenset"}:
            return e
    except SyntaxError:
        pass
    return repr(e)


def probe_targets(claims):
    """Claims routed to execution: behavioural, and extractor-intent claims re-typed FUNCTIONAL (purpose)."""
    return [c for c in claims if c.get("type2", c["type"]) in ("behavioural", "purpose")]


def main(claims_file="claims.jsonl", out_name="probe_runs.jsonl"):
    from discharge import type2_of, load_retype
    corpus = {r["fid"]: r for r in load_corpus() if r["corpus"] == "B"}
    retype = load_retype()
    claims = [json.loads(l) for l in open(os.path.join(RESULTS, claims_file))]
    for c in claims:
        c["type2"] = type2_of(c, retype)
    beh = [c for c in probe_targets(claims) if c["corpus"] == "B"]
    by_expl = {}
    for c in beh:
        by_expl.setdefault((c["explainer"], c["fid"]), []).append(c)
    t0 = time.time()
    with open(os.path.join(RESULTS, out_name), "w") as fo:
        for n, key in enumerate(sorted(by_expl), 1):
            rec = corpus[key[1]]
            probes = synthesise(rec, by_expl[key])
            for c in by_expl[key]:
                p = probes.get(c["cid"])
                oc, ev, det = evaluate(rec, p, c["text"]) if p else ("unverifiable", "no probe returned", {})
                fo.write(json.dumps({"cid": c["cid"], "fid": c["fid"], "explainer": c["explainer"], "probe": p,
                                     "type2": c["type2"], "outcome": oc, "evidence": ev, **det},
                                    sort_keys=True) + "\n")
            fo.flush()
            if n % 10 == 0:
                print(f"[probe] {n}/{len(by_expl)} explanations, {time.time()-t0:.0f}s, {stats()}", flush=True)
    print(f"probes: {len(beh)} claims over {len(by_expl)} explanations -> {out_name}")


if __name__ == "__main__":
    main()
