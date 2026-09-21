"""Same saved assessment is used by list/detail and active-population What-if."""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_compute_api import PREFIX, REGISTRY, TOKEN, event, snapshot_ref
from test_job_cohort import batch, criteria, posting
from test_job_input_union import output
from test_recommendation_engine import make_analysis

from job.cohort import JobCohort
from job.input_union import prepare_input_union
from job.matching import build_job_matching, restore_job_assessment
from job.projection import materialize_job_projection
from registry.mapper import RegistryMapper
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
        self.active_job_ids = None

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
        self,
        snapshot_id,
        *,
        owner,
        offset,
        limit,
        include_conditional,
        active_only=False,
        as_of=None,
    ):
        stored = self._matching(snapshot_id, owner)
        if not stored or stored["status"] != "READY":
            return stored
        sources = {row["job_id"]: row for row in stored["sources"]}
        rows = [
            row
            for row in stored["assessments"]
            if (not active_only or row["job_id"] in self.active_job_ids)
            and (include_conditional or row["eligibility"] == "ELIGIBLE")
        ]
        active_rows = [
            row
            for row in stored["assessments"]
            if not active_only or row["job_id"] in self.active_job_ids
        ]
        page = rows[offset : offset + limit]
        return {
            **stored,
            "total_count": len(active_rows),
            "eligible_count": sum(
                row["eligibility"] == "ELIGIBLE" for row in active_rows
            ),
            "conditional_count": sum(
                row["eligibility"] == "CONDITIONAL" for row in active_rows
            ),
            "active_current_count": (
                stored["metadata"]["current_count"] if not active_only else 0
            ),
            "items": [
                restore_job_assessment(
                    sources[row["job_id"]], row["assessment"]
                ).model_dump(mode="json")
                for row in page
            ],
            "has_next": offset + limit < len(rows),
        }

    def get_matching_detail(
        self, snapshot_id, *, owner, job_id, active_only=False, as_of=None
    ):
        stored = self._matching(snapshot_id, owner)
        if not stored or stored["status"] != "READY":
            return stored
        sources = {row["job_id"]: row for row in stored["sources"]}
        row = next(
            (
                row
                for row in stored["assessments"]
                if row["job_id"] == job_id
                and (not active_only or job_id in self.active_job_ids)
            ),
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

    def get_active_job_ids(self, job_ids, *, as_of=None):
        requested = frozenset(job_ids)
        return requested if self.active_job_ids is None else requested & self.active_job_ids

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


def test_partial_matching_roundtrip_pages_detail_and_active_whatif(client):
    result_id, request, original = _prepare(client)
    listing_url = PREFIX + f"/recommendations/{result_id}/matching-job-postings"
    response = client.get(listing_url, params={"user_id": "user-1", "size": 1})
    assert response.status_code == 200, response.text
    listing = response.json()["data"]
    assert listing["total_count"] == 2
    assert listing["conditional_count"] == 1
    assert listing["excluded_conditional_count"] == 1
    # The page response carries the recommendation summary and demand basis so B
    # does not need a second C round trip for every page navigation.
    assert listing["current_count"] == 1
    assert listing["demand"]["cohort_id"] == listing["cohort_id"]
    assert listing["demand"]["denominator"] == 3
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


def test_analysis_uses_resolved_demand_basis_for_scope_counts(client):
    store = client.matching_test_store
    if not isinstance(store, MemoryStore):
        pytest.skip("HTTP contract regression uses the in-memory snapshot double")

    job_response = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=batch(posting("scope-counts", required=("Java",))).model_dump(
                mode="json"
            ),
            criteria=criteria().model_dump(mode="json"),
        ),
    )
    cohort_id = snapshot_ref(job_response, "COHORT")
    original_demand_id = snapshot_ref(job_response, "DEMAND")
    demand = dict(store.snapshots[original_demand_id]["payload"])
    demand.update(input_count=6, excluded_count=4, review_count=1)
    demand_id = "c-" + "d" * 64
    store.snapshots[demand_id] = {
        "snapshot_id": demand_id,
        "kind": "DEMAND",
        "owner": None,
        "payload": demand,
    }

    response = client.post(
        PREFIX + "/analyses/completed",
        json=event(
            user_id="user-1",
            analysis_id="analysis-1",
            cohort_snapshot_id=cohort_id,
            demand_snapshot_id=demand_id,
            evidence=levelled_evidence_payload(),
        ),
    )

    assert response.status_code == 200, response.text
    result_id = snapshot_ref(response, "RECOMMENDATION")
    result = store.snapshots[result_id]["payload"]
    assert result["demand"]["input_count"] == 6
    assert result["demand"]["excluded_count"] == 4
    assert result["demand"]["review_count"] == 1
    assert "COHORT_RECORDS_REQUIRE_REVIEW:1" in result["data_gaps"]


