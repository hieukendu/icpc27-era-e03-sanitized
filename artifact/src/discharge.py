"""Attest: the evidence-discharge engine (round-4 revision).

Claim types after re-typing (SDBPR): structural, dataflow, behavioural, purpose (extractor-'intent' claims that
a different-family classifier labels FUNCTIONAL), rationale (the rest of 'intent').
Evidence set E = {tree-sitter structural facts, flow-sensitive def-use graph (defuse.py), sandboxed execution of
blind, mutant-validated probes (Corpus B only)}.

Outcomes
  true            the evidence entails the claim as grounded by the extractor's slots (see per-rule semantics)
  false           the evidence contradicts it
  consistent      the evidence is compatible but cannot entail it (qualifier unchecked, implicit flow only,
                  "returns a value" without content, instance evidence for a general sentence, indirect call)
  unverifiable    an evidence kind in E applies but the tooling / policy could not decide (ungrounded or compound
                  endpoint, repository code is never executed, invalid or non-discriminating probe, ...)
  undischargeable the claim is typed RATIONALE: outside E by construction of the typing (not "no tool could")
Every verdict records the `rule` that produced it (used for the v1 -> v2 flip analysis).
"""
import ast
import builtins as _bi
import json
import keyword as _kw
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

from config import RESULTS
from defuse import reach

STRUCT_SUBS = ("calls", "parameter", "default", "returns", "raises", "imports", "decorator")
KEYWORDS = {"yield", "return", "raise", "await", "assert", "del", "import", "throw", "new", "for", "while", "if",
            "null", "None", "true", "false", "this", "super", "with", "lambda", "in", "not", "is", "and", "or"}


def _norm(s):
    if s is None:
        return ""
    s = str(s).strip().strip("`'\"")
    s = re.sub(r"\(.*\)$", "", s)
    return s.strip()


def _strip_self(s):
    for p in ("self.", "this.", "cls."):
        if s.startswith(p):
            return s[len(p):]
    return s


def _norm_lit(s):
    return str(s).strip().strip("`").replace("'", '"').replace(" ", "")


# --------------------------------------------------------------------------------------------- structural
def _backticked_entities(text, g, fname):
    """Identifiers in `backticks` that name a variable / parameter / callee of the function."""
    out = []
    for seg in re.findall(r"`([^`]+)`", text or ""):
        seg = seg.strip()
        m = re.fullmatch(r"([A-Za-z_][\w.]*)(\(.*\))?", seg)
        if not m:
            continue
        name = m.group(1)
        if name == fname or name in KEYWORDS:
            continue
        ent = _entity(name, g, "source")
        if ent and ent not in out:
            out.append(ent)
    return out


_TYPE_NAMES = {"list", "dict", "str", "int", "float", "bool", "tuple", "set", "None", "True", "False", "bytes",
               "object", "iterator", "generator", "string", "String", "Integer", "Boolean", "List", "Map", "Set"}


def _returned_object(text):
    """The backticked object of the verb 'return(s)' (`returns the cached `x``) -- the only name the rule checks."""
    m = re.search(r"\breturn(?:s|ed|ing)?\b(?:\s+[\w'-]+){0,5}?\s*`([A-Za-z_][\w.]*)`", text or "", re.I)
    return m.group(1) if m else None


def _subject(text):
    """The backticked grammatical subject at the start of a sentence (`f` returns ...), if any."""
    m = re.match(r"\s*(?:the\s+)?(?:(?:inner|nested|helper|local)\s+)?(?:(?:function|method|helper)\s+)?`([A-Za-z_][\w.]*)`",
                 text or "", re.I)
    return m.group(1).split(".")[-1] if m else None


