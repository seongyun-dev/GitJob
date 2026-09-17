"""Same saved assessment is used by list/detail; strict What-if stays separate."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from job.cohort import JobCohort
from job.matching import build_job_matching, restore_job_assessment
from test_compute_api import PREFIX, REGISTRY, TOKEN, event, snapshot_ref
from test_job_cohort import batch, criteria, posting
from test_recommendation_engine import make_analysis
from worker.api import create_compute_app
from worker.store import (
    Artifact,
    ComputeStore,
    IdempotencyConflict,
    StoredMatchingIntegrityError,
    Ticket,
    apply_migration,
    digest,
)


def levelled_evidence_payload(level: str = "L1") -> dict:
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v3"
    payload["repositories"][0]["technologies"][0]["personal_level"] = level
    return payload


def ceiling_evidence_payload(level: str = "L1", ceiling: str = "L1") -> dict:
    payload = make_analysis().model_dump(mode="json")
    payload["schema_version"] = "evidence-consumption-input/v4"
    payload["personal_assessments"] = [
        {
            "tech_id": "java",
            "personal_level": level,
            "assessment_ceiling": ceiling,
            "attribution_status": "COMPLETE",
            "missing_scope": ["L2_L3_RULE_NOT_SUPPORTED"],
        }
    ]
    return payload


class MemoryStore:
    """HTTP/serialization test double; deliberately NOT PostgreSQL durability proof."""

    lease_seconds = 120

    def __init__(self):
        self.tickets = {}
        self.requests = {}
        self.snapshots = {}
        self.matching = {}
        self.get_snapshot_calls = 0

    def claim(self, *, event_id, kind, owner, occurred_at, request):
        fingerprint = digest([kind, owner, occurred_at.isoformat(), request])
        if event_id in self.tickets:
            if self.requests[event_id] != fingerprint:
                raise IdempotencyConflict("test event request changed")
            return self.tickets[event_id]
        ticket = Ticket(
            event_id, kind, owner, occurred_at, "RUNNING", str(uuid4()), 1, []
        )
        self.tickets[event_id] = ticket
        self.requests[event_id] = fingerprint
        return ticket

    def complete(self, ticket, artifacts):
        results = []
        for item in artifacts:
            self.snapshots[item.snapshot_id] = {
                "snapshot_id": item.snapshot_id,
                "kind": item.kind,
                "owner": item.owner,
                "payload": json.loads(json.dumps(item.payload)),
            }
            if item.matching is not None:
                self.matching[item.snapshot_id] = json.loads(json.dumps(item.matching))
            results.append({"snapshot_id": item.snapshot_id, "kind": item.kind})
        self.tickets[ticket.event_id] = replace(
            ticket, status="COMPLETED", results=results
        )
        return results

    def get_snapshot(self, snapshot_id, *, owner):
        self.get_snapshot_calls += 1
        value = self.snapshots.get(snapshot_id)
        return value if value and value["owner"] == owner else None

    def _matching(self, snapshot_id, owner):
        value = self.snapshots.get(snapshot_id)
        value = value if value and value["owner"] == owner else None
        if not value or value["kind"] != "RECOMMENDATION":
            return None
        if snapshot_id not in self.matching:
            return {
                "status": "LEGACY_EMBEDDED"
                if "job_matching" in value["payload"]
                else "NOT_PREPARED"
            }
        stored = self.matching[snapshot_id]
        reference = value["payload"].get("job_matching_ref")
        metadata = stored["metadata"]
        if (
            not isinstance(reference, dict)
            or reference.get("calculation_snapshot_id")
            != stored["calculation_snapshot_id"]
            or metadata.get("user_id") != owner
            or metadata.get("analysis_id") != value["payload"].get("analysis_id")
            or metadata.get("cohort_id") != value["payload"].get("cohort_id")
        ):
            raise StoredMatchingIntegrityError("test stored matching scope mismatch")
        return {"status": "READY", **stored}

    def get_matching_page(
        self, snapshot_id, *, owner, offset, limit, include_conditional
    ):
        stored = self._matching(snapshot_id, owner)
        if not stored or stored["status"] != "READY":
            return stored
        sources = {row["job_id"]: row for row in stored["sources"]}
        rows = [
            row
            for row in stored["assessments"]
            if include_conditional or row["eligibility"] == "ELIGIBLE"
        ]
        page = rows[offset : offset + limit]
        return {
            **stored,
            "items": [
                restore_job_assessment(
                    sources[row["job_id"]], row["assessment"]
                ).model_dump(mode="json")
                for row in page
            ],
            "has_next": offset + limit < len(rows),
        }

    def get_matching_detail(self, snapshot_id, *, owner, job_id):
        stored = self._matching(snapshot_id, owner)
        if not stored or stored["status"] != "READY":
            return stored
        sources = {row["job_id"]: row for row in stored["sources"]}
        row = next(
            (row for row in stored["assessments"] if row["job_id"] == job_id),
            None,
        )
        return {
            **stored,
            "item": (
                restore_job_assessment(sources[job_id], row["assessment"]).model_dump(
                    mode="json"
                )
                if row
                else None
            ),
        }

    def renew(self, ticket):
        return True

    def fail(self, ticket, code):
        pass


@pytest.fixture(params=["memory", "postgres"])
def client(request):
    if request.param == "postgres":
        dsn = os.getenv("C_COMPUTE_TEST_DATABASE_URL")
        if not dsn:
            pytest.skip(
                "Requires explicitly selected isolated PostgreSQL test database"
            )
        apply_migration(dsn)
        store = ComputeStore(dsn)
    else:
        store = MemoryStore()
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as value:
        value.matching_test_store = store
        yield value


def _prepare(client):
    records = batch(
        posting("exact", preferred=("Redis",)),
        posting("partial", required=("Java", "Docker")),
        posting("conditional", region=None),
        posting("closed", posting_status="CLOSED"),
    )
    jobs = event(
        batch=records.model_dump(mode="json"),
        criteria=criteria(regions=("서울",)).model_dump(mode="json"),
    )
    cohort = snapshot_ref(
        client.post(PREFIX + "/job-batches/completed", json=jobs), "COHORT"
    )
    request = event(
        user_id="user-1",
        analysis_id="analysis-1",
        cohort_snapshot_id=cohort,
        evidence=levelled_evidence_payload(),
    )
    reply = client.post(PREFIX + "/analyses/completed", json=request)
    result_id = snapshot_ref(reply, "RECOMMENDATION")
    return result_id, request, reply


def test_partial_matching_roundtrip_pages_detail_and_strict_whatif(client):
    result_id, request, original = _prepare(client)
    listing_url = PREFIX + f"/recommendations/{result_id}/matching-job-postings"
    response = client.get(listing_url, params={"user_id": "user-1", "size": 1})
    assert response.status_code == 200, response.text
    listing = response.json()["data"]
    assert listing["total_count"] == 2
    assert listing["conditional_count"] == 1
    assert listing["excluded_conditional_count"] == 1
    assert listing["has_next"] is True
    assert listing["items"][0]["job"]["job_id"] == "exact"
    second = client.get(
        listing_url, params={"user_id": "user-1", "size": 1, "page": 1}
    ).json()["data"]
    assert second["has_next"] is False
    assert second["items"][0]["job"]["job_id"] == "partial"
    assert second["items"][0]["required"]["fulfillment_ratio"] == 0.5
    detail = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-posting",
        params={"user_id": "user-1", "job_id": "partial"},
    )
    assert detail.json()["data"]["item"] == second["items"][0]
    assert (
        detail.json()["data"]["calculation_snapshot_id"]
        == listing["calculation_snapshot_id"]
    )
    conditional = client.get(
        listing_url, params={"user_id": "user-1", "include_conditional": True}
    ).json()["data"]
    assert conditional["total_count"] == 3
    assert conditional["conditional_count"] == 1
    assert conditional["excluded_conditional_count"] == 0
    assert conditional["items"][-1]["job"]["eligibility"] == "CONDITIONAL"
    strict = client.get(
        PREFIX + f"/recommendations/{result_id}/job-postings",
        params={"user_id": "user-1"},
    )
    assert strict.status_code == 200, strict.text
    assert strict.json()["data"]["current_count"] == 1
    assert [row["job_id"] for row in strict.json()["data"]["items"]] == ["exact"]
    repeated = client.post(
        PREFIX + "/analyses/completed", json={**request, "trace_id": str(uuid4())}
    )
    assert repeated.json() == original.json()


def test_v4_ceiling_roundtrips_through_saved_matching_projection(client):
    records = batch(
        posting(
            "levelled",
            required=("Java",),
            required_text="지원자격\n경력 5년 이상\nJava 경험",
        )
    )
    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=records.model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    response = client.post(
        PREFIX + "/analyses/completed",
        json=event(
            user_id="user-1",
            analysis_id="analysis-1",
            cohort_snapshot_id=cohort_id,
            evidence=ceiling_evidence_payload(),
        ),
    )
    assert response.status_code == 200, response.text
    result_id = snapshot_ref(response, "RECOMMENDATION")

    listing = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-postings",
        params={"user_id": "user-1"},
    ).json()["data"]
    clause = listing["items"][0]["required"]["clauses"][0]

    assert clause["verdict"] == "EVIDENCE_SCOPE_INCOMPLETE"
    assert clause["assessment_ceilings"] == {"java": "L1"}
    assert clause["assessment_ceiling_applied"] is True
    assert listing["items"][0]["required_status"] == "UNKNOWN"


def test_partial_matching_auth_scope_and_pagination(client):
    result_id, _, _ = _prepare(client)
    url = PREFIX + f"/recommendations/{result_id}/matching-job-postings"
    assert client.get(url, params={"user_id": "user-2"}).status_code == 404
    assert (
        client.get(
            url,
            params={"user_id": "user-1"},
            headers={"Authorization": "Bearer incorrect"},
        ).status_code
        == 401
    )
    assert client.get(url, params={"user_id": "user-1", "size": 51}).status_code == 422
    assert client.get(url, params={"user_id": "user-1", "page": -1}).status_code == 422
    response = client.get(url, params={"user_id": "user-1", "page": 100})
    assert response.json()["data"]["items"] == []
    huge = client.get(url, params={"user_id": "user-1", "page": 10**100})
    assert huge.status_code == 200
    assert huge.json()["data"]["items"] == []
    assert huge.json()["data"]["has_next"] is False
    assert (
        client.get(
            PREFIX + f"/recommendations/{result_id}/matching-job-posting",
            params={"user_id": "user-1", "job_id": "closed"},
        ).status_code
        == 404
    )


def test_matching_result_budget_rejects_without_publishing_a_truncated_snapshot(
    client, monkeypatch
):
    cohort = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting("budget-result")).model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    monkeypatch.setattr("job.matching.MAX_MATCHING_RESULT_BYTES", 1)

    response = client.post(
        PREFIX + "/analyses/completed",
        json=event(
            user_id="user-1",
            analysis_id="analysis-budget",
            cohort_snapshot_id=cohort,
            evidence={
                **make_analysis().model_dump(mode="json"),
                "analysis_id": "analysis-budget",
                "repositories": [
                    {
                        **row,
                        "user_id": "user-1",
                    }
                    for row in make_analysis().model_dump(mode="json")["repositories"]
                ],
            },
        ),
    )

    assert response.status_code == 413
    assert response.json()["code"] == "RESULT_TOO_LARGE"


def test_known_satisfaction_with_unresolved_conditions_is_partial_when_strict_is_empty(
    client,
):
    record = posting(
        required=("Java", "Python", "Docker"),
        required_text="Java 경험\nPython, Docker 등을 활용",
    )
    response = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=batch(record).model_dump(mode="json"),
            criteria=criteria().model_dump(mode="json"),
        ),
    )
    cohort_id = snapshot_ref(response, "COHORT")
    completed = client.post(
        PREFIX + "/analyses/completed",
        json=event(
            user_id="user-1",
            analysis_id="analysis-1",
            cohort_snapshot_id=cohort_id,
            evidence=levelled_evidence_payload("L3"),
        ),
    )
    result_id = snapshot_ref(completed, "RECOMMENDATION")
    result = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-postings",
        params={"user_id": "user-1"},
    )
    assert result.status_code == 200, result.text
    item = result.json()["data"]["items"][0]
    assert item["required"]["satisfied_count"] == 1
    assert item["required"]["fulfillment_ratio"] is None
    assert item["required_status"] == "PARTIAL"


def test_matching_application_recreation_reads_same_saved_result(client):
    result_id, request, original = _prepare(client)
    path = PREFIX + f"/recommendations/{result_id}/matching-job-postings"
    before = client.get(path, params={"user_id": "user-1"}).json()
    store = client.matching_test_store
    # Only the postgres parametrization proves a fresh connection reads durable data.
    reopened = (
        ComputeStore(os.environ["C_COMPUTE_TEST_DATABASE_URL"])
        if isinstance(store, ComputeStore)
        else store
    )
    app = create_compute_app(store=reopened, token=TOKEN, registry=REGISTRY)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as restarted:
        assert restarted.get(path, params={"user_id": "user-1"}).json() == before
        assert (
            restarted.post(PREFIX + "/analyses/completed", json=request).json()
            == original.json()
        )


def test_matching_list_and_detail_do_not_fetch_the_whole_recommendation(client):
    result_id, _, _ = _prepare(client)
    store = client.matching_test_store
    if not isinstance(store, MemoryStore):
        pytest.skip("The PostgreSQL query shape is covered by projection integration")
    store.get_snapshot_calls = 0

    list_response = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-postings",
        params={"user_id": "user-1", "size": 1},
    )
    detail_response = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-posting",
        params={"user_id": "user-1", "job_id": "partial"},
    )

    assert list_response.status_code == detail_response.status_code == 200
    assert store.get_snapshot_calls == 0


def test_postgres_projection_rows_cannot_be_updated_or_deleted(client):
    result_id, _, _ = _prepare(client)
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL trigger boundary")
    import psycopg

    dsn = os.environ["C_COMPUTE_TEST_DATABASE_URL"]
    statements = (
        (
            (
                "UPDATE c_compute.matching_job SET eligibility = 'CONDITIONAL' "
                "WHERE recommendation_snapshot_id = %s"
            ),
            (result_id,),
        ),
        (
            (
                "DELETE FROM c_compute.matching_job "
                "WHERE recommendation_snapshot_id = %s"
            ),
            (result_id,),
        ),
    )
    for sql, params in statements:
        with (
            pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
            psycopg.connect(dsn) as conn,
        ):
            conn.execute(sql, params)

    response = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-postings",
        params={"user_id": "user-1", "include_conditional": True},
    )
    assert response.status_code == 200
    assert response.json()["data"]["total_count"] == 3


@pytest.mark.parametrize("field", ["user_id", "analysis_id", "cohort_id"])
def test_stored_matching_scope_corruption_is_a_controlled_server_error(client, field):
    result_id, _, _ = _prepare(client)
    store = client.matching_test_store
    original = None
    if isinstance(store, ComputeStore):
        import psycopg
        from psycopg.types.json import Jsonb

        dsn = os.environ["C_COMPUTE_TEST_DATABASE_URL"]
        with psycopg.connect(dsn) as conn:
            original = conn.execute(
                "SELECT metadata FROM c_compute.matching_calculation "
                "WHERE recommendation_snapshot_id = %s",
                (result_id,),
            ).fetchone()[0]
            changed = dict(original)
            changed[field] = "stored-corruption"
            conn.execute(
                "UPDATE c_compute.matching_calculation "
                "SET metadata = %s, metadata_hash = %s "
                "WHERE recommendation_snapshot_id = %s",
                (Jsonb(changed), digest(changed), result_id),
            )
    else:
        original = dict(store.matching[result_id]["metadata"])
        store.matching[result_id]["metadata"][field] = "stored-corruption"
    try:
        response = client.get(
            PREFIX + f"/recommendations/{result_id}/matching-job-postings",
            params={"user_id": "user-1"},
        )
    finally:
        if isinstance(store, ComputeStore):
            with psycopg.connect(os.environ["C_COMPUTE_TEST_DATABASE_URL"]) as conn:
                conn.execute(
                    "UPDATE c_compute.matching_calculation "
                    "SET metadata = %s, metadata_hash = %s "
                    "WHERE recommendation_snapshot_id = %s",
                    (Jsonb(original), digest(original), result_id),
                )
        else:
            store.matching[result_id]["metadata"] = original
    assert response.status_code == 500
    assert response.json() == {
        "code": "STORED_MATCHING_INTEGRITY_FAILED",
        "message": "Stored matching result failed an integrity check",
    }


@pytest.mark.parametrize("field", ["user_id", "analysis_id", "cohort_id"])
def test_legacy_embedded_scope_corruption_is_also_a_controlled_server_error(
    client, field
):
    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting(f"legacy-{field}")).model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    cohort = JobCohort.model_validate(
        client.get(PREFIX + f"/snapshots/{cohort_id}").json()["data"]["payload"]
    )
    embedded = build_job_matching(
        cohort,
        make_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    ).model_dump(mode="json")
    embedded["schema_version"] = "job-matching/v1"
    embedded.pop("calculation_snapshot_id")
    embedded[field] = "stored-corruption"
    payload = {
        "analysis_id": "analysis-1",
        "cohort_id": cohort.cohort_id,
        "job_matching": embedded,
    }
    store = client.matching_test_store
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="ANALYSIS",
        owner="user-1",
        occurred_at=datetime.now(UTC),
        request={"legacy-corruption": field},
    )
    result_id = store.complete(
        ticket, [Artifact("RECOMMENDATION", "user-1", payload, str(uuid4()))]
    )[0]["snapshot_id"]

    response = client.get(
        PREFIX + f"/recommendations/{result_id}/matching-job-postings",
        params={"user_id": "user-1"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "STORED_MATCHING_INTEGRITY_FAILED"


def test_legacy_embedded_v1_remains_readable_with_bounded_empty_pages(client):
    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting("legacy-readable")).model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    cohort = JobCohort.model_validate(
        client.get(PREFIX + f"/snapshots/{cohort_id}").json()["data"]["payload"]
    )
    embedded = build_job_matching(
        cohort,
        make_analysis(),
        user_id="user-1",
        analysis_id="analysis-1",
    ).model_dump(mode="json")
    embedded["schema_version"] = "job-matching/v1"
    embedded.pop("calculation_snapshot_id")
    payload = {
        "analysis_id": "analysis-1",
        "cohort_id": cohort.cohort_id,
        "job_matching": embedded,
    }
    store = client.matching_test_store
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="ANALYSIS",
        owner="user-1",
        occurred_at=datetime.now(UTC),
        request={"legacy-readable": True},
    )
    result_id = store.complete(
        ticket, [Artifact("RECOMMENDATION", "user-1", payload, str(uuid4()))]
    )[0]["snapshot_id"]
    path = PREFIX + f"/recommendations/{result_id}/matching-job-postings"

    normal = client.get(path, params={"user_id": "user-1"})
    huge = client.get(path, params={"user_id": "user-1", "page": 10**100})

    assert normal.status_code == 200
    assert normal.json()["data"]["items"][0]["job"]["job_id"] == "legacy-readable"
    assert huge.status_code == 200
    assert huge.json()["data"]["items"] == []
    assert huge.json()["data"]["has_next"] is False


def test_legacy_result_keeps_strict_listing_but_does_not_synthesize_partial(client):
    payload = json.loads(
        (Path(__file__).parent / "fixtures/recommendation-legacy-v1.json").read_text()
    )
    store = client.matching_test_store
    ticket = store.claim(
        event_id=str(uuid4()),
        kind="ANALYSIS",
        owner="user-1",
        occurred_at=datetime.now(UTC),
        request={"legacy": payload["snapshot_id"]},
    )
    result_id = store.complete(
        ticket, [Artifact("RECOMMENDATION", "user-1", payload, str(uuid4()))]
    )[0]["snapshot_id"]
    path = PREFIX + f"/recommendations/{result_id}"
    before = client.get(
        PREFIX + f"/snapshots/{result_id}", params={"user_id": "user-1"}
    ).json()["data"]["payload"]
    assert before == payload
    assert (
        client.get(path + "/job-postings", params={"user_id": "user-1"}).status_code
        == 200
    )
    response = client.get(path + "/matching-job-postings", params={"user_id": "user-1"})
    assert response.status_code == 409
    assert response.json()["code"] == "JOB_MATCHING_NOT_PREPARED"
    assert (
        client.get(
            PREFIX + f"/snapshots/{result_id}", params={"user_id": "user-1"}
        ).json()["data"]["payload"]
        == before
    )
