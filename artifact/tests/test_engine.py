"""Regression test for the def-use engine: the round-2 reviewer's (R3) adversarial cases, with the outcome the
round-3 engine is meant to give. Run: python3 tests/test_engine.py  (exit code 1 on any mismatch).
Reviewer labels mapped as follows: false/unv -> false (a parameter source means its incoming value);
true(heap) -> true (field store weak-updates the base object); true(alias), true(closure) -> unverifiable
(unmodelled constructs never yield FALSE).
"""
import os
import sys
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import facts  # noqa: E402
from discharge import discharge_dataflow  # noqa: E402

FAIL = []


def F(src, lang="python"):
    return facts.facts_for({"source": textwrap.dedent(src), "lang": lang, "fid": "t", "context_imports": ""})


def T(name, src, s, t, expect, lang="python"):
    oc, ev = discharge_dataflow({"slots": {"source": s, "sink": t}, "text": ""}, F(src, lang))[:2]
    ok = oc in expect if isinstance(expect, tuple) else oc == expect
    if not ok:
        FAIL.append(name)
    print(f"{'OK ' if ok else 'BUG'} {name:48s} {s}->{t}: got {oc:12s} want {str(expect):12s} | {ev[:70]}")

# --- sanity
T("kill: x=a;x=0;return x+b", """
def f(a, b):
    x = a
    x = 0
    return x + b
""", "a", "return", "false")
T("kill: b survives", """
def f(a, b):
    x = a
    x = 0
    return x + b
""", "b", "return", "true")
T("control only: if a: return 1", """
def f(a):
    if a:
        return 1
    return 0
""", "a", "return", "consistent")
# --- adversarial
T("param reassigned before use (param value killed)", """
def f(a, b):
    a = b
    return a
""", "a", "return", "false")
T("loop-carried chain of length 5", """
def f(p, n):
    b = c = d = e = g = 0
    for i in range(n):
        g = e
        e = d
        d = c
        c = b
        b = p
    return g
""", "p", "return", "true")
T("loop-carried chain of length 3 (within bound)", """
def f(p, n):
    b = c = d = 0
    for i in range(n):
        d = c
        c = b
        b = p
    return d
""", "p", "return", "true")
T("walrus definition", """
def f(s, pat):
    if (m := pat.match(s)):
        return m.group(1)
    return None
""", "s", "return", "true")
T("try: def in middle of try reaches handler", """
def f(a):
    try:
        x = a
        y = int(x)
        x = 0
    except ValueError:
        return x
    return y
""", "a", "return", "true")
T("field write then return object", """
def f(a):
    o = Obj()
    o.value = a
    return o
""", "a", "return", "true")
T("subscript write then return container", """
def f(a):
    o = {}
    o['value'] = a
    return o
""", "a", "return", "true")
T("alias: append through alias", """
def f(a):
    out = []
    lst = out
    lst.append(a)
    return out
""", "a", "return", "unverifiable")
T("early-return guard: control dep of later return", """
def f(a, b):
    if a:
        return None
    y = b
    return y
""", "a", "y", "consistent")
T("break inside loop", """
def f(xs, t):
    r = None
    for x in xs:
        if x == t:
            r = x
            break
    return r
""", "xs", "return", "true")
T("nonlocal/closure write", """
def f(a):
    acc = []
    def g():
        acc.append(a)
    g()
    return acc
""", "a", "return", "unverifiable")
T("conjunction universal: a and b -> r (b unused)", """
def f(a, b):
    r = a + 1
    return r
""", "a, b", "r", "false")
T("augassign weak", """
def f(a, b):
    s = a
    s += b
    return s
""", "a", "return", "true")
T("with-as", """
def f(path):
    with open(path) as fh:
        data = fh.read()
    return data
""", "path", "data", "true")
T("while cond control", """
def f(n):
    i = 0
    while i < n:
        i = i + 1
    return i
""", "n", "return", "consistent")
T("global/self attr strong update kills", """
def f(self, a, b):
    self.x = a
    self.x = b
    return self.x
""", "a", "return", "false")
T("comprehension", """
def f(xs, k):
    return [x * k for x in xs if x]
""", "k", "return", "true")
T("for-else / generator yield", """
def f(xs):
    for x in xs:
        yield x * 2
""", "xs", "return", "true")
T("match capture (py3.10)", """
def f(cmd):
    match cmd:
        case [a, b]:
            return b
    return None
""", "cmd", "return", "true")
T("tuple unpack swap", """
def f(a, b):
    a, b = b, a
    return a
""", "b", "return", "true")
T("del then reassign", """
def f(a, b):
    x = a
    if b:
        x = b
    return x
""", "a", "return", "true")
# Java
T("java kill", """
int f(int a, int b) {
    int x = a;
    x = 0;
    return x + b;
}""", "a", "return", "false", "java")
T("java assignment inside while condition", """
List<String> f(BufferedReader in) {
    List<String> out = new ArrayList<>();
    String line;
    while ((line = in.readLine()) != null) {
        out.add(line);
    }
    return out;
}""", "in", "out", "true", "java")
T("java for loop chain", """
int f(int[] a) {
    int s = 0;
    for (int i = 0; i < a.length; i++) {
        s += a[i];
    }
    return s;
}""", "a", "return", "true", "java")
T("java ternary", """
int f(int a, int b) {
    int x = a > 0 ? b : 0;
    return x;
}""", "b", "return", "true", "java")
T("java field write this.x then return this.x", """
int f(int a) {
    this.x = a;
    return this.x;
}""", "a", "return", "true", "java")
T("java field accessed unqualified", """
int f(int a) {
    count = a;
    return count;
}""", "a", "return", "true", "java")
T("java try-catch middle def", """
int f(String a) {
    int x = 0;
    try {
        x = Integer.parseInt(a);
        x = 5;
    } catch (NumberFormatException e) {
        return x;
    }
    return 0;
}""", "a", "return", "true", "java")
T("java chained assign a=b=c", """
int f(int c) {
    int a, b;
    a = b = c;
    return b;
}""", "c", "return", "true", "java")
T("java lambda param", """
List<Integer> f(List<Integer> xs, int k) {
    return xs.stream().map(x -> x * k).collect(Collectors.toList());
}""", "k", "return", "true", "java")
T("java compound assignment in condition do-while", """
int f(int n) {
    int i = 0;
    do { i++; } while (i < n);
    return i;
}""", "n", "return", "consistent", "java")

