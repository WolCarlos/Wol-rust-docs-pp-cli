from __future__ import annotations

import os
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Page

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    section TEXT NOT NULL,
    slug TEXT NOT NULL,
    content TEXT NOT NULL,
    headings TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS pages_source_idx ON pages(source);
CREATE INDEX IF NOT EXISTS pages_slug_idx ON pages(slug);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title, source, section, slug, content, headings,
    content='pages', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, source, section, slug, content, headings)
    VALUES (new.rowid, new.title, new.source, new.section, new.slug, new.content, new.headings);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, source, section, slug, content, headings)
    VALUES ('delete', old.rowid, old.title, old.source, old.section, old.slug,
            old.content, old.headings);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, source, section, slug, content, headings)
    VALUES ('delete', old.rowid, old.title, old.source, old.section, old.slug,
            old.content, old.headings);
    INSERT INTO pages_fts(rowid, title, source, section, slug, content, headings)
    VALUES (new.rowid, new.title, new.source, new.section, new.slug, new.content, new.headings);
END;
CREATE TABLE IF NOT EXISTS examples (
    id TEXT PRIMARY KEY,
    page_url TEXT NOT NULL,
    page_title TEXT NOT NULL,
    source TEXT NOT NULL,
    language TEXT NOT NULL,
    code TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS examples_page_url_idx ON examples(page_url);
CREATE INDEX IF NOT EXISTS examples_source_idx ON examples(source);
CREATE VIRTUAL TABLE IF NOT EXISTS examples_fts USING fts5(
    page_title, source, language, code,
    content='examples', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS examples_ai AFTER INSERT ON examples BEGIN
    INSERT INTO examples_fts(rowid, page_title, source, language, code)
    VALUES (new.rowid, new.page_title, new.source, new.language, new.code);
END;
CREATE TRIGGER IF NOT EXISTS examples_ad AFTER DELETE ON examples BEGIN
    INSERT INTO examples_fts(examples_fts, rowid, page_title, source, language, code)
    VALUES ('delete', old.rowid, old.page_title, old.source, old.language, old.code);
END;
CREATE TRIGGER IF NOT EXISTS examples_au AFTER UPDATE ON examples BEGIN
    INSERT INTO examples_fts(examples_fts, rowid, page_title, source, language, code)
    VALUES ('delete', old.rowid, old.page_title, old.source, old.language, old.code);
    INSERT INTO examples_fts(rowid, page_title, source, language, code)
    VALUES (new.rowid, new.page_title, new.source, new.language, new.code);
END;
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class AmbiguousPageError(RuntimeError):
    def __init__(self, target: str, candidates: list[dict[str, str]]):
        super().__init__(f"Ambiguous page: {target}")
        self.target = target
        self.candidates = candidates


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def default_db_path() -> Path:
    if override := os.environ.get("RUST_DOCS_DB"):
        return Path(override).expanduser()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return root / "rust-docs-pp-cli" / "data.db"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "rust-docs-pp-cli" / "data.db"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "rust-docs-pp-cli" / "data.db"


class Store:
    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path).expanduser().resolve() if path else default_db_path().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def replace_source(self, source: str, pages: list[Page], *, detail: str = "") -> int:
        example_count = sum(len(page.examples) for page in pages)
        with self.conn:
            self.conn.execute("DELETE FROM examples WHERE source = ?", (source,))
            self.conn.execute("DELETE FROM pages WHERE source = ?", (source,))
            for page in pages:
                self._insert_page(page)
            self.set_meta(f"source:{source}:synced_at", utc_now())
            self.set_meta(f"source:{source}:pages", str(len(pages)))
            if detail:
                self.set_meta(f"source:{source}:detail", detail)
            self.set_meta("last_sync_at", utc_now())
        return example_count

    def add_page(self, page: Page) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM examples WHERE page_url = ?", (page.url,))
            self.conn.execute("DELETE FROM pages WHERE url = ?", (page.url,))
            self._insert_page(page)
            self.set_meta(f"source:{page.source}:synced_at", utc_now())
            self.set_meta("last_sync_at", utc_now())

    def _insert_page(self, page: Page) -> None:
        self.conn.execute(
            """INSERT INTO pages (id, url, title, source, section, slug, content, headings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                page.id,
                page.url,
                page.title,
                page.source,
                page.section,
                page.slug,
                page.content,
                "\n".join(page.headings),
            ),
        )
        for index, example in enumerate(page.examples):
            self.conn.execute(
                """INSERT INTO examples (id, page_url, page_title, source, language, code)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    f"{page.id}-{index}",
                    page.url,
                    page.title,
                    page.source,
                    example.language,
                    example.code,
                ),
            )

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """INSERT INTO meta (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )

    def get_meta(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else ""

    def search_pages(self, query: str, limit: int = 10, source: str = "") -> list[dict[str, Any]]:
        fts = fts_query(query)
        if not fts:
            return []
        hits = self._search_pages(fts, query, limit, source)
        tokens = fts.split(" ")
        if not hits and len(tokens) > 1:
            hits = self._search_pages(" OR ".join(tokens), query, limit, source)
        return hits

    def _search_pages(self, fts: str, query: str, limit: int, source: str) -> list[dict[str, Any]]:
        where = "pages_fts MATCH ?"
        params: list[Any] = [fts]
        if source:
            where += " AND p.source = ?"
            params.append(source)
        params.append(limit)
        rows = self.conn.execute(
            f"""SELECT p.url, p.title, p.source, p.section, p.slug,
                       snippet(pages_fts, 4, '[', ']', '…', 18) AS snippet,
                       bm25(pages_fts, 12.0, 2.0, 3.0, 10.0, 1.0, 4.0) AS rank
                FROM pages_fts JOIN pages p ON p.rowid = pages_fts.rowid
                WHERE {where} ORDER BY rank LIMIT ?""",
            params,
        ).fetchall()
        return [
            {
                "url": row["url"],
                "title": row["title"],
                "source": row["source"],
                "section": row["section"],
                "slug": row["slug"],
                "snippet": row["snippet"],
                "rank": round(float(row["rank"]), 6),
            }
            for row in rows
        ]

    def get_page(self, target: str) -> Page | None:
        target = target.strip()
        if not target:
            return None
        variants = [target]
        if target.endswith(".html"):
            variants.append(target[:-5])
        elif not target.endswith("/"):
            variants.extend([target + ".html", target + "/index.html"])
        for value in variants:
            row = self.conn.execute("SELECT * FROM pages WHERE url = ?", (value,)).fetchone()
            if row:
                return _row_to_page(row)
        for value in variants:
            rows = self.conn.execute(
                "SELECT * FROM pages WHERE slug = ? ORDER BY length(url), url LIMIT 6", (value,)
            ).fetchall()
            if len(rows) == 1:
                return _row_to_page(rows[0])
            if len(rows) > 1:
                raise AmbiguousPageError(target, _candidates(rows))
        rows = self.conn.execute(
            """SELECT * FROM pages WHERE url LIKE ? OR slug LIKE ?
               ORDER BY length(url), url LIMIT 6""",
            (f"%{target}%", f"%{target}%"),
        ).fetchall()
        if len(rows) == 1:
            return _row_to_page(rows[0])
        if len(rows) > 1:
            exact_path = [
                row for row in rows if str(row["url"]).rstrip("/").endswith(target.rstrip("/"))
            ]
            if len(exact_path) == 1:
                return _row_to_page(exact_path[0])
            raise AmbiguousPageError(target, _candidates(rows))
        return None

    def search_examples(
        self, query: str, limit: int = 5, language: str = "", source: str = ""
    ) -> list[dict[str, Any]]:
        fts = fts_query(query)
        if not fts:
            return []
        rows = self._search_examples(fts, limit, language, source)
        tokens = fts.split(" ")
        if not rows and len(tokens) > 1:
            rows = self._search_examples(" OR ".join(tokens), limit, language, source)
        return rows

    def _search_examples(
        self, fts: str, limit: int, language: str, source: str
    ) -> list[dict[str, Any]]:
        where = "examples_fts MATCH ?"
        params: list[Any] = [fts]
        if language:
            where += " AND e.language = ?"
            params.append(language.lower())
        if source:
            where += " AND e.source = ?"
            params.append(source)
        params.append(limit)
        rows = self.conn.execute(
            f"""SELECT e.page_url, e.page_title, e.source, e.language, e.code,
                       bm25(examples_fts, 5.0, 2.0, 1.0, 1.0) AS rank
                FROM examples_fts JOIN examples e ON e.rowid = examples_fts.rowid
                WHERE {where} ORDER BY rank LIMIT ?""",
            params,
        ).fetchall()
        return [
            {
                "page_url": row["page_url"],
                "page_title": row["page_title"],
                "source": row["source"],
                "language": row["language"],
                "code": row["code"],
                "rank": round(float(row["rank"]), 6),
            }
            for row in rows
        ]

    def sections(self, source: str = "") -> list[dict[str, Any]]:
        params: tuple[Any, ...] = (source,) if source else ()
        where = "WHERE source = ?" if source else ""
        rows = self.conn.execute(
            f"""SELECT source, section, COUNT(*) AS pages FROM pages {where}
                GROUP BY source, section ORDER BY source, pages DESC, section""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        pages = self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        examples = self.conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0]
        rows = self.conn.execute(
            """SELECT source, COUNT(*) AS pages, MAX(url) AS sample_url FROM pages
               GROUP BY source ORDER BY source"""
        ).fetchall()
        sources = [
            {
                "source": row["source"],
                "pages": row["pages"],
                "synced_at": self.get_meta(f"source:{row['source']}:synced_at"),
                "detail": self.get_meta(f"source:{row['source']}:detail"),
            }
            for row in rows
        ]
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "ok": pages > 0,
            "db_path": str(self.path),
            "db_bytes": size,
            "pages": pages,
            "examples": examples,
            "last_sync_at": self.get_meta("last_sync_at"),
            "sources": sources,
            "sqlite_version": sqlite3.sqlite_version,
        }


def fts_query(query: str) -> str:
    tokens = re.findall(r"[^\W_]+(?:_[^\W_]+)*", query.lower(), flags=re.UNICODE)
    return " ".join('"' + token.replace('"', "") + '"' for token in tokens)


def _row_to_page(row: sqlite3.Row) -> Page:
    return Page(
        url=row["url"],
        title=row["title"],
        source=row["source"],
        section=row["section"],
        slug=row["slug"],
        content=row["content"],
        headings=row["headings"].split("\n") if row["headings"] else [],
    )


def _candidates(rows: list[sqlite3.Row]) -> list[dict[str, str]]:
    return [
        {"title": row["title"], "url": row["url"], "source": row["source"], "slug": row["slug"]}
        for row in rows[:5]
    ]
