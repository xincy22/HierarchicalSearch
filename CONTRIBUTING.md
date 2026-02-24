# Contributing

Thanks for taking the time to contribute.

## Development Setup

- Python: 3.10+
- Install (editable):
  - `python -m pip install -e ".[dev]"`

## Running Tests

- Unit tests:
  - `pytest -q`

## Optional: Milvus Smoke Tests

Milvus tests are skipped by default.

1. Start Milvus (requires Docker / Docker Desktop):
   - `docker compose -f docker-compose.milvus.yaml up -d`
2. Run smoke tests:
   - `HS_RUN_MILVUS_TESTS=1 HS_MILVUS_URI=http://127.0.0.1:19530 pytest -q tests/test_milvus_smoke.py`
3. Stop:
   - `docker compose -f docker-compose.milvus.yaml down -v`

## Pull Requests

- Keep changes focused and small when possible.
- Add/adjust tests if behavior changes.
- Do not commit secrets:
  - `.env` is ignored; use `.env.example` as a template.
