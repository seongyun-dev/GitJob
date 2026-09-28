"""S15P21E102-347: the cache may accelerate intake, never decide it.

Every test here asks one of two questions. Does a hit still prove the durable
object is there (Mode C), and does anything going wrong -- Redis, the listing,
the stored bytes -- leave the caller doing exactly what it did before?
"""

from __future__ import annotations

import json

import pytest

from github.redis_artifact_analysis_cache import (
    ANALYSIS_CACHE_SCHEMA_VERSION,
    DirectoryArtifactValidator,
    RedisArtifactAnalysisCache,
    preload_directories,
)

DIR = "hdfs:///gitjob/analysis_input/github/repo_snapshot/x/repo_id=1/commit=a"
HASH = "a" * 64


class FakeRedis:
    """Duck-typed client; `fail_get`/`fail_set` model an unreachable broker."""

    def __init__(self, *, fail_get=False, fail_set=False):
        self.store: dict[str, str] = {}
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.set_calls = 0

    def get(self, key):
        if self.fail_get:
            raise ConnectionError("redis unavailable")
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.set_calls += 1
        if self.fail_set:
            # Redis runs maxmemory=0/noeviction in Production; a full instance
            # refuses the write rather than evicting.
            raise ConnectionError("OOM command not allowed")
        self.store[key] = value
        return True


class FakeReader:
    def __init__(self, entries, *, fail=False):
        self.entries = entries
        self.fail = fail
        self.calls = 0

    def list_directory(self, uri, *, max_entries=4096):
        self.calls += 1
        if self.fail:
            raise OSError("listing unavailable")
        return tuple(self.entries.get(uri, ()))


def file_entry(name, length):
    return {"pathSuffix": name, "type": "FILE", "length": length}


def cache(client, *, registry="registry-20260911.4", parser="parser/v1"):
    return RedisArtifactAnalysisCache(
        client, registry_version=registry, parser_version=parser
    )


def seed(client, subject, *, path="package.json", size=10, companion=""):
    subject.put(
        content_hash=HASH,
        path=path,
        size_bytes=size,
        companion_digest=companion or subject.companion_digest({}),
        candidates=[{"raw_value": "react"}],
        unresolved=[],
        analysis={"path": path, "status": "READY"},
    )


def reader_with(*files):
    return FakeReader({DIR: [file_entry(name, size) for name, size in files]})


# --- Mode C: one listing per directory, positive proof only -----------------


def test_one_listing_serves_every_artifact_in_the_directory():
    reader = reader_with(("package.json", 10), ("requirements.txt", 20))
    validator = DirectoryArtifactValidator(reader)

    assert validator.verify(f"{DIR}/package.json", size_bytes=10)
    assert validator.verify(f"{DIR}/requirements.txt", size_bytes=20)
    assert reader.calls == 1


def test_present_name_and_matching_size_validates():
    validator = DirectoryArtifactValidator(reader_with(("package.json", 10)))

    assert validator.verify(f"{DIR}/package.json", size_bytes=10)


def test_missing_artifact_does_not_validate():
    validator = DirectoryArtifactValidator(reader_with(("other.json", 10)))

    assert not validator.verify(f"{DIR}/package.json", size_bytes=10)


def test_size_mismatch_does_not_validate():
    validator = DirectoryArtifactValidator(reader_with(("package.json", 11)))

    assert not validator.verify(f"{DIR}/package.json", size_bytes=10)


def test_directory_entry_does_not_validate_as_a_file():
    reader = FakeReader({DIR: [{"pathSuffix": "package.json", "type": "DIRECTORY"}]})

    assert not DirectoryArtifactValidator(reader).verify(
        f"{DIR}/package.json", size_bytes=10
    )


def test_listing_failure_is_unknown_not_absent():
    reader = FakeReader({}, fail=True)
    validator = DirectoryArtifactValidator(reader)

    assert not validator.verify(f"{DIR}/package.json", size_bytes=10)
    # Remembered, so a failing NameNode is not asked once per artifact.
    validator.verify(f"{DIR}/requirements.txt", size_bytes=20)
    assert reader.calls == 1


def test_preload_fetches_one_listing_per_distinct_directory():
    other = DIR.replace("repo_id=1", "repo_id=2")
    reader = FakeReader({DIR: [file_entry("package.json", 10)], other: []})
    validator = DirectoryArtifactValidator(reader)

    fetched = preload_directories(
        validator, [f"{DIR}/package.json", f"{DIR}/a.txt", f"{other}/b.txt"]
    )

    assert fetched == 2
    assert reader.calls == 2


# --- hit requires durable validation ----------------------------------------


def test_hit_requires_the_artifact_to_be_listed():
    client = FakeRedis()
    subject = cache(client)
    seed(client, subject)
    validator = DirectoryArtifactValidator(reader_with(("package.json", 10)))

    hit = subject.lookup(
        content_hash=HASH,
        path="package.json",
        size_bytes=10,
        uri=f"{DIR}/package.json",
        companion_digest=subject.companion_digest({}),
        validator=validator,
    )

    assert hit is not None
    assert hit["candidates"] == [{"raw_value": "react"}]
    assert subject.metrics.hit_count == 1
    assert subject.metrics.durable_validation_count == 1


def test_stored_value_is_unusable_when_validation_fails():
    client = FakeRedis()
    subject = cache(client)
    seed(client, subject)
    validator = DirectoryArtifactValidator(reader_with(("package.json", 999)))

    assert (
        subject.lookup(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            uri=f"{DIR}/package.json",
            companion_digest=subject.companion_digest({}),
            validator=validator,
        )
        is None
    )
    assert subject.metrics.durable_fallback_count == 1
    assert subject.metrics.hit_count == 0