def discharge_structural(claim, f, rec=None):
    """Returns (outcome, evidence, scope, rule)."""
    sub, slots = claim["subtype"], claim["slots"] or {}
    if f is None or f.get("parse_error"):
        return "unverifiable", "no parse", "syntactic", "noparse"
    if sub == "calls":
        callee = _strip_self(_norm(slots.get("callee")))
        if not callee:
            return "unverifiable", "ungrounded callee", "syntactic", "calls-ungrounded"
        last = callee.split(".")[-1]
        if not re.fullmatch(r"(?:new\s+)?[A-Za-z_][\w.]*", callee):
            return "unverifiable", f"`{callee}` is not a callable name", "syntactic", "calls-ungrounded"
        if last in KEYWORDS:
            return "unverifiable", "keyword, not a callee", "syntactic", "calls-keyword"
        full = [_strip_self(c) for c in f["calls_full"]]
        if any(c == callee or c.endswith("." + callee) or c == "new " + callee for c in full):
            return "true", f"call site {callee}", "syntactic", "calls-exact"
        if last in f["calls"]:
            if "." not in callee:
                return "true", f"call site named {last}", "syntactic", "calls-name"
            return "consistent", f"a call named {last} exists; qualifier {callee} not matched ({f['calls_full'][:6]})", \
                "syntactic", "calls-qualifier"
        if last in f.get("calls_indirect", []) or callee in f.get("calls_indirect", []):
            return "consistent", f"indirect reference to {last} (getattr / higher-order / alias)", "syntactic", "calls-indirect"
        # calls fragment (round 4): FALSE only if no implicit or dynamic call could be the claimed one
        if f.get("has_with"):
            return "unverifiable", "a with-statement makes implicit calls", "syntactic", "calls-gated"
        if f.get("dyn_calls"):
            return "unverifiable", f"calls through local names {f['dyn_calls']}", "syntactic", "calls-gated"
        if last in f.get("identifiers", []) or last in f.get("decorators", []):
            return "unverifiable", f"`{last}` is referenced but not called", "syntactic", "calls-gated"
        if f.get("dyn_callsite") or any(c in ("getattr", "super", "eval", "exec", "invoke", "apply", "methodcaller",
                                                  "attrgetter", "globals", "locals") for c in f["calls"]):
            return "unverifiable", "dynamic dispatch present", "syntactic", "calls-gated"
        return "false", f"no call site named {last}; calls={f['calls'][:12]}", "syntactic", "calls-absent"
    if sub == "parameter":
        name = _norm(slots.get("name")).lstrip("*")
        if not name:
            return "unverifiable", "ungrounded parameter", "syntactic", "param-ungrounded"
        params = [p.lstrip("*") for p in f["params"]]
        if name in params:
            return "true", f"params={params}", "syntactic", "param"
        if f.get("has_kwargs") or f.get("has_varargs"):
            return "unverifiable", "absent from the signature, but the function accepts *args/**kwargs", "syntactic", "param-splat"
        if name in f.get("locals", []) or name in f.get("identifiers", []):
            return "unverifiable", f"`{name}` names an entity in the body (likely a mis-slotted claim)", "syntactic", "param-local"
        return "false", f"params={params}", "syntactic", "param"
    if sub == "default":
        name = _norm(slots.get("name")).lstrip("*")
        val = slots.get("value")
        if not name:
            return "unverifiable", "ungrounded parameter", "syntactic", "default-ungrounded"
        params = [p.lstrip("*") for p in f["params"]]
        if name in params and name in f["defaults"] and (val is None or str(val).strip() == ""):
            return "true", f"has default {f['defaults'][name]}", "syntactic", "default"
        if name in f["defaults"] and val is not None and _norm_lit(val) == _norm_lit(f["defaults"][name]):
            return "true", f"default={f['defaults'][name]}", "syntactic", "default"

        # v5: every FALSE branch below passes the same guards (Sec. III defaults fragment)
        def guarded(reason):
            if f["lang"] == "java":
                return "unverifiable", "Java emulates defaults with overloads; not modelled", "syntactic", "default-gated"
            if f.get("has_kwargs") or f.get("has_varargs"):
                return "unverifiable", "the function accepts *args/**kwargs", "syntactic", "default-gated"
            if val is not None and re.search(r"\||^\s*(?:str|int|float|bool|list|dict|tuple|bytes|Optional\[|t\.|typing\.)", str(val)):
                return "unverifiable", f"slot value `{val}` is a type annotation, not a default (mis-slot)", "syntactic", "default-gated"
            if not re.search(r"default|optional|if (?:not |none )?(?:given|provided|passed|omitted)|=", claim.get("text", ""), re.I):
                return "unverifiable", "the sentence states no default (likely a mis-slotted claim)", "syntactic", "default-gated"
            if name in f.get("locals", []) or name in f.get("identifiers", []):
                return "unverifiable", f"`{name}` is (re)assigned or used in the body (e.g. a None-sentinel default)", "syntactic", "default-gated"
            if f.get("decorators"):
                return "unverifiable", "decorators may supply defaults (e.g. click options)", "syntactic", "default-gated"
            if name in f["defaults"]:
                try:
                    ast.literal_eval(f["defaults"][name].strip())
                except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                    # v6.1: FALSE needs a literal signature default (not `DEFAULT_TIMEOUT`, `30*60`, `[]+x`)
                    return "unverifiable", f"non-literal default `{f['defaults'][name]}` is not compared", "syntactic", "default-gated"
            return "false", reason, "syntactic", "default"
        if name not in params:
            return guarded("no such parameter")
        if name not in f["defaults"]:
            return guarded("parameter has no default")
        return guarded(f"default={f['defaults'][name]}")
    if sub == "returns":
        rv = slots.get("returns_value")
        if rv is None:
            return "unverifiable", "returns_value slot missing", "syntactic", "returns-ungrounded"
        own_v, own_y = f.get("own_returns_value"), f.get("own_has_yield")
        actual = bool((f["returns_value"] if own_v is None else own_v) or (f["has_yield"] if own_y is None else own_y))
        names_value = bool(re.search(r"\breturn(?:s|ed|ing)?\b(?:\s+[\w`'-]+){0,3}?\s+`?(?:none|null|false|true|nothing useful)`?\b"
                                     r"|\breturn(?:s|ed|ing)?\s+(?:an?\s+empty|0\b)|\bor\s+`?none`?", claim.get("text", ""), re.I))
        if not bool(rv):
            if not actual:
                return "true", "no value-returning path", "syntactic", "returns-none"
            if names_value:
                return "unverifiable", "the sentence names a returned value (e.g. None), not 'returns nothing'", "syntactic", "returns-gated"
            if f.get("own_has_yield") or f.get("is_async"):
                return "unverifiable", "generator/coroutine: 'returns nothing' is ambiguous", "syntactic", "returns-gated"
            return "false", f"value-returning paths: {actual}", "syntactic", "returns-none"
        if not actual:
            if names_value:     # v6: the same exemption on this branch (Sec. III)
                return "unverifiable", "the sentence names a returned value (e.g. None)", "syntactic", "returns-gated"
            return "false", "the function never returns a value", "syntactic", "returns-none"
        g = f.get("du")
        subj = _subject(claim["text"])
        if subj and subj != f.get("name") and g and (subj in g.get("nested", []) or subj in g["calls"]):
            return "unverifiable", f"returns claim is about `{subj}`, not the function itself", "syntactic", "returns-other"
        x = _returned_object(claim["text"])
        ent = _entity(x, g, "source") if (g and x and x != f.get("name") and x not in _TYPE_NAMES) else None
        if not ent:
            return "consistent", "returns some value; what is returned is not checked", "syntactic", "returns-unchecked"
        oc, ev = _flow_verdict(g, [ent], [("return",)])
        if oc == "false":
            why = _false_gate(f, [ent], [("return",)])
            if why:
                return "unverifiable", f"returned `{x}`: no precise path, but {why}", "may-path", "returns-gated"
        return oc, "returned value vs " + ev, "may-path", "returns-content"
    if sub == "raises":
        exc = _norm(slots.get("exception")).split(".")[-1]
        if not exc:
            return "unverifiable", "ungrounded exception", "syntactic", "raises-ungrounded"
        if exc in f["raises"]:
            return "true", f"explicit raise/throw of {exc}", "syntactic", "raises-explicit"
        return "unverifiable", f"no explicit raise of {exc}; implicit exceptions are not modelled", "syntactic", "raises-implicit"
    if sub == "imports":
        mod = _norm(slots.get("module"))
        if not mod:
            return "unverifiable", "ungrounded module", "syntactic", "imports-ungrounded"
        imps = f["imports"]
        if mod in imps or any(i.endswith("." + mod) for i in imps):
            return "true", f"import of {mod}", "syntactic", "imports-exact"
        if set(mod.split(".")) & set(imps):
            return "consistent", f"partial module-name overlap with {imps[:8]}", "syntactic", "imports-partial"
        return "unverifiable", "not among the first 25 module import lines (import list truncated)", "syntactic", "imports-absent"
    if sub == "decorator":
        name = _norm(slots.get("name")).lstrip("@")
        if not name:
            return "unverifiable", "ungrounded decorator", "syntactic", "decorator-ungrounded"
        if name.split(".")[-1] in [d.split(".")[-1] for d in f["decorators"]]:
            return "true", f"decorators={f['decorators']}", "syntactic", "decorator"
        # v6: decorator FALSE passes the same splat / body-use guards as parameters (Sec. III)
        if f.get("has_kwargs") or f.get("has_varargs"):
            return "unverifiable", "the function accepts *args/**kwargs", "syntactic", "decorator-gated"
        if name.split(".")[-1] in f.get("identifiers", []):
            return "unverifiable", f"`{name}` is used in the body", "syntactic", "decorator-gated"
        return "false", f"decorators={f['decorators']}", "syntactic", "decorator"
    return "unverifiable", f"unknown structural subtype {sub}", "syntactic", "struct-unknown"