# --- round-2 reviewer, second batch
T("py try: def in middle of try reaches handler", """
def f(a):
    try:
        x = a
        int(x)
        x = 0
    except ValueError:
        return x
    return 1
""", "a", "return", "true")
T("java readLine in while cond (renamed)", """
List<String> f(BufferedReader rd) {
    List<String> out = new ArrayList<>();
    String line;
    while ((line = rd.readLine()) != null) {
        out.add(line);
    }
    return out;
}""", "rd", "out", "true", "java")
T("guard raise then use", """
def f(key, d):
    if key is None:
        raise ValueError()
    v = d[key]
    return v
""", "key", "v", "true")
T("guard raise: other var", """
def f(flag, d):
    if not flag:
        raise ValueError()
    v = d
    return v
""", "flag", "v", "consistent")
T("continue guard in loop", """
def f(xs):
    out = []
    for x in xs:
        if x < 0:
            continue
        out.append(1)
    return out
""", "xs", "out", "consistent")
T("java guard throw", """
int f(int a, int b) {
    if (a < 0) { throw new IllegalArgumentException(); }
    int y = b;
    return y;
}""", "a", "y", "consistent", "java")
T("java keyword-name param 'is'", """
int f(InputStream is) {
    int n = is.read();
    return n;
}""", "is", "n", "true", "java")

# --- round-3 audit of the corpus FALSE verdicts (minimal reproductions)
T("chained assignment stores the same object (A025)", """
def f(self, proxy):
    manager = self.pm[proxy] = make(proxy)
    return manager
""", "manager", "self.pm", "true")
T("return self includes a mutated field (A103)", """
def f(self, s):
    self._snips.append(s)
    return self
""", "_snips", "return", "true")
T("local function object flows into its call (A127)", """
def f(self, k, v):
    ins = self._insert
    for x in v:
        ins(k, x)
""", "self._insert", "ins", "true")
T("value fed to a method call on the sink object (B002)", """
def f(lst):
    ans, template = [], "the number i"
    for s in lst:
        n = len(s)
        ans.append(template.replace("i", str(n)))
    return ans
""", "n", "template", "consistent")


def R(name, src, text, expect):
    from discharge import discharge_structural
    claim = {"subtype": "returns", "slots": {"returns_value": True}, "text": text}
    oc = discharge_structural(claim, F(src))[0]
    if oc != expect:
        FAIL.append(name)
    print(f"{'OK ' if oc == expect else 'BUG'} {name:48s} got {oc:12s} want {expect}")


R("returns claim about a nested helper (B003)", """
def get(word):
    def is_vowel(c):
        return c in "aeiou"
    for i in range(len(word)):
        if is_vowel(word[i]):
            return word[i]
    return ""
""", "`is_vowel` returns True for vowels", "unverifiable")
R("returns content checked", """
def f(a, b):
    r = a * 2
    return r
""", "It returns `r`", "true")


