from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__
from .http import FetchError, HTTPClient
from .sources import (
    MDBOOK_SOURCES,
    OFFICIAL_SOURCES,
    SyncError,
    sync_crate,
    sync_official,
    sync_std,
    sync_url,
)
from .store import AmbiguousPageError, Store


class NotFoundError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rust-docs-pp-cli",
        description="Offline, agent-native lookup for Rust and docs.rs documentation.",
        epilog=(
            'Start with: rust-docs-pp-cli which "borrow checker" --json\n'
            "Then read:  rust-docs-pp-cli context <slug-or-url> --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit JSON for agent consumption")
    parser.add_argument("--compact", action="store_true", help="omit search snippets and ranks")
    parser.add_argument("--db", metavar="PATH", help="override the SQLite database path")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    sync = commands.add_parser("sync", help="download and index documentation")
    sync_commands = sync.add_subparsers(dest="sync_command")
    official = sync_commands.add_parser("official", help="sync official mdBook sources")
    official.add_argument("sources", nargs="*", choices=OFFICIAL_SOURCES, metavar="SOURCE")
    for name in OFFICIAL_SOURCES:
        sync_commands.add_parser(name, help=f"sync {MDBOOK_SOURCES[name]['repository']}")
    sync_commands.add_parser("std", help="sync stable std, core and alloc rustdoc")
    crate = sync_commands.add_parser("crate", help="sync a crate from docs.rs")
    crate.add_argument("name", help="crate name, for example serde")
    crate.add_argument("--version", default="latest", help="docs.rs version (default: latest)")
    crate.add_argument(
        "--max-pages",
        type=int,
        default=300,
        metavar="N",
        help="maximum pages including the crate root; 0 means unlimited (default: 300)",
    )
    url = sync_commands.add_parser("url", help="cache one rustdoc page")
    url.add_argument("target", help="https://doc.rust-lang.org or https://docs.rs page URL")

    for name, help_text, default_limit in (
        ("which", "find the best documentation pages for a topic", 5),
        ("find", "full-text search across all indexed pages", 10),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("query", nargs="+", help="topic or natural-language question")
        command.add_argument("-n", "--limit", type=_positive_int, default=default_limit)
        command.add_argument("--source", default="", help="filter: book, std, crate:serde, ...")

    context = commands.add_parser("context", help="print one complete documentation page")
    context.add_argument("target", help="slug, partial path, or exact URL from which/find")

    examples = commands.add_parser("examples", help="find paste-ready code blocks")
    examples.add_argument("query", nargs="+", help="topic, type, trait, or code symbol")
    examples.add_argument("-n", "--limit", type=_positive_int, default=5)
    examples.add_argument("--language", default="", help="rust, toml, bash, json, ...")
    examples.add_argument("--source", default="", help="filter: book, std, crate:serde, ...")

    sections = commands.add_parser("sections", help="list sources, sections, and page counts")
    sections.add_argument("--source", default="", help="filter by source")
    commands.add_parser("doctor", help="report index health and synchronization state")
    commands.add_parser("version", help="print the CLI version")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.command == "version":
        return {"version": __version__}
    with Store(args.db) as store:
        if args.command == "doctor":
            result = store.stats()
            result["version"] = __version__
            if not result["ok"]:
                result["hint"] = "Run: rust-docs-pp-cli sync"
            return result
        if args.command in {"which", "find"}:
            query = " ".join(args.query)
            matches = store.search_pages(query, args.limit, args.source)
            if args.compact:
                matches = [
                    {key: hit[key] for key in ("title", "url", "source", "slug")} for hit in matches
                ]
            return {"query": query, "matches": matches}
        if args.command == "context":
            page = store.get_page(args.target)
            if page is None:
                raise NotFoundError(f"Page not found: {args.target}")
            return {
                "url": page.url,
                "title": page.title,
                "source": page.source,
                "section": page.section,
                "slug": page.slug,
                "headings": page.headings,
                "content": page.content,
            }
        if args.command == "examples":
            query = " ".join(args.query)
            examples = store.search_examples(query, args.limit, args.language, args.source)
            if args.compact:
                examples = [
                    {key: hit[key] for key in ("page_url", "language", "code")} for hit in examples
                ]
            return {"query": query, "language": args.language, "examples": examples}
        if args.command == "sections":
            return {"sections": store.sections(args.source)}
        if args.command == "sync":
            client = HTTPClient(timeout=120)

            def progress(message: str) -> None:
                print(message, file=sys.stderr, flush=True)

            command = args.sync_command
            if command is None:
                results = [
                    sync_official(store, client, name, progress) for name in OFFICIAL_SOURCES
                ]
            elif command == "official":
                sources = args.sources or list(OFFICIAL_SOURCES)
                results = [sync_official(store, client, name, progress) for name in sources]
            elif command in MDBOOK_SOURCES:
                results = [sync_official(store, client, command, progress)]
            elif command == "std":
                results = [sync_std(store, client, progress)]
            elif command == "crate":
                results = [
                    sync_crate(
                        store,
                        client,
                        args.name,
                        args.version,
                        args.max_pages,
                        progress,
                    )
                ]
            elif command == "url":
                results = [sync_url(store, client, args.target, progress)]
            else:
                raise SyncError(f"Unknown sync command: {command}")
            return {
                "ok": True,
                "db_path": str(store.path),
                "results": [result.as_dict() for result in results],
                "pages_indexed": sum(result.pages for result in results),
                "examples_stored": sum(result.examples for result in results),
            }
    raise RuntimeError(f"Unhandled command: {args.command}")


def print_result(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    command = args.command
    if command == "version":
        print(result["version"])
    elif command in {"which", "find"}:
        matches = result["matches"]
        if not matches:
            print("No matches. Run `rust-docs-pp-cli doctor` to check the index.")
            return
        for index, hit in enumerate(matches, 1):
            print(f"{index}. [{hit['source']}] {hit['title']}")
            print(f"   {hit['url']}")
            print(f"   slug: {hit['slug']}")
            if "snippet" in hit:
                print(f"   {hit['snippet']}")
            print()
    elif command == "context":
        print(f"# {result['title']}\nSource: {result['url']}\n\n{result['content']}")
    elif command == "examples":
        if not result["examples"]:
            print("No examples found.")
            return
        for index, example in enumerate(result["examples"], 1):
            print(f"--- {index}. [{example['language']}] {example.get('page_title', '')} ---")
            if "page_url" in example:
                print(example["page_url"])
            print(example["code"])
            print()
    elif command == "sections":
        for section in result["sections"]:
            print(f"{section['source']:<20} {section['section']:<45} {section['pages']:>5}")
    elif command == "doctor":
        print(f"rust-docs-pp-cli {result['version']}")
        print(f"Database:  {result['db_path']}")
        print(f"Pages:     {result['pages']}")
        print(f"Examples:  {result['examples']}")
        print(f"Last sync: {result['last_sync_at'] or 'never'}")
        for source in result["sources"]:
            detail = f" — {source['detail']}" if source["detail"] else ""
            print(f"  {source['source']}: {source['pages']} pages{detail}")
        if result.get("hint"):
            print(f"\nHint: {result['hint']}")
    elif command == "sync":
        for item in result["results"]:
            truncated = " (truncated)" if item.get("truncated") else ""
            print(
                f"{item['source']}: {item['pages_indexed']} pages, "
                f"{item['examples_stored']} examples{truncated}"
            )
        print(f"Database: {result['db_path']}")


def main(argv: Sequence[str] | None = None) -> None:
    raw = list(argv if argv is not None else sys.argv[1:])
    cleaned, globals_found = _extract_globals(raw)
    parser = build_parser()
    args = parser.parse_args(cleaned)
    for key, value in globals_found.items():
        setattr(args, key, value)
    try:
        result = run(args)
        if result is not None:
            print_result(args, result)
    except NotFoundError as exc:
        _error(args, str(exc), 3)
    except AmbiguousPageError as exc:
        _error(args, str(exc), 3, {"target": exc.target, "candidates": exc.candidates})
    except (FetchError, SyncError) as exc:
        _error(args, str(exc), 5)
    except sqlite3.Error as exc:
        _error(args, f"SQLite error: {exc}", 1)
    except KeyboardInterrupt:
        _error(args, "Interrupted", 130)
    except Exception as exc:  # Keep subprocess-consuming agents informed without a traceback.
        if os.environ.get("RUST_DOCS_DEBUG"):
            raise
        _error(args, f"{type(exc).__name__}: {exc}", 1)


def _extract_globals(argv: list[str]) -> tuple[list[str], dict[str, Any]]:
    cleaned: list[str] = []
    found: dict[str, Any] = {"json": False, "compact": False, "db": None}
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--json":
            found["json"] = True
        elif value == "--compact":
            found["compact"] = True
        elif value == "--db":
            if index + 1 >= len(argv):
                break
            index += 1
            found["db"] = argv[index]
        elif value.startswith("--db="):
            found["db"] = value.split("=", 1)[1]
        else:
            cleaned.append(value)
        index += 1
    return cleaned, found


def _error(
    args: argparse.Namespace, message: str, code: int, extra: dict[str, Any] | None = None
) -> None:
    if args.json:
        payload = {"error": message, "exit_code": code}
        if extra:
            payload.update(extra)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Error: {message}", file=sys.stderr)
        if extra and extra.get("candidates"):
            for candidate in extra["candidates"]:
                print(f"  {candidate['slug']} — {candidate['url']}", file=sys.stderr)
    raise SystemExit(code)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


if __name__ == "__main__":
    main()
