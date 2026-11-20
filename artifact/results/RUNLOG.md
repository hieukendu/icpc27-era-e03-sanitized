# RUNLOG — Attest (E03)

All times +07, 2026-11-09.

## Cycle 0 — first builder session (14:12–15:24, interrupted)
- Built corpora (Corpus A: 150 Python functions from click, requests, tqdm, more-itertools, attrs, boltons
  and 40 Java methods from gson, commons-lang; Corpus B: 40 HumanEval+ + 40 MBPP+), facts for all 270.
- Started `explain.py` (all functions, model by model): 46 qwen2.5-coder:14b explanations in ~9 min, then
  the session ended. 49 responses were cached; all were reused.

## Cycle 1 — resume (22:10)
- **Observation.** Measured throughput with three sibling builders on the same Ollama: ~12 s per explanation and
  ~23 s per extraction (≈2–4 calls/min overall). The planned ~1,500 calls over 270 functions would take
  more than 8 h.
- **Diagnosis.** The stage-by-stage loop (all explanations, then all extractions) produces no complete unit of
  analysis until the very end, so stopping it early would leave the corpus unbalanced.
- **Fix.** Added `selection.py` with a deterministic stratified round-robin work order. Each round has 6 Python
  functions (one per repo), 2 Java methods and 4 EvalPlus problems. Added `warm.py`, which fills the cache for
  every LLM stage function by function (explain x2, extract, second extraction on positions p%4==0, judge on
  p%3==0, probe synthesis for Corpus B). The analysed corpus is the first N complete rounds, frozen in
  `data/selection.json`. The analysis scripts replay identical prompts from the cache.
- **Fix.** The Anthropic SDK in the venv (2.6.0) rejects `temperature`, so it was dropped for the frontier
  condition. That condition is made reproducible by the cache, not by decoding settings (stated in the paper).

## Cycle 2 — engine audit on round 1 (development data: the 12 functions of round 1)
- **Observation.** First replay of round 1 (24 explanations, 172 claims): 54.7% of claims discharged. 18 of 31
  data-flow claims were `unverifiable`, and several structural/data-flow claims were `false` although they
  looked correct on manual reading of the code.
- **Diagnosis** (each traced to code):
  1. Data-flow endpoints are usually expressions or statements (`link[VALUE]`, `return link[VALUE]`,
     `self.on_miss(key)`, `with self._lock`), but `_resolve` accepted only single names, giving
     "unresolved endpoint".
  2. Java data flow was not implemented, so every Java flow claim was `unverifiable`.
  3. Indirect calls were missed: `f = getattr(self._stream, "read1"); f(size)`, `partial(take, n, it)`, and
     `from .notebook import trange as _tnrange` were all counted as false "calls" claims.
  4. Mutating calls (`out.append(x)`, `System.arraycopy(src, _, dst, _, _)`) and subscript stores (`d[k] = v`)
     created no def-use edge.
  5. The probe synthesiser in JSON mode returned bare strings (`racecar`) as `expect`, which raised NameError
     and became `unverifiable`.
  6. The extractor once echoed an instruction line ("The code explicitly raises/throws exception type X") as
     a claim.
- **Fix.** (1) `_endpoint_nodes` parses an endpoint with `ast` and uses the set of graph nodes it mentions.
  Assignment statements denote their targets as sinks and their values as sources, and a source used inside
  a compound sink expression counts as flow. (2) `java_dataflow` over tree-sitter-java uses the same node
  conventions. (3) `calls_indirect` covers getattr string literals, higher-order references and import aliases;
  the evidence string says "indirect". (4) MUTATORS edges, arraycopy edges, and Subscript-store targets.
  (5) `_repair_expect` quotes non-literal bare strings. (6) `_is_template_echo` drops echoed instruction lines.
  None of these change any LLM prompt, so the cache stays valid.
- **Re-run (round 1).** Discharged share went from 54.7% to 66.5%. Data-flow `unverifiable` fell from 18 to 3.
  Remaining false verdicts were checked by hand: `ret = self[key] = on_miss(key)` (ret does not flow into
  self[key]) is correctly false. "acquires a lock" grounded as callee `_lock` is a mis-grounding (with-statement,
  not a call), and we keep it as an engine false alarm. Behavioural false verdicts on instantiated probes include
  synthesiser errors (it expected `move_one_ball([2,1,3]) == True`), so stated and instantiated probes are
  reported separately.