# --- round-3 reviewer (R3) adversarial cases, reconstructed from the review table. A tuple of outcomes means
# "any sound outcome": a FALSE is never acceptable where a path exists.
NF = ("true", "consistent", "unverifiable")      # anything but FALSE
NFC = ("consistent", "unverifiable")
T("C1 nested guard", """
def f(a, b, d):
    if a:
        if b:
            return None
    v = d
    return v
""", "a", "v", NFC)
T("C2 elif guard", """
def f(a, b, d):
    if a:
        return 1
    elif b:
        return 2
    v = d
    return v
""", "b", "v", NFC)
T("C3 raise in loop guards later code", """
def f(xs, t):
    for x in xs:
        if x == t:
            raise ValueError()
    found = 0
    return found
""", "t", "found", NFC)
T("C4 assert guard", """
def f(a, d):
    assert a > 0
    v = d
    return v
""", "a", "v", NFC)
T("C5 return inside try", """
def f(a, d):
    try:
        if a:
            return 0
    except Exception:
        pass
    v = d
    return v
""", "a", "v", NFC)
T("T1 def in nested if in try reaches handler", """
def f(a, c):
    x = 0
    try:
        if c:
            x = a
        int(x)
    except ValueError:
        return x
    return 1
""", "a", "return", ("true", "unverifiable"))
T("T2 def in loop in try reaches handler", """
def f(a, xs):
    x = 0
    try:
        for i in xs:
            x = a
            int(i)
    except ValueError:
        return x
    return 1
""", "a", "return", ("true", "unverifiable"))
T("A1 loop-variable alias", """
def f(rows, a):
    for row in rows:
        row.append(a)
    return rows
""", "a", "return", ("true", "unverifiable"))
T("A2 element alias", """
def f(grid, i, a):
    row = grid[i]
    row[0] = a
    return grid
""", "a", "return", ("true", "unverifiable"))
T("A3 attribute alias", """
def f(self, a):
    lst = self.items
    lst.append(a)
    return self.items
""", "a", "return", ("true", "unverifiable"))
T("A4 tuple alias", """
def f(out, a):
    lst, n = out, 0
    lst.append(a)
    return out
""", "a", "return", ("true", "unverifiable"))
T("A5 setdefault alias", """
def f(d, k, v):
    lst = d.setdefault(k, [])
    lst.append(v)
    return d
""", "v", "return", ("true", "unverifiable"))
T("A6 closure subscript write", """
def f(a):
    box = [None]
    def put(v):
        box[0] = v
    put(a)
    return box
""", "a", "return", ("true", "unverifiable"))
T("A7 mutator in comprehension", """
def f(xs):
    out = []
    [out.append(x) for x in xs]
    return out
""", "xs", "return", ("true", "unverifiable"))
T("A8 library mutation heappush", """
def f(h, a):
    heapq.heappush(h, a)
    return h
""", "a", "return", ("true", "unverifiable"))
T("A9 rebinding kills fields", """
def f(a, b):
    o = Box(0)
    o.val = a
    o = Box(b)
    return o
""", "a", "return", ("false", "unverifiable"))
T("A10 yield expression", """
def f(v):
    x = yield v
    return x
""", "v", "return", "true")
T("A11 comprehension variable shadows", """
def f(a, xs):
    x = a
    ys = [x for x in xs]
    return ys
""", "a", "return", ("false", "unverifiable"))
T("L1 10-step chain in nested loops", """
def f(p, n):
    a = b = c = d = e = g = h = i = j = k = 0
    for u in range(n):
        for w in range(n):
            k = j
            j = i
            i = h
            h = g
            g = e
            e = d
            d = c
            c = b
            b = a
            a = p
    return k
""", "p", "return", "true")
T("L2 while True with break", """
def f(it):
    while True:
        x = next(it)
        if x:
            break
    return x
""", "it", "return", ("true", "unverifiable"))
T("L3 try/finally def reaches after", """
def f(a):
    try:
        x = a
    finally:
        y = 1
    return x
""", "a", "return", ("true", "unverifiable"))
T("J1 arrow switch", """
int f(int k, int a) {
    int r = 0;
    switch (k) { case 1 -> r = a; default -> r = 0; }
    return r;
}""", "a", "return", ("true", "unverifiable"), "java")
T("J2 classic switch with break", """
int f(int k, int a) {
    int r = 0;
    switch (k) { case 1: r = a; break; default: r = 0; }
    return r;
}""", "a", "return", ("true", "unverifiable"), "java")
T("J3 switch break inside loop", """
int f(int[] ks, int a) {
    int r = 0;
    for (int k : ks) { switch (k) { case 1: r = a; break; default: break; } }
    return r;
}""", "a", "return", ("true", "unverifiable"), "java")
T("J4 Java alias", """
List<Integer> f(List<Integer> out, int a) {
    List<Integer> l = out;
    l.add(a);
    return out;
}""", "a", "return", ("true", "unverifiable"), "java")
T("J5 Arrays.fill", """
int[] f(int[] arr, int v) {
    Arrays.fill(arr, v);
    return arr;
}""", "v", "return", ("true", "unverifiable"), "java")
T("J6 forEach lambda", """
List<Integer> f(List<Integer> xs, List<Integer> out) {
    xs.forEach(x -> out.add(x));
    return out;
}""", "xs", "return", ("true", "unverifiable"), "java")
T("J7 try-with-resources", """
String f(String p) throws IOException {
    try (BufferedReader r = new BufferedReader(new FileReader(p))) {
        return r.readLine();
    }
}""", "p", "return", ("true", "unverifiable"), "java")
T("J8 nested Java guard", """
int f(boolean a, boolean b, int c) {
    if (a) { if (b) { return 0; } }
    int y = c;
    return y;
}""", "a", "y", NFC, "java")
T("J9 Java element alias via enhanced for", """
int[][] f(int[][] rows, int a) {
    for (int[] row : rows) { row[0] = a; }
    return rows;
}""", "a", "return", ("true", "unverifiable"), "java")


