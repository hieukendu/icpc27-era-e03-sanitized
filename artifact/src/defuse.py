"""Flow-sensitive intra-procedural def-use analysis (round-3 revision, R3-M2).

Both languages are lowered to a small statement IR and analysed with one reaching-definitions pass:
  * an assignment creates a definition node `d:<var>@<k>` whose DATA predecessors are the reaching definitions
    of what its right-hand side reads (variables, field paths, call sites); a strong assignment KILLS earlier
    definitions; weak updates (x[i] = v, x += v, x.append(v), System.arraycopy, and the base object of a field
    store o.f = v) depend on the old definitions and replace them;
  * field paths are field-sensitive when defined (o.f reads the definitions of o.f) and fall back to the base
    object otherwise;
  * every call creates a call-site node `c:<callee>@<k>` fed by its arguments and receiver;
  * every return / yield creates `r@<k>`, every raise / throw `x@<k>`;
  * branch and loop conditions create `cond@<k>`; statements nested in a branch, and every statement AFTER a
    branch that exits early (return / raise / continue / break), get CONTROL edges from that condition;
  * if/else join by union; try handlers start from the join of all intermediate states of the try body; loops
    iterate to a real fixpoint (nodes are keyed by statement, so the state lattice is finite);
  * walrus (:=), match captures, Java chained (a = b = c) and in-condition assignments are lowered to definitions.
Not modelled (stated in the paper; a function using an `unsupported` construct never yields FALSE):
aliasing and heap effects beyond the field/base rule, inter-procedural flow, closures writing outer variables
(nonlocal/global), Java anonymous classes and block lambdas that assign.
"""
import ast
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

MUTATORS = {"append", "extend", "add", "update", "insert", "put", "putAll", "addAll", "push", "appendleft",
            "setdefault", "write", "writelines", "set", "offer", "addFirst", "addLast", "fill", "remove",
            "discard", "pop", "clear", "sort", "reverse"}


# ----------------------------------------------------------------------------------------------- IR
class Expr:
    """reads: plain variables; attrs: (path, base) field reads; calls: (callee, args Expr, receiver)."""
    __slots__ = ("reads", "attrs", "calls")

    def __init__(self, reads=None, calls=None, attrs=None):
        self.reads = set(reads or ())
        self.attrs = set(attrs or ())
        self.calls = list(calls or ())

    def merge(self, other):
        self.reads |= other.reads
        self.attrs |= other.attrs
        self.calls += other.calls
        return self


class Stmt(list):
    """A list subclass so that every statement has a stable identity (used to key graph nodes)."""


def S(*xs):
    return Stmt(xs)


