# Stato del progetto

## Stato attuale

- CLI Python 3.11+ senza dipendenze runtime, comando `rust-docs-pp-cli`.
- Indice locale SQLite + FTS5 con ricerca pagine ed esempi, filtri per fonte/linguaggio e output JSON.
- Comandi: `sync`, `which`, `find`, `context`, `examples`, `sections`, `doctor`, `version`.
- Sorgenti mdBook: Rust Book, Reference, Cargo Book, Rust by Example.
- Sorgenti rustdoc: archivio stabile `std/core/alloc`, crate docs.rs e singole URL.
- Test unitari offline e CI GitHub Actions su Linux/Windows con Python 3.11/3.13.

## Database schema

- `pages`: `id`, `url`, `title`, `source`, `section`, `slug`, `content`, `headings`.
- `pages_fts`: indice FTS5 esterno sincronizzato con trigger INSERT/UPDATE/DELETE.
- `examples`: `id`, `page_url`, `page_title`, `source`, `language`, `code`.
- `examples_fts`: indice FTS5 esterno sincronizzato con trigger INSERT/UPDATE/DELETE.
- `meta`: timestamp e dettagli di sincronizzazione per fonte.

## API Endpoints

Nessun server o endpoint REST. La CLI legge esclusivamente:

- Archivi GitHub ufficiali `rust-lang/*` tramite codeload.
- `static.rust-lang.org` per manifest e archivio rustdoc stabile.
- `docs.rs` e `doc.rust-lang.org` per pagine rustdoc.

## AI Tasks

Nessun modello AI configurato. Il flusso per agenti è `which` → `context` → `examples`; istruzioni pubbliche nel README.