# --------------------------------------------------------------------------------------------- data flow
_RETURN_WORDS = {"return", "return value", "the return value", "returned", "returns", "caller", "the caller"}
# ("result"/"output" are NOT mapped to the return node: a local variable may carry that name)


def _entity(name, g, role):
    """Map a simple name to an entity tuple: ('var', name) | ('call', callee) | None."""
    if not name:
        return None
    defs, calls = g["defs"], g["calls"]
    if role == "sink" and name.split(".")[-1] in calls and "." not in name:
        return ("call", name)          # "flows into f" names the call, even if f is also a local function object
    for cand in (name, "self." + name, "this." + name, _strip_self(name)):
        if cand in defs and (role == "source" or any(not d.startswith("free:") for d in defs[cand])):
            if role == "sink" and not any(d.startswith("d:") for d in defs[cand]):
                continue
            return ("var", cand)
    last = name.split(".")[-1]
    if last in calls:
        return ("call", last)
    return None


def _nodes(ent, g, role):
    if ent[0] == "return":
        return g["rets"]
    if ent[0] == "call":
        return g["calls"].get(ent[1], [])
    ds = g["defs"].get(ent[1], [])
    if role == "source" and f"p:{ent[1]}" in ds:
        return [f"p:{ent[1]}"]          # a parameter as source means its incoming value, not later reassignments
    return ds if role == "source" else [d for d in ds if d.startswith("d:")]