def test_analysis_rejects_demand_from_another_cohort(client):
    store = client.matching_test_store
    if not isinstance(store, MemoryStore):
        pytest.skip("HTTP contract regression uses the in-memory snapshot double")

    job_response = client.post(
        PREFIX + "/job-batches/completed",
        json=event(
            batch=batch(posting("wrong-demand", required=("Java",))).model_dump(
                mode="json"
            ),
            criteria=criteria().model_dump(mode="json"),
        ),
    )
    cohort_id = snapshot_ref(job_response, "COHORT")
    original_demand_id = snapshot_ref(job_response, "DEMAND")
    demand = dict(store.snapshots[original_demand_id]["payload"])
    demand["cohort_id"] = "foreign-cohort"
    demand_id = "c-" + "e" * 64
    store.snapshots[demand_id] = {
        "snapshot_id": demand_id,
        "kind": "DEMAND",
        "owner": None,
        "payload": demand,
    }

    response = client.post(
        PREFIX + "/analyses/completed",
        json=event(
            user_id="user-1",
            analysis_id="analysis-1",
            cohort_snapshot_id=cohort_id,
            demand_snapshot_id=demand_id,
            evidence=levelled_evidence_payload(),
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


def test_projection_analysis_requires_its_resolved_demand_pair(client):
    store = client.matching_test_store
    if not isinstance(store, MemoryStore):
        pytest.skip("HTTP contract regression uses the in-memory snapshot double")

    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting("projection-without-demand")).model_dump(
                    mode="json"
                ),
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
            projection_version_id="jp-" + "a" * 64,
            evidence=levelled_evidence_payload(),
        ),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_INPUT"


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


def test_projection_active_mode_filters_count_page_detail_and_what_if(
    monkeypatch,
):
    monkeypatch.setenv("C_JOB_MATCHING_ACTIVE_MODE", "projection")
    store = MemoryStore()
    app = create_compute_app(store=store, token=TOKEN, registry=REGISTRY)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as active_client:
        result_id, _, _ = _prepare(active_client)
        store.active_job_ids = {"partial"}

        listing = active_client.get(
            PREFIX + f"/recommendations/{result_id}/matching-job-postings",
            params={"user_id": "user-1", "include_conditional": True},
        )
        assert listing.status_code == 200, listing.text
        data = listing.json()["data"]
        assert data["total_count"] == 1
        assert [row["job"]["job_id"] for row in data["items"]] == [
            "partial"
        ]

        hidden = active_client.get(
            PREFIX + f"/recommendations/{result_id}/matching-job-posting",
            params={"user_id": "user-1", "job_id": "exact"},
        )
        assert hidden.status_code == 404

        what_if = active_client.get(
            PREFIX + f"/recommendations/{result_id}/job-postings",
            params={
                "user_id": "user-1",
                "mode": "WHAT_IF",
                "recommended_tech_id": "docker",
            },
        )
        assert what_if.status_code == 200, what_if.text
        delta = what_if.json()["data"]
        assert delta["total_count"] == delta["increased_count"]
        assert {row["job_id"] for row in delta["items"]} <= store.active_job_ids


