# Bibliography metadata check — 2026-11-11

All 29 entries were rechecked against publisher-deposited Crossref metadata, ACL Anthology BibTeX, NeurIPS proceedings, arXiv metadata, or the official tree-sitter repository. Retrieved records and source URLs are in `results/revision/bibliography_metadata.json`. This is metadata verification, not independent verification of every cited scientific claim.

Corrections:

- Nam et al., *Using an LLM to Help With Code Understanding*, DOI 10.1145/3597503.3639187: publisher record gives pages 1–13; replaced 1184–1196.
- ETF and ReFEree: added their ACL Anthology DOIs after checking the publisher BibTeX, including authors, year and pages.
- Thakur et al.: retained the source's spelling `Exection-Traces` verbatim without injecting `[sic]` into the title field.
- Tree-sitter: the original reference identified release 0.27.2, but the replay environment uses Python binding 0.26.0. The citation now identifies that installed binding; grammar package versions are pinned separately in requirements.txt.

Other checked years, author lists, venue/page metadata and preprint identities agree at the granularity used in the manuscript. Publisher page ranges for PACM journals can be article-local rather than continuous proceedings pages; recorded ranges were retained when supported. ArXiv citations remain identified as preprints and version notes are preserved. No new related-work claims were introduced in this revision.