- **Guard against overfitting.** Round 1 was used to develop these fixes, so `analyze.py` also reports H1
  on the held-out rounds 2..N.

## Cycle 3 — stalled warm-up (23:01–23:17)
- **Observation.** No cache writes for 16 min during round 2. Ollama answered a probe request in 12 s, and the
  warm process was blocked in `sock_recv_into` on an open connection.
- **Diagnosis.** Under four-way contention the server dropped one request. The client's 900 s read timeout
  then wasted 15 min before the retry.
- **Fix.** Read timeout lowered to 300 s, retries raised to 5. warm.py was restarted; it resumes from the cache
  (earlier log kept as results/warm_part1.log). Frontier explanations for rounds 1-3 (35 API calls + 1 cached)
  were generated meanwhile, using no GPU.

## Cycle 4 — audit on rounds 1-2 incl. frontier (23:40)
- **Observation.** Several data-flow claims about in-place updates ("x is incremented", "offsets are clamped
  using max0") were `unverifiable` with source == sink. One statement-shaped endpoint
  (`ret = self[key] = self.on_miss(key)`) was resolved to `call:on_miss` by the call-name fallback.
  Frontier claims grounded keywords as callees (`for`, `null`).
- **Fix.** Def-use graphs now record `self_updates` (Python `x = g(x)`, `x += e`; Java compound assignment,
  `x = ...x...`, `x++`), and a source == sink claim is decided against them. The call-name fallback now applies
  only to dotted identifiers. More keywords are rejected as callees.
- **Re-run (rounds 1-2, 445 claims).** Data-flow unverifiable fell from 24 to 16, data-flow true rose from 62
  to 69, and data-flow false rose from 6 to 7. The remaining unverifiable flow claims are mostly control-dependence
  sentences that the extractor typed as flow with no sink ("checks whether mode includes 'b'"). We keep these
  as an honest tooling/typing gap.

## Cycle 5 — throughput and corpus freeze (01:16, 2026-11-10)
- **Observation.** Round 4 took 71 min and round 5 about 20 min. The cache shows gaps of 270–1,331 s between
  writes (dropped requests, recovered by the 300 s timeout and retries) while three sibling builders used the
  same server.
- **Decision.** Freeze the analysed corpus at **5 complete rounds = 60 functions** (30 Python from six repos,
  10 Java from two repos, 20 EvalPlus: 10 HumanEval+, 10 MBPP+). That gives 120 local explanations plus
  36 frontier explanations (claude-haiku-5-5, rounds 1-3). The plan called for 270 functions. The reduction
  is deterministic (a prefix of the stratified work order) and is stated in the paper. Cached responses for
  functions beyond round 5 stay in the cache but are not analysed.
- `make run` started: replays the cache, extracts the 12 frontier explanations of round 3 (new calls), and builds
  the planted set (new extraction and probe calls).

## Cycle 6 — engine validity on the planted set (01:45)
- **Observation.** End-to-end, Attest caught only 41.7% of the 151 planted false twins (calls 51%, parameter
  63%, flow 30%, behavioural 21%). Precision of a discharged-false verdict was 84%, and 27% of false twins were
  discharged TRUE.
- **Diagnosis.** We read every false twin that came out `true`. The usual cause is *re-grounding*: when the
  extractor re-decomposes the perturbed sentence, it grounds the slots on a different, correct part of the
  sentence (e.g. "uses `partial(appendleft, n, iter(iterable))`" became flow iter(iterable)->iterator), so the
  falsified token is never checked. Flow perturbations often replaced a word that had not been grounded. For
  behavioural twins, the probe tested an aspect the flipped word did not affect.
- **Fix (Attest+E).** Added an entity-existence check, structural evidence in the spirit of entity tracing (ETF):
  a non-intent claim whose `backticked` identifiers occur nowhere in the function, its module context or the
  language's standard vocabulary is discharged false (`dangling entity`). Recorded as `outcome_e`, next to the
  primary `outcome`.
- **Re-run.** False twins caught: 41.7% -> 49.7% (calls 51% -> 73%). True-claim retention unchanged (69.5%);
  precision of false verdicts 86%. The check flipped **0** of the 822 real local claims. Caveat stated in the
  paper: the sibling names used for calls/parameter twins were chosen to be absent from the function, which
  favours this check by construction; role-swap perturbations (an existing name in the wrong role) are future
  work. Planted items are selected with the primary outcome, so the planted cache stays valid.

## Cycle 7 — empty frontier explanations (01:50)
- **Observation.** 12 of 36 Claude Haiku 5.5 explanations were empty and most of the others were truncated
  (mean 54 words). Every call used exactly 450 output tokens.
- **Diagnosis.** The model's default adaptive thinking consumed the max_tokens budget before any text block.
- **Fix.** `thinking={"type": "disabled"}` (comparable to the answer-only local models), and the cache key now
  includes `thinking=disabled`. The 36 frontier explanations were regenerated (now 162–240 words, mean 203).
  The old cached responses are kept but no longer used. Total Anthropic calls so far: 74 (cap 300).

## Cycle 8 — final replay checks (02:00–02:20)
- **Observation.** Two frontier explanations (A027, A102) produced zero claims. The extractor's JSON degenerated
  into a run of spaces inside the last string, so the document was truncated and failed to parse.
- **Fix.** `extract.salvage_claims` recovers every complete claim object before the truncation (no prompt change).
  Zero-claim explanations went from 2 to 0, and frontier claims from 321 to 331. Local results are unchanged
  (822 claims).
- **Observation.** The entity check (+E) flipped 6 frontier claims and 0 local ones. On inspection all 6 are false
  alarms: dunder protocol methods (`__hash__`, `__setitem__`), JDK exceptions not named in the method
  (`ArithmeticException`), and illustrative names (`Foo`, `Bar`, `instance`).
- **Decision.** +E stays an ablation (Table III, "+E" column). The primary engine, which all profile numbers use,
  is Attest without +E.
- **Final numbers** (summary.json): 60 functions, 156 explanations (120 local + 36 Haiku), 1,153 claims
  (822 local). H1: discharged 55.2% [49.1, 60.9]; held-out rounds 2–5: 52.5% [45.3, 59.5]; intent = 50.8% of the
  residue; policy (behavioural claims about repository code) = 34.2% of the residue. Planted: 151 pairs, false
  twins caught 41.7% (+E 49.7%), true kept 69.5%, precision of false verdicts 84.0%. H2 proxy: rho = 0.37
  [-0.05, 0.70], n = 27. Extractor agreement: 77% of claims matched, type kappa 0.52.
- **Determinism.** `make run render` executed twice after the final fixes: summary.json sha1
  da6234a1217869734a13eeba6b1f875b7668b5e9 both times, with zero new LLM calls.

# Round 2 — revision after review (R1 WR, R2 WA, R3 WR), 2026-11-10 02:20–03:40

The round-1 outputs are archived in results/v1/ (discharge, planted, probes, judge, tables, summary). The planted
item set was frozen to results/planted_items.json before any engine change, so the pseudo-explanations, and
therefore their cached extractions, stay byte-identical.

## R2-1 — sound discharge semantics (R3-M1, R2-S3)
- **Diagnosis** (reviewers, confirmed in code): the data-flow graph was flow-insensitive with no kill sets.
  Endpoints were existential sets, a "compound sink" counted bare identifier containment, and `x = g(x)`
  certified "x flows to x". The returns rule checked only "returns some value". Calls matched on the last
  dotted name, imports on any segment overlap, Java callees case-insensitively, and raises only on explicit
  raises while absence was counted as false.
- **Fix.** New `defuse.py`: one reaching-definitions analysis over a small statement IR, lowered from Python
  `ast` and from tree-sitter-java. Strong assignments kill, weak updates (subscript store, `+=`, mutators,
  `arraycopy`) don't; if/else and try join; loops reach a fixpoint; conditions add control edges.
  Discharge rules were rewritten:
  - endpoints must resolve to one variable/call/return, and conjunctions are checked universally;
  - compound expressions and self-references are `unverifiable`;
  - a data path gives true, a control-only path the new outcome `consistent`;
  - "returns X" is true/false only if X names an entity whose definitions reach a return, else `consistent`;
  - qualified callees must match the call path, else `consistent`; indirect references are `consistent`;
  - raises absent an explicit raise are `unverifiable`; import absence is `unverifiable` (truncated context).
  Every verdict records its `rule`.
- **Flips** (local claims, v1 TRUE = 420): 117 are no longer TRUE: 49 behavioural (R2-2), 38 data-flow (26
  compound endpoints, 10 self-updates, 2 control-only), 27 returns (26 content unchecked -> consistent,
  1 -> false), 3 indirect calls. Full transition matrix: summary.json `flips.transitions`.

## R2-2 — blind, validated probes (R3-M2)
- **Fix.** The probe synthesiser now sees only the signature (body replaced by `...`) and the claim, and returns
  a precondition. A probe counts only if the precondition holds and the call does not raise in a non-raise
  probe; a passing probe must also fail on at least one of up to 8 first-order AST mutants (comparison,
  arithmetic, boolean-connective and constant swaps). Stated pass -> true, instantiated pass -> consistent.
  `__approx__` compares booleans type-strictly (True != 1).
- **Observation (first run).** 20 probe FALSE verdicts (19 instantiated, 1 stated).
- **Audit** (data/probe_audit.csv): 16 synthesiser errors (wrong expectation for a correct general claim),
  3 real falsifications, 1 ambiguous.
- **Fix.** A failing *instantiated* probe is now `unverifiable` ("instance disagreement", 19 cases); only stated
  probes can yield FALSE. **Result:** of 65 v1 probe TRUE verdicts, 2 stay true, 35 are consistent and 28
  unverifiable. 137 probe-routed claims: 3 stated (2 T, 1 F), 105 instantiated (52 consistent,
  18 non-discriminating, 3 invalid precondition, 19 disagreements), 19 "none", and the rest without a probe.

## R2-3 — sandbox (R3-M7)
- macOS refuses to lower RLIMIT_AS/RLIMIT_DATA ("current limit exceeds maximum"; tested), so **there is no
  memory limit**.
- Added `sandbox-exec` with a profile that denies network* and file-write* outside the temp dir (tested: a
  socket connect and a write to $HOME both fail with PermissionError), plus proxy env blocks. The temp cwd, the
  5 s timeout, the CPU rlimit and `python -I` are unchanged. The paper states exactly this.

## R2-4 — Intent split (R1-1, R3-M6)
- `retype.py` (prompt fixed before any output was read): gemma2:9b (primary) and llama3.1:8b label each of the
  279 extractor-intent claims FUNCTIONAL vs RATIONALE from the claim text and function name.
  - Agreement 81%, kappa 0.62. Against the extractor's own purpose/other subtype: kappa 0.40.
  - FUNCTIONAL becomes Purpose (P): routed to probes on Corpus B, and to a class-membership check (enclosing
    class from the corpus record) when the claim places the function in a class. RATIONALE becomes R
    (undischargeable = outside E by the typing).
- **Fix during audit.** The membership regex matched "cache class" in "the LRU (Least Recently Used) cache
  class". Class names are now required to be capitalised or `_`-prefixed. One false verdict removed.

## R2-5 — independent judge (R1-5, R2-7)
- Judge switched to gemma2:9b (different family from every explainer and extractor). It judged all 120 local
  explanations; the round-1 qwen2.5:14b judge output is kept in v1/.
- H2 now compares the engine-true rate and the judge-true rate on the same decided claims (function-clustered
  bootstrap, permutation p, Kendall tau-b reported), plus the judge rate on undecided claims.

## R2-6 — planted set (R2-4/5, R3-M5)
- Frozen 151 pairs, replayed through the new engine. 32 pairs were dropped because the original claim is no
  longer TRUE, leaving only 1 behavioural pair.
- **Audit** (data/planted_audit.csv) of all 29 false twins judged TRUE: 1 label error (pid 121, "determines the
  size of the grid `grid`" is true of the code), removed; 28 label_ok, each with a note.
- 118 valid pairs. Cluster-bootstrap CIs on every metric; primary and +E are reported separately.
- The miss breakdown uses token-level slot analysis (old/new token from a word diff).

## R2-7 — power simulation (R1-4, R2-9)
- The smoke test now simulates the planned design: 24 claims, 3 conditions, 2 wrong-evidence items of 4 false
  per condition, crossed participant/claim random intercepts. Test: the per-participant interaction contrast.
- Power for OR 2.2: 0.35 at N=36, 0.58 at N=72, 0.75 at N=108; the old 0.86 at N=24 is withdrawn. Wording
  changed to "planned protocol (not yet registered)".

## R2-8 — anonymity
- The Makefile uses `PY ?= python3`. Logs with absolute paths were deleted (run*.log) or scrubbed (replay*.log),
  and script output prints basenames. The data-availability URL is marked as a placeholder to be added at
  submission.

## R2-9 — determinism
- `make run render` twice: summary.json sha1 b4e921800ee58af04af742a58ac84f48483eb2f9 both times, with zero new
  LLM calls on the second replay.
- Not done (optional item G): corpus scale-up. The revision used the GPU time for the re-typing (118 calls),
  the judge (120) and the probes (46 + 11 planted).

# Round 3 — revision after round-2 review (R1/R2/R3 all WA), 2026-11-10 ~04:00–05:00

Round-2 outputs are archived in results/v2/. Reviewer R3's adversarial def-use cases (41) plus 6 minimal
reproductions of corpus FALSE verdicts now form `tests/test_engine.py`, which `make render` runs. Result: 0
failing cases (results/test_engine.log).

## R3-1 — membership rule certified compound sentences
- **Diagnosis.** All 24 local Purpose TRUE verdicts came from `member`, which checked only the enclosing class.
- **Fix.** TRUE only for pure membership sentences ("X is a method of class C (in library L)"). The span must
  contain no extra qualifiers ("property method"), and a named library must be the repository. Otherwise
  CONSISTENT (`member-compound`).
- **Result.** 17 TRUE -> CONSISTENT; 7 TRUE remain, all hand-checked pure statements.

## R3-2 — unsound data-flow FALSE (defuse.py rewritten)
- Early-exit guards (return/raise/continue/break) add control edges to all later statements.
- Try handlers start from the join of every intermediate state of the try body.
- Nodes are keyed by statement, so loops iterate to a real fixpoint (bound 200).
- Field stores also weak-update the base object, field reads are field-sensitive, and a whole-object read
  includes its defined fields.
- Walrus, match captures, Java chained (`a = b = c`) and in-condition assignments are lowered to definitions.
- Chained Python assignment: later targets receive the first target's object.
- A local function object flows into its own call.
- Plain identifiers bypass the Python parser (Java `in`, `is`).
- A parameter source means the parameter's incoming value.
- Aliasing, closure writes, global/nonlocal, Java anonymous classes and block lambdas are flagged; flagged
  functions never yield FALSE.
- A source that feeds a method call ON the sink object gives CONSISTENT (`flow-receiver`; the `template.replace`
  case).
- Returns-content no longer applies to nested helpers or to the sentence's subject (`returns-other`).
- **Re-audit of local data-flow / returns-content FALSE verdicts.** Before the fix there were 5 (A077, A103, B003,
  B002, A125).
  - A103 and A125 are now TRUE (heap field / chained assignment).
  - B002 is CONSISTENT (receiver rule).
  - B003 is UNVERIFIABLE (returns claim about a nested helper).
  - A077 remains FALSE and is correct: `repeat(1)` is passed to `compress`, not zipped.
  - Frontier: A025 is now TRUE (chained assignment) and A127 is TRUE (local function object).

## R3-3 — probe validity (R3-S1, R3-S8)
- **Observation.** 42 of 52 round-2 consistent probes had precondition `True`, including probes on conditional
  claims.
- **Fix.** An instantiated probe with precondition `True` on a claim containing if/when/unless/ties/while/...
  is UNVERIFIABLE (36 probes). A failing stated probe whose result and expectation differ in type is UNVERIFIABLE.
  This turned the only stated FALSE (Haiku B002:07, a synthesiser error) into UNVERIFIABLE.
- Probe partition (sums to 137): 2 stated-true, 1 stated type-mismatch, 25 instantiated-consistent, 36 vacuous
  precondition, 16 disagreement, 12 non-discriminating, 3 invalid precondition, 1 error, 12 without a call,
  19 "none", 10 no probe returned.

## R2-2 — held-out contamination of the probe rule
- The round-2 probe audit covered 6 held-out verdicts (3 real, 3 errors), 6 tuning-round verdicts (6 errors)
  and 8 Haiku verdicts (7 errors, 1 ambiguous).
- Without the "failing instantiated -> unverifiable" rule, the held-out share is 40.8% [33.0, 48.2] (it is 40.0%
  with the rule). Both are now emitted by analyze.py and disclosed in the paper's deviations paragraph.

## R2-3 — degenerate H2 interval
- `boot()` now counts undefined resamples and reports no CI if more than 5% are undefined.
- The H2 p-value is derived from the same function-clustered bootstrap (p_boot), so CI and p agree. The
  permutation p is kept in summary.json only.
- Undecided-claim H2: the judge marks 98% true and 58 of 61 points sit at 1.0; 250/2000 resamples are undefined,
  so no CI is reported. The paper calls it a ceiling.
- Same-claim H2: rho 0.31 [-0.02, 0.62], p_boot 0.063, so inconclusive.

## Results after round 3
- Decided share: all rounds 40.0% [34.2, 45.7]; held-out 40.0% [31.8, 47.5]. R3's estimate was 40.6/40.4 with only
  the membership fix.
- Engine history: round-1 55.2%, round-2 42.3%, round-3 40.0%. Round-2 -> round-3 transitions: 17 true->consistent,
  18 consistent->unverifiable, 2 false->true, 1 false->consistent, 1 false->unverifiable.
- Round-1 -> round-3: 117 TRUE -> other, and 11 -> TRUE (7 undischargeable -> pure membership, 4 false -> true).
- Planted (118 audited pairs; no new false-twin-TRUE cases needed auditing): caught 44.9% [33.7, 55.6], F->T 23.7%,
  kept 72.0%, precision 89.8%.
- Determinism: `make run render` twice gives summary.json sha1 6150912971a3074720a59dfc666d68f8ed038358 both times,
  with no new LLM calls.

## R2-4 — anonymity
- `__pycache__` and `build/` deleted via the new `make package-clean`; `.gitignore` added.
- A binary-inclusive grep (`grep -a`) for the username or absolute home-directory paths over the whole project, including cloned repos and
  excluding only reviews/, finds nothing.
- Replay logs are no longer written into results/.

# Round 4 — conservative FALSE after round-3 review (R1/R2/R3 all WA), 2026-11-10

Round-3 outputs are archived in results/v3/. All three reviewers' must-fix items concerned unreliable FALSE verdicts.
- R2 audited all 15 local FALSE verdicts and found 14 on true sentences.
- R3's 46 adversarial cases produced 30 unsound FALSE verdicts.

## R4-1 — concrete fact bugs (regression test for each)
- Python decorators are now read from the parent `decorated_definition` (bug A).
- Typed `*args`/`**kwargs` are captured (bug B). The parameter and default rules return UNVERIFIABLE for absent
  names when the function takes splats.
- Bound-method aliases (`x = obj.m; x(...)`) count as indirect calls (bug C).
- Tuple destructuring with a tuple literal is element-wise and simultaneous (`x, y = a, b` no longer certifies b→x).
- A strong assignment to `o` kills `o.*` fields (R3-S5).
- "Returns nothing / something" uses the function's own returns (nested helpers excluded).

## R4-2 — FALSE only inside explicit supported fragments (structural change)
- **Data flow.** No-path FALSE requires all four:
  - (i) no try/with/match/assert/nested def/global/Java switch/anonymous class/effectful lambda or comprehension;
  - (ii) exits only at top level or directly in a top-level if (no elif, no nested guards, no exits in loops or
    try blocks);
  - (iii) no mutated variable bound to a non-fresh object (loop variable, element, attribute, tuple element,
    call result; in Java, any receiver);
  - (iv) no path in a conservative graph where every non-pure call may update its arguments and receivers with
    everything the statement reads.
  Otherwise the verdict is UNVERIFIABLE (`flow-gated`). Returns-content is gated the same way.
- **Calls.** FALSE only without with-statements, calls through local names, getattr/super/eval, a mere reference to
  the name, or a non-identifier callee.
- **Parameters/defaults.** FALSE only without splats, if the name is not used in the body, and, for defaults,
  only if the sentence states a default and the slot value is not a type annotation.
- **Returns-content** checks only the backticked object of "return", skipping type names and the sentence subject.
- **Membership** is anchored to the subject (which must be the function's own name) followed directly by
  "(is a) method of/in class C". Non-adjective qualifiers mean the sentence is not a membership claim.
- **Probe preconditions.** Constant expressions (`1 == 1`, `(True)`) are normalised to `True` and then count as
  vacuous on conditional claims.
- **Regression test.** `tests/test_engine.py` now holds 100 cases: 47 earlier, R3's 46 reconstructed from the
  review table, and R1/R2's fact and mis-slot patterns. All pass. Where a path may exist, the accepted outcomes
  exclude FALSE. On R3's table the round-3 engine gave 30 unsound FALSE; this engine gives none.

## R4-3 — real-corpus FALSE audit (AI assistant; data/false_audit.csv)
- FALSE verdicts on all 1,153 claims: 27 (15 local) under the round-3 engine, 1 now.
- The remaining one (coder14b:A077:02, "`repeat(1)` … is then zipped with the input iterable") is a correct
  refutation: 1/1.
- render.py refuses to build if any FALSE verdict is unaudited.
- Round-4 transitions, all explainers (34): false→unverifiable 18, false→true 7, false→consistent 1,
  true→consistent 4, true→unverifiable 1, consistent→unverifiable 3.

## Results
- Decided share: all rounds 38.4% [32.7, 43.9]; held-out (rounds 3–5, held out from the round-1 tuning)
  38.0% [30.2, 45.2]; held-out without the post-hoc probe rule 38.8%. The H1 coverage clause still holds.
- Planted (117 audited pairs): caught 37.6% [27.4, 48.3], F→T 23.9%, precision 91.7% at 50% prevalence.
  Flow catch fell to 5% because flow FALSE is gated.
- The planted audit gained one label error (pid 78; with `**kwargs` captured, "optional key parameters" reads
  as keyword arguments, so the perturbed sentence is plausibly true).
- H2: with a single FALSE, the engine-true rate is 1.0 for 69 of 70 explanations, κ = −0.01. H2 cannot be assessed
  with this proxy.
- Determinism: `make run render` twice gives summary.json sha1 18052d8426599330df5926e0c333eb0e863f96de both times,
  with no new LLM calls.
- Hygiene: stale files removed (replay logs, discharge_test.jsonl, fig_h2.tex). render.py fails loudly without the
  smoke output (which `make render` produces). Ref [1] pages fixed to 1184–1196. `make package-clean` was run, and
  a binary-inclusive grep for the username or home paths is clean.

# Engine v5 — honest framing after round-4 review (all WA), 2026-11-10

Engine versions are renamed v1–v5 so that "round" means only data rounds. v1 = original, v2 = sound-direction rules
and blind probes, v3 = membership and data-flow fixes, v4 = supported-fragment gate, v5 = this revision. v4 outputs
are archived in results/v4/.

## Reframing (no chasing of individual cases)
The paper now describes Attest as a heuristic slot-level checker:
- TRUE means the extracted slot is supported by a fact or by a may-path over the modelled fragment, not that the
  sentence is entailed.
- Rule-based FALSE is gated to syntactic fragments and is not sound under heap, inter-procedural or implicit-protocol
  effects.
- "Conservative" and "requires entailment" were removed.
- Sec. III lists each rule's blind spots, using the reviewer's categories.

## Data-touching bugs fixed
- **Default rule.** Every FALSE branch (absent name, no default, value mismatch) now passes the same guards:
  Java → UNV (defaults are emulated by overloads); splats; a type-annotation slot; the sentence states no default;
  the name is reassigned or used in the body (None-sentinel idioms).
- **Java "returns nothing"** now excludes returns inside lambdas and anonymous classes.
- **Returns-none.** A sentence that names a returned value ("returns None/False/an empty …") is not routed to FALSE.
- **Keywords.** `in`, `not`, `is`, `and`, `or` are no longer callees.
- **Effect.** No corpus verdict changes (v4→v5: 0 transitions). Second-extractor FALSE verdicts go from 3 to 0 (A104,
  B004, A100 — all on true sentences, recorded in data/false_audit_v3.csv history and as regression tests).
  Planted: caught 36.8% [26.4, 47.3], F→T 23.9%, precision 93.5%. The A171 true twin is no longer FALSE.
- **Audit guard.** `render.py` refuses to build if any corpus or second-extraction FALSE is unaudited, or if the test
  suite has a failing case.

## Regression and limitations suite
- `tests/test_engine.py`: 148 cases. 111 pass, 34 are documented limitations (known unsound or imprecise verdicts;
  none affects a corpus verdict), and 3 limitation cases now give sound outcomes.
- The limitations are: R3's F1–F10, F16, F17, T1–T15, T17, T18; implicit protocol calls; and Java constructor
  delegation.

## Audits (all by the AI assistant)
- **data/false_audit_v3.csv**, the 27 v3 FALSE verdicts: 1 correct refutation, 8 fact bugs, 5 names passed
  through **kwargs, 13 mis-slots. Local: 14 of 15 on true sentences or mis-slots.
- **The same file**, the 4 FALSE verdicts on planted TRUE twins (v4): 2 mis-slots, 1 correct refutation (the twin's
  label was inherited from a calls slot, but the sentence is false), and 1 engine bug (A171), fixed in v5.
- **data/true_audit.csv**, 40 random local TRUE verdicts (seed 20261110): 33 sentences assert more than the checked
  slot, 1 slot is unrelated to its sentence, and 6 are pure. Sentence-level decided share: 35.5% (any slot) and
  33.4% (all slots) of 740 texts, against 38.4% of claims. 99.7% of decided claims are TRUE.

## H2
- With one FALSE, the predictor is 1.0 for 69 of 70 explanations, so H2 as stated is untestable with this engine.
- H2 is reformulated as future work (certified-TRUE share vs. human-judged faithfulness).
- The judge disputes 13 of 285 judge-labelled TRUE claims.

## Determinism and hygiene
- `make run render` twice gives summary.json sha1 4bc30a85d16f46114380982504e95bc0a435aff3 both times, with no new
  LLM calls.
- package-clean run; binary-inclusive grep for the username and home paths is clean.

# Engine v6 — final pass after round-5 review (Accept ×3), 2026-11-10
v5 outputs are archived in results/v5/.

## In-sample wording (R1-M1, R2-S1)
- v5's guards were written from the 3 second-extraction FALSE verdicts of v4, so v5's 0 there is in-sample. The
  abstract and §IV now say so.
- The only out-of-sample result is v4 on the second extraction: 0 of 3 FALSE correct.
- The hard-coded `n_second_false_v4 = 3` is removed. The count now comes from audit rows `second_v4:*` in
  data/false_audit_v3.csv.

## Code ≠ Sec. III (R3-M1), fixed in code
- The returns "names a value" exemption (None/null/False/…, "or None") now applies on both branches. An explicit
  `return None` is no value, async functions return a coroutine, and generators give UNV for "returns nothing".
- Decorator FALSE passes the splat and body-use guards.
- Cheap should-fix code changes:
  - calls FALSE is blocked by dynamic call sites (subscript/call callee, `methodcaller`/`attrgetter`/`globals`);
  - default FALSE is blocked for decorated functions and symbolic signature defaults;
  - Python mutation now also counts augmented assignment and any non-pure method call.
- Suite: 169 cases. 126 behave as specified, 39 are documented limitations (incl. D1/D2 Java implicit `this`,
  C5 `super(..)`, C8 `del`, K3, K4), and 4 earlier limitations are now sound.
- Effect: 0 corpus, 0 second-extraction and 0 planted verdict changes vs v5.
- Planted: one more label error (pid 20, a TRUE twin that is false of the code) is removed. This gives 116 pairs,
  precision 95.5%, caught 36.2%.

## Reporting
- TRUE audit: 34/40 partial (85%, Wilson CI 71–93) and 6/40 pure (15%, CI 7–29), so about 6% of local claims are
  fully checked.
- Engine versions are named v1–v6. Abstract held-out wording is scoped ("held out from the first engine version's
  tuning").
- C3 wrong-evidence items show "partially checked"; the 67% vs ≈75% figure is stated for C2 only.
- The reformulated H2 is stratified by claim type and cites kept 72% vs certified false twins 24%.
- Table II shows "0 (none)" instead of "0.0 [0.0, 0.0]"; Table III caption is fixed; Fig. 1 labels are larger.
- To stay within 4 pages, the FActScore citation was removed (29 references) and the end matter merged.

## Determinism and hygiene
- `make run render` twice gives summary.json sha1 0ce4621fd25d2aff7e2d872f5e394501aff06a0a both times, with no new
  LLM calls.
- package-clean run; binary-inclusive grep clean.

# v6.1 — final verification fixes (2026-11-10)
- Default FALSE requires a literal signature default (`ast.literal_eval`).
- async + "returns nothing" gives UNV.
- Suite: 173 cases (130/39/4).
- No corpus, second-extraction or planted verdict changes. summary.json changed only by the reporting key
  `planted_audit_sides`. sha1 9f3609eb65a2771457166701aa4be02c35259643 is identical across two replays.
