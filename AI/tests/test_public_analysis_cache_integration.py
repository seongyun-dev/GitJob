"""S15P21E102-347: the cache must change the cost and nothing else.

`test_redis_artifact_analysis_cache` covers the component. This covers the
wiring: the same batch analysed with the cache off, cold and warm has to
produce the same `PublicBatchResult`, and the warm run has to get there without
reading the artifacts again.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from github.contracts import GitHubRepoSnapshotBatch
from github.public_analysis import (
    PUBLIC_MANIFEST_PARSER_VERSION,
    PUBLIC_PARSER_VERSION,
    analyze_public_batch,
)
from github.redis_artifact_analysis_cache import ArtifactAnalysisCacheContext
from registry.contracts import TechnologyRegistry
from registry.mapper import RegistryMapper

DIRECTORY = "hdfs://trusted/artifacts/repo_id=1/commit=abc"
PACKAGE_JSON = b'{"dependencies":{"react":"18","next":"14"}}'
REQUIREMENTS = b"fastapi==0.1\nnumpy==2.0\n"
PARSER_VERSION = f"{PUBLIC_PARSER_VERSION}+{PUBLIC_MANIFEST_PARSER_VERSION}"


@pytest.fixture
def mapper():
    return RegistryMapper(
        TechnologyRegistry.model_validate_json(
            Path("registry/data/technology_registry_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )


def batch() -> GitHubRepoSnapshotBatch:
    """One repository whose two artifacts share a directory.

    Sharing the directory is the point: Mode C claims one listing answers for
    both, and a fixture with one artifact per directory could not show that.
    """

    data = json.loads(Path("github/fixtures/github_repo_snapshot_v1.json").read_text())
    data["records"] = data["records"][:1]
    row = data["records"][0]
    row["collection_status"] = "COMPLETE"
    row["collection_issues"] = []
    row["artifacts"] = [
        {
            "artifact_type": "MANIFEST",
            "path": name,
            "uri": f"{DIRECTORY}/{name}",
            "size_bytes": len(content),
            "content_hash": hashlib.sha256(content).hexdigest(),
        }
        for name, content in (
            ("package.json", PACKAGE_JSON),
            ("requirements.txt", REQUIREMENTS),
        )
    ]
    return GitHubRepoSnapshotBatch.model_validate(data)


CONTENT = {
    f"{DIRECTORY}/package.json": PACKAGE_JSON,
    f"{DIRECTORY}/requirements.txt": REQUIREMENTS,
}


class CountingReader:
    """Reader that records what the run actually asked the NameNode for."""

    def __init__(self, *, present=None, sizes=None, listing_fails=False):
        self.reads = 0
        self.listings = 0
        self.listing_fails = listing_fails
        self.present = CONTENT.keys() if present is None else present
        self.sizes = sizes or {}

    def read(self, uri, *, max_bytes):
        self.reads += 1
        return CONTENT[uri][: max_bytes + 1]

    def list_directory(self, uri, *, max_entries=4096):
        self.listings += 1
        if self.listing_fails:
            raise OSError("namenode unavailable")
        return tuple(
            {
                "pathSuffix": full.rsplit("/", 1)[1],
                "type": "FILE",
                "length": self.sizes.get(full, len(CONTENT[full])),
            }
            for full in self.present
            if full.rsplit("/", 1)[0] == uri
        )


class FakeRedis:
    def __init__(self, *, fail_get=False, fail_set=False, store=None):
        self.store = {} if store is None else store
        self.fail_get = fail_get
        self.fail_set = fail_set

    def get(self, key):
        if self.fail_get:
            raise ConnectionError("redis down")
        return self.store.get(key)

    def set(self, key, value, ex=None):
        if self.fail_set:
            raise ConnectionError("OOM command not allowed")
        self.store[key] = value
        return True


def context(client, reader):
    return ArtifactAnalysisCacheContext.build(
        client,
        reader,
        registry_version="registry-20260911.4",
        parser_version=PARSER_VERSION,
    )


def digest(result) -> str:
    """Canonical digest of the whole analysis output."""

    return hashlib.sha256(
        json.dumps(
            result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def run(mapper, reader, cache=None):
    return analyze_public_batch(batch(), reader, mapper, cache=cache)


# --- the deploy gate --------------------------------------------------------


def test_off_cold_and_warm_produce_the_same_output(mapper):
    off_reader = CountingReader()
    off = run(mapper, off_reader)

    store = {}
    cold_reader = CountingReader()
    cold = run(mapper, cold_reader, context(FakeRedis(store=store), cold_reader))

    warm_reader = CountingReader()
    warm = run(mapper, warm_reader, context(FakeRedis(store=store), warm_reader))

    assert digest(off) == digest(cold) == digest(warm)
    # The cost is what moved: warm reads nothing and lists once.
    assert off_reader.reads == 2
    assert cold_reader.reads == 2
    assert warm_reader.reads == 0
    assert warm_reader.listings == 1


def test_warm_output_matches_field_by_field_not_just_by_digest(mapper):
    """A digest match could hide a reordering; assert the parts that carry meaning."""

    store = {}
    reader = CountingReader()
    off = run(mapper, CountingReader())
    run(mapper, reader, context(FakeRedis(store=store), reader))
    warm = run(mapper, reader, context(FakeRedis(store=store), reader))

    assert [r.included_in_denominator for r in warm.records] == [
        r.included_in_denominator for r in off.records
    ]
    for warm_record, off_record in zip(warm.records, off.records, strict=True):
        assert warm_record.observations == off_record.observations
        assert warm_record.unresolved == off_record.unresolved
        assert warm_record.artifacts == off_record.artifacts
        assert warm_record.status == off_record.status
        assert warm_record.quality_reasons == off_record.quality_reasons
    assert warm.technologies == off.technologies


# --- cache disabled is the old path -----------------------------------------


def test_cache_disabled_never_lists(mapper):
    reader = CountingReader()

    run(mapper, reader)

    assert reader.listings == 0
    assert reader.reads == 2


# --- Mode C validation gates the hit ----------------------------------------


def test_missing_artifact_falls_back_to_reading(mapper):
    store = {}
    warm_reader = CountingReader()
    run(mapper, warm_reader, context(FakeRedis(store=store), warm_reader))

    gone = CountingReader(present=[f"{DIRECTORY}/package.json"])
    result = run(mapper, gone, context(FakeRedis(store=store), gone))

    assert gone.reads == 1  # only the one the listing could not confirm
    assert digest(result) == digest(run(mapper, CountingReader()))


def test_size_mismatch_falls_back_to_reading(mapper):
    store = {}
    warm_reader = CountingReader()
    run(mapper, warm_reader, context(FakeRedis(store=store), warm_reader))

    wrong = CountingReader(sizes={f"{DIRECTORY}/requirements.txt": 999})
    result = run(mapper, wrong, context(FakeRedis(store=store), wrong))

    assert wrong.reads == 1
    assert digest(result) == digest(run(mapper, CountingReader()))


def test_listing_failure_falls_back_to_reading_everything(mapper):
    store = {}
    warm_reader = CountingReader()
    run(mapper, warm_reader, context(FakeRedis(store=store), warm_reader))

    broken = CountingReader(listing_fails=True)
    result = run(mapper, broken, context(FakeRedis(store=store), broken))

    assert broken.reads == 2
    assert digest(result) == digest(run(mapper, CountingReader()))


# --- Redis failure modes ----------------------------------------------------


def test_redis_get_failure_still_produces_the_same_output(mapper):
    reader = CountingReader()

    result = run(mapper, reader, context(FakeRedis(fail_get=True), reader))

    assert reader.reads == 2
    assert digest(result) == digest(run(mapper, CountingReader()))


def test_redis_set_failure_still_produces_the_same_output(mapper):
    reader = CountingReader()

    result = run(mapper, reader, context(FakeRedis(fail_set=True), reader))

    assert digest(result) == digest(run(mapper, CountingReader()))


def test_corrupt_stored_value_recomputes(mapper):
    store = {}
    seed_reader = CountingReader()
    run(mapper, seed_reader, context(FakeRedis(store=store), seed_reader))
    for key in list(store):
        store[key] = "{not json"

    reader = CountingReader()
    result = run(mapper, reader, context(FakeRedis(store=store), reader))

    assert reader.reads == 2
    assert digest(result) == digest(run(mapper, CountingReader()))


# --- key identity across runs -----------------------------------------------


@pytest.mark.parametrize(
    "changed",
    [
        {"registry_version": "registry-20261001.1"},
        {"parser_version": "c-public-static-observations/v7"},
    ],
)
def test_version_change_does_not_reuse_the_previous_run(mapper, changed):
    store = {}
    seed_reader = CountingReader()
    run(mapper, seed_reader, context(FakeRedis(store=store), seed_reader))

    reader = CountingReader()
    later = ArtifactAnalysisCacheContext.build(
        FakeRedis(store=store),
        reader,
        **{
            "registry_version": "registry-20260911.4",
            "parser_version": PARSER_VERSION,
            **changed,
        },
    )
    result = analyze_public_batch(batch(), reader, mapper, cache=later)

    assert reader.reads == 2
    assert digest(result) == digest(run(mapper, CountingReader()))


def test_second_run_reports_hits_and_one_listing(mapper):
    store = {}
    cold_reader = CountingReader()
    cold = context(FakeRedis(store=store), cold_reader)
    run(mapper, cold_reader, cold)

    warm_reader = CountingReader()
    warm = context(FakeRedis(store=store), warm_reader)
    run(mapper, warm_reader, warm)

    assert cold.cache.metrics.hit_count == 0
    assert cold.cache.metrics.miss_count == 2
    assert warm.cache.metrics.hit_count == 2
    assert warm.cache.metrics.hit_rate == 1.0
    assert warm.cache.metrics.listing_count == 1


# --- shared content across repositories -------------------------------------

OTHER_DIRECTORY = "hdfs://trusted/artifacts/repo_id=2/commit=def"


def two_repo_batch() -> GitHubRepoSnapshotBatch:
    """Two repositories whose `package.json` bytes are identical.

    This is common -- a generated or copied manifest -- and it is the case the
    cache key is built to share, because the parse really is the same. What is
    not the same is which file was parsed, so the stored entry must not be able
    to tell the second repository that its evidence came from the first one's
    URI.
    """

    data = json.loads(Path("github/fixtures/github_repo_snapshot_v1.json").read_text())
    first = data["records"][0]
    second = json.loads(json.dumps(first))
    second["github_repo_id"] = first["github_repo_id"] + 1
    second["repo_snapshot_id"] = first["repo_snapshot_id"] + "-second"
    second["repo_full_name"] = first["repo_full_name"] + "-second"
    second["activity_rank"] = first["activity_rank"] + 1
    for row, directory in ((first, DIRECTORY), (second, OTHER_DIRECTORY)):
        row["collection_status"] = "COMPLETE"
        row["collection_issues"] = []
        row["artifacts"] = [
            {
                "artifact_type": "MANIFEST",
                "path": "package.json",
                "uri": f"{directory}/package.json",
                "size_bytes": len(PACKAGE_JSON),
                "content_hash": hashlib.sha256(PACKAGE_JSON).hexdigest(),
            }
        ]
    data["records"] = [first, second]
    return GitHubRepoSnapshotBatch.model_validate(data)


SHARED_CONTENT = {
    f"{DIRECTORY}/package.json": PACKAGE_JSON,
    f"{OTHER_DIRECTORY}/package.json": PACKAGE_JSON,
}


class SharedReader(CountingReader):
    def __init__(self):
        super().__init__(present=SHARED_CONTENT.keys())

    def read(self, uri, *, max_bytes):
        self.reads += 1
        return SHARED_CONTENT[uri][: max_bytes + 1]

    def list_directory(self, uri, *, max_entries=4096):
        self.listings += 1
        return tuple(
            {
                "pathSuffix": "package.json",
                "type": "FILE",
                "length": len(PACKAGE_JSON),
            }
            for full in SHARED_CONTENT
            if full.rsplit("/", 1)[0] == uri
        )


def test_identical_content_in_two_repositories_keeps_its_own_uri(mapper):
    """Regression: a shared entry must not carry the first repository's URI.

    Caught by the 3-way gate on real data -- 8 of 1,080 artifacts in the
    2026-08-31 batch shared content, and the cached run disagreed with the
    uncached one on exactly those.
    """

    shared = two_repo_batch()
    off = analyze_public_batch(shared, SharedReader(), mapper)

    reader = SharedReader()
    cached = analyze_public_batch(
        shared, reader, mapper, cache=context(FakeRedis(), reader)
    )

    assert reader.reads == 1  # the second repository reused the first parse
    assert digest(cached) == digest(off)
    uris = [record.artifacts[0].uri for record in cached.records]
    assert uris == [f"{DIRECTORY}/package.json", f"{OTHER_DIRECTORY}/package.json"]
    for record in cached.records:
        for observation in record.observations:
            assert observation.uri == record.artifacts[0].uri
