from __future__ import annotations

import hashlib
import io
import platform
import posixpath
import re
import tarfile
import tomllib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import PurePosixPath
from urllib.parse import urlparse

from .http import FetchError, HTTPClient
from .models import Page, SyncResult
from .parsing import markdown_page, normalize_language
from .rustdoc import html_page, rustdoc_links
from .store import Store

MDBOOK_SOURCES = {
    "book": {
        "repository": "rust-lang/book",
        "branch": "main",
        "prefix": "src",
        "base_url": "https://doc.rust-lang.org/book/",
    },
    "reference": {
        "repository": "rust-lang/reference",
        "branch": "master",
        "prefix": "src",
        "base_url": "https://doc.rust-lang.org/reference/",
    },
    "cargo": {
        "repository": "rust-lang/cargo",
        "branch": "master",
        "prefix": "doc/book/src",
        "base_url": "https://doc.rust-lang.org/cargo/",
    },
    "rust-by-example": {
        "repository": "rust-lang/rust-by-example",
        "branch": "master",
        "prefix": "src",
        "base_url": "https://doc.rust-lang.org/rust-by-example/",
    },
}
OFFICIAL_SOURCES = tuple(MDBOOK_SOURCES)
_INCLUDE_RE = re.compile(r"^\s*\{\{#(include|rustdoc_include|playground)\s+([^}]+)\}\}\s*$")
_CRATE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
Progress = Callable[[str], None]


class SyncError(RuntimeError):
    pass


def sync_official(store: Store, client: HTTPClient, source: str, progress: Progress) -> SyncResult:
    if source not in MDBOOK_SOURCES:
        raise SyncError(f"Unknown official source: {source}")
    config = MDBOOK_SOURCES[source]
    archive_url = (
        f"https://codeload.github.com/{config['repository']}/tar.gz/refs/heads/{config['branch']}"
    )
    progress(f"Downloading {source}: {config['repository']}@{config['branch']}")
    response = client.get(archive_url)
    members = _text_tar_members(response.body, mode="r:gz")
    prefix = config["prefix"]
    pages: list[Page] = []
    for name, text in members.items():
        path = PurePosixPath(name)
        parts = path.parts
        if len(parts) < 3 or parts[1] != prefix.split("/")[0] or not name.endswith(".md"):
            continue
        root_prefix = f"{parts[0]}/{prefix}/"
        if not name.startswith(root_prefix):
            continue
        relative = name[len(root_prefix) :]
        if relative in {"SUMMARY.md", "README.md"} or relative.startswith("."):
            continue
        expanded = _expand_includes(text, name, members)
        slug = relative[:-3]
        url = config["base_url"] + slug + ".html"
        pages.append(markdown_page(expanded, url=url, source=source, slug=slug))
    if not pages:
        raise SyncError(f"No Markdown pages found in {archive_url}")
    examples = store.replace_source(
        source,
        pages,
        detail=f"{config['repository']}@{config['branch']}",
    )
    progress(f"Indexed {len(pages)} pages from {source}")
    return SyncResult(source, len(pages), examples, f"{config['repository']}@{config['branch']}")