# ----------------------------------------------------------------------------------------------- Python lowering
def _py_name(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        b = _py_name(n.value)
        return f"{b}.{n.attr}" if b else None
    if isinstance(n, (ast.Subscript, ast.Starred)):
        return _py_name(n.value)
    return None


def _py_callee(call):
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def py_expr(node, bound=frozenset()):
    e = Expr()
    if node is None:
        return e
    if isinstance(node, ast.NamedExpr):
        # the definition is emitted before the statement (see _walrus); here the value is the target
        if isinstance(node.target, ast.Name):
            e.reads.add(node.target.id)
        return e
    if isinstance(node, ast.Call):
        args = Expr()
        recv = None
        if isinstance(node.func, ast.Attribute):
            args.merge(py_expr(node.func.value, bound))
            recv = _py_name(node.func.value)
        elif not isinstance(node.func, ast.Name):
            args.merge(py_expr(node.func, bound))
        elif node.func.id not in bound:
            args.reads.add(node.func.id)        # a local function object flows into its own call
        for a in list(node.args) + [k.value for k in node.keywords]:
            args.merge(py_expr(a, bound))
        e.calls.append((_py_callee(node) or "<dyn>", args, recv))
        return e
    if isinstance(node, ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id not in bound:
            e.reads.add(node.id)
        return e
    if isinstance(node, ast.Attribute):
        nm = _py_name(node)
        if nm and isinstance(node.value, (ast.Name, ast.Attribute)):
            root = nm.split(".")[0]
            if root not in bound:
                e.attrs.add((nm, _py_name(node.value)))
            return e
        return e.merge(py_expr(node.value, bound))
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        b = set(bound)
        for g in node.generators:
            e.merge(py_expr(g.iter, frozenset(b)))
            for t in ast.walk(g.target):
                if isinstance(t, ast.Name):
                    b.add(t.id)
            for cond in g.ifs:
                e.merge(py_expr(cond, frozenset(b)))
        parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        for p in parts:
            e.merge(py_expr(p, frozenset(b)))
        return e
    if isinstance(node, ast.Lambda):
        b = set(bound) | {a.arg for a in node.args.args}
        return e.merge(py_expr(node.body, frozenset(b)))
    for ch in ast.iter_child_nodes(node):
        if isinstance(ch, ast.expr):
            e.merge(py_expr(ch, bound))
        elif isinstance(ch, ast.comprehension):
            e.merge(py_expr(ch.iter, bound))
        elif isinstance(ch, ast.keyword):
            e.merge(py_expr(ch.value, bound))
    return e


def _py_targets(t):
    """[(name, weak)] for an assignment target; a field store also weak-updates its base object."""
    if isinstance(t, ast.Name):
        return [(t.id, False)]
    if isinstance(t, ast.Attribute):
        nm, base = _py_name(t), _py_name(t.value)
        out = [(nm, False)] if nm else []
        if base:
            out.append((base, True))
        return out
    if isinstance(t, ast.Subscript):
        b = _py_name(t.value)
        return [(b, True)] if b else []
    if isinstance(t, ast.Starred):
        return _py_targets(t.value)
    if isinstance(t, (ast.Tuple, ast.List)):
        out = []
        for el in t.elts:
            out += _py_targets(el)
        return out
    return []


def _assigns(targets, rhs):
    """One IR assignment per (name, weak) target group."""
    strong = [n for n, w in targets if not w]
    weak = [n for n, w in targets if w]
    out = []
    if strong:
        out.append(S("assign", strong, rhs, False))
    if weak:
        out.append(S("assign", weak, rhs, True))
    return out


def _walrus(nodes):
    """Definitions for := expressions inside the given expression nodes (emitted before the statement)."""
    out = []
    for root in nodes:
        if root is None:
            continue
        for n in ast.walk(root):
            if isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
                out.append(S("assign", [n.target.id], py_expr(n.value), False))
    return out


def _captures(p):
    names = []
    for n in ast.walk(p):
        if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name:
            names.append(n.name)
        elif isinstance(n, ast.MatchMapping) and n.rest:
            names.append(n.rest)
    return names


class _Flags:
    def __init__(self):
        self.unsupported = set()
        self.copies = set()      # (target, source) bare variable copies
        self.mutated = set()     # variables updated in place


def py_stmts(body, flags):
    out = []
    for s in body:
        if isinstance(s, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr, ast.Return)):
            out += _walrus([getattr(s, "value", None)])
        if isinstance(s, ast.Assign):
            rhs = py_expr(s.value)
            if isinstance(s.value, ast.Name):
                for t in s.targets:
                    if isinstance(t, ast.Name):
                        flags.copies.add((t.id, s.value.id))
            first = None
            for t in s.targets:
                if isinstance(t, (ast.Subscript, ast.Attribute)) and _py_name(t.value):
                    flags.mutated.add(_py_name(t.value).split(".")[0])
                extra = py_expr(t.slice) if isinstance(t, ast.Subscript) else Expr()
                if first is None and isinstance(t, (ast.Tuple, ast.List)) and isinstance(s.value, (ast.Tuple, ast.List)) \
                        and len(t.elts) == len(s.value.elts) and not any(isinstance(x, ast.Starred) for x in t.elts + s.value.elts):
                    # round 4: `x, y = a, b` is element-wise and simultaneous (b does not reach x)
                    out.append(S("multi", [(_py_targets(te), py_expr(ve)) for te, ve in zip(t.elts, s.value.elts)]))
                    first = [n for te in t.elts for n, w in _py_targets(te) if not w][:1]
                elif first is None:
                    out += _assigns(_py_targets(t), Expr(rhs.reads, rhs.calls, rhs.attrs).merge(extra))
                    tg = _py_targets(t)
                    first = [n for n, w in tg if not w][:1] or [n for n, _ in tg][:1]
                else:
                    # chained `a = b[k] = e`: every later target receives the same object as the first
                    out += _assigns(_py_targets(t), Expr(set(first)).merge(extra))
        elif isinstance(s, ast.AugAssign):
            out += _assigns([(n, True) for n, _ in _py_targets(s.target)], py_expr(s.value))
        elif isinstance(s, ast.AnnAssign):
            if s.value is not None:
                out += _assigns(_py_targets(s.target), py_expr(s.value))
        elif isinstance(s, ast.Expr):
            v = s.value
            ex = py_expr(v)
            if isinstance(v, (ast.Yield, ast.YieldFrom)):
                out.append(S("return", py_expr(v.value)))
            elif isinstance(v, ast.Await) and isinstance(v.value, (ast.Yield, ast.YieldFrom)):
                out.append(S("return", py_expr(v.value.value)))
            else:
                out.append(S("expr", ex))
                if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr in MUTATORS:
                    recv = _py_name(v.func.value)
                    if recv:
                        out.append(S("assign", [recv], ex, True))
                        flags.mutated.add(recv.split(".")[0])
                if isinstance(v, ast.Call) and _py_callee(v) in ("exec", "eval", "setattr", "globals", "locals"):
                    flags.unsupported.add("reflection")
        elif isinstance(s, ast.Return):
            out.append(S("return", py_expr(s.value) if s.value is not None else None))
        elif isinstance(s, ast.Raise):
            out.append(S("raise", py_expr(s.exc)))
        elif isinstance(s, ast.If):
            out += _walrus([s.test])
            out.append(S("if", py_expr(s.test), py_stmts(s.body, flags), py_stmts(s.orelse, flags)))
        elif isinstance(s, (ast.For, ast.AsyncFor)):
            out += _walrus([s.iter])
            header = _assigns(_py_targets(s.target), py_expr(s.iter))
            out.append(S("loop", header, py_expr(s.iter), py_stmts(s.body, flags)))
            out += py_stmts(s.orelse, flags)
        elif isinstance(s, ast.While):
            out += _walrus([s.test])
            out.append(S("loop", _walrus([s.test]), py_expr(s.test), py_stmts(s.body, flags)))
            out += py_stmts(s.orelse, flags)
        elif isinstance(s, (ast.With, ast.AsyncWith)):
            for item in s.items:
                ce = py_expr(item.context_expr)
                if item.optional_vars is not None:
                    out += _assigns(_py_targets(item.optional_vars), ce)
                else:
                    out.append(S("expr", ce))
            out += py_stmts(s.body, flags)
        elif isinstance(s, ast.Try) or s.__class__.__name__ == "TryStar":
            handlers = []
            for h in s.handlers:
                hb = py_stmts(h.body, flags)
                if h.name:
                    hb = [S("assign", [h.name], py_expr(h.type), False)] + hb
                handlers.append(hb)
            out.append(S("try", py_stmts(s.body, flags) + py_stmts(s.orelse, flags), handlers,
                         py_stmts(s.finalbody, flags)))
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ex = Expr()
            for n in ast.walk(s):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    ex.reads.add(n.id)
                if isinstance(n, (ast.Nonlocal, ast.Global)):
                    flags.unsupported.add("closure-write")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in MUTATORS:
                    flags.unsupported.add("closure-write")
            out.append(S("assign", [s.name], ex, False))
        elif isinstance(s, ast.Assert):
            out.append(S("expr", py_expr(s.test)))
        elif isinstance(s, (ast.Global, ast.Nonlocal)):
            flags.unsupported.add("global")
        elif isinstance(s, (ast.Break, ast.Continue)):
            out.append(S("jump"))
        elif s.__class__.__name__ == "Match":
            subj = py_expr(s.subject)
            branches = []
            for c in s.cases:
                caps = _captures(c.pattern)
                b = ([S("assign", caps, py_expr(s.subject), False)] if caps else []) + py_stmts(c.body, flags)
                branches.append(b)
            st = S("if", subj, branches[-1] if branches else [], [])
            for b in reversed(branches[:-1]):
                st = S("if", subj, b, [st])
            out.append(st)
    return out


def py_ir(func_src):
    try:
        mod = ast.parse(func_src)
    except SyntaxError:
        return None
    fn = next((n for n in ast.walk(mod) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if fn is None:
        return None
    a = fn.args
    params = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs]
    if a.vararg:
        params.append(a.vararg.arg)
    if a.kwarg:
        params.append(a.kwarg.arg)
    flags = _Flags()
    stmts = py_stmts(fn.body, flags)
    if any(a in flags.mutated or b in flags.mutated for a, b in flags.copies):
        flags.unsupported.add("alias")
    nested = sorted({n.name for n in ast.walk(fn) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn})
    return params, stmts, sorted(flags.unsupported), nested, py_fragment(fn)


# ----------------------------------------------------------------------------------------------- Java lowering
def _t(node, src):
    return src[node.start_byte:node.end_byte].decode("utf8", "replace")


_TYPE_NODES = ("type_identifier", "generic_type", "integral_type", "floating_point_type", "boolean_type",
               "scoped_type_identifier", "array_type", "dimensions")


def java_expr(node, src):
    e = Expr()
    if node is None:
        return e
    t = node.type
    if t == "method_invocation":
        nm = node.child_by_field_name("name")
        obj = node.child_by_field_name("object")
        args = Expr()
        recv = None
        if obj is not None:
            args.merge(java_expr(obj, src))
            if obj.type in ("identifier", "field_access"):
                recv = _t(obj, src).replace(" ", "")
        a = node.child_by_field_name("arguments")
        if a is not None:
            for ch in a.named_children:
                args.merge(java_expr(ch, src))
        e.calls.append((_t(nm, src) if nm is not None else "<dyn>", args, recv))
        return e
    if t == "object_creation_expression":
        ty = node.child_by_field_name("type")
        args = Expr()
        a = node.child_by_field_name("arguments")
        if a is not None:
            for ch in a.named_children:
                args.merge(java_expr(ch, src))
        e.calls.append((_t(ty, src).split("<")[0].split(".")[-1] if ty is not None else "<new>", args, None))
        return e
    if t == "assignment_expression":
        left = node.child_by_field_name("left")
        name, _ = _java_target(left, src) if left is not None else (None, False)
        if name:
            e.reads.add(name)               # its definition is emitted before the statement (_java_nested)
        return e
    if t == "identifier":
        e.reads.add(_t(node, src))
        return e
    if t == "field_access":
        obj = node.child_by_field_name("object")
        full = _t(node, src).replace(" ", "")
        if obj is not None and obj.type in ("identifier", "field_access", "this"):
            e.attrs.add((full, _t(obj, src).replace(" ", "")))
            return e
        return e.merge(java_expr(obj, src))
    if t == "lambda_expression":
        body = node.child_by_field_name("body")
        return e.merge(java_expr(body, src)) if body is not None else e
    for ch in node.named_children:
        if ch.type in _TYPE_NODES:
            continue
        e.merge(java_expr(ch, src))
    return e


def _java_target(node, src):
    if node.type == "identifier":
        return _t(node, src), False
    if node.type == "field_access":
        return _t(node, src).replace(" ", ""), False
    if node.type == "array_access":
        arr = node.child_by_field_name("array")
        if arr is not None:
            n, _ = _java_target(arr, src)
            return n, True
    return None, False


def _java_assign(ex, src):
    """IR for one assignment_expression (handles a = b = c recursively)."""
    left, right = ex.child_by_field_name("left"), ex.child_by_field_name("right")
    op = ex.child_by_field_name("operator")
    opt = _t(op, src) if op is not None else "="
    name, weak = _java_target(left, src) if left is not None else (None, False)
    out = []
    if right is not None and right.type == "assignment_expression":
        out += _java_assign(right, src)
    out += _java_nested(right, src)
    rhs = java_expr(right, src)
    if left is not None and left.type == "array_access":
        rhs.merge(java_expr(left.child_by_field_name("index"), src))
    if name:
        tg = [(name, weak or opt != "=")]
        if left is not None and left.type == "field_access":
            obj = left.child_by_field_name("object")
            if obj is not None:
                tg.append((_t(obj, src).replace(" ", ""), True))
        out += _assigns(tg, rhs)
    return out


def _java_nested(node, src):
    """Definitions for assignment expressions nested inside an expression (e.g. while ((l = r.readLine()) != null))."""
    out = []
    if node is None:
        return out
    stack = list(node.named_children) if node.type != "assignment_expression" else []
    while stack:
        n = stack.pop(0)
        if n.type == "assignment_expression":
            out += _java_assign(n, src)
            continue
        if n.type in ("lambda_expression", "class_body"):
            continue
        stack.extend(n.named_children)
    return out


def java_stmts(node, src, flags):
    out = []
    if node is None:
        return out
    kids = node.named_children if node.type in ("block", "constructor_body", "switch_block_statement_group",
                                                "switch_block", "program") else [node]
    for s in kids:
        t = s.type
        for n in _walk_ts(s):
            if n.type == "class_body":
                flags.unsupported.add("anonymous-class")
            if n.type == "lambda_expression":
                b = n.child_by_field_name("body")
                if b is not None and b.type == "block":
                    flags.unsupported.add("block-lambda")
        if t == "local_variable_declaration":
            for d in s.named_children:
                if d.type == "variable_declarator":
                    nm, val = d.child_by_field_name("name"), d.child_by_field_name("value")
                    if nm is not None and val is not None:
                        out += _java_nested(val, src) + ([] if val.type != "assignment_expression" else _java_assign(val, src))
                        out.append(S("assign", [_t(nm, src)], java_expr(val, src), False))
        elif t == "expression_statement":
            ex = s.named_children[0] if s.named_children else None
            if ex is not None:
                out += _java_expr_stmt(ex, src)
        elif t == "return_statement":
            val = s.named_children[0] if s.named_children else None
            out += _java_nested(val, src) if val is not None else []
            out.append(S("return", java_expr(val, src) if val is not None else None))
        elif t == "throw_statement":
            out.append(S("raise", java_expr(s.named_children[0] if s.named_children else None, src)))
        elif t == "if_statement":
            cond = s.child_by_field_name("condition")
            out += _java_nested(cond, src)
            out.append(S("if", java_expr(cond, src), java_stmts(s.child_by_field_name("consequence"), src, flags),
                         java_stmts(s.child_by_field_name("alternative"), src, flags)))
        elif t == "for_statement":
            header = []
            for init in s.children_by_field_name("init"):
                header += java_stmts(init, src, flags) if init.type == "local_variable_declaration" else _java_expr_stmt(init, src)
            cond = s.child_by_field_name("condition")
            body = java_stmts(s.child_by_field_name("body"), src, flags)
            for upd in s.children_by_field_name("update"):
                body += _java_expr_stmt(upd, src)
            out += header
            out.append(S("loop", _java_nested(cond, src), java_expr(cond, src), body))
        elif t == "enhanced_for_statement":
            nm, val = s.child_by_field_name("name"), s.child_by_field_name("value")
            hdr = [S("assign", [_t(nm, src)], java_expr(val, src), False)] if nm is not None else []
            out.append(S("loop", hdr, java_expr(val, src), java_stmts(s.child_by_field_name("body"), src, flags)))
        elif t in ("while_statement", "do_statement"):
            cond = s.child_by_field_name("condition")
            out += _java_nested(cond, src)
            out.append(S("loop", _java_nested(cond, src), java_expr(cond, src),
                         java_stmts(s.child_by_field_name("body"), src, flags)))
        elif t in ("try_statement", "try_with_resources_statement"):
            body = java_stmts(s.child_by_field_name("body"), src, flags)
            handlers, final = [], []
            for ch in s.named_children:
                if ch.type == "catch_clause":
                    handlers.append(java_stmts(ch.child_by_field_name("body"), src, flags))
                elif ch.type == "finally_clause":
                    final = java_stmts(ch.named_children[-1] if ch.named_children else None, src, flags)
            out.append(S("try", body, handlers, final))
        elif t == "block":
            out += java_stmts(s, src, flags)
        elif t in ("switch_expression", "switch_statement"):
            cond = java_expr(s.child_by_field_name("condition"), src)
            body = s.child_by_field_name("body")
            branches = [java_stmts(g, src, flags) for g in (body.named_children if body is not None else [])]
            st = S("if", cond, branches[-1] if branches else [], [])
            for b in reversed(branches[:-1]):
                st = S("if", cond, b, [st])
            out.append(st)
        elif t == "synchronized_statement":
            out += java_stmts(s.child_by_field_name("body") or (s.named_children[-1] if s.named_children else None), src, flags)
        elif t == "labeled_statement":
            out += java_stmts(s.named_children[-1] if s.named_children else None, src, flags)
        elif t in ("break_statement", "continue_statement"):
            out.append(S("jump"))
    return out


def _walk_ts(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(n.children)


def _java_expr_stmt(ex, src):
    out = []
    t = ex.type
    if t == "assignment_expression":
        out += _java_assign(ex, src)
    elif t == "update_expression":
        for ch in ex.named_children:
            name, _ = _java_target(ch, src)
            if name:
                out.append(S("assign", [name], Expr(), True))
    elif t == "method_invocation":
        out += _java_nested(ex, src)
        e = java_expr(ex, src)
        out.append(S("expr", e))
        nm = ex.child_by_field_name("name")
        callee = _t(nm, src) if nm is not None else ""
        obj = ex.child_by_field_name("object")
        if callee in MUTATORS and obj is not None and obj.type in ("identifier", "field_access"):
            out.append(S("assign", [_t(obj, src).replace(" ", "")], e, True))
        if callee == "arraycopy":
            args = ex.child_by_field_name("arguments")
            al = args.named_children if args is not None else []
            if len(al) >= 3:
                dst, _ = _java_target(al[2], src)
                if dst:
                    out.append(S("assign", [dst], java_expr(al[0], src), True))
    else:
        out += _java_nested(ex, src)
        out.append(S("expr", java_expr(ex, src)))
    return out


def java_ir(method_src, parser):
    wsrc = ("class __W {\n" + method_src + "\n}").encode()
    root = parser.parse(wsrc).root_node
    mdef = next((n for n in _walk_ts(root) if n.type in ("method_declaration", "constructor_declaration")), None)
    if mdef is None:
        return None
    params = []
    pn = mdef.child_by_field_name("parameters")
    if pn is not None:
        for p in pn.named_children:
            if p.type in ("formal_parameter", "spread_parameter"):
                ident = p.child_by_field_name("name")
                if ident is None:
                    ids = [c for c in p.named_children if c.type in ("identifier", "variable_declarator")]
                    ident = ids[-1] if ids else None
                if ident is not None:
                    params.append(_t(ident, wsrc).split("[")[0].strip())
    flags = _Flags()
    stmts = java_stmts(mdef.child_by_field_name("body"), wsrc, flags)
    return params, stmts, sorted(flags.unsupported), [], java_fragment(mdef, wsrc)


# ----------------------------------------------------------------------------------------------- supported fragment
# round 4: FALSE is emitted only for functions inside an explicit fragment; anything outside -> UNVERIFIABLE.
FRESH_CALLS = {"list", "dict", "set", "tuple", "str", "int", "float", "bool", "sorted", "object", "deque",
               "defaultdict", "OrderedDict", "Counter", "bytearray", "frozenset", "len", "sum", "range", "enumerate",
               "zip", "map", "filter", "max", "min", "abs", "repr", "format", "join", "split", "lower", "upper",
               "strip", "replace"}


def _fresh_py(v):
    if isinstance(v, (ast.Constant, ast.List, ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp,
                      ast.GeneratorExp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.JoinedStr, ast.Lambda)):
        return True
    if isinstance(v, ast.Tuple):
        return all(_fresh_py(x) for x in v.elts)
    if isinstance(v, ast.Call):
        f = v.func
        nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        return bool(nm) and (nm in FRESH_CALLS or nm[:1].isupper())
    return False


def py_fragment(fn):
    """Reasons why `fn` is outside the data-flow fragment in which a FALSE (no path) verdict is trusted."""
    why = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Try,)) or n.__class__.__name__ == "TryStar":
            why.add("try")
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            why.add("with")
        elif n.__class__.__name__ == "Match":
            why.add("match")
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            why.add("global")
        elif isinstance(n, ast.Assert):
            why.add("assert")
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
            why.add("nested-def")
        elif isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for m in ast.walk(n):
                if (isinstance(m, ast.Call) and isinstance(m.func, ast.Attribute) and m.func.attr in MUTATORS) \
                        or isinstance(m, ast.NamedExpr):
                    why.add("expression-effect")

    def exits(stmts, ctx):
        for st in stmts:
            if isinstance(st, (ast.Return, ast.Raise, ast.Break, ast.Continue)) and ctx == "deep":
                why.add("nested-exit")
            if isinstance(st, ast.If):
                inner = "topif" if ctx == "top" else "deep"
                exits(st.body, inner)
                elif_ = len(st.orelse) == 1 and isinstance(st.orelse[0], ast.If)
                exits(st.orelse, "deep" if (elif_ or ctx != "top") else inner)
            elif isinstance(st, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)) or \
                    st.__class__.__name__ in ("TryStar", "Match"):
                for field in ("body", "orelse", "finalbody"):
                    exits(getattr(st, field, []) or [], "deep")
                for h in getattr(st, "handlers", []) or []:
                    exits(h.body, "deep")
                for c in getattr(st, "cases", []) or []:
                    exits(c.body, "deep")
    exits(fn.body, "top")

    nonfresh, mutated = set(), set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and not _fresh_py(n.value):
                    nonfresh.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    vals = n.value.elts if isinstance(n.value, (ast.Tuple, ast.List)) and len(n.value.elts) == len(t.elts) else None
                    for i, el in enumerate(t.elts):
                        if isinstance(el, ast.Name) and (vals is None or not _fresh_py(vals[i])):
                            nonfresh.add(el.id)
                if isinstance(t, (ast.Subscript, ast.Attribute)):
                    b = t.value
                    while isinstance(b, (ast.Subscript, ast.Attribute)):
                        b = b.value
                    if isinstance(b, ast.Name):
                        mutated.add(b.id)
        elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
            for m in ast.walk(n.target):
                if isinstance(m, ast.Name):
                    nonfresh.add(m.id)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for it in n.items:
                if it.optional_vars is not None:
                    for m in ast.walk(it.optional_vars):
                        if isinstance(m, ast.Name):
                            nonfresh.add(m.id)
        elif isinstance(n, ast.AugAssign):
            b = n.target
            while isinstance(b, (ast.Subscript, ast.Attribute)):
                b = b.value
            if isinstance(b, ast.Name):
                mutated.add(b.id)              # v6: `y += [a]` / `y |= {a}` may mutate in place
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and not (
                isinstance(n.func.value, ast.Name) and n.func.attr in PURE):
            # v6: any non-pure method call may mutate its receiver (as for Java)
            b = n.func.value
            while isinstance(b, (ast.Subscript, ast.Attribute)):
                b = b.value
            if isinstance(b, ast.Name):
                mutated.add(b.id)
    if nonfresh & mutated:
        why.add("alias")
    return sorted(why)


