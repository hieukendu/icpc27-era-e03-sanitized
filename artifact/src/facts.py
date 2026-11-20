"""Evidence sources for Attest.

* Structural facts (both languages) from tree-sitter: parameter names/defaults, called names, return
  statements, raised/thrown exception types, imports, decorators/annotations, yield.
* Round-1 data-flow facts (Python, kept for the v1 comparison only) from a flow-insensitive walk over `ast`: a directed
  graph whose nodes are variable names, `call:<callee>` nodes and `return`; an edge u->v means a value
  read from u contributes to v in one step. Claims "X feeds Y" are discharged by reachability.
Java round-1 graph: same conventions over tree-sitter-java. The engine itself uses `du`, the flow-sensitive
reaching-definitions graph from defuse.py (both languages).
"""
import ast
import json
import warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)
import os
import sys

from tree_sitter import Language, Parser
import tree_sitter_java
import tree_sitter_python

from config import DATA, RESULTS

PY = Language(tree_sitter_python.language())
JAVA = Language(tree_sitter_java.language())
_PARSERS = {"python": Parser(PY), "java": Parser(JAVA)}


def _txt(node, src):
    return src[node.start_byte:node.end_byte].decode("utf8", "replace")


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


# --------------------------------------------------------------------------- Python structural facts
def py_struct_facts(func_src, context_imports=""):
    src = func_src.encode()
    tree = _PARSERS["python"].parse(src)
    root = tree.root_node
    fdef = next((n for n in _walk(root) if n.type == "function_definition"), None)
    facts = {"params": [], "defaults": {}, "calls": [], "calls_full": [], "returns_count": 0,
             "returns_value": False, "raises": [], "imports": [], "decorators": [], "has_yield": False,
             "name": None, "parse_error": root.has_error}
    if fdef is None:
        return facts
    facts["name"] = _txt(fdef.child_by_field_name("name"), src)
    # round 4 (R1/R2 bug A): the function's own decorators sit on the parent `decorated_definition`
    if fdef.parent is not None and fdef.parent.type == "decorated_definition":
        for d in fdef.parent.children:
            if d.type == "decorator":
                facts["decorators"].append(_txt(d, src).lstrip("@").split("(")[0].strip())
    params = fdef.child_by_field_name("parameters")

    def _splat(node):
        ident = next((c for c in node.children if c.type == "identifier"), None)
        if ident is not None:
            star = "*" if node.type == "list_splat_pattern" else "**"
            facts["params"].append(star + _txt(ident, src))
            facts["has_kwargs" if star == "**" else "has_varargs"] = True

    if params is not None:
        for p in params.children:
            if p.type == "identifier":
                facts["params"].append(_txt(p, src))
            elif p.type in ("default_parameter", "typed_default_parameter"):
                nm = _txt(p.child_by_field_name("name"), src)
                facts["params"].append(nm)
                facts["defaults"][nm] = _txt(p.child_by_field_name("value"), src)
            elif p.type == "typed_parameter":
                # round 4 (bug B): a typed splat (`**kwargs: Unpack[...]`) wraps a splat pattern
                sp = next((c for c in p.children if c.type in ("list_splat_pattern", "dictionary_splat_pattern")), None)
                if sp is not None:
                    _splat(sp)
                else:
                    ident = next((c for c in p.children if c.type == "identifier"), None)
                    if ident is not None:
                        facts["params"].append(_txt(ident, src))
            elif p.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                _splat(p)
    facts.setdefault("has_kwargs", False)
    facts.setdefault("has_varargs", False)
    body = fdef.child_by_field_name("body")
    facts["identifiers"] = sorted({_txt(n, src) for n in _walk(body) if n.type == "identifier"}) if body is not None else []
    facts["has_with"] = any(n.type == "with_statement" for n in _walk(fdef))
    try:
        fn_ast = next(n for n in ast.walk(ast.parse(func_src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        locs, called_vars = set(), set()
        for n in ast.walk(fn_ast):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                locs.add(n.id)
        local_names = locs | {a.arg for a in fn_ast.args.args + fn_ast.args.kwonlyargs + fn_ast.args.posonlyargs}
        for n in ast.walk(fn_ast):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in local_names:
                called_vars.add(n.func.id)
        facts["locals"] = sorted(locs)
        facts["dyn_calls"] = sorted(called_vars)
        # returns of the function itself (nested defs/lambdas excluded)
        own_ret, own_val, own_yield = 0, False, False
        stack = list(fn_ast.body)
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(n, ast.Return):
                own_ret += 1
                # v6: an explicit `return None` is not a value
                own_val = own_val or (n.value is not None and not (isinstance(n.value, ast.Constant) and n.value.value is None))
            if isinstance(n, (ast.Yield, ast.YieldFrom)):
                own_yield = True
            stack.extend(ast.iter_child_nodes(n))
        facts["is_async"] = isinstance(fn_ast, ast.AsyncFunctionDef)
        if facts["is_async"]:
            own_val = True                    # v6: an async function always returns a coroutine
        facts["own_returns_value"], facts["own_has_yield"] = own_val, own_yield
        facts["dyn_callsite"] = any(isinstance(n, ast.Call) and isinstance(n.func, (ast.Subscript, ast.Call))
                                    for n in ast.walk(fn_ast))
    except (SyntaxError, StopIteration):
        facts["locals"], facts["dyn_calls"] = [], []
        facts["own_returns_value"], facts["own_has_yield"] = None, None
        facts["dyn_callsite"] = True
    for n in _walk(fdef):
        if n.type == "call":
            f = n.child_by_field_name("function")
            if f is not None:
                full = _txt(f, src).replace("\n", "").replace(" ", "")
                facts["calls_full"].append(full)
                facts["calls"].append(full.split(".")[-1].split("[")[0].split("(")[0])
        elif n.type == "return_statement":
            facts["returns_count"] += 1
            if len(n.children) > 1:
                facts["returns_value"] = True
        elif n.type == "yield":
            facts["has_yield"] = True
        elif n.type == "raise_statement":
            if len(n.children) > 1:
                e = n.children[1]
                t = _txt(e, src)
                name = t.split("(")[0].split(".")[-1].strip()
                if name:
                    facts["raises"].append(name)
        elif n.type in ("import_statement", "import_from_statement"):
            facts["imports"].extend(_import_names(_txt(n, src)))
        elif n.type == "decorator":
            facts["decorators"].append(_txt(n, src).lstrip("@").split("(")[0])
    for line in context_imports.splitlines():
        line = line.strip()
        if line.startswith(("import ", "from ")):
            facts["imports"].extend(_import_names(line))
    facts["calls_indirect"] = _py_indirect_calls(func_src, context_imports)
    for k in ("calls", "calls_full", "raises", "imports", "decorators", "calls_indirect"):
        facts[k] = sorted(set(facts[k]))
    return facts


_HIGHER_ORDER = {"partial", "map", "filter", "sorted", "min", "max", "reduce", "starmap", "apply", "submit",
                 "run_in_executor", "wraps", "callback", "setdefault"}


def _py_indirect_calls(func_src, context_imports=""):
    """Callees reached indirectly (RUNLOG cycle 2): `getattr(obj, "name")` string literals, function references
    passed to higher-order functions (partial/map/filter/sorted key=...), and the original names behind
    `import X as Y` aliases that the function calls (in the function body or the module context)."""
    out = set()
    try:
        mod = ast.parse(func_src)
    except SyntaxError:
        return []
    aliases = {}
    import_lines = context_imports.splitlines() + [l.strip() for l in func_src.splitlines()]
    for line in import_lines:
        line = line.strip()
        if line.startswith(("import ", "from ")) and " as " in line:
            body = line.split(" import ", 1)[1] if line.startswith("from ") else line[7:]
            for part in body.strip("() ").split(","):
                if " as " in part:
                    orig, al = [x.strip() for x in part.split(" as ", 1)]
                    aliases[al] = orig
    for n in ast.walk(mod):
        if not isinstance(n, ast.Call):
            continue
        fname = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else None)
        if fname == "getattr" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str):
            out.add(n.args[1].value)
        if fname in _HIGHER_ORDER:
            refs = list(n.args[:1]) + [k.value for k in n.keywords if k.arg in ("key", "func", "fn", "default_factory")]
            for a in refs:
                if isinstance(a, ast.Name):
                    out.add(a.id)
                elif isinstance(a, ast.Attribute):
                    out.add(a.attr)
        if fname in aliases:
            out.add(aliases[fname].split(".")[-1])
            out.add(aliases[fname])
    # round 4 (bug C): bound-method aliases `x = obj.m; x(...)` call m
    bound = {}
    for n in ast.walk(mod):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Attribute):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    bound[t.id] = n.value.attr
    for n in ast.walk(mod):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in bound:
            out.add(bound[n.func.id])
    return sorted(out)