def sync_std(store: Store, client: HTTPClient, progress: Progress) -> SyncResult:
    progress("Resolving the stable Rust documentation archive")
    manifest = tomllib.loads(
        client.get("https://static.rust-lang.org/dist/channel-rust-stable.toml").text()
    )
    target = _host_target()
    package = manifest["pkg"]["rust-docs"]["target"].get(target)
    if not package or not package.get("available"):
        raise SyncError(f"Rust documentation is unavailable for target {target}")
    archive_url = package.get("xz_url") or package.get("url")
    expected_hash = package.get("xz_hash") if package.get("xz_url") else package.get("hash")
    progress(f"Downloading std/core/alloc docs for {target}")
    response = client.get(archive_url)
    if expected_hash and hashlib.sha256(response.body).hexdigest() != expected_hash:
        raise SyncError("SHA-256 mismatch for the Rust documentation archive")
    version = manifest["pkg"]["rust"]["version"].split(" ", 1)[0]
    pages: list[Page] = []
    with tarfile.open(
        fileobj=io.BytesIO(response.body), mode="r:xz" if package.get("xz_url") else "r:gz"
    ) as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".html"):
                continue
            marker = "/share/doc/rust/html/"
            if marker not in member.name:
                continue
            relative = member.name.split(marker, 1)[1]
            if not relative.startswith(("std/", "core/", "alloc/")):
                continue
            if "/src/" in relative or relative.endswith("/all.html"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            document = extracted.read().decode("utf-8", errors="replace")
            slug = relative[:-5]
            url = "https://doc.rust-lang.org/" + relative
            pages.append(html_page(document, url=url, source="std", slug=slug))
    if not pages:
        raise SyncError("No std/core/alloc HTML pages found in the Rust archive")
    examples = store.replace_source("std", pages, detail=f"Rust {version}; target {target}")
    progress(f"Indexed {len(pages)} pages from std/core/alloc")
    return SyncResult("std", len(pages), examples, f"Rust {version}; target {target}")


def sync_crate(
    store: Store,
    client: HTTPClient,
    crate: str,
    version: str,
    max_pages: int,
    progress: Progress,
) -> SyncResult:
    if not _CRATE_RE.fullmatch(crate):
        raise SyncError(f"Invalid crate name: {crate}")
    if not _VERSION_RE.fullmatch(version):
        raise SyncError(f"Invalid crate version: {version}")
    if max_pages < 0:
        raise SyncError("max_pages must be zero (unlimited) or greater")
    source = f"crate:{crate}"
    root_response = _crate_root(client, crate, version)
    root_url = root_response.url
    if not root_url.endswith("/"):
        root_url += "/"
    root_document = root_response.text()
    pages = [html_page(root_document, url=root_url, source=source, slug="root")]
    progress(f"Reading the docs.rs item index for {crate} {version}")
    all_url = root_url + "all.html"
    all_response = client.get(all_url)
    links = rustdoc_links(all_response.text(), base_url=all_response.url, root_url=root_url)
    total_available = len(links) + 1
    truncated = bool(max_pages and len(links) >= max_pages)
    selected = links[: max_pages - 1] if max_pages else links
    failures: list[str] = []

    def fetch(url: str) -> Page:
        response = client.get(url)
        slug = urlparse(url).path[len(urlparse(root_url).path) :]
        slug = slug[:-5] if slug.endswith(".html") else slug.rstrip("/")
        return html_page(response.text(), url=url, source=source, slug=slug or "root")

    workers = min(4, max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch, url): url for url in selected}
        completed = 0
        for future in as_completed(futures):
            url = futures[future]
            try:
                pages.append(future.result())
            except (FetchError, ValueError, RuntimeError) as exc:
                failures.append(f"{url}: {exc}")
            completed += 1
            if completed % 50 == 0:
                progress(f"Indexed {completed}/{len(selected)} docs.rs item pages")
    if len(pages) == 1 and selected and len(failures) == len(selected):
        raise SyncError(f"Unable to index any item pages for {crate}: {failures[0]}")
    pages.sort(key=lambda page: page.url)
    detail = f"docs.rs {crate} {version}; {total_available} pages available"
    if failures:
        detail += f"; {len(failures)} pages failed"
    examples = store.replace_source(source, pages, detail=detail)
    progress(f"Indexed {len(pages)} pages from {source}")
    return SyncResult(source, len(pages), examples, detail, truncated)


def sync_url(store: Store, client: HTTPClient, url: str, progress: Progress) -> SyncResult:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"doc.rust-lang.org", "docs.rs"}:
        raise SyncError("Only https://doc.rust-lang.org and https://docs.rs URLs are supported")
    progress(f"Downloading {url}")
    response = client.get(url)
    final_url = response.url
    parts = [part for part in urlparse(final_url).path.split("/") if part]
    if parsed.netloc == "docs.rs":
        if len(parts) < 3:
            raise SyncError("A docs.rs rustdoc URL is required, not a crate information page")
        source = f"crate:{parts[0]}"
        slug_parts = parts[3:]
    else:
        first = parts[0] if parts else "std"
        source = first if first in {"std", "core", "alloc", *OFFICIAL_SOURCES} else "url"
        slug_parts = parts[1:] if source != "url" else parts
    slug = "/".join(slug_parts) or "root"
    if slug.endswith(".html"):
        slug = slug[:-5]
    page = html_page(response.text(), url=final_url, source=source, slug=slug)
    store.add_page(page)
    return SyncResult(source, 1, len(page.examples), final_url)


