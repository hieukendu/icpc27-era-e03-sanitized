# Detailed rules and known limitations

These describe frozen engine v6.1; raw `true` means slot-supported (SS), and raw `false` means candidate refutation (CR). The guards below are implementation heuristics, not a complete semantic fragment with a soundness theorem. The source and tests are authoritative for exact branching.

## Calls

A call site with the slot name supports the slot. Qualified mismatches, indirect references and bound-method aliases can yield consistent. CR guards exclude `with`, local-name calls, dynamic call sites (handler tables, `globals()[..]()`, `methodcaller`), `getattr`/`super`, bare references, and non-identifier-shaped callee claims.

Known gaps include implicit protocols (`len`/`__len__`, iteration, operators, deletion, formatting), Java constructor delegation, receiver stripping (`self.close` versus `fh.close`), and calls inside nested functions. Finding a call site does not show its execution, condition, recursion behavior, argument values or result.

## Parameters, defaults and decorators

Targets are signature names, literal defaults and decorators on the decorated definition. Parameter/decorator CR guards require no splats and a claimed name unused in the body. Default CR additionally requires explicit default wording, a non-type value, no decorators, and a literal signature default (`literal_eval`); Java default claims do not receive CR.

Membership qualifiers, nested annotations/definitions, anonymous classes, and properties defined elsewhere can escape the modeled scope. A parameter name does not establish its type, optionality or semantic role.

## Returns, raises, imports and membership

Own return statements support a narrow return/no-return target; `return None` has no returned value and async functions return a coroutine. Named-value sentences, generators and coroutines are guarded from the returns-nothing CR rule. Returns-content seeks a path from the backticked return object, excluding type names and nested helpers. Negation and scope words can remain unchecked.

Explicit raises can be caught locally or nested. Imported names are syntactic evidence, not proof of runtime use. Membership support requires an anchored subject; extra content produces consistent. A membership contradiction remains only a candidate refutation.

## Data flow

Python and Java share reaching-definitions machinery with kills, weak updates, joins, loop fixpoints, condition edges and early exits. Subscripts reduce to base objects; calls can map to every call site with that callee. A data path yields SS; control-only and sink-receiver paths yield consistent; compound endpoints are not checked.

CR requires a guarded syntactic fragment and no path in a conservative graph where non-pure calls may update arguments. Exclusions include try/with/match/assert/nested definitions/Java switch, unsupported exits, and mutation of non-fresh bindings. The implementation still has limitations involving wrappers (`csv.writer(buf)`), effectful pure-list entries, stores through call targets, globals/field reads by callees, implicit `this`, call-induced exits, destructuring and ternary conditions. Graph reachability is not sentence entailment or proof that an execution path exists.

## Probes

Only Corpus B is executed. Synthesis sees the signature and extracted text, not the body. Conditional statements require a non-vacuous precondition, checked lexically; unexpected exceptions invalidate probes. A passing probe must kill a first-order mutant. Stated probes can produce SS or type-compatible failing CR; instantiated probes produce consistent on pass and not checked on fail. These are observations on the stated inputs, not universal behavioral guarantees.

The original execution wrapper uses `python -I`, five-second limits and macOS `sandbox-exec`, denying network and writes outside a temporary directory. Reads and memory are not bounded. The offline revision replay executes neither generated probes nor repository functions; it consumes their frozen records.

## Audits and versions

All semantic audits were performed by an AI assistant and are tentative. Later engines used all rounds and second-extraction failures during development. No current-version independent hold-out or human ground-truth validation is claimed. Historical comments, variable names and logs retain old terminology for provenance; the display contract is [semantic-contract.md](semantic-contract.md).