def _import_names(line):
    line = line.strip().rstrip("\\").strip()
    out = []
    if line.startswith("import "):
        for part in line[7:].split(","):
            part = part.strip()
            if " as " in part:
                mod, alias = [x.strip() for x in part.split(" as ")]
                out += [mod, alias, mod.split(".")[-1]]
            elif part:
                out += [part, part.split(".")[-1]]
    elif line.startswith("from "):
        try:
            mod, names = line[5:].split(" import ", 1)
        except ValueError:
            return out
        mod = mod.strip()
        out.append(mod)
        out.append(mod.split(".")[-1])
        names = names.strip().strip("()")
        for part in names.split(","):
            part = part.strip()
            if " as " in part:
                nm, alias = [x.strip() for x in part.split(" as ")]
                out += [nm, alias]
            elif part:
                out.append(part)
    return [o for o in out if o]


# --------------------------------------------------------------------------- Python def-use graph
MUTATORS = {"append", "extend", "add", "update", "insert", "put", "putAll", "addAll", "push", "appendleft",
            "setdefault", "write", "writelines", "set", "offer", "addFirst", "addLast", "append_child", "fill"}
class _DefUse(ast.NodeVisitor):
    def __init__(self):
        self.edges = set()
        self.nodes = set()
        self.self_updates = set()     # x = g(x), x += e: x flows into itself (RUNLOG cycle 4)

    @staticmethod
    def _name(n):
        if isinstance(n, ast.Name):
            return n.id
        if isinstance(n, ast.Attribute):
            try:
                return ast.unparse(n)
            except Exception:
                return None
        if isinstance(n, (ast.Subscript, ast.Starred)):
            return _DefUse._name(n.value)
        return None

    def _reads(self, expr):
        """Variable names and call nodes read inside expr (one step). Callee names are not data reads."""
        out = set()
        callees = {id(n.func) for n in ast.walk(expr) if isinstance(n, ast.Call)}
        for n in ast.walk(expr):
            if id(n) in callees:
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                out.add(n.id)
            elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
                nm = self._name(n)
                if nm:
                    out.add(nm)
            elif isinstance(n, ast.Call):
                c = self._callee(n)
                if c:
                    out.add("call:" + c)
        return out

    def _callee(self, call):
        f = call.func
        if isinstance(f, ast.Name):
            return f.id
        if isinstance(f, ast.Attribute):
            return f.attr
        return None

    def _targets(self, t):
        out = set()
        for n in ast.walk(t):
            if isinstance(n, (ast.Name, ast.Attribute, ast.Subscript)) and isinstance(getattr(n, "ctx", None), ast.Store):
                nm = self._name(n)          # x[k] = v stores into x (RUNLOG cycle 2)
                if nm:
                    out.add(nm)
        return out

    def _edge(self, srcs, dsts):
        for s in srcs:
            for d in dsts:
                if s != d:
                    self.edges.add((s, d))
                self.nodes.add(s)
                self.nodes.add(d)

    def visit_Call(self, node):
        c = self._callee(node)
        if c:
            cn = "call:" + c
            self.nodes.add(cn)
            for a in list(node.args) + [k.value for k in node.keywords]:
                self._edge(self._reads(a), {cn})
            # method call on an object: receiver feeds the call
            if isinstance(node.func, ast.Attribute):
                self._edge(self._reads(node.func.value), {cn})
                # mutating method: arguments flow into the receiver (RUNLOG cycle 2)
                if c in MUTATORS:
                    recv = self._name(node.func.value)
                    if recv:
                        for a in list(node.args) + [k.value for k in node.keywords]:
                            self._edge(self._reads(a), {recv})
        self.generic_visit(node)

    def visit_Assign(self, node):
        srcs = self._reads(node.value)
        for t in node.targets:
            tg = self._targets(t)
            self._edge(srcs, tg)
            self.self_updates |= (srcs & tg)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        tg = self._targets(node.target)
        self._edge(self._reads(node.value) | tg, tg)
        self.self_updates |= tg
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._edge(self._reads(node.value), self._targets(node.target))
        self.generic_visit(node)

    def visit_NamedExpr(self, node):
        self._edge(self._reads(node.value), self._targets(node.target))
        self.generic_visit(node)

    def visit_Return(self, node):
        if node.value is not None:
            self._edge(self._reads(node.value), {"return"})
        self.generic_visit(node)

    def visit_Yield(self, node):
        if node.value is not None:
            self._edge(self._reads(node.value), {"return"})
        self.generic_visit(node)

    def visit_YieldFrom(self, node):
        self._edge(self._reads(node.value), {"return"})
        self.generic_visit(node)

    def visit_For(self, node):
        self._edge(self._reads(node.iter), self._targets(node.target))
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self._edge(self._reads(node.iter), self._targets(node.target))
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if item.optional_vars is not None:
                self._edge(self._reads(item.context_expr), self._targets(item.optional_vars))
        self.generic_visit(node)

    def visit_Raise(self, node):
        if node.exc is not None:
            self._edge(self._reads(node.exc), {"raise"})
        self.generic_visit(node)


