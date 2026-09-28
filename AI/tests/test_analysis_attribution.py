"""Pinned-commit evidence attribution keeps identity and history gaps explicit."""

from __future__ import annotations

import subprocess

from test_analysis_result_v2 import _request

from analysis.attribution import (
    FixtureIdentityResolver,
    GitEvidenceAttributor,
)
from analysis.configs import ConfigScanner, facts_from_configs
from analysis.judge import (
    EvidenceFact,
    Fact,
    Judge,
    facts_from_calls,
    facts_from_imports,
    facts_from_sources,
    facts_from_syntax,
)
from analysis.manifests import ManifestScanner
from analysis.parse import RepositoryParser
from analysis.personal_level import assess_personal_levels
from analysis.publish import completed_result
from analysis.rulepack import (
    SCOPE_REGISTRY_PATH,
    SCOPE_RULE_PACK_PATH,
    load_rule_pack,
    mappings_from_registry_artifact,
)


def _git(repo, *args, env=None):
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def _commit(repo, message, *, name, email):
    _git(
        repo,
        "-c",
        f"user.name={name}",
        "-c",
        f"user.email={email}",
        "commit",
        "-am",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _evidence(rule_id, line):
    return EvidenceFact(
        rule_id,
        "python",
        Fact(
            "SYNTAX_NODE",
            {"KIND": "FUNCTION_DECLARATION", "FILE_PATH": "service.py"},
            "service.py",
            line,
            frozenset({"python"}),
        ),
    )


def test_pinned_lines_are_self_or_other_from_b_supplied_logins(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    source = repo / "service.py"
    source.write_text("def owned():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "service.py")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "alice line",
    )
    alice_sha = _git(repo, "rev-parse", "HEAD")
    source.write_text(
        "def owned():\n    return 1\n\ndef maintained():\n    return 2\n",
        encoding="utf-8",
    )
    bob_sha = _commit(repo, "bob line", name="Bob", email="bob@example.invalid")

    attributed = GitEvidenceAttributor(max_deepen_commits=0).attribute(
        repo,
        bob_sha,
        "analysis-repository-1",
        (_evidence("python.l2.structured-function", 1), _evidence("python.l3.task", 4)),
        FixtureIdentityResolver(
            target_login="AliceHub",
            author_logins={alice_sha: "alicehub", bob_sha: "bobhub"},
        ),
    )

    assert [item.attribution for item in attributed] == ["SELF", "OTHER"]
    assert [item.attribution_commit_sha for item in attributed] == [
        alice_sha,
        bob_sha,
    ]
    assert all(not item.missing_scope for item in attributed)


def test_unresolved_commit_identity_is_unknown_not_other(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    (repo / "service.py").write_text("def owned():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "service.py")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "line",
    )
    pinned = _git(repo, "rev-parse", "HEAD")

    attributed = GitEvidenceAttributor(max_deepen_commits=0).attribute(
        repo,
        pinned,
        "analysis-repository-1",
        (_evidence("python.l2.structured-function", 1),),
        FixtureIdentityResolver(target_login="alice", author_logins={}),
    )

    assert attributed[0].attribution == "UNKNOWN"
    assert attributed[0].attribution_commit_sha == pinned
    assert attributed[0].missing_scope == ("AUTHOR_IDENTITY_UNRESOLVED",)


def test_git_output_is_decoded_as_utf8_on_windows(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    GitEvidenceAttributor()._git(tmp_path, "status")

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


def test_shallow_boundary_is_unknown_and_never_sent_to_identity_resolver(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    (source / "service.py").write_text("def owned():\n    return 1\n", encoding="utf-8")
    _git(source, "add", "service.py")
    _git(
        source,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "first",
    )
    pinned = _git(source, "rev-parse", "HEAD")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", source.as_uri(), str(shallow)],
        check=True,
        capture_output=True,
        text=True,
    )
    resolver = FixtureIdentityResolver(
        target_login="alice", author_logins={pinned: "alice"}
    )

    attributed = GitEvidenceAttributor(max_deepen_commits=0).attribute(
        shallow,
        pinned,
        "analysis-repository-1",
        (_evidence("python.l2.structured-function", 1),),
        resolver,
    )

    assert attributed[0].attribution == "UNKNOWN"
    assert attributed[0].attribution_commit_sha is None
    assert attributed[0].missing_scope == ("BLAME_HISTORY_INCOMPLETE",)
    assert resolver.requested_commit_shas == ()


def test_fact_without_a_usable_line_is_unknown_not_an_invented_file_owner(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    resolver = FixtureIdentityResolver(
        target_login="alice", author_logins={"a" * 40: "alice"}
    )
    evidence = EvidenceFact(
        "python.l1.source",
        "python",
        Fact(
            "SOURCE_FILE",
            {"LANGUAGE": "python", "FILE_PATH": "service.py"},
            "service.py",
            0,
            frozenset({"python"}),
        ),
    )

    attributed = GitEvidenceAttributor().attribute(
        repo,
        "b" * 40,
        "analysis-repository-1",
        (evidence,),
        resolver,
    )

    assert attributed[0].attribution == "UNKNOWN"
    assert attributed[0].attribution_commit_sha is None
    assert attributed[0].missing_scope == ("EVIDENCE_LINE_UNAVAILABLE",)
    assert resolver.requested_commit_shas == ()


def test_source_file_line_one_is_not_treated_as_file_authorship(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    (repo / "service.py").write_text(
        "# Bob's header\ndef owned():\n    pass\n", encoding="utf-8"
    )
    _git(repo, "add", "service.py")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "file",
    )
    pinned = _git(repo, "rev-parse", "HEAD")
    source = EvidenceFact(
        "python.l1.source",
        "python",
        Fact(
            "SOURCE_FILE",
            {"LANGUAGE": "python", "FILE_PATH": "service.py"},
            "service.py",
            1,
            frozenset({"python"}),
        ),
    )
    resolver = FixtureIdentityResolver(
        target_login="alice", author_logins={pinned: "alice"}
    )

    attributed = GitEvidenceAttributor().attribute(
        repo, pinned, "analysis-repository-1", (source,), resolver
    )

    assert attributed[0].attribution == "UNKNOWN"
    assert attributed[0].attribution_commit_sha is None
    assert attributed[0].missing_scope == ("EVIDENCE_LINE_UNAVAILABLE",)
    assert resolver.requested_commit_shas == ()


def test_deepen_budget_and_blame_cache_are_shared_by_one_attribute_request(tmp_path):
    class RecordingAttributor(GitEvidenceAttributor):
        def __init__(self):
            super().__init__(max_deepen_commits=10, deepen_step=4)
            self.deepen_amounts = []
            self.blame_calls = []

        def _run_blame(self, _checkout, _pinned, relative_path, line):
            self.blame_calls.append((relative_path, line))
            return "a" * 40, True

        def _is_shallow(self, _checkout):
            return True

        def _deepen(self, _checkout, _pinned, amount):
            self.deepen_amounts.append(amount)
            return True

    first = _evidence("python.l2.first", 1)
    duplicate = _evidence("python.l2.duplicate-rule", 1)
    second = _evidence("python.l3.second", 2)
    resolver = FixtureIdentityResolver(
        target_login="alice", author_logins={"a" * 40: "alice"}
    )
    attributor = RecordingAttributor()

    attributed = attributor.attribute(
        tmp_path,
        "b" * 40,
        "analysis-repository-1",
        (first, duplicate, second),
        resolver,
    )

    assert attributor.deepen_amounts == [4, 4, 2]
    assert sum(attributor.deepen_amounts) == attributor.max_deepen_commits
    assert attributor.blame_calls.count(("service.py", 1)) == 4
    assert attributor.blame_calls.count(("service.py", 2)) == 1
    assert all(
        item.missing_scope == ("BLAME_HISTORY_INCOMPLETE",) for item in attributed
    )


def test_try_finally_fact_is_attributed_at_the_actual_finally_clause(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    source = repo / "service.py"
    source.write_text(
        "def placeholder():\n"
        "    try:\n"
        "        pass\n"
        "    except Exception:\n"
        "        raise\n",
        encoding="utf-8",
    )
    _git(repo, "add", "service.py")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "try header",
    )
    alice_sha = _git(repo, "rev-parse", "HEAD")
    source.write_text(
        "import asyncio\n\n"
        "async def run(work):\n"
        "    task = asyncio.create_task(work)\n"
        "    try:\n"
        "        return await asyncio.wait_for(task, timeout=1)\n"
        "    except Exception:\n"
        "        raise\n"
        "    finally:\n"
        "        task.cancel()\n",
        encoding="utf-8",
    )
    bob_sha = _commit(
        repo, "finally implementation", name="Bob", email="bob@example.invalid"
    )
    report = RepositoryParser().parse_repository(repo)
    evidence = EvidenceFact(
        "python.l3.task-timeout-cleanup",
        "python",
        next(
            fact
            for fact in facts_from_syntax(report.syntax)
            if fact.fields.get("KIND") == "TRY_FINALLY"
        ),
    )

    attributed = GitEvidenceAttributor(max_deepen_commits=0).attribute(
        repo,
        bob_sha,
        "analysis-repository-1",
        (evidence,),
        FixtureIdentityResolver(
            target_login="alice",
            author_logins={alice_sha: "alice", bob_sha: "bob"},
        ),
    )

    assert evidence.fact.line == 9
    assert attributed[0].attribution == "OTHER"
    assert attributed[0].attribution_commit_sha == bob_sha


def test_literal_backslash_git_path_does_not_collide_with_slash_path(tmp_path):
    class PathAwareAttributor(GitEvidenceAttributor):
        def __init__(self):
            super().__init__(max_deepen_commits=0)
            self.paths = []

        def _run_blame(self, _checkout, _pinned, relative_path, _line):
            self.paths.append(relative_path)
            return (
                ("a" * 40, False)
                if relative_path == "foo/bar.py"
                else ("b" * 40, False)
            )

        def _is_shallow(self, _checkout):
            return False

    def path_evidence(path):
        return EvidenceFact(
            "python.l2.structured-function",
            "python",
            Fact("SYNTAX_NODE", {"KIND": "FUNCTION"}, path, 1),
        )

    attributor = PathAwareAttributor()
    attributed = attributor.attribute(
        tmp_path,
        "c" * 40,
        "analysis-repository-1",
        (path_evidence("foo/bar.py"), path_evidence(r"foo\bar.py")),
        FixtureIdentityResolver(
            target_login="alice",
            author_logins={"a" * 40: "bob", "b" * 40: "alice"},
        ),
    )

    assert attributor.paths == ["foo/bar.py", r"foo\bar.py"]
    assert [item.attribution for item in attributed] == ["OTHER", "SELF"]


def test_typescript_l3_narrowed_alias_prerequisite_does_not_promote_owner(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    source = repo / "advanced.ts"
    source.write_text("type Advanced<T> =\n    T;\n", encoding="utf-8")
    _git(repo, "add", "advanced.ts")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "type alias",
    )
    alice_sha = _git(repo, "rev-parse", "HEAD")
    source.write_text(
        "type Advanced<T> =\n"
        "    T extends infer U ? { [K in keyof U]: U[K] } : never;\n",
        encoding="utf-8",
    )
    bob_sha = _commit(
        repo, "advanced type operations", name="Bob", email="bob@example.invalid"
    )
    report = RepositoryParser().parse_repository(repo)
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    judgement = Judge(rule_set).judge(
        facts_from_imports(report.occurrences)
        + facts_from_calls(report.calls)
        + facts_from_sources(report.sources)
        + facts_from_syntax(report.syntax)
    )
    attribution = GitEvidenceAttributor().attribute(
        repo,
        bob_sha,
        "analysis-repository-typescript",
        judgement.personal_evidence,
        FixtureIdentityResolver("alice", {alice_sha: "alice", bob_sha: "bob"}),
    )
    assessments = assess_personal_levels(rule_set, judgement, attribution)
    typescript = next(item for item in assessments if item.tech_id == "typescript")
    request = _request().model_copy(
        update={
            "payload": _request().payload.model_copy(
                update={
                    "registry_version": "registry-20260911.4",
                    "commit_sha": bob_sha,
                    "analysis_repository_id": "analysis-repository-typescript",
                }
            )
        }
    )
    result = completed_result(
        request,
        judgement,
        report,
        ManifestScanner().scan(repo),
        configs=ConfigScanner().scan(repo),
        attributed_evidence=attribution,
        personal_assessments=assessments,
        checkout=repo,
    )
    advanced_kinds = {"CONDITIONAL_TYPE", "MAPPED_TYPE", "INFER_TYPE"}

    assert (
        next(item.level for item in judgement.verdicts if item.tech_id == "typescript")
        == "L3"
    )
    assert {
        item.evidence.fact.fields.get("KIND")
        for item in attribution
        if item.evidence.fact.fields.get("KIND") in advanced_kinds
        and item.attribution == "OTHER"
    } == advanced_kinds
    assert any(
        item.evidence.fact.fields.get("KIND") == "TYPE_ALIAS_DECLARATION"
        and item.attribution == "SELF"
        for item in attribution
    )
    assert typescript.personal_level == "L2"
    published = next(
        item
        for item in result.payload.personal_assessments
        if item.tech_id == "typescript"
    )
    assert published.personal_level == "L2"


def test_kubernetes_profile_does_not_lend_later_hardening_to_container_author(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    manifest = repo / "deployment.yaml"
    manifest.write_text(
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: api\n"
        "spec:\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "        - name: app\n"
        "          image: app:1\n",
        encoding="utf-8",
    )
    _git(repo, "add", "deployment.yaml")
    _git(
        repo,
        "-c",
        "user.name=Alice",
        "-c",
        "user.email=alice@example.invalid",
        "commit",
        "-m",
        "add workload",
    )
    alice_sha = _git(repo, "rev-parse", "HEAD")
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "          resources:\n"
        "            requests:\n"
        "              cpu: 100m\n"
        "              memory: 128Mi\n"
        "          readinessProbe:\n"
        "            httpGet:\n"
        "              path: /ready\n"
        "          livenessProbe:\n"
        "            httpGet:\n"
        "              path: /live\n"
        "          securityContext:\n"
        "            runAsNonRoot: true\n"
        "            allowPrivilegeEscalation: false\n"
        "            readOnlyRootFilesystem: true\n",
        encoding="utf-8",
    )
    bob_sha = _commit(repo, "harden workload", name="Bob", email="bob@example.invalid")
    rule_set = load_rule_pack(SCOPE_RULE_PACK_PATH).as_rule_set(
        mappings=mappings_from_registry_artifact(SCOPE_REGISTRY_PATH)
    )
    configs = ConfigScanner().scan(repo)
    judgement = Judge(rule_set).judge(facts_from_configs(configs.occurrences))
    kubernetes_evidence = tuple(
        item for item in judgement.personal_evidence if item.tech_id == "kubernetes"
    )
    attribution = GitEvidenceAttributor().attribute(
        repo,
        bob_sha,
        "analysis-repository-kubernetes",
        kubernetes_evidence,
        FixtureIdentityResolver("alice", {alice_sha: "alice", bob_sha: "bob"}),
    )
    assessment = next(
        item
        for item in assess_personal_levels(rule_set, judgement, attribution)
        if item.tech_id == "kubernetes"
    )

    assert (
        next(item.level for item in judgement.verdicts if item.tech_id == "kubernetes")
        == "L3"
    )
    assert assessment.personal_level == "L1"
