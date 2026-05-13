# Philosophical Transactions Explorer

An interactive Quarto site for exploring metadata of the *Philosophical
Transactions of the Royal Society* across **1665–1886** — 8,545 articles,
2,679 unique author surface forms, 25 topical labels.

Part of the [_Secrets to Patent_](https://secretstopatents.org/) project.

🌐 **Live site:** <https://digitalhistory-lund.github.io/SecToPat-PhilTransExplorer/>

## What's here

| Path | Purpose |
| --- | --- |
| `index.qmd`, `topics.qmd`, `authors.qmd`, `length.qmd`, `dashboard.qmd`, `browse.qmd`, `about.qmd` | Site pages |
| `_quarto.yml` | Quarto site config |
| `scripts/build_derivatives.py` | Reads `corpus/data/index.db` → writes pre-aggregated CSV/JSON to `data/derivatives/` |
| `data/derivatives/` | Generated artifacts the site consumes; rebuildable, committed |
| `corpus/` | Git submodule containing the source SQLite catalogue (private) |
| `robots.txt` | Denies all crawlers except the Internet Archive |

## What is and isn't published

- ✅ Aggregate counts (articles per year, per topic, per author, per page length).
- ✅ Per-article bibliographic metadata: title, DOI, year, topic, author names,
  link to the article on royalsocietypublishing.org.
- ❌ The raw SQLite metadata file.
- ❌ Internal paths or URLs.

The `scripts/build_derivatives.py` script enforces this boundary at build time.

## Build it locally

Prerequisites: [Quarto](https://quarto.org/docs/get-started/) ≥ 1.7 and
Python ≥ 3.11.

```bash
git clone --recurse-submodules https://github.com/DigitalHistory-Lund/SecToPat-PhilTransExplorer.git
cd SecToPat-PhilTransExplorer

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Quarto's pre-render hook calls build_derivatives.py automatically:
quarto preview        # local dev with auto-reload
# or:
quarto render         # one-shot build into _site/
```

The build script asserts that totals reconcile (8,545 articles, 455 Experiment
articles, 8,081 articles with numeric pagination) and that no forbidden
columns leak into `data/derivatives/`.

## License

This work is licensed under a
[Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/)
(CC BY-NC 4.0). See [`LICENSE`](LICENSE).

## Citation

If you use this site or its derivative data, please cite the Zenodo deposit:
[10.5281/zenodo.20162091](https://doi.org/10.5281/zenodo.20162091).
Machine-readable metadata is in [`CITATION.cff`](CITATION.cff).

## Contact

For questions or feedback, contact Mathias Johansson at
[MathiasJohansson@kultur.lu.se](mailto:MathiasJohansson@kultur.lu.se),
or open an [issue](https://github.com/DigitalHistory-Lund/SecToPat-PhilTransExplorer/issues).