def java_fragment(mdef, src):
    why = set()
    body = mdef.child_by_field_name("body")
    nonfresh, mutated = set(), set()
    for n in _walk_ts(mdef):
        t = n.type
        if t in ("try_statement", "try_with_resources_statement"):
            why.add("try")
        elif t in ("switch_expression", "switch_statement"):
            why.add("switch")
        elif t == "lambda_expression":
            b = n.child_by_field_name("body")
            if b is not None and (b.type == "block" or any(m.type == "method_invocation" for m in _walk_ts(b))):
                why.add("expression-effect")
        elif t == "class_body":
            why.add("anonymous-class")
        elif t in ("return_statement", "throw_statement", "break_statement", "continue_statement"):
            # allowed: directly in the method body, or directly in the branch of a top-level if
            p, ifs, bad = n.parent, 0, False
            bk = (body.start_byte, body.end_byte) if body is not None else None
            while p is not None and (p.start_byte, p.end_byte, p.type) != (bk[0], bk[1], "block"):
                if p.type == "if_statement":
                    ifs += 1
                elif p.type not in ("block",):
                    bad = True
                p = p.parent
            if bad or ifs > 1:
                why.add("nested-exit")
        elif t == "variable_declarator":
            nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
            if nm is not None and val is not None and val.type in ("identifier", "field_access", "array_access",
                                                                    "method_invocation", "cast_expression",
                                                                    "ternary_expression"):
                nonfresh.add(_t(nm, src))
        elif t == "assignment_expression":
            left, right = n.child_by_field_name("left"), n.child_by_field_name("right")
            if left is not None and right is not None:
                if left.type == "identifier" and right.type in ("identifier", "field_access", "array_access",
                                                                "method_invocation", "cast_expression"):
                    nonfresh.add(_t(left, src))
                if left.type in ("array_access", "field_access"):
                    b = left
                    while b.type in ("array_access", "field_access"):
                        b = b.child_by_field_name("array") or b.child_by_field_name("object")
                        if b is None:
                            break
                    if b is not None and b.type == "identifier":
                        mutated.add(_t(b, src))
        elif t == "enhanced_for_statement":
            nm = n.child_by_field_name("name")
            if nm is not None:
                nonfresh.add(_t(nm, src))
        elif t == "method_invocation":
            obj = n.child_by_field_name("object")
            if obj is not None and obj.type == "identifier":
                mutated.add(_t(obj, src))          # Java: any method may mutate its receiver
    if nonfresh & mutated:
        why.add("alias")
    return sorted(why)