def RT(name, src, text, allowed):
    from discharge import discharge_structural
    oc = discharge_structural({"subtype": "returns", "slots": {"returns_value": True}, "text": text}, F(src))[0]
    ok = oc in allowed
    if not ok:
        FAIL.append(name)
    print(f"{'OK ' if ok else 'BUG'} {name:48s} got {oc:12s} want {allowed}")


RT("R1 returns x or raises", """
def f(x):
    if x < 0:
        raise ValueError()
    return x
""", "Returns `x` unchanged, or raises `ValueError` when `x` is negative", ("true", "consistent"))
RT("R2 returns result after logging", """
def f(a):
    result = a * 2
    logger.info(result)
    return result
""", "returns `result` after logging it with `logger`", ("true", "consistent"))
RT("R3 returns a list of keys", """
def f(d):
    ks = [k for k in d]
    tmp = list(d)
    return ks
""", "returns a `list` of the remaining keys of `d`", ("true", "consistent", "unverifiable"))
RT("R4 returns string produced by _norm", """
def f(s):
    return _norm(s)
""", "Returns the normalised string produced by `_norm`", ("true",))


def P(name, src, cls, text, allowed, fname="f"):
    from discharge import membership_check
    r = membership_check({"text": text}, {"cls": cls, "name": fname, "repo": "proj"})
    oc = r[0] if r else "none"
    ok = oc in allowed
    if not ok:
        FAIL.append(name)
    print(f"{'OK ' if ok else 'BUG'} {name:48s} got {oc:12s} want {allowed}")


P("P1 creates instances of another class", "", None, "The `f` function creates instances of the `Config` class.", ("none", "consistent"))
P("P2 delegates to helper in another class", "", "Parser", "The `f` method delegates to a helper defined in the `Utils` class.", ("none", "consistent"))
P("P3 overrides method of base class", "", "Monitor", "The `f` method overrides the method of the `Thread` class.", ("none", "consistent"))
P("P4 pure, right class", "", "Parser", "The `f` method is a method of the `Parser` class.", ("true",))
P("P5 pure, wrong class", "", "Parser", "The `f` method is a method of the `Lexer` class.", ("false",))
P("P6 pure, wrong library", "", "Parser", "The `f` method is a method of the `Parser` class in the `numpy` library.", ("consistent",))


def PQ(name, call, pre, text, allowed):
    from probe import evaluate
    rec = {"exec_source": "def f(xs):\n    return max(xs) if xs else None\n", "name": "f"}
    p = {"concreteness": "instantiated", "call": call, "expect": "3", "expect_raises": None, "precondition": pre}
    oc = evaluate(rec, p, text)[0]
    ok = oc in allowed
    if not ok:
        FAIL.append(name)
    print(f"{'OK ' if ok else 'BUG'} {name:48s} got {oc:12s} want {allowed}")


PQ("Q2 conditional claim, pre 1 == 1", "f([1, 2, 3])", "1 == 1", "If the list is non-empty it returns the maximum.", ("unverifiable",))
PQ("Q3 conditional claim, pre (True)", "f([1, 2, 3])", "(True)", "If the list is non-empty it returns the maximum.", ("unverifiable",))
PQ("Q4 conditional claim, pre True", "f([1, 2, 3])", "True", "If the list is non-empty it returns the maximum.", ("unverifiable",))


# --- round-3 reviewers R1/R2: structural fact bugs and mis-slot guards
def SF(name, src, claim, allowed, lang="python"):
    from discharge import discharge_structural
    oc = discharge_structural(claim, F(src, lang))[0]
    ok = oc in allowed
    if not ok:
        FAIL.append(name)
    print(f"{'OK ' if ok else 'BUG'} {name:48s} got {oc:12s} want {allowed}")


SF("decorator @classmethod (bug A)", "@classmethod\ndef from_int(cls, i):\n    return cls(i)\n",
   {"subtype": "decorator", "slots": {"name": "classmethod"}, "text": "is a class method"}, ("true",))
SF("decorator @contextlib.contextmanager (bug A)", "@contextlib.contextmanager\ndef g(x):\n    yield x\n",
   {"subtype": "decorator", "slots": {"name": "contextmanager"}, "text": "is a context manager"}, ("true",))
SF("typed **kwargs captured; json via kwargs (bug B)", "def put(url: str, data: int = None, **kwargs: Unpack[K]):\n    return request(url, data=data, **kwargs)\n",
   {"subtype": "parameter", "slots": {"name": "json"}, "text": "supports the `json` parameter"}, ("unverifiable",))
SF("default via **kwargs (bug B)", "def tzip(it, *its, **tqdm_kwargs):\n    k = tqdm_kwargs.copy()\n    c = k.pop('tqdm_class', tqdm_auto)\n    return c\n",
   {"subtype": "default", "slots": {"name": "tqdm_class", "value": "tqdm.auto.tqdm"}, "text": "`tqdm_class` defaults to `tqdm.auto.tqdm`"}, ("unverifiable",))
SF("bound-method alias is a call (bug C)", "def addlist(self, k, v):\n    ins = self._insert\n    for x in v:\n        ins(k, x)\n",
   {"subtype": "calls", "slots": {"callee": "_insert"}, "text": "uses the `_insert` method"}, ("consistent", "true"))
