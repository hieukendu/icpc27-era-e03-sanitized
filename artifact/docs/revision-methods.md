# Retrospective analysis specification

## Frozen inputs and provenance

`data/revision/frozen_engine.json` hashes the evaluated checker, fact/extraction/probe implementations, observed outcomes, original pair set, and original semantic audits. `replay_inputs.json` hashes every required raw observation/cache input. These do not assert that the corpus was untouched during engine development. All rounds were inspected in later versions.

## Pair flow and denominators

All 151 frozen pairs have both replay records (302 twins). The ledger stores each side's text, extraction status and outcome. Ordered exclusions reproduce the historical 116-pair cohort: 32 originals no longer slot-supported, then three known assistant-coded label-error pairs. The third cohort removes known label errors without conditioning on original support (148 pairs). No error record is erased. All original/mutated-side rates use the corresponding pair count, and extraction-loss rates use both twins. The labels are nominal construction labels, not independent truth.

The 31 historical audits were targeted at failures (30 mutated sides and one original side), not a representative truth-label sample. The ledger identifies the audited side; an audit of one side does not validate both. Some textual perturbations are malformed or change a descriptive noun rather than a code entity, which further limits deployment interpretation. Label-error uncertainty is not captured by bootstrap intervals. Untouched originals cannot be treated as gold because their nominal labels inherited engine outcomes.

## Assistant-corrected-slot diagnostic

All 123 S/D pairs (246 twins) have frozen input annotations. The assistant read paired text and selected source context, retained original-slot contextual grounding, applied explicit receiver/endpoint corrections and literal mutations, and marked 40 targets unrepresentable. Full text and unassessed qualifiers are retained. The diagnostic is not blinded, independent or gold: it starts from original extracted slots and was informed by existing failures. The freeze precedes running the corrected inputs through the checker. `prepare_slot_diagnostic.py` records explicit decisions; analysis checks the frozen annotation hash and never silently regenerates it.

One target is tested per twin, not a conjunction of every sentence clause. Unrepresentable targets are retained as a distinct output; they are not counted as successful checks. `slot_ablation.jsonl` contains the aligned before/after rows, and `slot_transitions.csv` the complete transition matrix. Differences locate sensitivity to representation; remaining support is not automatically a checker error, since nominal labels and selected subclaims may be wrong or partial.

## Audit sample and uncertainty

The 40 rows in `true_audit.csv` exactly equal Python `random.Random(20261110).sample(frame, 40)`, where the frame is the 315 local-explainer slot-supported verdicts in frozen discharge file order. No row is duplicated or outside the frame. Of 822 local claims, the estimated full-scope fraction is `(315/822)*(6/40)`. Full-scope is the existing tentative assistant category `pure`; it does not establish sentence truth.

For finite-population success count K, retain every K in 0..315 for which `P(X<=6)>=.025` and `P(X>=6)>=.025` under Hypergeometric(N=315,K,n=40). The resulting 20..91 interval divided by 822 is 2.43%..11.07%. This is sampling uncertainty conditional on the fixed corpus and audit labels, not model-based generalization or uncertainty about annotation validity.

## Risk versus coverage

Policies were fixed without optimizing against audit labels: an independent exact call/parameter string-match baseline; supported exact structural rules; supported structural/data-flow rules; and all supported outcomes. The baseline does not strip receivers, perform suffix matching, analyze flow or issue refutations. All policies use the same frozen extracted inputs.

For local claims, risk means scope overstatement/unrelatedness among accepted sampled items. Coverage divides accepted claims by all 822 local claims. Missing labels remain unknown and produce worst-case bounds `known_errors/accepted` to `(known_errors+unknown)/accepted`; these are identification bounds, not confidence intervals. Since the sample frame was SS verdicts, baseline outputs outside that frame would also remain unknown. For policies whose accepted set lies entirely within the verified sampling frame, the artifact also reports an exact hypergeometric scope-error interval conditional on that accepted population and its observed audit sample size. Policies accepting items outside the frame receive no such interval. Neither these intervals nor the observed rates include semantic-label uncertainty.

For all 302 planted twins, risk is agreement with nominal sentence labels, with known label-error pairs treated as unknown. Remaining nominal labels are unvalidated, so bounds do not establish semantic accuracy. Slot-evidence correctness is a separate unmeasured construct; its bounds are [0,1]. The artifact does not turn an engine's own successful matching into a correctness label.

## Prevalence sensitivity

For each cohort, estimate sensitivity `t = CR on nominal false twins / false twins` and false-positive rate `f = CR on nominal true twins / true twins`. At assumed false-claim prevalence p, precision is `p*t / (p*t+(1-p)*f)` for p=.01,.05,.10,.25,.50. Function-cluster bootstrap (2,000 seeded draws) retains both twins and uses the same resample for t and f. Undefined draws are counted; intervals are omitted if more than 5% are undefined. No smoothing or deployment prevalence estimate is used. Very wide intervals, including 1, reflect rare false positives.
