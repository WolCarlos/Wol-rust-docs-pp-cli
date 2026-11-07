from __future__ import annotations

import unittest

from rust_docs_pp_cli.parsing import markdown_page, normalize_language
from rust_docs_pp_cli.rustdoc import html_page, rustdoc_links
from rust_docs_pp_cli.sources import _expand_includes, _select_anchor


class MarkdownTests(unittest.TestCase):
    def test_h2_is_title_when_h1_is_missing(self) -> None:
        page = markdown_page(
            "## Validating References\n\nText.\n\n### Details\n\n```rust,ignore\nlet x = 1;\n```",
            url="https://example.test/page.html",
            source="book",
            slug="page",
        )
        self.assertEqual(page.title, "Validating References")
        self.assertEqual(page.headings, ["Details"])
        self.assertEqual(page.examples[0].language, "rust")
        self.assertEqual(page.examples[0].code, "let x = 1;")

    def test_headings_inside_code_are_ignored(self) -> None:
        page = markdown_page(
            "# Title\n\n```text\n## not a heading\n```\n\n## Real heading",
            url="https://example.test/",
            source="test",
            slug="root",
        )
        self.assertEqual(page.headings, ["Real heading"])

    def test_language_aliases(self) -> None:
        self.assertEqual(normalize_language("rust,ignore,does_not_compile"), "rust")
        self.assertEqual(normalize_language("console"), "bash")
        self.assertEqual(normalize_language(""), "text")


class IncludeTests(unittest.TestCase):
    def test_include_inside_fence_does_not_create_nested_fence(self) -> None:
        members = {
            "repo/src/page.md": "```rust\n{{#rustdoc_include ../listing.rs:here}}\n```",
            "repo/listing.rs": (
                '// ANCHOR: here\nfn main() {\n    println!("ok");\n}\n// ANCHOR_END: here'
            ),
        }
        expanded = _expand_includes(members["repo/src/page.md"], "repo/src/page.md", members)
        self.assertEqual(expanded.count("```"), 2)
        self.assertIn('    println!("ok");', expanded)
        self.assertNotIn("ANCHOR", expanded)

    def test_include_outside_fence_gets_language(self) -> None:
        members = {
            "repo/src/page.md": "{{#include ../Cargo.toml}}",
            "repo/Cargo.toml": '[package]\nname = "demo"',
        }
        expanded = _expand_includes(members["repo/src/page.md"], "repo/src/page.md", members)
        self.assertTrue(expanded.startswith("```toml\n[package]"))

    def test_missing_anchor_falls_back_to_cleaned_source(self) -> None:
        source = "// ANCHOR: other\nlet x = 1;\n// ANCHOR_END: other"
        self.assertEqual(_select_anchor(source, "missing"), "let x = 1;")


class RustdocTests(unittest.TestCase):
    def test_rustdoc_html_preserves_code_and_ignores_chrome(self) -> None:
        document = """<!doctype html><html><head><title>Vec in std::vec - Rust</title></head>
        <body><nav>navigation</nav><section id="main-content">
        <h1>Struct Vec</h1><script>bad()</script><p>A growable array.</p>
        <pre class="rust"><code><span>fn main() {</span>
    <span>println!("ok");</span>
}</code></pre></section></body></html>"""
        page = html_page(
            document,
            url="https://doc.rust-lang.org/std/vec/struct.Vec.html",
            source="std",
            slug="std/vec/struct.Vec",
        )
        self.assertEqual(page.title, "Vec in std::vec")
        self.assertNotIn("navigation", page.content)
        self.assertNotIn("bad()", page.content)
        self.assertIn('    println!("ok");', page.examples[0].code)

    def test_links_are_limited_to_the_crate_root(self) -> None:
        document = """<a href="trait.Serialize.html#x">Serialize</a>
        <a href="/other/latest/other/trait.Other.html">Other</a>
        <a href="all.html">All</a><a href="../src/lib.rs.html">Source</a>"""
        links = rustdoc_links(
            document,
            base_url="https://docs.rs/serde/latest/serde/all.html",
            root_url="https://docs.rs/serde/latest/serde/",
        )
        self.assertEqual(links, ["https://docs.rs/serde/latest/serde/trait.Serialize.html"])


if __name__ == "__main__":
    unittest.main()