def _crate_root(client: HTTPClient, crate: str, version: str):
    candidates = [crate]
    underscored = crate.replace("-", "_")
    if underscored != crate:
        candidates.append(underscored)
    last_error: FetchError | None = None
    for library in candidates:
        url = f"https://docs.rs/{crate}/{version}/{library}/"
        try:
            response = client.get(url)
            if "rustdoc" not in response.text()[:5000].lower():
                raise SyncError(f"Not a rustdoc page: {response.url}")
            return response
        except FetchError as exc:
            last_error = exc
    raise SyncError(f"Unable to open docs.rs for {crate} {version}: {last_error}")


def _text_tar_members(body: bytes, mode: str) -> dict[str, str]:
    members: dict[str, str] = {}
    text_suffixes = {".md", ".rs", ".toml", ".json", ".yaml", ".yml", ".txt", ".sh", ".html"}
    with tarfile.open(fileobj=io.BytesIO(body), mode=mode) as archive:
        for member in archive:
            if not member.isfile() or member.size > 2_000_000:
                continue
            if PurePosixPath(member.name).suffix not in text_suffixes:
                continue
            extracted = archive.extractfile(member)
            if extracted:
                members[member.name] = extracted.read().decode("utf-8", errors="replace")
    return members


def _expand_includes(text: str, member_name: str, members: dict[str, str], depth: int = 0) -> str:
    if depth > 4:
        return text
    output: list[str] = []
    in_fence = False
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if not match:
            if line.lstrip().startswith(("```", "~~~")):
                in_fence = not in_fence
            output.append(line)
            continue
        reference = match.group(2).strip()
        direct = posixpath.normpath(posixpath.join(posixpath.dirname(member_name), reference))
        included_name = direct if direct in members else ""
        anchor = ""
        if not included_name:
            base_reference, separator, anchor = reference.partition(":")
            candidate = posixpath.normpath(
                posixpath.join(posixpath.dirname(member_name), base_reference)
            )
            if separator and candidate in members:
                included_name = candidate
        if not included_name:
            output.append(f"<!-- unresolved mdBook include: {reference} -->")
            continue
        included = members[included_name]
        if included_name.endswith(".md"):
            output.append(_expand_includes(included, included_name, members, depth + 1))
        else:
            included = _select_anchor(included, anchor).rstrip()
            if in_fence:
                output.append(included)
            else:
                suffix = PurePosixPath(included_name).suffix.lstrip(".") or "text"
                output.extend([f"```{normalize_language(suffix)}", included, "```"])
    return "\n".join(output)


def _select_anchor(text: str, anchor: str) -> str:
    """Apply mdBook ANCHOR selection and remove non-rendered anchor markers."""
    if not anchor or anchor == "all" or ":" in anchor:
        selected = text.splitlines()
    else:
        selected = []
        active = False
        found = False
        for line in text.splitlines():
            start = re.search(r"\bANCHOR:\s*([^\s*]+)", line)
            end = re.search(r"\bANCHOR_END:\s*([^\s*]+)", line)
            if start:
                if start.group(1) == anchor:
                    active = True
                    found = True
                continue
            if end:
                if end.group(1) == anchor:
                    active = False
                continue
            if active:
                selected.append(line)
        if not found:
            selected = text.splitlines()
    return "\n".join(line for line in selected if not re.search(r"\bANCHOR(?::|_END:)", line))


def _host_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm = machine in {"arm64", "aarch64"}
    if system == "windows":
        return "aarch64-pc-windows-msvc" if arm else "x86_64-pc-windows-msvc"
    if system == "darwin":
        return "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
    return "aarch64-unknown-linux-gnu" if arm else "x86_64-unknown-linux-gnu"
