from __future__ import annotations

import re
from pathlib import PurePosixPath

from .models import Example, Page

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
_HEADING_RE = re.compile(r"^#{2,3}\s+(.+?)\s*$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([^\s`]*)")
_DIRECTIVE_RE = re.compile(r"^\s*\{\{#(?:include|rustdoc_include|playground)\s+[^}]+\}\}\s*$")


def markdown_page(markdown: str, *, url: str, source: str, slug: str, title: str = "") -> Page:
    """Convert one mdBook Markdown file into an indexable page."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = text.split("\n")
    found_title = title.strip()
    headings: list[str] = []
    examples: list[Example] = []
    body: list[str] = []
    in_fence = False
    fence_marker = ""
    language = "text"
    code: list[str] = []

    for line in lines:
        fence = _FENCE_RE.match(line)
        if fence and (not in_fence or fence.group(1).startswith(fence_marker)):
            if in_fence:
                value = "\n".join(code).strip()
                if len(value) >= 2:
                    examples.append(Example(language=language, code=value))
                code = []
                in_fence = False
                fence_marker = ""
            else:
                in_fence = True
                fence_marker = fence.group(1)
                language = normalize_language(fence.group(2))
            body.append(line)
            continue
        if in_fence:
            code.append(line)
            body.append(line)
            continue

        if not found_title and (match := _TITLE_RE.match(line)):
            found_title = match.group(1).strip()
        elif match := _HEADING_RE.match(line):
            heading = _plain_inline(match.group(1))
            if heading and len(heading) < 200:
                headings.append(heading)
        body.append(line)

    if not found_title and headings:
        # Current rust-lang/book chapters use one H2 as the page title.
        found_title = headings.pop(0)
    if not found_title:
        found_title = PurePosixPath(slug).name.replace("-", " ").replace("_", " ").title()
    section = str(PurePosixPath(slug).parent)
    if section == ".":
        section = "root"
    return Page(
        url=url,
        title=_plain_inline(found_title),
        source=source,
        section=section,
        slug=slug,
        content="\n".join(body).strip(),
        headings=headings,
        examples=examples,
    )


def normalize_language(value: str) -> str:
    value = value.strip().lower().split(",", 1)[0]
    if value in {"rs", "rust", "rust,ignore", "ignore", "no_run", "should_panic"}:
        return "rust"
    if value in {"sh", "shell", "bash", "console", "terminal"}:
        return "bash"
    if value in {"yml", "yaml"}:
        return "yaml"
    if value in {"js", "javascript"}:
        return "javascript"
    if value in {"py", "python"}:
        return "python"
    if value in {"toml", "json", "text", "txt"}:
        return "toml" if value == "toml" else "json" if value == "json" else "text"
    return value or "text"


def _plain_inline(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    return re.sub(r"[*_~]", "", value).strip()