SF("invented default slot (mis-slot)", "def longest(strings):\n    return max(strings) if strings else None\n",
   {"subtype": "default", "slots": {"name": "strings", "value": "None"}, "text": "takes a list of strings"}, ("unverifiable",))
SF("local variable slotted as parameter (mis-slot)", "def f(cls, i):\n    key = (cls, i)\n    return key\n",
   {"subtype": "parameter", "slots": {"name": "key"}, "text": "creates a tuple named `key`"}, ("unverifiable",))
SF("referenced, not called (inherits from tuple)", "def make(name, attrs):\n    return type(name, (tuple,), {})\n",
   {"subtype": "calls", "slots": {"callee": "tuple"}, "text": "inherits from `tuple`"}, ("unverifiable",))
SF("with-statement lock (implicit call)", "def get(self, key):\n    with self._lock:\n        return self._d[key]\n",
   {"subtype": "calls", "slots": {"callee": "acquire"}, "text": "acquires a lock"}, ("unverifiable",))
T("tuple destructuring is element-wise", """
def f(a, b):
    x, y = a, b
    return x
""", "b", "x", ("false", "unverifiable"))


# =====================================================================================================================
# Limitations suite (v5). Cases marked LIMIT document a KNOWN unsound or imprecise verdict of this heuristic,
# slot-level checker (none of them changes a corpus verdict); `ok` lists the sound outcomes. A LIMIT case that starts
# behaving soundly is reported as FIXED. Cases marked PASS must give a sound outcome.
LIMITS, FIXED, PASSED = [], [], []


def _rec(name, oc, ok, kind):
    good = oc in ok
    if kind == "PASS":
        (PASSED if good else FAIL).append(name)
        tag = "OK " if good else "BUG"
    else:
        (FIXED if good else LIMITS).append(name)
        tag = "FIX" if good else "LIM"
    print(f"{tag} {name:52s} got {oc:12s} sound={ok}")


def DF(kind, name, src, s, t, ok, lang="python"):
    oc = discharge_dataflow({"slots": {"source": s, "sink": t}, "text": ""}, F(src, lang))[0]
    _rec(name, oc, ok, kind)


def ST(kind, name, src, claim, ok, lang="python"):
    from discharge import discharge_structural
    _rec(name, discharge_structural(claim, F(src, lang))[0], ok, kind)


def MB(kind, name, cls, text, ok, fname):
    from discharge import membership_check
    r = membership_check({"text": text}, {"cls": cls, "name": fname, "repo": "proj"})
    _rec(name, r[0] if r else "none", ok, kind)


def PQ2(kind, name, pre, text, ok):
    from probe import evaluate
    rec = {"exec_source": "def f(xs):\n    return max(xs) if xs else None\n", "name": "f"}
    p = {"concreteness": "instantiated", "call": "f([1, 2, 3])", "expect": "3", "expect_raises": None, "precondition": pre}
    _rec(name, evaluate(rec, p, text)[0], ok, kind)


NOTF = ("true", "consistent", "unverifiable")
NOTT = ("false", "consistent", "unverifiable")
CU = ("consistent", "unverifiable")

# --- second-extractor FALSE verdicts on true sentences (v4 -> fixed in v5)
ST("PASS", "A104 None-sentinel default", "def f(eq=None, default_eq=True):\n    if eq is None:\n        eq = default_eq\n    return eq\n",
   {"subtype": "default", "slots": {"name": "eq", "value": "default_eq"}, "text": "If eq is None, it defaults to a specified default_eq value"}, NOTF)
ST("PASS", "B004 'returns None' slotted as returns-nothing", "def longest(strings):\n    if not strings:\n        return None\n    return max(strings, key=len)\n",
   {"subtype": "returns", "slots": {"returns_value": False}, "text": "immediately returns None if so"}, NOTF)
ST("PASS", "A100 operator `in` slotted as a call", "def g(f):\n    if f not in CACHE:\n        CACHE[f] = 1\n    return CACHE[f]\n",
   {"subtype": "calls", "slots": {"callee": "in"}, "text": "if f not in _IS_GENERATOR_RESULTS"}, NOTF)

# --- round-4 reviewer (R3) cases, reconstructed from the review table
DF("LIMIT", "F1 map(out.append) (map on PURE list)", "def f(xs):\n    out = []\n    list(map(out.append, xs))\n    return out\n", "xs", "return", NOTF)
DF("LIMIT", "F2 wrapper object csv.writer", "def f(buf, row):\n    w = csv.writer(buf)\n    w.writerow(row)\n    return buf.getvalue()\n", "row", "return", NOTF)
DF("LIMIT", "F3 wrapper object ZipFile", "def f(buf, n, data):\n    zf = ZipFile(buf, 'w')\n    zf.writestr(n, data)\n    return buf.getvalue()\n", "data", "return", NOTF)
DF("LIMIT", "F4 print(file=buf) (print on PURE list)", "def f(a, buf):\n    print(a, file=buf)\n    return buf.getvalue()\n", "a", "return", NOTF)
DF("LIMIT", "F5 store through a call target vars(o)[k]", "def f(o, k, a):\n    vars(o)[k] = a\n    return o\n", "a", "return", NOTF)
DF("LIMIT", "F6 callee reads a module global", "def f(k, a):\n    CACHE[k] = a\n    return lookup(k)\n", "a", "return", NOTF)
DF("LIMIT", "F7 Java wrapper PrintWriter", "String f(int a) {\n    StringWriter sw = new StringWriter();\n    PrintWriter pw = new PrintWriter(sw);\n    pw.print(a);\n    return sw.toString();\n}", "a", "return", NOTF, "java")
DF("LIMIT", "F8 Java callee reads this field", "int f(int a) {\n    this.v = a;\n    return compute();\n}", "a", "return", NOTF, "java")
DF("LIMIT", "F9 Java callee reads a bare field", "int f(int a) {\n    v = a;\n    return compute();\n}", "a", "return", NOTF, "java")
DF("LIMIT", "F10 exit through a call (ctx.abort)", "def f(ctx, a, d):\n    if not a:\n        ctx.abort()\n    v = d\n    return v\n", "a", "v", CU)
ST("PASS", "F11 x=None; x = x or 5", "def f(x=None):\n    x = x or 5\n    return x\n",
   {"subtype": "default", "slots": {"name": "x", "value": "5"}, "text": "`x` defaults to 5 if not given"}, NOTF)
