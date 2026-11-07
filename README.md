# rust-docs-pp-cli

Offline, agent-native CLI for the Rust Book, Rust Reference, Cargo Book, Rust by Example, the standard library, and crates documented on docs.rs.

```bash
rust-docs-pp-cli which "borrow checker" --json
rust-docs-pp-cli context ch04-02-references-and-borrowing --json
rust-docs-pp-cli examples "Vec::new" --language rust --json
```

The CLI downloads public documentation into a local SQLite + FTS5 index. Lookup commands then work offline and return bounded search results or exactly the page/example requested, avoiding repeated web navigation and unnecessary tokens.

## Features

- `which` and `find`: ranked full-text page search with snippets.
- `context`: complete page content by slug, path, or URL.
- `examples`: code-block search with language and source filters.
- `sections` and `doctor`: index map, counts, sync state, and database path.
- JSON on every command, compact search output, and typed exit codes.
- Atomic per-source replacement: a failed refresh does not delete the previous index.
- No runtime dependencies outside Python 3.11+ and its included SQLite FTS5 support.

## Install

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/WolCarlos/Wol-rust-docs-pp-cli.git
rust-docs-pp-cli sync
```

Or with pip:

```bash
python -m pip install git+https://github.com/WolCarlos/Wol-rust-docs-pp-cli.git
rust-docs-pp-cli sync
```

The default `sync` downloads the four official mdBook sources. No Rust toolchain, Go toolchain, account, or API key is required. If the command is not found after installation, ensure the uv/pip executable directory is on `PATH` or open a new shell.

For a one-command setup on Unix-like systems:

```bash
curl -sSf https://raw.githubusercontent.com/WolCarlos/Wol-rust-docs-pp-cli/main/install.sh | bash
```

On Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/WolCarlos/Wol-rust-docs-pp-cli/main/install.ps1 | iex
```

## Documentation sources

| Source | Sync command | Content |
|---|---|---|
| Rust Book | `rust-docs-pp-cli sync book` | Official `rust-lang/book` Markdown, including referenced code listings |
| Rust Reference | `rust-docs-pp-cli sync reference` | Official language reference |
| Cargo Book | `rust-docs-pp-cli sync cargo` | Cargo guide, commands, and reference |
| Rust by Example | `rust-docs-pp-cli sync rust-by-example` | Runnable examples and explanations |
| `std`, `core`, `alloc` | `rust-docs-pp-cli sync std` | Stable official rustdoc archive for the current host target |
| Any docs.rs crate | `rust-docs-pp-cli sync crate serde` | Crate root plus rustdoc item pages from its `all.html` index |
| One rustdoc page | `rust-docs-pp-cli sync url <url>` | A single doc.rust-lang.org or docs.rs page |

`sync` without a subcommand refreshes Book, Reference, Cargo, and Rust by Example. `sync official book cargo` refreshes only selected mdBook sources.

The standard-library archive is larger than the mdBook sources (roughly 24 MB compressed; the extracted search index is larger). Its SHA-256 is verified against the official stable Rust manifest.

For crates, `--version` defaults to `latest` and `--max-pages` defaults to 300 including the crate root:

```bash
rust-docs-pp-cli sync crate tokio --version latest --max-pages 300
rust-docs-pp-cli sync crate serde --max-pages 0   # all item pages
rust-docs-pp-cli sync url https://docs.rs/serde/latest/serde/trait.Serialize.html
```

A truncated crate sync is reported with `"truncated": true`. Use `--max-pages 0` when complete coverage is required. Crate downloads use at most four concurrent read-only requests.

## Agent workflow

Always start with `which`, then pass the returned slug or URL to `context`. Do not invent slugs.

```bash
# 1. Find a small set of candidate pages.
rust-docs-pp-cli which "how do lifetimes work" -n 3 --json

# 2. Read only the selected page.
rust-docs-pp-cli context ch10-03-lifetime-syntax --json

# 3. Optionally retrieve focused code examples.
rust-docs-pp-cli examples "lifetime annotation" --language rust -n 3 --json
```

Useful filters:

```bash
rust-docs-pp-cli which "Vec push capacity" --source std --json
rust-docs-pp-cli which "Serialize derive" --source crate:serde --json
rust-docs-pp-cli examples "cargo test" --source cargo --language bash --json
rust-docs-pp-cli which "ownership" --compact --json
```

All lookup commands are offline. Run `sync` again when documentation needs refreshing; `doctor --json` exposes per-source sync timestamps.

## Command reference

| Command | Purpose |
|---|---|
| `sync [official] [SOURCES...]` | Refresh all or selected official mdBook sources |
| `sync std` | Refresh stable `std`, `core`, and `alloc` rustdoc |
| `sync crate NAME [--version V] [--max-pages N]` | Refresh a docs.rs crate |
| `sync url URL` | Cache one supported rustdoc page |
| `which QUERY [-n N] [--source S]` | Return the five best page candidates |
| `find QUERY [-n N] [--source S]` | Return ten full-text search results |
| `context SLUG_OR_URL` | Return one complete page |
| `examples QUERY [-n N] [--language L] [--source S]` | Return matching code blocks |
| `sections [--source S]` | List sections and page counts |
| `doctor` | Report database and synchronization health |
| `version` | Print the CLI version |

Global flags can appear before or after the subcommand:

- `--json`: machine-readable stdout.
- `--compact`: remove snippets and ranks from search results.
- `--db PATH`: override the database location. The `RUST_DOCS_DB` environment variable is also supported.

Empty searches return an empty `matches`/`examples` array. A missing or ambiguous `context` exits with code 3 and, in JSON mode, includes candidate pages when ambiguous. Network/source failures use exit code 5; argument parsing uses 2; unexpected failures use 1.

## Data storage

Default database locations:

- Windows: `%LOCALAPPDATA%\rust-docs-pp-cli\data.db`
- macOS: `~/Library/Application Support/rust-docs-pp-cli/data.db`
- Linux/Unix: `${XDG_DATA_HOME:-~/.local/share}/rust-docs-pp-cli/data.db`

Downloaded documentation is stored only in this local database. The repository does not contain mirrored Rust documentation, credentials, local databases, or analysis artifacts.

## Development

```bash
git clone https://github.com/WolCarlos/Wol-rust-docs-pp-cli.git
cd Wol-rust-docs-pp-cli
uv venv
uv pip install -e .

# Unix
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

PYTHONPATH=src python -m unittest discover -s tests -v
rust-docs-pp-cli sync book --db ./dev.db
rust-docs-pp-cli which "ownership" --db ./dev.db --json
```

On Windows CMD, set `PYTHONPATH=src` before running the tests. The test suite is offline; live source formats are smoke-tested separately against official documentation.

## Sources and inspiration

- [CLI Printing Press](https://github.com/mvanhorn/cli-printing-press): agent-native CLI, local SQLite, verification, and token-efficiency principles.
- [agno-docs-pp-cli](https://github.com/sekai1710/agno-docs-pp-cli): the `which` → `context` → `examples` documentation workflow and SQLite FTS5 design.
- [The Rust Programming Language](https://github.com/rust-lang/book), [Rust Reference](https://github.com/rust-lang/reference), [Cargo](https://github.com/rust-lang/cargo), and [Rust by Example](https://github.com/rust-lang/rust-by-example).
- [Rust standard-library documentation](https://doc.rust-lang.org/std/) and [docs.rs](https://docs.rs/).

Rust documentation remains subject to its upstream licenses. This repository contains the lookup implementation, not a redistributed documentation snapshot.

## License

MIT. See [LICENSE](LICENSE).