# ----------------------------------------------------------------------------------------------- analysis
class Graph:
    def __init__(self, cons=False):
        self.cons = cons
        self.data, self.ctrl, self.keys = {}, {}, {}
        self.k = 0
        self.defs, self.calls = {}, {}
        self.rets, self.raises, self.params = [], [], []
        self.jumps = []
        self.recv = {}

    def node(self, prefix, key):
        n = self.keys.get(key)
        if n is None:
            self.k += 1
            n = f"{prefix}@{self.k}"
            self.keys[key] = n
            self.data[n] = set()
            self.ctrl[n] = set()
        return n

    def to_json(self, unsupported, nested):
        return {"data": {n: sorted(p) for n, p in self.data.items() if p},
                "ctrl": {n: sorted(p) for n, p in self.ctrl.items() if p},
                "defs": {v: ns for v, ns in self.defs.items()}, "calls": self.calls, "rets": self.rets,
                "raises": self.raises, "params": self.params, "unsupported": unsupported, "nested": nested,
                "recv": dict(sorted(self.recv.items()))}


def _resolve_path(g, path, state):
    """Definitions a field path reads: its own if defined, else the nearest defined prefix (base object)."""
    deps = set()
    if path in state:
        return set(state[path])
    deps.add(_free_named(g, path))
    p = path
    while "." in p:
        p = p.rsplit(".", 1)[0]
        if p in state:
            return deps | set(state[p])
    root = path.split(".")[0]
    return deps | ({_free_named(g, root)} if root not in state else set(state[root]))