ST("PASS", "F12 same with **kw", "def f(x=None, **kw):\n    x = x or 5\n    return x\n",
   {"subtype": "default", "slots": {"name": "x", "value": "5"}, "text": "`x` defaults to 5 if not given"}, NOTF)
ST("PASS", "F13 Java overload default charset", "String f(byte[] b) {\n    return f(b, StandardCharsets.UTF_8);\n}",
   {"subtype": "default", "slots": {"name": "charset", "value": "UTF_8"}, "text": "the charset defaults to `UTF_8`"}, NOTF, "java")
ST("PASS", "F14 Java 'takes an integer n' slotted as default", "int f(int n) {\n    return n + 1;\n}",
   {"subtype": "default", "slots": {"name": "n", "value": "int"}, "text": "takes an integer `n`"}, NOTF, "java")
ST("PASS", "F15 Java void with block-lambda return", "void f(List<Integer> xs) {\n    xs.sort((a, b) -> { return a - b; });\n}",
   {"subtype": "returns", "slots": {"returns_value": False}, "text": "returns nothing"}, ("true", "consistent", "unverifiable"), "java")
ST("LIMIT", "F16 implicit protocol call __len__", "def f(x):\n    return len(x)\n",
   {"subtype": "calls", "slots": {"callee": "__len__"}, "text": "calls `__len__`"}, NOTF)
ST("LIMIT", "F17 Java for-each obtains an iterator", "int f(List<Integer> xs) {\n    int s = 0;\n    for (int x : xs) { s += x; }\n    return s;\n}",
   {"subtype": "calls", "slots": {"callee": "iterator"}, "text": "obtains an `iterator`"}, NOTF, "java")
MB("LIMIT", "T1 'static method' qualifier unchecked", "Parser", "`parse` is a static method of the `Parser` class.", CU + ("none",), "parse")
MB("LIMIT", "T2 'private method' qualifier unchecked", "Parser", "`parse` is a private method of the `Parser` class.", CU + ("none",), "parse")
MB("LIMIT", "T3 'instance method' qualifier unchecked", "Version", "`cmp` is an instance method of the `Version` class.", CU + ("none",), "cmp")
ST("LIMIT", "T4 nested wrapper decorator credited to factory", "def deco(fn):\n    @functools.wraps(fn)\n    def w(*a):\n        return fn(*a)\n    return w\n",
   {"subtype": "decorator", "slots": {"name": "wraps"}, "text": "is decorated with `functools.wraps`"}, NOTT)
ST("LIMIT", "T5 Java parameter annotation credited to method", "String f(@Nullable String s) {\n    return s;\n}",
   {"subtype": "decorator", "slots": {"name": "Nullable"}, "text": "the method is annotated `@Nullable`"}, NOTT, "java")
ST("LIMIT", "T6 Java @Override inside anonymous class", "Runnable f() {\n    return new Runnable() { @Override public void run() {} };\n}",
   {"subtype": "decorator", "slots": {"name": "Override"}, "text": "is annotated with `@Override`"}, NOTT, "java")
ST("LIMIT", "T7 receiver stripped: self.close vs fh.close()", "def f(path):\n    fh = open(path)\n    fh.close()\n",
   {"subtype": "calls", "slots": {"callee": "self.close"}, "text": "calls `self.close()`"}, CU)
ST("LIMIT", "T8 Java receiver stripped: this.validate", "void f(Obj other) {\n    other.validate();\n}",
   {"subtype": "calls", "slots": {"callee": "this.validate"}, "text": "calls `this.validate()`"}, CU, "java")
ST("LIMIT", "T9 raise caught inside f counts as raises", "def f(x):\n    try:\n        raise ValueError()\n    except ValueError:\n        return 0\n",
   {"subtype": "raises", "slots": {"exception": "ValueError"}, "text": "raises `ValueError`"}, NOTT)
ST("LIMIT", "T10 raise only in a nested def", "def f():\n    def g():\n        raise KeyError()\n    return g\n",
   {"subtype": "raises", "slots": {"exception": "KeyError"}, "text": "raises `KeyError`"}, NOTT)
