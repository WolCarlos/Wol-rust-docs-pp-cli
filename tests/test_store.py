from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rust_docs_pp_cli.models import Example, Page
from rust_docs_pp_cli.store import AmbiguousPageError, Store, fts_query


def page(slug: str, title: str, content: str, source: str = "book") -> Page:
    return Page(
        url=f"https://doc.rust-lang.org/{source}/{slug}.html",
        title=title,
        source=source,
        section="root",
        slug=slug,
        content=content,
        headings=["Usage"],
        examples=[Example("rust", "let mut values = Vec::new();\nvalues.push(1);")],
    )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "docs.db"
        self.store = Store(self.db_path)
        self.store.replace_source(
            "book",
            [
                page("ownership", "What Is Ownership?", "Ownership and the borrow checker."),
                page("vectors", "Storing Values with Vectors", "Vec<T> has capacity and push."),
            ],
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_search_context_and_examples(self) -> None:
        hits = self.store.search_pages("borrow checker", 5)
        self.assertEqual(hits[0]["slug"], "ownership")
        self.assertEqual(self.store.get_page("ownership").title, "What Is Ownership?")
        self.assertEqual(
            self.store.get_page("https://doc.rust-lang.org/book/vectors.html")["slug"]
            if isinstance(self.store.get_page("https://doc.rust-lang.org/book/vectors.html"), dict)
            else self.store.get_page("https://doc.rust-lang.org/book/vectors.html").slug,
            "vectors",
        )
        examples = self.store.search_examples("Vec::new", 5, "rust")
        self.assertEqual(len(examples), 2)

    def test_replace_source_removes_stale_rows_only_for_that_source(self) -> None:
        self.store.replace_source("std", [page("std/vec", "Vec", "A vector", "std")])
        self.store.replace_source("book", [page("ownership", "Ownership", "New body")])
        stats = self.store.stats()
        self.assertEqual(stats["pages"], 2)
        self.assertIsNone(self.store.get_page("vectors"))
        self.assertEqual(self.store.get_page("std/vec").source, "std")

    def test_source_filter_and_empty_query(self) -> None:
        self.assertEqual(self.store.search_pages("::: ???"), [])
        self.assertEqual(self.store.search_pages("Vec", source="std"), [])
        self.assertEqual(len(self.store.search_pages("Vec", source="book")), 1)

    def test_ambiguous_partial_match_returns_candidates(self) -> None:
        self.store.replace_source(
            "book",
            [page("one/shared", "One", "first"), page("two/shared", "Two", "second")],
        )
        with self.assertRaises(AmbiguousPageError) as caught:
            self.store.get_page("shared")
        self.assertEqual(len(caught.exception.candidates), 2)

    def test_fts_escapes_operators(self) -> None:
        self.assertEqual(fts_query("Vec<T> OR String::from"), '"vec" "t" "or" "string" "from"')


if __name__ == "__main__":
    unittest.main()