def py_dataflow(func_src):
    """Return {'nodes': [...], 'edges': [[u,v],...], 'params': [...]} or None on syntax error."""
    try:
        mod = ast.parse(func_src)
    except SyntaxError:
        return None
    fn = next((n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None:
        return None
    v = _DefUse()
    params = [a.arg for a in fn.args.args + fn.args.posonlyargs + fn.args.kwonlyargs]
    if fn.args.vararg:
        params.append(fn.args.vararg.arg)
    if fn.args.kwarg:
        params.append(fn.args.kwarg.arg)
    v.nodes.update(params)
    for stmt in fn.body:
        v.visit(stmt)
    return {"nodes": sorted(v.nodes), "edges": sorted(list(e) for e in v.edges), "params": params,
            "self_updates": sorted(v.self_updates)}


def reachable(graph, src, dst):
    adj = {}
    for u, v in graph["edges"]:
        adj.setdefault(u, set()).add(v)
    seen, stack = set(), [src]
    while stack:
        u = stack.pop()
        if u == dst:
            return True
        if u in seen:
            continue
        seen.add(u)
        stack.extend(adj.get(u, ()))
    return False


# --------------------------------------------------------------------------- Java structural facts
def java_struct_facts(method_src, context_imports=""):
    src = method_src.encode()
    tree = _PARSERS["java"].parse(("class __W {\n" + method_src + "\n}").encode())
    wsrc = ("class __W {\n" + method_src + "\n}").encode()
    root = tree.root_node
    mdef = next((n for n in _walk(root) if n.type in ("method_declaration", "constructor_declaration")), None)
    facts = {"params": [], "defaults": {}, "calls": [], "calls_full": [], "returns_count": 0,
             "returns_value": False, "raises": [], "imports": [], "decorators": [], "has_yield": False,
             "name": None, "parse_error": root.has_error, "declared_throws": []}
    if mdef is None:
        return facts
    facts["name"] = _txt(mdef.child_by_field_name("name"), wsrc)
    params = mdef.child_by_field_name("parameters")
    if params is not None:
        for p in params.children:
            if p.type in ("formal_parameter", "spread_parameter"):
                ident = p.child_by_field_name("name") or next((c for c in p.children if c.type == "identifier"), None)
                if ident is None:
                    ident = next((c for c in reversed(p.children) if c.type == "identifier" or c.type == "variable_declarator"), None)
                if ident is not None:
                    facts["params"].append(_txt(ident, wsrc).split("[")[0].strip())
    for n in _walk(mdef):
        if n.type == "method_invocation":
            nm = n.child_by_field_name("name")
            obj = n.child_by_field_name("object")
            if nm is not None:
                facts["calls"].append(_txt(nm, wsrc))
                facts["calls_full"].append(((_txt(obj, wsrc) + ".") if obj is not None else "") + _txt(nm, wsrc))
        elif n.type == "object_creation_expression":
            t = n.child_by_field_name("type")
            if t is not None:
                facts["calls"].append(_txt(t, wsrc).split("<")[0].split(".")[-1])
                facts["calls_full"].append("new " + _txt(t, wsrc).split("<")[0])
        elif n.type == "return_statement":
            facts["returns_count"] += 1
            if len(n.children) > 2:
                facts["returns_value"] = True
        elif n.type == "throw_statement":
            for c in _walk(n):
                if c.type == "object_creation_expression":
                    t = c.child_by_field_name("type")
                    if t is not None:
                        facts["raises"].append(_txt(t, wsrc).split("<")[0].split(".")[-1])
                    break
        elif n.type == "throws":
            for c in n.children:
                if c.type in ("type_identifier", "scoped_type_identifier"):
                    facts["declared_throws"].append(_txt(c, wsrc).split(".")[-1])
        elif n.type in ("marker_annotation", "annotation"):
            nm = n.child_by_field_name("name")
            if nm is not None:
                facts["decorators"].append(_txt(nm, wsrc))
    for line in context_imports.splitlines():
        line = line.strip()
        if line.startswith("import "):
            mod = line[7:].rstrip(";").strip()
            facts["imports"] += [mod, mod.split(".")[-1]]
    facts["has_kwargs"] = False
    facts["has_varargs"] = any(n.type == "spread_parameter" for n in _walk(mdef))
    body = mdef.child_by_field_name("body")
    facts["identifiers"] = sorted({_txt(n, wsrc) for n in _walk(body) if n.type == "identifier"}) if body is not None else []
    facts["has_with"] = any(n.type in ("try_with_resources_statement", "resource_specification") for n in _walk(mdef))
    facts["locals"] = sorted({_txt(d.child_by_field_name("name"), wsrc) for d in _walk(mdef)
                              if d.type == "variable_declarator" and d.child_by_field_name("name") is not None})
    facts["dyn_calls"] = []
    # v5: Java own returns exclude lambdas and anonymous classes
    own = False
    stack = [mdef.child_by_field_name("body")] if mdef.child_by_field_name("body") is not None else []
    while stack:
        n = stack.pop()
        if n.type in ("lambda_expression", "class_body"):
            continue
        if n.type == "return_statement" and len(n.children) > 2:
            own = True
        stack.extend(n.children)
    facts["own_returns_value"], facts["own_has_yield"] = own, False
    facts["raises"] = sorted(set(facts["raises"]) | set(facts["declared_throws"]))
    for k in ("calls", "calls_full", "imports", "decorators"):
        facts[k] = sorted(set(facts[k]))
    return facts


def java_dataflow(method_src):
    """Intra-procedural def-use graph for a Java method (same node conventions as py_dataflow):
    local declarations / assignments: reads(rhs) -> target; call arguments and receiver -> call:<name>;
    `new T(args)` -> call:T; return expression -> return; enhanced-for: iterable -> loop variable."""
    wsrc = ("class __W {\n" + method_src + "\n}").encode()
    root = _PARSERS["java"].parse(wsrc).root_node
    mdef = next((n for n in _walk(root) if n.type in ("method_declaration", "constructor_declaration")), None)
    if mdef is None:
        return None
    nodes, edges, selfupd = set(), set(), set()

    def reads(node):
        out = set()
        if node is None:
            return out
        stack = [node]
        while stack:
            n = stack.pop()
            if n.type == "identifier" and (n.parent is None or n.parent.type != "method_invocation"
                                           or n.parent.child_by_field_name("name") != n):
                if not (n.parent is not None and n.parent.type == "field_access" and n.parent.child_by_field_name("field") == n):
                    out.add(_txt(n, wsrc))
            elif n.type == "field_access":
                out.add(_txt(n, wsrc).replace(" ", ""))
            if n.type == "method_invocation":
                nm = n.child_by_field_name("name")
                if nm is not None:
                    out.add("call:" + _txt(nm, wsrc))
                obj = n.child_by_field_name("object")
                if obj is not None:
                    stack.append(obj)
                continue          # arguments are edges into the call node, not direct reads
            if n.type == "object_creation_expression":
                t = n.child_by_field_name("type")
                if t is not None:
                    out.add("call:" + _txt(t, wsrc).split("<")[0].split(".")[-1])
                continue
            stack.extend(n.children)
        return out

    def edge(srcs, dst):
        for s_ in srcs:
            nodes.add(s_)
            nodes.add(dst)
            if s_ != dst:
                edges.add((s_, dst))

    params = []
    pnode = mdef.child_by_field_name("parameters")
    if pnode is not None:
        for p in pnode.children:
            if p.type in ("formal_parameter", "spread_parameter"):
                ident = p.child_by_field_name("name") or next((c for c in reversed(p.children) if c.type in ("identifier", "variable_declarator")), None)
                if ident is not None:
                    params.append(_txt(ident, wsrc).split("[")[0].strip())
    nodes.update(params)
    for n in _walk(mdef):
        if n.type == "variable_declarator":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            if nm is not None and val is not None:
                edge(reads(val), _txt(nm, wsrc))
        elif n.type == "assignment_expression":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if left is not None and right is not None:
                tgt = _txt(left, wsrc).replace(" ", "").split("[")[0]
                op = _txt(n.child_by_field_name("operator") or n, wsrc)
                rs = reads(right)
                srcs = rs | ({tgt} if op != "=" else set())
                edge(srcs, tgt)
                all_ids = {_txt(x, wsrc) for x in _walk(right) if x.type == "identifier"}
                if op != "=" or tgt in all_ids:
                    selfupd.add(tgt)
        elif n.type in ("method_invocation", "object_creation_expression"):
            obj = None
            if n.type == "method_invocation":
                nm = n.child_by_field_name("name")
                cn = "call:" + _txt(nm, wsrc) if nm is not None else None
                obj = n.child_by_field_name("object")
                if cn and obj is not None:
                    edge(reads(obj), cn)
            else:
                t = n.child_by_field_name("type")
                cn = "call:" + _txt(t, wsrc).split("<")[0].split(".")[-1] if t is not None else None
            args = n.child_by_field_name("arguments")
            if cn and args is not None:
                alist = [a for a in args.children if a.type not in ("(", ")", ",")]
                for a in alist:
                    edge(reads(a), cn)
                # mutating calls: arguments flow into the receiver; System.arraycopy(src,_,dest,_,_): src -> dest
                if n.type == "method_invocation" and cn[5:] in MUTATORS and obj is not None:
                    for a in alist:
                        edge(reads(a), _txt(obj, wsrc).replace(" ", ""))
                if cn == "call:arraycopy" and len(alist) >= 3:
                    for d in reads(alist[2]):
                        edge(reads(alist[0]), d)
        elif n.type == "return_statement":
            for c in n.children:
                if c.type not in ("return", ";"):
                    edge(reads(c), "return")
        elif n.type == "update_expression":
            for c in n.children:
                if c.type == "identifier":
                    selfupd.add(_txt(c, wsrc))
        elif n.type == "enhanced_for_statement":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            if nm is not None and val is not None:
                edge(reads(val), _txt(nm, wsrc))
    return {"nodes": sorted(nodes), "edges": sorted([list(e) for e in edges]), "params": params,
            "self_updates": sorted(selfupd)}


def facts_for(rec):
    """Compute all facts for a corpus record. `du` is the flow-sensitive def-use graph used by the round-2
    engine (defuse.py); `dataflow` is the round-1 flow-insensitive name graph, kept only for the v1 comparison."""
    import defuse
    if rec["lang"] == "python":
        f = py_struct_facts(rec["source"], rec.get("context_imports", ""))
        f["dataflow"] = py_dataflow(rec["source"])
        f["du"] = defuse.analyse(defuse.py_ir(rec["source"]))
        f["du_cons"] = defuse.analyse(defuse.py_ir(rec["source"]), cons=True)
    else:
        f = java_struct_facts(rec["source"], rec.get("context_imports", ""))
        f["dataflow"] = java_dataflow(rec["source"])
        f["du"] = defuse.analyse(defuse.java_ir(rec["source"], _PARSERS["java"]))
        f["du_cons"] = defuse.analyse(defuse.java_ir(rec["source"], _PARSERS["java"]), cons=True)
        f["calls_indirect"] = []
    f["fid"] = rec["fid"]
    f["lang"] = rec["lang"]
    return f


def main():
    out = os.path.join(RESULTS, "facts.jsonl")
    n = 0
    with open(out, "w") as fo:
        for corpus in ("corpus_a.jsonl", "corpus_b.jsonl"):
            p = os.path.join(DATA, corpus)
            if not os.path.exists(p):
                continue
            for line in open(p):
                rec = json.loads(line)
                fo.write(json.dumps(facts_for(rec), sort_keys=True) + "\n")
                n += 1
    print(f"facts: {n} records -> {os.path.basename(out)}")


if __name__ == "__main__":
    main()