ST("LIMIT", "T11 call only in a returned callback", "def f():\n    def cb():\n        save()\n    return cb\n",
   {"subtype": "calls", "slots": {"callee": "save"}, "text": "calls `save`"}, NOTT)
ST("LIMIT", "T12 returns object 'without consulting cache'", "def f(k, cache):\n    if k in cache:\n        return cache[k]\n    return []\n",
   {"subtype": "returns", "slots": {"returns_value": True}, "text": "returns an empty list without consulting `cache`"}, NOTT)
ST("LIMIT", "T13 negation: never returns token", "def f(token):\n    return token\n",
   {"subtype": "returns", "slots": {"returns_value": True}, "text": "never returns `token`"}, NOTT)
DF("LIMIT", "T14 starred destructuring", "def f(a, b, c):\n    x, *rest = a, b, c\n    return x\n", "b", "x", NOTT)
DF("LIMIT", "T15 nested destructuring", "def f(a, b, c):\n    x, (y, z) = a, (b, c)\n    return y\n", "c", "y", NOTT)
DF("LIMIT", "T16 Java switch-break in loop then reassign", "int f(int[] ks, int a, int b) {\n    int r = a;\n    for (int k : ks) { switch (k) { case 1: r = a; break; default: break; } }\n    r = b;\n    return r;\n}", "a", "return", NOTT, "java")
DF("LIMIT", "T17 conditional-expression test as data", "def f(c):\n    x = 1 if c else 2\n    return x\n", "c", "x", ("consistent", "unverifiable"))
DF("LIMIT", "T18 Java ternary test as data", "int f(boolean c) {\n    int x = c ? 1 : 2;\n    return x;\n}", "c", "x", ("consistent", "unverifiable"), "java")
DF("PASS", "T19 field kill o.v=a; o.v=b", "def f(a, b):\n    o = Box()\n    o.v = a\n    o.v = b\n    return o.v\n", "a", "return", NOTT)
DF("PASS", "T20 Java kill on both branches", "int f(int a, boolean c) {\n    int x = a;\n    if (c) { x = 1; } else { x = 2; }\n    return x;\n}", "a", "return", NOTT, "java")
DF("PASS", "T21 kill after loop", "def f(a, xs):\n    x = a\n    for i in xs:\n        pass\n    x = 0\n    return x\n", "a", "return", NOTT)
PQ2("LIMIT", "Q1 precondition `len(..) > 0 or True` (lexical gate)", "len([1, 2, 3]) > 0 or True", "If the list is non-empty it returns the maximum.", ("unverifiable",))
PQ2("LIMIT", "Q2 precondition `True or ...` (lexical gate)", "True or len([1]) > 5", "If the list is non-empty it returns the maximum.", ("unverifiable",))

# --- implicit protocol calls and constructor delegation (round-4 R1-S2 / R2-S2)
ST("LIMIT", "for-loop 'calls iter'", "def f(xs):\n    s = 0\n    for x in xs:\n        s += x\n    return s\n",
   {"subtype": "calls", "slots": {"callee": "iter"}, "text": "calls `iter`"}, NOTF)
ST("LIMIT", "operator 'uses __add__'", "def f(a, b):\n    return a + b\n", {"subtype": "calls", "slots": {"callee": "__add__"}, "text": "uses `__add__`"}, NOTF)
ST("LIMIT", "f-string 'formats with format'", "def f(x):\n    return f'{x}'\n", {"subtype": "calls", "slots": {"callee": "format"}, "text": "formats `x` with `format`"}, NOTF)
ST("LIMIT", "str(x) 'calls __str__'", "def f(x):\n    return str(x)\n", {"subtype": "calls", "slots": {"callee": "__str__"}, "text": "calls `__str__`"}, NOTF)
ST("LIMIT", "Java this(...) constructor delegation", "Foo(int x) {\n    this(x, 0);\n}", {"subtype": "calls", "slots": {"callee": "Foo"}, "text": "delegates to the `Foo` constructor"}, NOTF, "java")


# --- round-5 reviewer (R3) cases (v6)
ST("PASS", "R1 'returns None early' slotted returns-something", "def f(self, x):\n    if not x:\n        return\n    self.items.append(x)\n",
   {"subtype": "returns", "slots": {"returns_value": True}, "text": "returns `None` early when `x` is empty"}, NOTF)
ST("PASS", "R2 'It returns None.' on a function without return", "def f(self, x):\n    self.items.append(x)\n",
   {"subtype": "returns", "slots": {"returns_value": True}, "text": "It returns None."}, NOTF)
ST("PASS", "K1 decorator name used in the body", "def f(gen):\n    return contextmanager(gen)\n",
   {"subtype": "decorator", "slots": {"name": "contextmanager"}, "text": "wraps `gen` with the `contextmanager` decorator"}, NOTF)
ST("PASS", "K2 decorator claim with splats", "def f(*args, **kwargs):\n    return g(*args, **kwargs)\n",
   {"subtype": "decorator", "slots": {"name": "wraps"}, "text": "is decorated with `wraps`"}, NOTF)
