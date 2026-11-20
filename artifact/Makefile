# Attest artifact (E03 Evidence-Bearing Explanations). All LLM responses are cached in results/llm_cache/,
# so `make all` replays deterministically without a model server once the cache is populated.
# PY: a Python 3.13 interpreter with numpy, scipy, tree-sitter (+python/java grammars), datasets.
PY      ?= python3
ROUNDS  ?= 5
FRONTIER_ROUNDS ?= 3
SIM_CORES ?= 12
MS      := ../manuscript

.PHONY: all data warm select run render pdf clean package-clean

all: replay

# Corpora (network: GitHub shallow clones + Hugging Face EvalPlus; skipped if already present) and static facts
data:
	test -s data/corpus_a.jsonl || $(PY) src/data_corpus_a.py
	test -s data/corpus_b.jsonl || $(PY) src/data_corpus_b.py
	$(PY) src/facts.py

# Fill the LLM cache function-by-function along the work order (needs Ollama; long; resumable)
warm:
	$(PY) -u src/warm.py $(ROUNDS)
	$(PY) -u src/warm.py --frontier $(FRONTIER_ROUNDS)

# Freeze the analysed corpus at a complete round boundary (+ frontier subset = first FRONTIER_ROUNDS rounds)
select:
	$(PY) src/select_corpus.py $(ROUNDS)
	$(PY) -c "import json,sys;sys.path.insert(0,'src');from selection import work_order;json.dump(sorted(f for r in work_order()[:$(FRONTIER_ROUNDS)] for f in r),open('data/frontier_subset.json','w'))"

# Round-2 engine: re-typing and the different-family judge run before probes/discharge (probes need the types)
run:
	test -s data/selection.json || (echo "data/selection.json missing: run make select" && false)
	$(PY) src/facts.py
	$(PY) src/explain.py
	$(PY) src/extract.py first
	$(PY) src/extract.py second
	$(PY) src/retype.py
	$(PY) src/judge.py
	$(PY) src/probe.py
	$(PY) src/discharge.py
	$(PY) src/planted.py
	$(PY) src/analyze.py

render:
	$(PY) tests/test_engine.py > results/test_engine.log
	$(PY) src/render.py
	$(PY) src/render_revision.py

# Build-verify with pgfplots compat=1.17 (TeX Live 2020); the shipped source keeps compat=1.18
pdf:
	rm -rf build && mkdir -p build && cp -r $(MS)/main.tex $(MS)/references.bib $(MS)/sections $(MS)/generated $(MS)/figures build/
	sed -i.bak 's/compat=1.18/compat=1.17/' build/main.tex
	cd build && pdflatex -interaction=nonstopmode main.tex >/dev/null && bibtex main >/dev/null && \
	  pdflatex -interaction=nonstopmode main.tex >/dev/null && pdflatex -interaction=nonstopmode main.tex >/dev/null
	cp build/main.pdf $(MS)/main.pdf
	grep -c "undefined" build/main.log || true
	pdfinfo $(MS)/main.pdf | grep Pages

package-clean:
	rm -rf build src/__pycache__ tests/__pycache__
	find . -name '*.pyc' -delete

clean: package-clean
	rm -f results/explanations.jsonl results/claims*.jsonl results/probe_runs.jsonl results/discharge.jsonl \
	      results/planted.jsonl results/judge.jsonl results/retype.jsonl results/*.csv results/summary.json

.PHONY: replay revision test-revision simulate
replay:
	$(PY) src/replay_revision.py

revision:
	$(PY) src/revision_analysis.py

test-revision:
	$(PY) tests/test_revision.py

simulate:
	$(PY) src/run_simulation.py --cores $(SIM_CORES)