def _free_named(g, name):
    n = "free:" + name
    if n not in g.data:
        g.data[n] = set()
        g.ctrl[n] = set()
    g.defs.setdefault(name, [])
    if n not in g.defs[name]:
        g.defs[name].append(n)
    return n


def _eval(g, e, state, ctrl):
    deps = set()
    if e is None:
        return deps
    for v in sorted(e.reads):
        deps |= set(state[v]) if v in state else {_free_named(g, v)}
        for k in sorted(state):              # reading a whole object also reads its defined fields
            if k.startswith(v + "."):
                deps |= set(state[k])
    for path, base in sorted(e.attrs):
        deps |= _resolve_path(g, path, state)
    for callee, args, recv in e.calls:
        c = g.node(f"c:{callee}", ("c", id(args)))
        if c not in g.calls.setdefault(callee, []):
            g.calls[callee].append(c)
        if recv:
            g.recv[c] = recv
        g.data[c] |= _eval(g, args, state, ctrl)
        g.ctrl[c] |= ctrl
        deps.add(c)
    return deps


PURE = {"len", "str", "int", "float", "bool", "isinstance", "range", "enumerate", "zip", "sorted", "abs", "repr",
        "type", "min", "max", "sum", "round", "ord", "chr", "hash", "id", "print", "format", "any", "all", "list",
        "tuple", "set", "dict", "frozenset", "map", "filter", "reversed", "divmod", "pow", "lower", "upper", "strip",
        "split", "join", "replace", "startswith", "endswith", "keys", "values", "items", "count", "index", "find",
        "isdigit", "isalpha", "get", "equals", "length", "size", "charAt", "toString", "hashCode", "contains",
        "isEmpty", "valueOf", "parseInt", "substring", "indexOf", "getClass", "compareTo"}


