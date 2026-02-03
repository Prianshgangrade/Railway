from __future__ import annotations


def test_platform_suggestions_scoring_and_cache(seeded_client, app_module, today_str):
    payload = {
        "trainNo": "12345",
        "incomingLine": "MDN DN Joint",
        "platforms": [
            {"id": "Platform 1", "isOccupied": False, "isUnderMaintenance": False},
            {"id": "Platform 2", "isOccupied": False, "isUnderMaintenance": False},
            {"id": "Platform 3", "isOccupied": True, "isUnderMaintenance": False},
        ],
    }

    r = seeded_client.post("/api/platform-suggestions", json=payload)
    assert r.status_code == 200
    body = r.json()

    suggestions = body.get("suggestions")
    assert isinstance(suggestions, list)
    assert len(suggestions) >= 1

    # Our test matrix makes Platform 1 the best (score 0) and Platform 2 worse (score 1)
    assert suggestions[0]["platformId"] == "Platform 1"

    # BackgroundTasks should persist a snapshot into the suggestions cache.
    cache_doc = app_module.suggestions_cache_collection.find_one({"date": today_str, "trainNo": "12345"})
    assert cache_doc is not None
    assert cache_doc.get("incoming_line") == "MDN DN Joint"

    # Snapshot stores normalized labels, e.g. ["1", "2"] rather than ["Platform 1", ...]
    saved = cache_doc.get("suggestions")
    assert isinstance(saved, list)
    assert "1" in saved


def test_platform_suggestions_unknown_train_returns_404(seeded_client):
    payload = {
        "trainNo": "00000",
        "incomingLine": "MDN DN Joint",
        "platforms": [{"id": "Platform 1", "isOccupied": False, "isUnderMaintenance": False}],
    }
    r = seeded_client.post("/api/platform-suggestions", json=payload)
    assert r.status_code == 404


def test_long_train_constraints_partner_and_filtering(seeded_client):
    # For long trains:
    # - P1 is allowed only if P3 is also free (paired option)
    # - P2 is allowed only if P4 is also free
    # - P5-8 are allowed as single
    payload = {
        "trainNo": "99901",
        "incomingLine": "HIJ Freight",  # bypasses blockage matrix while still exercising constraints
        "platforms": [
            {"id": "Platform 1", "isOccupied": False, "isUnderMaintenance": False},
            {"id": "Platform 2", "isOccupied": False, "isUnderMaintenance": False},
            {"id": "Platform 3", "isOccupied": False, "isUnderMaintenance": False},
            # Note: Platform 4 is missing (so P2 must be filtered out)
            {"id": "Platform 5", "isOccupied": False, "isUnderMaintenance": False},
        ],
    }
    r = seeded_client.post("/api/platform-suggestions", json=payload)
    assert r.status_code == 200

    suggestions = r.json()["suggestions"]
    ids = [s["platformId"] for s in suggestions]

    assert "Platform 2" not in ids
    assert "Platform 1" in ids

    # Partner should be included for Platform 1 suggestion.
    p1 = next(s for s in suggestions if s["platformId"] == "Platform 1")
    assert "Platform 3" in p1.get("platformIds", [])


def test_assign_platform_merges_cached_suggestions_into_report(seeded_client, app_module, today_str):
    # First compute suggestions to populate suggestions_cache_collection.
    r1 = seeded_client.post(
        "/api/platform-suggestions",
        json={
            "trainNo": "12345",
            "incomingLine": "MDN DN Joint",
            "platforms": [
                {"id": "Platform 1", "isOccupied": False, "isUnderMaintenance": False},
                {"id": "Platform 2", "isOccupied": False, "isUnderMaintenance": False},
            ],
        },
    )
    assert r1.status_code == 200

    # Now assign the train; the assignment report entry should merge cached suggestions.
    r2 = seeded_client.post(
        "/api/assign-platform",
        json={
            "trainNo": "12345",
            "platformIds": ["Platform 1"],
            "actualArrival": "10:05",
            "incomingLine": "MDN DN Joint",
        },
    )
    assert r2.status_code == 200

    report_row = app_module.reports_collection.find_one({"date": today_str, "trainNo": "12345"})
    assert report_row is not None
    assert isinstance(report_row.get("suggestions"), list)
    assert "1" in report_row.get("suggestions")

    # Cache should be cleared after successful assignment insert.
    cache_doc = app_module.suggestions_cache_collection.find_one({"date": today_str, "trainNo": "12345"})
    assert cache_doc is None
