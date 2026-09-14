# Dead dependencies, undeclared dependency, stale example config, lint findings

**Priority: low**

## Problem

- `python-dotenv` is imported by `core/config.py` but not declared in `pyproject.toml`; it arrives only
  transitively through `uvicorn[standard]` and would vanish with a dependency change.
- `aiosqlite` is declared but unusable: `Vector` columns, the RLS module and `hnsw.iterative_scan` all
  require Postgres; `storage.py` still carries a `sqlite` insert dialect branch.
- `.env.example` documents `OLLAMA_ENRICHMENT_MODEL` ("not used by any command yet"); the code reads
  `OLLAMA_ANSWER_MODEL`, so following the example leaves the answer model at its default silently.
  `.env.example` also omits `OLLAMA_ANSWER_MODEL`.
- `pyproject.toml` still has `description = "Add your description here"`.
- `ruff check --select E,F,B,I,UP,ASYNC,S` reports 20 findings (unsorted imports, `datetime.UTC`,
  `str, Enum` → `StrEnum`, ASYNC240 in `main.py`, S608 on the intentional f-string DDL in `rls.py`),
  with no ruff/mypy config in the repo to make the intended set explicit.

## Approach

- `uv add python-dotenv`; `uv remove aiosqlite` and delete the sqlite branch in `storage.py`
  (`_INSERT_BY_DIALECT` → `postgresql.insert`).
- Fix `.env.example` (`OLLAMA_ANSWER_MODEL=qwen3:8b`, drop the enrichment line) and the README table.
- Add `[tool.ruff]` with the selected rules and `# noqa: S608` on the two DDL lines; run `ruff --fix`
  once; add `mypy`/`pyright` config. Hook both into CI (`ISSUE_NO_TESTS_NO_CI.md`).
