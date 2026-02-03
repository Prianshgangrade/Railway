## Backend integration tests (no backend code changes)

These tests validate the FastAPI backend end-to-end (routes + scoring + persistence),
while using an in-memory MongoDB substitute via `mongomock`.

### What this covers

- `POST /api/platform-suggestions`: scoring output + suggestions snapshot persisted
- Long-train constraints (paired platforms 1+3 / 2+4, and 5–8 singles)
- `POST /api/assign-platform`: merges cached suggestions into daily reports and clears cache

### Install test deps

```powershell
python -m pip install -r api/requirements-test.txt
```

### Run tests

```powershell
pytest -q
```

Notes:
- These tests do **not** modify any production backend files.
- MongoDB access is patched at runtime so no real DB is required.
