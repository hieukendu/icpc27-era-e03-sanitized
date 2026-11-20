# What Evidence Supports an AI Code Explanation?

This private project snapshot contains the working manuscript and its research artifact as of 12 November 2026. The manuscript uses IEEEtran conference format at 10pt. Semantic validation and participant outcomes retain the status stated in the paper. No new experiments were run to create this snapshot.

## Project structure

| Path | Contents |
| --- | --- |
| `manuscript/main.tex` | Manuscript entry point and document settings. |
| `manuscript/main.pdf` | Compiled five-page paper. Main text and disclosures end on page 4. References occupy page 5. |
| `manuscript/references.bib` | Bibliography records. |
| `manuscript/sections/` | Abstract and section sources. |
| `manuscript/generated/` | Numerical macros, tables and plots generated from analysis results. Some retained outputs support artifact-level detail. |
| `manuscript/figures/` | Finished Figure 1 artwork. The distributed copy contains a flattened image. |
| `artifact/README.md` | Detailed methods, dependencies and reproduction instructions. |
| `artifact/Makefile` | Analysis, rendering, testing and PDF build commands. |
| `artifact/requirements.txt` | Python dependencies. |
| `artifact/src/` | Analysis, checking, simulation and rendering programs. |
| `artifact/tests/` | Regression and consistency checks. |
| `artifact/data/` | Frozen analysis inputs, selections and annotations. Upstream repository clones are omitted. |
| `artifact/results/` | Cached observations, analysis outputs and design-simulation results. |
| `artifact/docs/` | Method specifications, annotation provenance and release documentation. |
| `artifact/licenses/` | Applicable licenses and artwork attribution. |

## Build and reproduce

From the project root, run `make -C artifact pdf` to rebuild the manuscript with an installed LaTeX distribution. The build requires IEEEtran, BibTeX, pgfplots and the packages loaded in `manuscript/main.tex`. The build copy supports pgfplots 1.17. Read `artifact/README.md` before running analyses, and use the documented pinned dependencies. Network download and model-generation commands are separate from cached analysis.

The distributed snapshot includes `MANIFEST.json` and `verify_package.py`. Run `python3 verify_package.py` to check its contents before rebuilding. A rebuild can legitimately change generated outputs and the PDF hash.

## Distribution boundaries

The sanitized repository and Drive archive include only this root README and Markdown files under `artifact/`. They exclude Figure 1 source, separate icon assets, previous Git history, local notes, review reports, old manuscript snapshots, nested release archives, repository clones and build caches. The finished illustration remains visible in the paper and in a flattened image. Artwork attribution is retained under `artifact/licenses/`.

Local source projects retain their original editing files. Existing repositories and frozen release tags remain unchanged. This snapshot is a separate private distribution and does not replace the frozen evidence package cited in the manuscript.

## Anonymous release

The blinded artifact entry point is available at [anonymous.4open.science](https://anonymous.4open.science/r/icpc27-era-e03-sanitized-637D/). The private GitHub repository remains the source repository; this URL is the reviewer-facing anonymous mirror.
