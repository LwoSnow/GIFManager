# Contributing to GIFManager

Thanks for your interest in contributing to GIFManager! Please read and follow the guidelines below.

## Development Environment

- Python 3.10+ (3.12+ recommended), dependencies in `requirements.txt`
- Install: `pip install -r requirements.txt`
- Run: `python main.py`
- Test: `python -m unittest tests.test_columns tests.test_layout -v`

## Code Style

All code must follow the project's `gifmanager-code-style` rules (PEP8 + bilingual comments):

- Max line length ≤ 100, 4-space indentation, PEP8 base formatting
- Triple-quoted docstrings only at file headers (English line + Chinese line); use `#` bilingual comments everywhere else
- After changes, you must pass `py_compile` and all regression tests

## Branch Naming

- Feature branch: `feature/<short-description>` (e.g. `feature/export-support`)
- Fix branch: `fix/<short-description>` (e.g. `fix/all-group-sync`)

## Commit Guidelines

- Use Conventional Commits:
  - `feat: add export support` / `fix: fix "All" group not syncing`
  - `refactor:`, `docs:`, `test:`, `style:`, `perf:` etc. likewise
- Commit messages should explain the "why", not mechanically repeat the code
- Each commit should remain independently compilable and testable

## Pull Request Workflow

1. Branch from the latest `main`; keep changes focused on a single topic
2. Before submitting, run: `py_compile` on the changed files + `python -m unittest tests.test_columns tests.test_layout -v` — all green
3. New features must come with corresponding tests (under `tests/`)
4. Translation changes must update both `language/zh_CN.json` and `language/en_US.json`
5. Describe the changes, test results, and screenshots (if the UI is involved)

## Version & License

- The project is released under the [MIT License](LICENSE); by submitting code you agree to release it under this license
