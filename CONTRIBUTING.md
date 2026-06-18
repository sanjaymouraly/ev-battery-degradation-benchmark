# Contributing
- Python 3.11+; `pip install -e ".[dev]"`, run `ruff check src tests` and `pytest`.
- Scientific changes require tests against synthetic ground truth (see tests/test_science.py).
- Never commit datasets >1 MB, secrets, or verifier ground truth outside
  `tasks/**/tests/private/`. Never copy `tests/private/` content into `environment/`.
- Upstream Terminal-Bench-Science submission additionally requires an approved
  proposal and a named domain-expert author — see docs/task-proposal.md.
