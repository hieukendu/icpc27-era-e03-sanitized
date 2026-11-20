# Scoped-badge study: protocol specification, not registration

Status: no participants, no independent stimulus labels, no ethics approval or registration claimed.

Primary estimand: the conditional odds ratio for correct rejection of false sentences with genuinely supported subclaims, comparing scoped with generic badges while holding evidence fixed. It is the fixed scoped-condition coefficient in the reference partial-support stratum, conditional on participant/item intercepts. Claim truth, evidence validity and evidence sufficiency are separate annotation fields. A supported subclaim can coexist with a false sentence without being invalid evidence.

Three conditions: generic `checked`; scoped target plus unassessed content; prose with code links. Every condition offers identical access to code and evidence. The future scoped interface can distinguish supported static slots, tested stated inputs, weaker observed instances, partial support and not checked; refutation badges require independent human confirmation.

Every participant sees 24 unique items in three balanced blocks of eight. Rotate blocks across conditions using participant index modulo three. Each block has four true items (two fully supported, one partially supported, one no evidence) and four false items (two valid partial evidence, one misleading evidence, one no evidence). Every item appears in every condition across participants, without within-participant repetition. The six false partial-support items drive the primary contrast. This small item pool limits item-level generalization.

Two humans independently label sentence truth, validity, sufficiency and the proposed scope description; report agreement and adjudicate disagreements before recruitment. Provide identical evidence in the generic and scoped presentations of an item. Randomize order within each participant, counterbalance block order, and do not reuse a target sentence as an unbadged neighbor in another condition. Neighbor judgments are secondary and need separately validated stimuli; they are not included in this 24-item primary-design simulation.

Secondary measures: truth judgments on other cells, confidence and Brier scores, time, evidence comprehension, link clicks, and unbadged-neighbor judgments. A comprehension question asks what the displayed evidence actually establishes; clicking alone is not evidence inspection. Secondary contrasts are exploratory unless separately preregistered. Oversampling partial/misleading evidence must be disclosed.

Primary analysis on false sentences:

`reject ~ condition * evidence + (1 | participant) + (1 | item)`

Reference levels are generic and partial. Test `conditionscoped` two-sided with a Wald normal contrast at alpha .05. Report effect/interval, convergence and singularity. No pooled badge-versus-links interaction substitutes for this contrast.

Simulation uses `lme4::glmer`, binomial logit, Laplace approximation (`nAGQ=1`), bobyqa and maxfun=20000. N={36,72,108,144,216}, target OR={1,1.3,1.65,2.2}, participant/item SD pairs={(0.5,0.4),(1,0.8),(1.5,1.2)}. Conditional rejection intercept is logit(.5); misleading evidence has -.4 and no evidence +.3 logits; only scoped/partial gets the target effect. Links equal generic in the data-generating model. Seed is 20261111+10000*scenario_index; 1,000 repetitions per scenario.

Failures count as non-rejections in primary power; conditional-on-success power is also reported. Boundary-singular fits are counted separately from convergence failure. Report null rejection, Monte Carlo SE, and per-replicate estimates in the package. There are no treatment slopes, learning, dropout or annotation errors in the simulation; this restricts what it can justify. A minimum meaningful effect, independent stimuli, ethics approval, consent, debriefing and registration are prerequisites for a confirmatory recruitment target. Simulated outcomes are never presented as participant observations.