def _parse_endpoint(text, g, role):
    """Endpoint text -> (list of entities, reason). Lists are UNIVERSAL: every entity must satisfy the flow."""
    raw = "" if text is None else str(text).strip().strip("`'\"").strip()
    if not raw or raw.lower() in ("none", "null", "unknown"):
        return None, "ungrounded endpoint"
    low = raw.lower()
    if low in _RETURN_WORDS or low.startswith("return ") or low.startswith("yield "):
        return ([("return",)], "") if role == "sink" else (None, "return used as a source")
    if re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", raw):
        e = _entity(raw, g, role)          # plain identifiers bypass the Python parser (Java names like `in`, `is`)
        return ([e], "") if e else (None, f"unresolved endpoint {raw!r}")
    expr = re.sub(r"^(?:with|if|while|for|elif)\s+", "", raw).rstrip(":")
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"\(\s*\(?[A-Z][\w.<>?, \[\]]*\)\s*\)?", "", expr) if "(" in expr and ")" in expr else expr
    tree = None
    for mode in ("eval", "exec"):
        try:
            tree = ast.parse(expr, mode=mode)
            break
        except SyntaxError:
            continue
    if tree is None:
        return None, "endpoint is not code"
    node = tree.body if mode == "eval" else (tree.body[0] if tree.body else None)
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        if role == "sink":
            tg = node.targets if isinstance(node, ast.Assign) else [node.target]
            ents = []
            for t in tg:
                for el in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t]):
                    e = _simple(el, g, role)
                    if e is None:
                        return None, f"unresolved assignment target in {raw!r}"
                    ents.append(e)
            return ents, ""
        node = node.value
    if isinstance(node, ast.Expr):
        node = node.value
    simple = _simple(node, g, role)
    if simple is not None:
        return [simple], ""
    if isinstance(node, (ast.BoolOp, ast.Tuple, ast.List)):
        parts = node.values if isinstance(node, ast.BoolOp) else node.elts
        ents = [_simple(p, g, role) for p in parts]
        if all(e is not None for e in ents):
            return ents, ""
    return None, f"compound or unresolved endpoint {raw!r}"