def _define(g, key, targets, deps, weak, state, ctrl):
    state = dict(state)
    for t in targets:
        d = g.node(f"d:{t}", ("d", id(key) if not isinstance(key, tuple) else (id(key[0]),) + key[1:], t))
        if d not in g.defs.setdefault(t, []):
            g.defs[t].append(d)
        g.data[d] |= deps
        if weak:
            g.data[d] |= state.get(t, set()) if t in state else {_free_named(g, t)}
        else:
            for k in [k for k in state if k.startswith(t + ".")]:
                del state[k]                 # rebinding an object kills its fields (round 4)
        g.ctrl[d] |= ctrl
        state[t] = {d}
    return state


def _call_arg_vars(e, out):
    for callee, args, recv in e.calls:
        if callee not in PURE:
            if recv:
                out.add(recv.split(".")[0])
            out |= {v for v in args.reads}
            out |= {p.split(".")[0] for p, _ in args.attrs}
        _call_arg_vars(args, out)
    return out


def _call_effects(g, s, e, deps, state, ctrl):
    """Conservative mode: every variable passed to (or receiving) a non-pure call may be updated in place by
    that call with everything the statement reads (library / higher-order / lambda side effects)."""
    vs = sorted(_call_arg_vars(e, set()))
    if not vs:
        return state
    return _define(g, (s, "eff", 0), vs, deps, True, state, ctrl)


