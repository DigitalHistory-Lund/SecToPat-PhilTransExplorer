"""Build site derivatives from corpus/data/index.db.

Reads the SQLite metadata DB and writes pre-aggregated CSV/JSON files into
data/derivatives/. The Quarto site reads only these derivatives, never the DB.

Outputs:
    topic_totals.csv          25 rows   topic, count, first_year, last_year
    topic_year_counts.csv     ~5.5k     year, topic, count
    articles_per_year.csv     ~222      year, count
    experiment_articles.json  455       year, title, doi, authors[], canonical_url

Privacy: no file contains url_path / pdf_path / html_path / pdf_url / xml_url.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "corpus" / "data" / "index.db"
OUT_DIR = ROOT / "data" / "derivatives"

EXPECTED_TOTAL = 8545
EXPECTED_EXPERIMENT = 455


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        articles = pd.read_sql_query(
            """
            SELECT url_path, title, doi, publication_date, topic, canonical_url
            FROM articles
            """,
            conn,
        )
        authors = pd.read_sql_query(
            """
            SELECT article_url_path, position, name
            FROM authors
            ORDER BY article_url_path, position
            """,
            conn,
        )
    finally:
        conn.close()

    articles["year"] = pd.to_numeric(
        articles["publication_date"].str.slice(0, 4), errors="coerce"
    ).astype("Int64")
    articles["topic"] = articles["topic"].fillna("Unknown")

    assert len(articles) == EXPECTED_TOTAL, (
        f"articles row count {len(articles)} != expected {EXPECTED_TOTAL}"
    )

    topic_totals = (
        articles.groupby("topic", as_index=False)
        .agg(
            count=("url_path", "size"),
            first_year=("year", "min"),
            last_year=("year", "max"),
        )
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    assert topic_totals["count"].sum() == EXPECTED_TOTAL
    experiment_row = topic_totals.loc[topic_totals["topic"] == "Experiment"]
    assert len(experiment_row) == 1 and int(experiment_row["count"].iloc[0]) == EXPECTED_EXPERIMENT, (
        f"Experiment count {experiment_row['count'].iloc[0] if len(experiment_row) else 'missing'} "
        f"!= expected {EXPECTED_EXPERIMENT}"
    )
    topic_totals.to_csv(OUT_DIR / "topic_totals.csv", index=False)

    dated = articles.dropna(subset=["year"]).copy()
    dated["year"] = dated["year"].astype(int)

    articles_per_year = (
        dated.groupby("year", as_index=False)
        .agg(count=("url_path", "size"))
        .sort_values("year")
        .reset_index(drop=True)
    )
    articles_per_year.to_csv(OUT_DIR / "articles_per_year.csv", index=False)

    topic_year_counts = (
        dated.groupby(["year", "topic"], as_index=False)
        .agg(count=("url_path", "size"))
        .sort_values(["year", "topic"])
        .reset_index(drop=True)
    )
    assert topic_year_counts["count"].sum() == articles_per_year["count"].sum()
    topic_year_counts.to_csv(OUT_DIR / "topic_year_counts.csv", index=False)

    authors_by_article: dict[str, list[str]] = {}
    for url_path, name in zip(authors["article_url_path"], authors["name"]):
        authors_by_article.setdefault(url_path, []).append(name)

    experiment = articles.loc[articles["topic"] == "Experiment"].copy()
    experiment_records = []
    for row in experiment.itertuples(index=False):
        experiment_records.append(
            {
                "year": int(row.year) if pd.notna(row.year) else None,
                "title": row.title,
                "doi": row.doi,
                "authors": authors_by_article.get(row.url_path, []),
                "canonical_url": row.canonical_url,
            }
        )
    experiment_records.sort(
        key=lambda r: (r["year"] if r["year"] is not None else 99999, r["title"] or "")
    )
    assert len(experiment_records) == EXPECTED_EXPERIMENT, (
        f"experiment_records {len(experiment_records)} != {EXPECTED_EXPERIMENT}"
    )
    forbidden = {"url_path", "pdf_path", "html_path", "pdf_url", "xml_url"}
    for rec in experiment_records:
        leaked = forbidden & set(rec.keys())
        assert not leaked, f"forbidden key in output: {leaked}"

    with (OUT_DIR / "experiment_articles.json").open("w") as f:
        json.dump(experiment_records, f, ensure_ascii=False, indent=2)

    print(
        f"Wrote derivatives to {OUT_DIR.relative_to(ROOT)}/:\n"
        f"  topic_totals.csv         {len(topic_totals):>5} rows\n"
        f"  articles_per_year.csv    {len(articles_per_year):>5} rows  ({articles_per_year['year'].min()}-{articles_per_year['year'].max()})\n"
        f"  topic_year_counts.csv    {len(topic_year_counts):>5} rows\n"
        f"  experiment_articles.json {len(experiment_records):>5} records\n"
        f"All assertions passed."
    )


if __name__ == "__main__":
    main()
