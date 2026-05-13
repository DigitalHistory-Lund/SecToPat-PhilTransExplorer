"""Build site derivatives from corpus/data/index.db.

Reads the SQLite metadata DB and writes pre-aggregated CSV/JSON files into
data/derivatives/. The Quarto site reads only these derivatives, never the DB.

Outputs:
    topic_totals.csv                25 rows    topic, count, first_year, last_year
    topic_year_counts.csv         ~1.5k        year, topic, count
    articles_per_year.csv         ~222         year, count
    experiment_articles.json       455         year, title, doi, authors[], canonical_url
    author_productivity.csv     ~2,679         author_name, n_articles, first_year, last_year, span_years, n_topics
    author_year_counts_top50.csv ≤5k           author_name, year, count
    collab_size_distribution.csv  ~12          n_authors, n_articles
    length_distribution.csv        ~10         pages_bin, count
    length_by_topic.csv           ~100         topic, pages_bin, count
    length_per_year.csv           ~222         year, n_articles_with_pages, mean_pages, median_pages
    articles.json                8,545         id, title, doi, year, topic, n_pages, authors[], canonical_url

Privacy: no file contains url_path / pdf_path / html_path / pdf_url / xml_url.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "corpus" / "data" / "index.db"
OUT_DIR = ROOT / "data" / "derivatives"

EXPECTED_TOTAL = 8545
EXPECTED_AUTHOR_ROWS = 7640
EXPECTED_EXPERIMENT = 455
EXPECTED_NUMERIC_PAGES = 8081
EXPECTED_ANONYMOUS = 1643

PAGE_BINS = [0, 1, 2, 3, 4, 5, 10, 20, 50, 100, float("inf")]
PAGE_BIN_LABELS = ["1", "2", "3", "4", "5", "6–10", "11–20", "21–50", "51–100", "101+"]
TOP_AUTHORS = 50
TOP_TOPICS_FOR_LENGTH = 10
FORBIDDEN_KEYS = {"url_path", "pdf_path", "html_path", "pdf_url", "xml_url"}


def hash_id(url_path: str) -> str:
    return hashlib.sha1(url_path.encode("utf-8")).hexdigest()[:10]


def page_count(firstpage: object, lastpage: object) -> int | None:
    if firstpage is None or lastpage is None:
        return None
    if not (isinstance(firstpage, str) and isinstance(lastpage, str)):
        return None
    if not (firstpage.lstrip("-").isdigit() and lastpage.lstrip("-").isdigit()):
        return None
    fp, lp = int(firstpage), int(lastpage)
    if lp < fp:
        return None
    return lp - fp + 1


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        articles = pd.read_sql_query(
            """
            SELECT url_path, title, doi, publication_date, topic, canonical_url,
                   firstpage, lastpage
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

    assert len(articles) == EXPECTED_TOTAL, len(articles)
    assert len(authors) == EXPECTED_AUTHOR_ROWS, len(authors)

    articles["year"] = pd.to_numeric(
        articles["publication_date"].str.slice(0, 4), errors="coerce"
    ).astype("Int64")
    articles["topic"] = articles["topic"].fillna("Unknown")
    articles["pages"] = [
        page_count(fp, lp) for fp, lp in zip(articles["firstpage"], articles["lastpage"])
    ]
    articles["pages"] = articles["pages"].astype("Int64")

    pages_bin = pd.cut(
        articles["pages"].astype("Float64"),
        bins=PAGE_BINS,
        labels=PAGE_BIN_LABELS,
        right=True,
        include_lowest=False,
    )
    articles["pages_bin"] = pages_bin

    authors_by_article: dict[str, list[str]] = {}
    for url_path, name in zip(authors["article_url_path"], authors["name"]):
        authors_by_article.setdefault(url_path, []).append(name)

    # --- topic_totals.csv ----------------------------------------------------
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
    experiment_count = int(topic_totals.loc[topic_totals["topic"] == "Experiment", "count"].iloc[0])
    assert experiment_count == EXPECTED_EXPERIMENT, experiment_count
    topic_totals.to_csv(OUT_DIR / "topic_totals.csv", index=False)

    # --- articles_per_year.csv + topic_year_counts.csv -----------------------
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

    # --- experiment_articles.json -------------------------------------------
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
    assert len(experiment_records) == EXPECTED_EXPERIMENT
    with (OUT_DIR / "experiment_articles.json").open("w") as f:
        json.dump(experiment_records, f, ensure_ascii=False, indent=2)

    # --- collab_size_distribution.csv ---------------------------------------
    authors_per_article = (
        articles.set_index("url_path")
        .assign(n_authors=lambda d: d.index.map(lambda u: len(authors_by_article.get(u, []))))
    )
    collab = (
        authors_per_article["n_authors"]
        .value_counts()
        .rename_axis("n_authors")
        .reset_index(name="n_articles")
        .sort_values("n_authors")
        .reset_index(drop=True)
    )
    assert collab["n_articles"].sum() == EXPECTED_TOTAL
    anon_row = collab.loc[collab["n_authors"] == 0]
    assert len(anon_row) == 1 and int(anon_row["n_articles"].iloc[0]) == EXPECTED_ANONYMOUS
    collab.to_csv(OUT_DIR / "collab_size_distribution.csv", index=False)

    # --- author_productivity.csv + author_year_counts_top50.csv -------------
    authors_x_articles = authors.merge(
        articles[["url_path", "year", "topic"]],
        left_on="article_url_path",
        right_on="url_path",
        how="left",
    )

    author_prod = (
        authors_x_articles.groupby("name", as_index=False)
        .agg(
            n_articles=("article_url_path", "nunique"),
            first_year=("year", "min"),
            last_year=("year", "max"),
            n_topics=("topic", "nunique"),
        )
        .rename(columns={"name": "author_name"})
        .sort_values("n_articles", ascending=False)
        .reset_index(drop=True)
    )
    author_prod["span_years"] = (author_prod["last_year"] - author_prod["first_year"]).astype("Int64") + 1
    author_prod.to_csv(OUT_DIR / "author_productivity.csv", index=False)

    top_author_names = author_prod.head(TOP_AUTHORS)["author_name"].tolist()
    top_author_years = (
        authors_x_articles[authors_x_articles["name"].isin(top_author_names)]
        .dropna(subset=["year"])
        .assign(year=lambda d: d["year"].astype(int))
        .groupby(["name", "year"], as_index=False)
        .agg(count=("article_url_path", "nunique"))
        .rename(columns={"name": "author_name"})
        .sort_values(["author_name", "year"])
        .reset_index(drop=True)
    )
    top_author_years.to_csv(OUT_DIR / "author_year_counts_top50.csv", index=False)

    # --- length_distribution.csv + length_by_topic.csv + length_per_year.csv
    with_pages = articles.dropna(subset=["pages"]).copy()
    assert len(with_pages) == EXPECTED_NUMERIC_PAGES, len(with_pages)

    length_dist = (
        with_pages.groupby("pages_bin", observed=True, as_index=False)
        .agg(count=("url_path", "size"))
    )
    length_dist["pages_bin"] = pd.Categorical(length_dist["pages_bin"], categories=PAGE_BIN_LABELS, ordered=True)
    length_dist = length_dist.sort_values("pages_bin").reset_index(drop=True)
    assert length_dist["count"].sum() == EXPECTED_NUMERIC_PAGES
    length_dist.to_csv(OUT_DIR / "length_distribution.csv", index=False)

    top_length_topics = topic_totals.head(TOP_TOPICS_FOR_LENGTH + 1)
    top_length_topics = top_length_topics.loc[top_length_topics["topic"] != "Unknown"].head(TOP_TOPICS_FOR_LENGTH)
    top_length_topic_names = top_length_topics["topic"].tolist()
    length_by_topic = (
        with_pages[with_pages["topic"].isin(top_length_topic_names)]
        .groupby(["topic", "pages_bin"], observed=True, as_index=False)
        .agg(count=("url_path", "size"))
    )
    length_by_topic["pages_bin"] = pd.Categorical(length_by_topic["pages_bin"], categories=PAGE_BIN_LABELS, ordered=True)
    length_by_topic = length_by_topic.sort_values(["topic", "pages_bin"]).reset_index(drop=True)
    length_by_topic.to_csv(OUT_DIR / "length_by_topic.csv", index=False)

    with_pages_dated = with_pages.dropna(subset=["year"]).copy()
    with_pages_dated["year"] = with_pages_dated["year"].astype(int)
    length_per_year = (
        with_pages_dated.groupby("year", as_index=False)
        .agg(
            n_articles_with_pages=("pages", "size"),
            mean_pages=("pages", "mean"),
            median_pages=("pages", "median"),
        )
        .sort_values("year")
        .reset_index(drop=True)
    )
    length_per_year["mean_pages"] = length_per_year["mean_pages"].round(2)
    length_per_year.to_csv(OUT_DIR / "length_per_year.csv", index=False)

    # --- articles.json (all 8545 records, bibliographic only) ----------------
    records = []
    for row in articles.itertuples(index=False):
        records.append(
            {
                "id": hash_id(row.url_path),
                "title": row.title,
                "doi": row.doi,
                "year": int(row.year) if pd.notna(row.year) else None,
                "topic": row.topic,
                "n_pages": int(row.pages) if pd.notna(row.pages) else None,
                "authors": authors_by_article.get(row.url_path, []),
                "canonical_url": row.canonical_url,
            }
        )
    assert len(records) == EXPECTED_TOTAL
    for rec in records[:50]:
        leaked = FORBIDDEN_KEYS & set(rec.keys())
        assert not leaked, leaked
    with (OUT_DIR / "articles.json").open("w") as f:
        json.dump(records, f, ensure_ascii=False)

    print(
        f"Wrote derivatives to {OUT_DIR.relative_to(ROOT)}/:\n"
        f"  topic_totals.csv               {len(topic_totals):>5}\n"
        f"  articles_per_year.csv          {len(articles_per_year):>5}\n"
        f"  topic_year_counts.csv          {len(topic_year_counts):>5}\n"
        f"  experiment_articles.json       {len(experiment_records):>5}\n"
        f"  collab_size_distribution.csv   {len(collab):>5}\n"
        f"  author_productivity.csv        {len(author_prod):>5}\n"
        f"  author_year_counts_top50.csv   {len(top_author_years):>5}\n"
        f"  length_distribution.csv        {len(length_dist):>5}\n"
        f"  length_by_topic.csv            {len(length_by_topic):>5}\n"
        f"  length_per_year.csv            {len(length_per_year):>5}\n"
        f"  articles.json                  {len(records):>5}\n"
        f"All assertions passed."
    )


if __name__ == "__main__":
    main()