def test_postgres_current_result_payload_is_slim_and_head_is_atomic(client):
    result_id, _, _ = _prepare(client)
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL result tables")
    import psycopg

    with psycopg.connect(
        os.environ["C_COMPUTE_TEST_DATABASE_URL"], row_factory=psycopg.rows.dict_row
    ) as conn:
        result = conn.execute(
            "SELECT * FROM c_compute.user_result WHERE recommendation_snapshot_id = %s",
            (result_id,),
        ).fetchone()
        head = conn.execute(
            """SELECT * FROM c_compute.user_result_head
               WHERE user_id = 'user-1' AND result_id = %s""",
            (result["result_id"],),
        ).fetchone()

    assert result is not None and head is not None
    assert result["status"] == "READY"
    assert result["compact_payload"]["recommendation_snapshot_id"] == result_id
    assert not {
        "jobs",
        "matching_jobs",
        "job_matching",
        "job_matching_ref",
    }.intersection(result["compact_payload"])
    assert isinstance(result["compact_payload"]["explanation"], dict)


def test_postgres_current_head_does_not_regress_on_late_older_completion(client):
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL result tables")
    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting("ordered-head")).model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    target_key = "BACKEND|서울|신입"
    older_at = datetime.now(UTC) - timedelta(minutes=1)
    newer_at = datetime.now(UTC)

    def complete(*, occurred_at, level):
        request = event(
            user_id="user-1",
            analysis_id="analysis-1",
            target_key=target_key,
            cohort_snapshot_id=cohort_id,
            evidence=levelled_evidence_payload(level),
        )
        request["occurred_at"] = occurred_at.isoformat()
        response = client.post(PREFIX + "/analyses/completed", json=request)
        assert response.status_code == 200, response.text
        return next(
            reference["result_id"]
            for reference in response.json()["data"]["results"]
            if reference["kind"] == "RECOMMENDATION"
        )

    newer_result_id = complete(occurred_at=newer_at, level="L2")
    older_result_id = complete(occurred_at=older_at, level="L1")

    current = store.get_current_user_result(owner="user-1", target_key=target_key)
    assert current["result_id"] == newer_result_id
    assert current["result_id"] != older_result_id


def test_postgres_projection_a_b_a_restores_each_pinned_fact(client):
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL projection tables")
    mapper = RegistryMapper(REGISTRY)
    selected = criteria(as_of="2026-09-10T00:00:00Z")

    def projection(required, collected_at):
        prepared = prepare_input_union(
            (
                output(
                    posting(
                        "fact-history",
                        required=required,
                        collected_at=collected_at,
                    )
                ),
            ),
            selected,
            mapper,
        )
        return materialize_job_projection(prepared)

    projection_a = projection(("Java",), "2026-09-07T00:00:00Z")
    projection_b = projection(("Docker",), "2026-09-08T00:00:00Z")
    projection_a_again_id = "jp-" + digest(
        {"again": projection_a.projection_version_id}
    )
    projection_a_again = replace(
        projection_a,
        projection_version_id=projection_a_again_id,
        observed_at=datetime(2026, 9, 9, tzinfo=UTC),
        jobs=tuple(
            replace(job, projection_version_id=projection_a_again_id)
            for job in projection_a.jobs
        ),
        market_jobs=tuple(
            replace(job, projection_version_id=projection_a_again_id)
            for job in projection_a.market_jobs
        ),
        market_candidates=tuple(
            replace(candidate, projection_version_id=projection_a_again_id)
            for candidate in projection_a.market_candidates
        ),
    )

    def complete(pinned):
        store.publish_job_projection(pinned)
        projected = store.query_job_projection_cohort(
            selected, projection_version_id=pinned.projection_version_id
        )
        pair = store.store_projection_compatibility_pair(
            projected.cohort, projected.snapshot
        )
        response = client.post(
            PREFIX + "/analyses/completed",
            json=event(
                user_id="user-1",
                analysis_id="analysis-1",
                target_key="BACKEND|서울|신입",
                cohort_snapshot_id=pair["cohort_snapshot_id"],
                projection_version_id=pinned.projection_version_id,
                evidence=levelled_evidence_payload("L3"),
            ),
        )
        assert response.status_code == 200, response.text
        return snapshot_ref(response, "RECOMMENDATION")

    result_a = complete(projection_a)
    result_b = complete(projection_b)
    result_a_again = complete(projection_a_again)

    def required_techs(result_id):
        response = client.get(
            PREFIX + f"/recommendations/{result_id}/matching-job-posting",
            params={"user_id": "user-1", "job_id": "SARAMIN:fact-history"},
        )
        assert response.status_code == 200, response.text
        clause = response.json()["data"]["item"]["required"]["clauses"][0]
        return sorted(
            clause["held_tech_ids"]
            + clause["missing_tech_ids"]
            + clause["unknown_tech_ids"]
        )

    assert required_techs(result_a) == ["java"]
    assert required_techs(result_b) == ["docker"]
    assert required_techs(result_a_again) == ["java"]


