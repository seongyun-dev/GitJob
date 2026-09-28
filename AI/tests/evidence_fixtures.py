"""Synthetic accepted B proofs; not evidence from an actual repository."""


def proof_payload(kind, *, tech_id="java", suffix="1"):
    return {
        "evidence_id": f"evidence-{kind}-{suffix}",
        "fact_id": f"fact-{kind}-{suffix}",
        "rule_id": f"synthetic-{kind}-rule",
        "rule_version": "evidence-rules/v2",
        "tech_id": tech_id,
        "user_id": "user-1",
        "analysis_id": "analysis-1",
        "repository_id": "repo-1",
        "repository_analysis_id": "repo-analysis-1",
        "source_commit_sha": "a" * 40,
        "kind": kind,
        "source_kind": "MANIFEST" if kind == "DIRECT_DEPENDENCY" else "SOURCE",
        "path": "pom.xml" if kind == "DIRECT_DEPENDENCY" else "src/Main.java",
        "line_start": 1,
        "line_end": 2,
        "source_ref": f"b-evidence://repo-1/{kind}/{suffix}",
        "acceptance": "ACCEPTED",
        "exclusion_reason": None,
        "origin": "PROJECT",
        "inherited": False,
        "attribution": "SELF" if kind != "DIRECT_DEPENDENCY" else "NONE",
        "attribution_commit_sha": "b" * 40 if kind != "DIRECT_DEPENDENCY" else None,
        "direct_dependency": True if kind == "DIRECT_DEPENDENCY" else None,
    }