def _simple(node, g, role):
    if isinstance(node, (ast.Name, ast.Attribute)):
        try:
            return _entity(ast.unparse(node), g, role)
        except Exception:
            return None
    if isinstance(node, ast.Subscript):
        return _simple(node.value, g, role)
    if isinstance(node, ast.Call):
        f = node.func
        nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        if nm and nm in g["calls"]:
            return ("call", nm)
    return None


def _flow_verdict(g, srcs, dsts):
    """All (source, sink) pairs must be connected. Data path -> true; only via control dependence -> consistent;
    no path at all -> false."""
    worst = "true"
    ev = []
    for s in srcs:
        for d in dsts:
            sn, dn = _nodes(s, g, "source"), _nodes(d, g, "sink")
            if not sn or not dn:
                return "unverifiable", f"no graph nodes for {s}->{d}"
            if reach(g, sn, dn, False):
                ev.append(f"{s[-1]}->{d[-1]}: data")
            elif reach(g, sn, dn, True):
                ev.append(f"{s[-1]}->{d[-1]}: control only")
                worst = "consistent" if worst == "true" else worst
            else:
                ev.append(f"{s[-1]}->{d[-1]}: none")
                worst = "false"
    return worst, "; ".join(ev)


def _false_gate(f, srcs, dsts):
    """A data-flow FALSE is emitted only inside the supported fragment AND when the conservative graph (every
    non-pure call may update its arguments) has no path either. Returns None if FALSE may stand, else a reason."""
    g = f.get("du") or {}
    if g.get("outside"):
        return f"outside the supported fragment ({', '.join(g['outside'])})"
    if g.get("unsupported"):
        return f"unmodelled constructs ({', '.join(g['unsupported'])})"
    gc = f.get("du_cons")
    if not gc:
        return "no conservative graph"
    g0 = f.get("du")
    for s_ in srcs:
        for d in dsts:
            if reach(g0, _nodes(s_, g0, "source"), _nodes(d, g0, "sink"), True):
                continue                      # this pair is connected anyway; the FALSE rests on another pair
            sn, dn = _nodes(s_, gc, "source"), _nodes(d, gc, "sink")
            if sn and dn and not reach(gc, sn, dn, True):
                return None                   # a pair without any path even in the conservative graph
    return "a path may exist through call side effects (conservative graph)"


