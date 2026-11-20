# Slot-support contract (frozen checker v6.1)

This is a retrospective, heuristic evidence instrument. It does not certify sentence truth.
The engine implementation and raw observations are frozen in `data/revision/frozen_engine.json`.

| Raw code | Manuscript/display label | Meaning |
|---|---|---|
| `true` | slot-supported (SS) | A modeled fact, may-path, or stated-input probe supports the extracted target under the rule's scope. |
| `false` | candidate refutation (CR) | A heuristic rule contradicts the target. Semantic confirmation is required. |
| `consistent` | consistent | Weaker compatibility, e.g. control-only flow, indirect names or instance observations. |
| `unverifiable` | not checked | A policy exclusion, unsupported fragment, unresolved grounding or failed probe validation. Inspect `rule` and `evidence` for the reason. |
| `undischargeable` | outside evidence scope | Rationale typed outside this implementation's evidence sources. Design records might support it. |
| `lost` (planted evaluation only) | extraction unmatched | No extracted claim matched the planted text; retained in denominators. |

The evidence sources are tree-sitter syntax facts, Python/Java reaching definitions and executed EvalPlus probes.
These sources do not establish general natural-language entailment. Candidate-refutation guards are not a proof of soundness.

## Records

`results/revision/claim_contracts.jsonl` retains the original model explanation separately from extractor claim text (which may be a paraphrase), a normalized predicate/arguments object, the raw outcome and display label, the rule, its evidence and scope. `original_sentences` retains each source sentence and its character span. `matching_source_sentence_indices` records verbatim containment only; paraphrases are not assigned an invented source sentence. `verbatim_in_explanation` distinguishes literal excerpts. `unresolved_remainder` deliberately retains the entire claim: it does not pretend that an automatic span partition proves any leftover clause has been checked. `sentence_truth` is unassessed.

Corrected-slot annotations also retain complete original planted sentences, receiver spellings, qualifier flags, and the whole unassessed remainder. Flags are a convenience for inspection, not a complete semantic parse. Targets that cannot faithfully be represented by one slot are marked unrepresentable rather than repaired to a different claim.

## Evidence boundaries

| Kind | Admitted target/evidence | Not established |
|---|---|---|
| Structural | Syntactic occurrence/name/default/decorator under the specific rule | Reachability, correct runtime receiver, conditions, argument semantics, universal occurrence |
| Data-flow | A grounded may-analysis path | Feasible executions, full heap/interprocedural effects, unconditional dependency |
| Behavioural | A specific stated input/output probe with guards and (for passing probes) a killed mutant | Other inputs, quantified behavior, internal steps |
| Purpose | Subject-anchored membership or a scoped probe | Extra purpose/functionality not represented by that evidence |
| Rationale | No corresponding source in this evidence set | Impossibility of checking with richer evidence |

See [detailed rule specification](detailed-rules.md), [frozen implementation](../src/discharge.py),
[flow analysis](../src/defuse.py), and [regression/limitations suite](../tests/test_engine.py).
The suite intentionally includes documented unsound or imprecise cases. Passing the suite does not make the checker sound.