def test_no_validator_means_no_hit():
    """Nothing in the process has seen the object, so the entry cannot be used."""

    client = FakeRedis()
    subject = cache(client)
    seed(client, subject)

    assert (
        subject.lookup(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            uri=f"{DIR}/package.json",
            companion_digest=subject.companion_digest({}),
            validator=None,
        )
        is None
    )


# --- key identity -----------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("content_hash", "b" * 64),
        ("path", "requirements.txt"),
        ("size_bytes", 11),
    ],
)
def test_artifact_identity_change_does_not_hit(field, value):
    client = FakeRedis()
    subject = cache(client)
    seed(client, subject)
    request = {
        "content_hash": HASH,
        "path": "package.json",
        "size_bytes": 10,
        "uri": f"{DIR}/package.json",
        "companion_digest": subject.companion_digest({}),
        "validator": DirectoryArtifactValidator(
            reader_with(("package.json", 10), ("requirements.txt", 10))
        ),
    }
    request[field] = value

    assert subject.lookup(**request) is None


def test_registry_change_does_not_hit():
    client = FakeRedis()
    seed(client, cache(client))
    later = cache(client, registry="registry-20261001.1")

    assert (
        later.lookup(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            uri=f"{DIR}/package.json",
            companion_digest=later.companion_digest({}),
            validator=DirectoryArtifactValidator(reader_with(("package.json", 10))),
        )
        is None
    )


def test_parser_change_does_not_hit():
    client = FakeRedis()
    seed(client, cache(client))
    later = cache(client, parser="parser/v2")

    assert (
        later.lookup(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            uri=f"{DIR}/package.json",
            companion_digest=later.companion_digest({}),
            validator=DirectoryArtifactValidator(reader_with(("package.json", 10))),
        )
        is None
    )


def test_companion_change_does_not_hit():
    client = FakeRedis()
    subject = cache(client)
    seed(
        client,
        subject,
        companion=subject.companion_digest({"libs.versions.toml": b"a"}),
    )

    assert (
        subject.lookup(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            uri=f"{DIR}/package.json",
            companion_digest=subject.companion_digest({"libs.versions.toml": b"b"}),
            validator=DirectoryArtifactValidator(reader_with(("package.json", 10))),
        )
        is None
    )


def test_companion_digest_is_order_independent_and_empty_by_default():
    subject = cache(FakeRedis())
    one = subject.companion_digest({"a": b"1", "b": b"2"})

    assert one == subject.companion_digest({"b": b"2", "a": b"1"})
    assert one != subject.companion_digest({})


# --- fail-open --------------------------------------------------------------


def request_for(subject):
    return {
        "content_hash": HASH,
        "path": "package.json",
        "size_bytes": 10,
        "uri": f"{DIR}/package.json",
        "companion_digest": subject.companion_digest({}),
        "validator": DirectoryArtifactValidator(reader_with(("package.json", 10))),
    }


def test_empty_cache_is_a_miss():
    subject = cache(FakeRedis())

    assert subject.lookup(**request_for(subject)) is None
    assert subject.metrics.miss_count == 1
    assert subject.metrics.error_count == 0


def test_redis_get_failure_is_a_miss_not_an_error_to_the_caller():
    subject = cache(FakeRedis(fail_get=True))

    assert subject.lookup(**request_for(subject)) is None
    assert subject.metrics.fail_open_count == 1


def test_redis_set_failure_does_not_raise():
    client = FakeRedis(fail_set=True)
    subject = cache(client)

    assert (
        subject.put(
            content_hash=HASH,
            path="package.json",
            size_bytes=10,
            companion_digest=subject.companion_digest({}),
            candidates=[],
            unresolved=[],
            analysis={"status": "READY"},
        )
        is False
    )
    assert subject.metrics.fail_open_count == 1


@pytest.mark.parametrize(
    "stored",
    [
        "not json at all",
        json.dumps({"schema_version": "something-else"}),
        json.dumps({"schema_version": ANALYSIS_CACHE_SCHEMA_VERSION}),
        json.dumps([1, 2, 3]),
    ],
)
def test_corrupt_value_is_a_miss(stored):
    client = FakeRedis()
    subject = cache(client)
    # Reaching for the key builder on purpose: this asserts what a corrupt
    # stored value does, which needs the exact key the cache would read.
    key = subject._key(
        content_hash=HASH,
        path="package.json",
        companion_digest=subject.companion_digest({}),
    )
    client.store[key] = stored

    assert subject.lookup(**request_for(subject)) is None


def test_metrics_expose_hit_rate_and_latency():
    client = FakeRedis()
    subject = cache(client)
    seed(client, subject)
    subject.lookup(**request_for(subject))
    subject.lookup(**{**request_for(subject), "content_hash": "c" * 64})

    assert subject.metrics.lookup_count == 2
    assert subject.metrics.hit_rate == 0.5
    assert subject.metrics.percentile_ms(0.95) is not None


def test_ttl_and_namespace_follow_the_weekly_convention():
    subject = cache(FakeRedis())

    assert subject.ttl_seconds == 2_592_000
    assert subject.namespace == "gitjob:weekly:artifact-analysis:v1"
    assert "gitjob:benchmark" not in subject.namespace


def test_construction_rejects_blank_versions():
    for bad in ({"registry_version": " "}, {"parser_version": ""}):
        kwargs = {"registry_version": "r", "parser_version": "p", **bad}
        with pytest.raises(ValueError):
            RedisArtifactAnalysisCache(FakeRedis(), **kwargs)
