import importlib
import os
import sys
from datetime import datetime

import pytest


def _workspace_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "."))


@pytest.fixture(scope="session")
def app_module():
    """Import the FastAPI module with pymongo patched to mongomock.

    This avoids touching production code while preventing real Mongo connections
    and allowing us to assert DB side-effects.
    """
    # Ensure repo root is on sys.path so `import api.index.fastapi_app` works.
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    os.environ.setdefault("MONGO_URI", "mongodb://test")

    import pymongo  # noqa: WPS433
    import mongomock  # noqa: WPS433

    shared_client = mongomock.MongoClient()

    def _mongo_client(*args, **kwargs):  # noqa: ANN001
        return shared_client

    # Patch *before* importing `api.index.fastapi_app` so its `from pymongo import MongoClient`
    # binds to this mongomock-backed factory.
    pymongo.MongoClient = _mongo_client  # type: ignore[assignment]

    mod = importlib.import_module("api.index.fastapi_app")
    return mod


@pytest.fixture()
def seeded_client(app_module):
    """TestClient with a clean mongomock DB, seeded train master, and test blockage matrix."""
    from fastapi.testclient import TestClient  # noqa: WPS433

    # Clean collections used by the backend.
    for coll in (
        app_module.trains_collection,
        app_module.platforms_collection,
        app_module.state_collection,
        app_module.logs_collection,
        app_module.reports_collection,
        app_module.counters_collection,
        app_module.suggestions_cache_collection,
    ):
        try:
            coll.delete_many({})
        except Exception:
            pass

    # Provide a tiny deterministic blockage matrix to exercise the scoring path.
    # Keep scores simple: P1 has 0 blockages, P2 has 1 full blockage.
    test_line = "MDN DN Joint"
    test_matrix = {
        test_line: {
            # scoring_algorithm maps P1/P3 -> "P1-3" and P2/P4 -> "P2-4"
            "P1-3": [{"full": [], "partial": []}],
            "P2-4": [{"full": ["P5"], "partial": []}],
        }
    }

    app_module.load_blockage_matrix_from_mongo = lambda: (test_matrix, [test_line])

    # Seed trains master with a short and a long train.
    app_module.trains_collection.insert_many(
        [
            {
                "TRAIN NO": "12345",
                "TRAIN NAME": "Passenger 12345",
                "ARRIVAL AT KGP": "10:00",
                "DEPARTURE FROM KGP": None,
                "LENGTH": "short",
                "DIRECTION": "UP",
                "PLATFORM NO": "1",
                "ZONE": "SER",
            },
            {
                "TRAIN NO": "99901",
                "TRAIN NAME": "Passenger 99901",
                "ARRIVAL AT KGP": "11:00",
                "DEPARTURE FROM KGP": None,
                "LENGTH": "long",
                "DIRECTION": "UP",
                "PLATFORM NO": "1",
                "ZONE": "SER",
            },
        ]
    )

    # Refresh in-memory cache so endpoints find trains without hitting DB logic surprises.
    try:
        app_module.refresh_train_cache()
    except Exception:
        pass

    with TestClient(app_module.app) as client:
        yield client


@pytest.fixture()
def today_str():
    return datetime.now().strftime("%Y-%m-%d")