def discharge_dataflow(claim, f, rec=None):
    if f is None or not f.get("du"):
        return "unverifiable", "no def-use graph", "may-path", "flow-nograph"
    g = f["du"]
    slots = claim["slots"] or {}
    srcs, r1 = _parse_endpoint(slots.get("source"), g, "source")
    dsts, r2 = _parse_endpoint(slots.get("sink"), g, "sink")
    if srcs is None or dsts is None:
        return "unverifiable", (r1 or r2), "may-path", "flow-unresolved"
    if any(s == d for s in srcs for d in dsts):
        return "unverifiable", "source and sink are the same entity (self-reference)", "may-path", "flow-self"
    oc, ev = _flow_verdict(g, srcs, dsts)
    if oc == "false" and all(d[0] == "var" for d in dsts) and len(srcs) == 1:
        # the source feeds a method call ON the sink object (e.g. template.replace("i", str(n))): the sentence
        # may describe the call's result rather than a store into the sink -> compatible, not entailed
        recv_calls = [c for c, r in g.get("recv", {}).items() if r in {d[1] for d in dsts}]
        if recv_calls and reach(g, _nodes(srcs[0], g, "source"), recv_calls, True):
            return "consistent", ev + "; source feeds a method call on the sink object", "may-path", "flow-receiver"
    if oc == "false":
        why = _false_gate(f, srcs, dsts)
        if why:
            return "unverifiable", f"no path in the precise graph, but {why}", "may-path", "flow-gated"
    rule = {"true": "flow-data", "consistent": "flow-control", "false": "flow-none"}.get(oc, "flow-unresolved")
    return oc, ev, "may-path", rule


def _resolve(name, graph, params):
    """Compatibility shim for planted.build_items (round-1 graph); not used by the round-2 engine."""
    return None


# --------------------------------------------------------------------------------------------- purpose / membership
_MEMBER = re.compile(r"\b(?:method|member|part|defined|function)\b[^.]{0,40}?\b(?:of|in|within|on)\s+(?:the\s+|an?\s+)?"
                     r"(?:Java\s+|Python\s+)?(?:class\s+`?([A-Z_]\w*)`?|`?([A-Z_]\w*)`?\s+class)")   # class names: capitalised / _-prefixed


_ANCHOR = re.compile(r"^\s*(?:the\s+)?`?(?P<subj>[A-Za-z_]\w*)`?(?:\s+(?:function|method|constructor))?\s+"
                     r"(?:(?:is|is\s+a|is\s+an)\s+(?:\w+\s+){0,2}?)?", re.I)


_STRICT = re.compile(r"\s*(?:(?:function|method|constructor)\s+)?(?:is\s+)?(?:(?:a|an|the)\s+)?"
                     r"(?P<qual>(?:\w+\s+){0,2}?)(?:(?:method|member|part|function)\s+)?(?:of|in|within|inside|from|on)\s+"
                     r"(?:the\s+)?(?:Java\s+|Python\s+)?(?:class\s+`?(?P<c1>[A-Z_]\w*)`?|`?(?P<c2>[A-Z_]\w*)`?\s+class)", re.I)
_QUAL_OK = {"", "instance", "static", "special", "public", "private", "helper"}
_QUAL_ADJ = _QUAL_OK | {"property", "abstract", "protected", "inner", "nested", "utility", "internal", "overloaded",
                        "class", "overridden", "magic", "dunder", "constructor", "getter", "setter", "builder"}


def membership_check(claim, rec):
    """Structural evidence for purpose claims that place THE FUNCTION ITSELF in a class (round 4): the sentence
    subject must be the function's own name and the membership phrase must follow it directly ("`f` is a method
    of the `C` class", "The `f` method in the `C` class ..."). Other sentences are not membership claims."""
    if rec is None:
        return None
    a = re.match(r"\s*(?:the\s+)?`?(?P<subj>[A-Za-z_]\w*)`?", claim["text"], re.I)
    if not a or a.group("subj") != rec.get("name"):
        return None
    m = _STRICT.match(claim["text"], a.end())
    if not m:
        return None
    qual = m.group("qual").strip().lower()
    if any(w not in _QUAL_ADJ for w in qual.split()):
        return None                           # e.g. "creates instances of the C class": not a membership claim
    cls = m.group("c1") or m.group("c2")
    actual = rec.get("cls")
    if actual is None:
        return "false", f"function is not a method (claimed class {cls})", "syntactic", "member"
    if cls != actual:
        return "false", f"enclosing class {actual}", "syntactic", "member"
    qual_ok = m.group("qual").strip().lower() in _QUAL_OK
    tail = claim["text"][m.end():]
    lt = _LOC_TAIL.match(tail)
    lib_ok = True
    if lt and re.search(r"(library|module|package)", tail, re.I):
        words = [w for w in (x.lower().strip("`'.,") for x in re.findall(r"[`\w.\-']+", tail))
                 if w and w not in ("of", "in", "from", "the", "library", "module", "package")]
        lib_ok = bool(words) and all(w.replace("_", "-") in (rec.get("repo") or "").lower() for w in words)
    if qual_ok and lt and lib_ok:
        return "true", f"enclosing class {actual}", "syntactic", "member"
    return "consistent", f"enclosing class {actual} matches; the rest of the sentence is not checked", \
        "syntactic", "member-compound"