ST("PASS", "C1 operator.methodcaller dispatch", "def f(xs):\n    return list(map(operator.methodcaller('strip'), xs))\n",
   {"subtype": "calls", "slots": {"callee": "strip"}, "text": "calls `strip`"}, NOTF)
ST("PASS", "C2 handler-table dispatch", "def f(k, x):\n    return HANDLERS[k](x)\n",
   {"subtype": "calls", "slots": {"callee": "load"}, "text": "dispatches to `load` via the handler table"}, NOTF)
ST("PASS", "C3 globals()[...]() dispatch", "def f(name):\n    return globals()['cmd_' + name]()\n",
   {"subtype": "calls", "slots": {"callee": "cmd_run"}, "text": "calls `cmd_run`"}, NOTF)
DF("LIMIT", "D1 Java implicit this: this.v = a; return v", "int f(int a) {\n    this.v = a;\n    return v;\n}", "a", "return", NOTF, "java")
DF("LIMIT", "D2 Java implicit this: v = a; return this.v", "int f(int a) {\n    v = a;\n    return this.v;\n}", "a", "return", NOTF, "java")
DF("PASS", "H1 y = x; y += [a] (in-place augassign)", "def f(x, a):\n    y = x\n    y += [a]\n    return x\n", "a", "return", NOTF)
DF("PASS", "H2 y = x; y.custom_add(a)", "def f(x, a):\n    y = x\n    y.custom_add(a)\n    return x\n", "a", "return", NOTF)
DF("PASS", "H3 y = x; y |= {a}", "def f(x, a):\n    y = x\n    y |= {a}\n    return x\n", "a", "return", NOTF)
ST("LIMIT", "C5 Java super(x) constructor delegation", "Foo(int x) {\n    super(x);\n}",
   {"subtype": "calls", "slots": {"callee": "Base"}, "text": "calls the `Base` constructor"}, NOTF, "java")
ST("LIMIT", "C8 del d[k] calls __delitem__", "def f(d, k):\n    del d[k]\n",
   {"subtype": "calls", "slots": {"callee": "__delitem__"}, "text": "calls `__delitem__`"}, NOTF)
ST("PASS", "R3 explicit return None + 'returns nothing'", "def f(x):\n    print(x)\n    return None\n",
   {"subtype": "returns", "slots": {"returns_value": False}, "text": "returns nothing"}, NOTF)
ST("PASS", "R4 async def + 'returns a coroutine'", "async def f(x):\n    await g(x)\n",
   {"subtype": "returns", "slots": {"returns_value": True}, "text": "returns a coroutine"}, NOTF)
ST("PASS", "R6 generator + 'has no return statement'", "def f(xs):\n    for x in xs:\n        yield x\n",
   {"subtype": "returns", "slots": {"returns_value": False}, "text": "has no return statement"}, NOTF)
ST("PASS", "P6 symbolic default vs literal", "def f(url, timeout=DEFAULT_TIMEOUT):\n    return get(url)\n",
   {"subtype": "default", "slots": {"name": "timeout", "value": "30"}, "text": "`timeout` defaults to 30"}, NOTF)
ST("PASS", "P7 click decorator-supplied default", "@click.option('--count', default=1)\ndef f(count):\n    return 0\n",
   {"subtype": "default", "slots": {"name": "count", "value": "1"}, "text": "`count` defaults to 1"}, NOTF)
ST("LIMIT", "K3 Java override without @Override slotted as decorator", "public String toString() {\n    return name;\n}",
   {"subtype": "decorator", "slots": {"name": "Override"}, "text": "overrides `toString`"}, NOTF, "java")
ST("LIMIT", "K4 property defined outside the snippet", "def area(self):\n    return self.w * self.h\n",
   {"subtype": "decorator", "slots": {"name": "property"}, "text": "`area` is a `property`"}, NOTF)

ST("PASS", "P8 constant-expression default 30*60 vs 'defaults to 1800'", "def f(url, timeout=30*60):\n    return get(url)\n",
   {"subtype": "default", "slots": {"name": "timeout", "value": "1800"}, "text": "`timeout` defaults to 1800"}, NOTF)
ST("PASS", "P9 constant-expression default 2**10 vs 'defaults to 1024'", "def f(n=2**10):\n    return 0\n",
   {"subtype": "default", "slots": {"name": "n", "value": "1024"}, "text": "`n` defaults to 1024"}, NOTF)
ST("PASS", "P10 literal default mismatch still FALSE", "def f(n=5):\n    return 0\n",
   {"subtype": "default", "slots": {"name": "n", "value": "6"}, "text": "`n` defaults to 6"}, ("false",))
ST("PASS", "R7 async def + 'returns nothing'", "async def f(x):\n    await g(x)\n",
   {"subtype": "returns", "slots": {"returns_value": False}, "text": "returns nothing"}, NOTF)


if __name__ == "__main__":
    n_suite = len(PASSED) + len(LIMITS) + len(FIXED)
    print(f"limitations suite: {n_suite} cases, {len(LIMITS)} documented limitations, {len(FIXED)} limitations now sound")
    print(f"{len(FAIL)} failing case(s)" + (": " + ", ".join(FAIL) if FAIL else ""))
    sys.exit(1 if FAIL else 0)
