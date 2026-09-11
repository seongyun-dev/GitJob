"""Cross-run posting identity: the behaviour the cursor could not provide."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from job.collector.identity import (
    Decision,
    PostingIdentityStore,
    identity_path_for,
)


def _store(tmp_path: Path) -> PostingIdentityStore:
    return PostingIdentityStore(source_site="WORKNET", path=tmp_path / "identity.json")


def test_first_sighting_is_new(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.record("K1", "hash-a") is Decision.NEW


def test_same_hash_is_unchanged(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("K1", "hash-a")
    assert store.record("K1", "hash-a") is Decision.UNCHANGED


def test_moved_hash_is_changed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("K1", "hash-a")
    assert store.record("K1", "hash-b") is Decision.CHANGED


def test_changed_posting_keeps_first_seen_and_advances_last_seen(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record("K1", "hash-a", now=datetime(2026, 9, 8, tzinfo=UTC))
    store.record("K1", "hash-b", now=datetime(2026, 9, 11, tzinfo=UTC))

    assert store.first_seen_at("K1").startswith("2026-09-08")
    assert store.last_seen_at("K1").startswith("2026-09-11")


def test_unchanged_posting_still_advances_last_seen(tmp_path: Path) -> None:
    """A posting still being listed is information even when it has not moved."""

    store = _store(tmp_path)
    store.record("K1", "hash-a", now=datetime(2026, 9, 8, tzinfo=UTC))
    store.record("K1", "hash-a", now=datetime(2026, 9, 11, tzinfo=UTC))

    assert store.first_seen_at("K1").startswith("2026-09-08")
    assert store.last_seen_at("K1").startswith("2026-09-11")


def test_survives_a_reload(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("K1", "hash-a")
    store.save()

    reloaded = PostingIdentityStore.load(
        tmp_path / "identity.json", source_site="WORKNET"
    )
    assert len(reloaded) == 1
    assert reloaded.decide("K1", "hash-a") is Decision.UNCHANGED
    assert reloaded.decide("K1", "hash-b") is Decision.CHANGED


def test_reload_is_independent_of_any_date_range(tmp_path: Path) -> None:
    """The regression this module exists for.

    `Cursor.load` drops its ids when the run's range moves, so a daily schedule
    starts every run empty. The identity store carries no range at all, so a
    posting seen on 2026-09-08 is still known on 2026-09-11.
    """

    store = _store(tmp_path)
    store.record("K1", "hash-a")
    store.save()

    for _ in range(3):  # three later runs, each a different date range
        later = PostingIdentityStore.load(
            tmp_path / "identity.json", source_site="WORKNET"
        )
        assert later.decide("K1", "hash-a") is Decision.UNCHANGED
        later.record("K1", "hash-a")
        later.save()


def test_missing_file_starts_empty(tmp_path: Path) -> None:
    store = PostingIdentityStore.load(tmp_path / "absent.json", source_site="WORKNET")
    assert len(store) == 0
    assert store.decide("K1", "hash-a") is Decision.NEW


def test_corrupt_file_starts_empty_rather_than_raising(tmp_path: Path) -> None:
    """One run of duplicates beats losing the whole run to a parse error."""

    path = tmp_path / "identity.json"
    path.write_text("{not json", encoding="utf-8")

    store = PostingIdentityStore.load(path, source_site="WORKNET")
    assert len(store) == 0


def test_entry_without_a_hash_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps({"postings": {"K1": {"first_seen_at": "2026-09-08"}}}),
        encoding="utf-8",
    )

    store = PostingIdentityStore.load(path, source_site="WORKNET")
    assert store.decide("K1", "anything") is Decision.NEW


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record("K1", "hash-a")
    store.save()

    assert (tmp_path / "identity.json").exists()
    assert not (tmp_path / "identity.json.tmp").exists()


def test_two_sites_can_reuse_one_posting_id(tmp_path: Path) -> None:
    """Identity is namespaced by site, so numeric ids cannot collide."""

    worknet = PostingIdentityStore(
        source_site="WORKNET", path=tmp_path / "worknet" / "identity.json"
    )
    saramin = PostingIdentityStore(
        source_site="SARAMIN", path=tmp_path / "saramin" / "identity.json"
    )
    worknet.record("54944929", "hash-a")
    worknet.save()
    saramin.save()

    assert saramin.decide("54944929", "hash-a") is Decision.NEW


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        (Path("../data/worknet/cursor.json"), Path("../data/worknet/identity.json")),
        (Path("/data/saramin/cursor.json"), Path("/data/saramin/identity.json")),
    ],
)
def test_identity_path_sits_beside_the_cursor(cursor: Path, expected: Path) -> None:
    assert identity_path_for(cursor) == expected


def test_identity_path_is_none_without_a_cursor() -> None:
    assert identity_path_for(None) is None


def test_no_cursor_means_no_file_is_written(tmp_path: Path) -> None:
    store = PostingIdentityStore(source_site="WORKNET", path=None)
    store.record("K1", "hash-a")
    store.save()

    assert list(tmp_path.iterdir()) == []