_LOC_TAIL = re.compile(r"^[\s,]*(?:(?:of|in|from)\s+(?:the\s+)?(?:[`\w.\-]+\s+){0,2}?(?:library|module|package))?"
                       r"[\s,]*\.?\s*$", re.I)
_SUBJ_HEAD = re.compile(r"^\s*(?:the\s+)?`?[\w.]+`?(?:\s+(?:function|method|constructor))?\s+(?:is|is\s+a|is\s+an|"
                        r"is\s+defined|is\s+part|is\s+a\s+method|is\s+a\s+member|belongs)?\b", re.I)


def _pure_membership(text, m, rec=None):
    """True iff the sentence asserts nothing beyond 'X is a method of class C (in library/module L)'."""
    head, tail = text[:m.start()], text[m.end():]
    head_ok = bool(re.fullmatch(r"\s*(?:the\s+)?`?[\w.]+`?(?:\s+(?:function|method|constructor))?\s+"
                                r"(?:is\s+)?(?:(?:a|an|the)\s+)?(?:(?:special|static|private|public|instance|helper)\s+)?", head, re.I))
    allowed = {"function", "method", "member", "part", "defined", "is", "a", "an", "the", "of", "in", "within",
               "on", "inside", "class", "java", "python", "instance", "static"}
    span_words = [w.lower() for w in re.findall(r"[A-Za-z_]\w*", re.sub(r"`[^`]*`", " ", m.group(0)))]
    cls = (m.group(1) or m.group(2) or "").lower()
    span_ok = all(w in allowed or w == cls for w in span_words)
    lt = _LOC_TAIL.match(tail)
    lib_ok = True
    if lt and re.search(r"(library|module|package)", tail, re.I) and rec is not None:
        # a named library/module must be the repository the function comes from
        words = [w for w in (x.lower().strip("`'.,") for x in re.findall(r"[`\w.\-']+", tail))
                 if w and w not in ("of", "in", "from", "the", "library", "module", "package")]
        lib_ok = bool(words) and all(w.replace("_", "-") in (rec.get("repo") or "").lower() for w in words)
    return head_ok and span_ok and bool(lt) and lib_ok


# --------------------------------------------------------------------------------------------- entity check (+E ablation)
_JAVA_LANG = {"String", "Math", "System", "Integer", "Long", "Double", "Float", "Short", "Byte", "Boolean",
              "Character", "Object", "StringBuilder", "StringBuffer", "Arrays", "List", "Map", "Set", "Collections",
              "Iterator", "Iterable", "Exception", "RuntimeException", "IllegalArgumentException", "Class", "Thread",
              "Number", "Comparable", "CharSequence", "Objects", "Optional", "null", "true", "false", "int", "long",
              "byte", "char", "short", "float", "double", "boolean", "void", "new", "this", "super", "array",
              "length", "equals", "hashCode", "toString", "Override", "final", "static", "public", "private"}
_PY_OK = set(dir(_bi)) | set(_kw.kwlist) | {"self", "cls", "args", "kwargs", "dict", "list", "str", "int"}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def entity_universe(rec):
    src = (rec.get("exec_source") or "") + "\n" + rec["source"] + "\n" + (rec.get("context_imports") or "")
    toks = set(_IDENT.findall(src))
    toks |= {rec.get("name") or "", rec.get("cls") or "", rec.get("repo") or ""}
    toks |= set(_IDENT.findall((rec.get("path") or "").replace("/", " ").replace(".", " ")))
    return toks


