# Details retained alongside the narrative revision

The 2026-11-12 manuscript reorganizes presentation without changing analyses, labels, checker outputs or simulations. This working document supplements the unchanged E03-scoped-v1 release; the frozen release is not overwritten.

## Engine history and secondary hypotheses

Rounds 3–5 were untouched only during v1 development. Versions v2–v6 used all rounds, and failures from a second extraction informed later rule guards. Every current-engine finding is retrospective and exploratory. The detailed model and corpus profile remains in `manuscript/generated/tab_profile.tex` and the historical result files.

The assistant audit of v3's 27 candidate-refutation outcomes judged 26 to concern true sentences or incorrect slots. The current corpus has one candidate refutation, judged correct by the assistant after in-sample revision. The v4 second extraction produced three candidates judged incorrect, and later guards used those cases. These are debugging observations, not independent accuracy estimates.

The earlier H2 predictor, SS/(SS+CR), equals one for 69 of 70 eligible explanations. This leaves too little variation for a credible correlation test. Human-judged explanation faithfulness and alternative predictors remain future work.

The planned 270-function collection was limited by shared GPU time to 60 functions in five balanced rounds. Qwen2.5-Coder-14B and Qwen2.5-14B cover all rounds; Haiku covers rounds 1–3. Model re-typing agreement is a model comparison, not human semantic validation.

## Implementation and execution limits

The frozen v6.1 checker uses tree-sitter and Python/Java reaching-definitions analysis with kills, joins, loops and conservative call effects. Dynamic dispatch, aliases, nested definitions, implicit protocols and heap effects remain limitations; 39 regression cases deliberately document unsound or imprecise behavior.

Blind probe synthesis sees the signature and claim, not the body. Repository code is parsed only. EvalPlus probes ran with a five-second timeout under `python -I` and macOS `sandbox-exec`, denying network and writes outside a temporary directory, without a memory limit. Replay consumes cached probe observations without executing generated code.

## Full analysis and study specifications

- `semantic-contract.md` and `detailed-rules.md`: outcome meanings, per-rule guards and unresolved scope.
- `revision-methods.md`: all cohort denominators, exact audit interval, fixed policies, unknown-label bounds and function-clustered prevalence sensitivity.
- `badge-study.md`: full 24-item allocation, true-item evidence categories, study model, primary contrast, safeguards and simulation assumptions.
- `results/revision/simulation/power_1000.csv`: all 60 simulation cells; replicate files retain all 60,000 fitted-model results.

The simulation covers N = 36, 72, 108, 144, 216; target OR = 1, 1.3, 1.65, 2.2; and participant/item SD pairs (0.5, 0.4), (1, 0.8), (1.5, 1.2). Each cell has 1,000 seeded repetitions. No sample size is recommended without an agreed minimum meaningful effect and independently validated stimuli. No participant outcomes, ethics approval or registration are claimed.