def _copy(st):
    return None if st is None else {k: set(v) for k, v in st.items()}


def _join(*states):
    out = None
    for s in states:
        if s is None:
            continue
        if out is None:
            out = _copy(s)
        else:
            for k, v in s.items():
                out.setdefault(k, set()).update(v)
    return out


def _run(g, stmts, state, ctrl, collect=None):
    """Abstract execution; returns the out-state (None if every path left the block)."""
    ctrl = frozenset(ctrl)
    for s in stmts:
        if state is None:
            return None
        kind = s[0]
        if kind == "assign":
            _, targets, e, weak = s
            deps = _eval(g, e, state, ctrl)
            state = _define(g, s, targets, deps, weak, state, ctrl)
            if g.cons:
                state = _call_effects(g, s, e, deps, state, ctrl)
        elif kind == "multi":
            evals = [(tg, _eval(g, e, state, ctrl)) for tg, e in s[1]]
            for i, (tg, deps) in enumerate(evals):
                strong = [n for n, w in tg if not w]
                weak_ = [n for n, w in tg if w]
                if strong:
                    state = _define(g, (s, i, 0), strong, deps, False, state, ctrl)
                if weak_:
                    state = _define(g, (s, i, 1), weak_, deps, True, state, ctrl)
        elif kind == "expr":
            deps = _eval(g, s[1], state, ctrl)
            if g.cons:
                state = _call_effects(g, s, s[1], deps, state, ctrl)
        elif kind in ("return", "raise"):
            deps = _eval(g, s[1], state, ctrl) if s[1] is not None else set()
            r = g.node("r" if kind == "return" else "x", ("r", id(s)))
            lst = g.rets if kind == "return" else g.raises
            if r not in lst:
                lst.append(r)
            g.data[r] |= deps
            g.ctrl[r] |= ctrl
            state = None
        elif kind == "jump":
            if g.jumps:
                g.jumps[-1].append(_copy(state))
            state = None
        elif kind == "if":
            cnode = g.node("cond", ("cond", id(s)))
            g.data[cnode] |= _eval(g, s[1], state, ctrl)
            g.ctrl[cnode] |= ctrl
            st1 = _run(g, s[2], _copy(state), ctrl | {cnode})
            st2 = _run(g, s[3], _copy(state), ctrl | {cnode})
            if (st1 is None) != (st2 is None):
                ctrl = ctrl | {cnode}          # an early exit guards everything after the if
            state = _join(st1, st2)
        elif kind == "loop":
            _, header, cond, body = s
            cnode = g.node("cond", ("cond", id(s)))
            entry = _copy(state)
            exits = []
            for _ in range(200):
                h = _run(g, header, _copy(entry), ctrl)
                if h is None:
                    break
                g.data[cnode] |= _eval(g, cond, h, ctrl)
                g.jumps.append([])
                after = _run(g, body, _copy(h), ctrl | {cnode})
                jumped = g.jumps.pop()
                exits = jumped
                new_entry = _join(entry, after, *jumped)
                if new_entry == entry:
                    break
                entry = new_entry
            state = _join(state, entry, *exits)
        elif kind == "try":
            _, body, handlers, final = s
            seen = [_copy(state)]
            after_body = _run(g, body, _copy(state), ctrl, collect=seen)
            hstate = _join(*seen)
            outs = after_body
            for h in handlers:
                outs = _join(outs, _run(g, h, _copy(hstate), ctrl))
            fin = _run(g, final, _copy(outs if outs is not None else hstate), ctrl)
            state = fin if outs is not None else None
        if collect is not None and state is not None:
            collect.append(_copy(state))
    return state


def analyse(ir, cons=False):
    """cons=True builds the CONSERVATIVE graph used to gate FALSE (every non-pure call may update its arguments)."""
    if ir is None:
        return None
    params, stmts, unsupported, nested, outside = ir
    g = Graph(cons)
    g.params = params
    state = {}
    for p in params:
        n = f"p:{p}"
        g.data[n] = set()
        g.ctrl[n] = set()
        g.defs.setdefault(p, []).append(n)
        state[p] = {n}
    _run(g, stmts, state, frozenset())
    out = g.to_json(unsupported, nested)
    out["outside"] = outside
    return out


def reach(graph, sources, targets, allow_ctrl):
    data, ctrl = graph["data"], graph["ctrl"]
    tgt, src = set(targets), set(sources)
    seen, stack = set(), list(tgt)
    while stack:
        n = stack.pop()
        if n in src:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(data.get(n, ()))
        if allow_ctrl:
            stack.extend(ctrl.get(n, ()))
    return False