def dangling_entities(text, universe, lang):
    bad = []
    for seg in re.findall(r"`([^`]+)`", text):
        seg = re.sub(r"(['\"]).*?\1", " ", seg)
        for tok in _IDENT.findall(seg):
            if tok in universe or tok in _PY_OK or (lang == "java" and tok in _JAVA_LANG) or len(tok) < 2:
                continue
            bad.append(tok)
    return sorted(set(bad))


def apply_entity_check(claim, rec, outcome, evidence):
    """Attest+E (ablation only): a non-rationale claim naming a non-existent code entity is discharged false."""
    if claim.get("type2", claim["type"]) in ("intent", "rationale") or outcome == "false" or rec is None:
        return outcome, evidence
    bad = dangling_entities(claim["text"], entity_universe(rec), rec["lang"])
    if bad:
        return "false", f"dangling entity {bad}"
    return outcome, evidence


# --------------------------------------------------------------------------------------------- typing
def load_retype():
    p = os.path.join(RESULTS, "retype.jsonl")
    if not os.path.exists(p):
        return {}
    return {json.loads(l)["cid"]: json.loads(l) for l in open(p)}


def type2_of(c, retype):
    if c["type"] != "intent":
        return c["type"]
    r = retype.get(c["cid"], {})
    lab = r.get("retype_primary") or r.get("retype_second")
    return "purpose" if lab == "FUNCTIONAL" else "rationale"


def discharge_claim(c, f, rec, probes):
    t = c["type2"]
    if t == "structural":
        return discharge_structural(c, f, rec)
    if t == "dataflow":
        return discharge_dataflow(c, f, rec)
    if t in ("behavioural", "purpose"):
        if t == "purpose":
            m = membership_check(c, rec)
            if m is not None:
                return m
        if c["corpus"] != "B":
            return "unverifiable", "policy: repository code is not executed", "instance", "policy"
        p = probes.get(c["cid"])
        if p is None:
            return "unverifiable", "no probe record", "instance", "probe-missing"
        rule = "probe-" + (p.get("concreteness") or "none") + "-" + p["outcome"]
        return p["outcome"], p["evidence"], "instance", rule
    return "undischargeable", "rationale/context: outside the evidence set E", None, "rationale"


def main(claims_file="claims.jsonl", probe_file="probe_runs.jsonl", out_name="discharge.jsonl"):
    from explain import load_corpus
    corpus = {r["fid"]: r for r in load_corpus()}
    facts = {json.loads(l)["fid"]: json.loads(l) for l in open(os.path.join(RESULTS, "facts.jsonl"))}
    probes = {}
    pp = os.path.join(RESULTS, probe_file)
    if os.path.exists(pp):
        for l in open(pp):
            r = json.loads(l)
            probes[r["cid"]] = r
    retype = load_retype()
    counts = {}
    n = 0
    with open(os.path.join(RESULTS, out_name), "w") as fo:
        for l in open(os.path.join(RESULTS, claims_file)):
            c = json.loads(l)
            c["type2"] = type2_of(c, retype)
            rec = corpus.get(c["fid"])
            oc, ev, scope, rule = discharge_claim(c, facts.get(c["fid"]), rec, probes)
            oce, eve = apply_entity_check(c, rec, oc, ev)
            c.update({"outcome": oc, "evidence": ev, "scope": scope, "rule": rule, "outcome_e": oce, "evidence_e": eve})
            counts[(c["type2"], oc)] = counts.get((c["type2"], oc), 0) + 1
            fo.write(json.dumps(c, sort_keys=True) + "\n")
            n += 1
    print(f"discharge: {n} claims -> {out_name}")
    for k in sorted(counts):
        print(f"  {k[0]:12s} {k[1]:16s} {counts[k]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