def test_postgres_target_a_b_a_keeps_independent_logical_heads(client):
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL result tables")
    cohort_id = snapshot_ref(
        client.post(
            PREFIX + "/job-batches/completed",
            json=event(
                batch=batch(posting("target-history")).model_dump(mode="json"),
                criteria=criteria().model_dump(mode="json"),
            ),
        ),
        "COHORT",
    )
    target_a = "BACKEND|서울|신입"
    target_b = "BACKEND|부산|경력"

    def complete(target_key, level):
        response = client.post(
            PREFIX + "/analyses/completed",
            json=event(
                user_id="user-1",
                analysis_id="analysis-1",
                target_key=target_key,
                cohort_snapshot_id=cohort_id,
                evidence=levelled_evidence_payload(level),
            ),
        )
        assert response.status_code == 200, response.text
        return next(
            reference["result_id"]
            for reference in response.json()["data"]["results"]
            if reference["kind"] == "RECOMMENDATION"
        )

    first_a = complete(target_a, "L1")
    current_b = complete(target_b, "L2")
    current_a = complete(target_a, "L3")

    head_a = store.get_current_user_result(owner="user-1", target_key=target_a)
    head_b = store.get_current_user_result(owner="user-1", target_key=target_b)
    assert head_a["result_id"] == current_a
    assert head_a["previous_result_id"] == first_a
    assert head_b["result_id"] == current_b


def test_postgres_c_and_ur_aliases_share_legacy_status_and_explanation(client):
    store = client.matching_test_store
    if not isinstance(store, ComputeStore):
        pytest.skip("Requires the isolated PostgreSQL result tables")
    snapshot_id, _, completed = _prepare(client)
    compact_id = next(
        reference["result_id"]
        for reference in completed.json()["data"]["results"]
        if reference["kind"] == "RECOMMENDATION"
    )

    legacy_alias = client.get(
        PREFIX + f"/results/{snapshot_id}", params={"user_id": "user-1"}
    )
    compact_alias = client.get(
        PREFIX + f"/results/{compact_id}", params={"user_id": "user-1"}
    )

    assert legacy_alias.status_code == compact_alias.status_code == 200
    legacy_data = legacy_alias.json()["data"]
    compact_data = compact_alias.json()["data"]
    assert legacy_data["status"] == compact_data["status"] == "LEGACY"
    assert not legacy_data["recompute_required"]
    assert not compact_data["recompute_required"]
    assert legacy_data["payload"]["explanation"] == compact_data["payload"][
        "explanation"
    ]


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
