from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

from .models import Page
from .parsing import markdown_page

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}
_SKIP_TAGS = {"script", "style", "button", "rustdoc-toolbar", "svg"}


class _RustdocHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.main_depth = 0
        self.skip_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.in_pre = False
        self.pre_parts: list[str] = []
        self.pre_language = "text"

    @property
    def active(self) -> bool:
        return self.main_depth > 0 and self.skip_depth == 0

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs_list)
        if tag == "title":
            self.in_title = True
        if self.main_depth == 0:
            if attrs.get("id") == "main-content" or tag == "article":
                self.main_depth = 1
                self.out.append("\n")
            return
        if tag not in _VOID_TAGS:
            self.main_depth += 1
        if self.skip_depth:
            if tag not in _VOID_TAGS:
                self.skip_depth += 1
            return
        classes = attrs.get("class", "") or ""
        if tag in _SKIP_TAGS or (tag == "summary" and "hideme" in classes):
            if tag not in _VOID_TAGS:
                self.skip_depth = 1
            return
        if self.in_pre:
            if tag in {"br", "div"}:
                self.pre_parts.append("\n")
            return
        if tag == "pre":
            self.in_pre = True
            self.pre_parts = []
            self.pre_language = _language_from_classes(classes)
        elif tag in {"h1", "h2", "h3", "h4"}:
            self.out.append(f"\n\n{'#' * int(tag[1])} ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in {"p", "div", "section", "details", "tr", "table", "ul", "ol"}:
            self.out.append("\n")
        elif tag == "br":
            self.out.append("\n")
        elif tag == "code":
            self.out.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if self.main_depth == 0:
            return
        if self.skip_depth:
            if tag not in _VOID_TAGS:
                self.skip_depth -= 1
            self.main_depth -= 1
            return
        if self.in_pre and tag != "pre":
            self.main_depth -= 1
            return
        if tag == "pre" and self.in_pre:
            code = "".join(self.pre_parts).strip("\n")
            self.out.append(f"\n```{self.pre_language}\n{code}\n```\n")
            self.in_pre = False
            self.pre_parts = []
        elif tag in {
            "h1",
            "h2",
            "h3",
            "h4",
            "p",
            "div",
            "section",
            "details",
            "tr",
            "table",
            "ul",
            "ol",
        }:
            self.out.append("\n")
        elif tag == "code" and not self.in_pre:
            self.out.append("`")
        if tag not in _VOID_TAGS:
            self.main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self.active:
            return
        if self.in_pre:
            self.pre_parts.append(data)
        else:
            self.out.append(data)

    def markdown(self) -> str:
        value = "".join(self.out).replace("\x00", "")
        lines: list[str] = []
        in_fence = False
        for line in value.splitlines():
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                lines.append(line.strip())
            elif in_fence:
                lines.append(line.rstrip())
            else:
                lines.append(re.sub(r"[ \t]+", " ", line).strip())
        value = "\n".join(lines)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip()


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def html_page(document: str, *, url: str, source: str, slug: str) -> Page:
    parser = _RustdocHTMLParser()
    parser.feed(document)
    parser.close()
    title = html.unescape("".join(parser.title_parts)).strip()
    title = re.sub(r"\s+-\s+Rust\s*$", "", title)
    return markdown_page(
        parser.markdown(),
        url=url,
        source=source,
        slug=slug,
        title=title or PureSlug(slug).title,
    )


def rustdoc_links(document: str, *, base_url: str, root_url: str) -> list[str]:
    """Return unique, canonical rustdoc item links below root_url."""
    parser = _LinkParser()
    parser.feed(document)
    root = urlparse(root_url)
    root_path = root.path if root.path.endswith("/") else root.path + "/"
    links: set[str] = set()
    for href in parser.hrefs:
        absolute = urldefrag(urljoin(base_url, href))[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != root.netloc:
            continue
        if not parsed.path.startswith(root_path):
            continue
        if not parsed.path.endswith(".html") or parsed.path.endswith("/all.html"):
            continue
        if "/src/" in parsed.path or "/static.files/" in parsed.path:
            continue
        links.add(absolute)
    return sorted(links)


def _language_from_classes(classes: str) -> str:
    values = classes.lower().split()
    if any(value in {"rust", "rust-example-rendered", "item-decl"} for value in values):
        return "rust"
    for language in ("toml", "json", "bash", "console", "python", "javascript", "yaml", "text"):
        if language in values:
            return "bash" if language == "console" else language
    return "rust" if any("rust" in value for value in values) else "text"


class PureSlug:
    """Small title fallback without coupling the parser to URL conventions."""

    def __init__(self, slug: str) -> None:
        self.title = slug.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()
