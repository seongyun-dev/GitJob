# Repository analysis result v4

> 상태: C producer implemented, B resolver/topic integration pending
> 기준일: 2026-09-13
> Event: `repository.analysis.completed`
> Schema version: `repository-analysis-result/v4`

V4 is an additive successor to `repository-analysis-result/v3`. The v1-v3
Pydantic models and result routes remain unchanged. C emits v4 only when a
target GitHub login and the distinct evidence commit SHA to GitHub
`author.login` mapping have been supplied through the identity resolver
interface.

## Ownership boundary

- C owns pinned-commit blame, Rule Pack fact attribution, decisive-fact
  selection, `personal_level`, `assessment_ceiling`, `attribution_status`, and
  `missing_scope` production.
- B owns OAuth/token handling, the target user's real GitHub identity, commit
  SHA to `author.login` resolution, persistence, service API, and FE exposure.
- The request Kafka event remains `repository-analysis-request/v1`; it does not
  gain a token, email, user DB ID, or GitHub login. B supplies identity through
  the `analysis_repository_id` resolver boundary.

## Added evidence fields

Each existing v3 `payload.evidence[]` item adds:

| Field | Type | Meaning |
|---|---|---|
| `fact_id` | non-blank string | Deterministic ID of the existing Rule Pack fact |
| `repository_analysis_id` | path-safe identifier | Repository-scoped provenance for `fact_id`; aggregate keys use this pair |
| `tech_id` | non-blank string | Technology resolved by the Rule Pack |
| `attribution` | `SELF \| OTHER \| UNKNOWN` | Login comparison result |
| `attribution_commit_sha` | 40-hex SHA or null | Commit returned by pinned blame; null for unresolved history/line |
| `attribution_missing_scope` | string array | Explicit reason when attribution is unknown |

`SELF` and `OTHER` require `attribution_commit_sha`. `UNKNOWN` requires a
missing-scope reason. Git author names and emails are never used as identity.
`SOURCE_FILE` is file-level presence evidence rather than an authored line; its
synthetic line 1 is therefore never blamed and remains
`UNKNOWN/EVIDENCE_LINE_UNAVAILABLE` until a safe file-level policy exists.

## Added personal assessment

`payload.personal_assessments[]` contains one item for every repository-positive
technology:

| Field | Type | Meaning |
|---|---|---|
| `tech_id` | string | Registry44 technology ID |
| `personal_level` | `L0..L3` or null | Highest level with a SELF decisive fact; null when incomplete evidence prevents a safe conclusion |
| `assessment_ceiling` | `L0..L3` | Highest level safely assessed in this run, distinct from repository level |
| `attribution_status` | `COMPLETE \| PARTIAL \| UNKNOWN` | Completeness of personal attribution |
| `missing_scope` | string array | History, identity, extraction, or Rule Pack coverage gaps |
| `decisive_fact_ids` | string array | Existing Rule Pack facts used for the personal assessment |

Decisive clauses are derived from required Rule Pack conditions. Conditions
already required by a lower-level rule are prerequisites, not a second
technology ruleset and not sufficient by themselves to promote the personal
level. For alternative groups, only the group actually selected by Judge is
evaluated. L3 therefore requires SELF evidence on an L3-specific decisive fact.

`fact_id` remains deterministic within a repository result. Cross-repository
proof aggregation keys it together with `repository_analysis_id`, so identical
paths/rules/lines in two repositories cannot overwrite opposing attribution.
Bounded history growth and the `(path, line)` blame cache are shared by the
whole attribution request; the sum of deepen fetches cannot exceed the declared
budget.

The Judge keeps the complete matched Fact set only inside the Worker for
personal attribution. The ordinary evidence list remains display-bounded; a v4
result adds only the minimum decisive proofs needed by `personal_assessments`.
If a caller supplies only the display-bounded evidence and a decisive Fact was
not attributed, C returns a partial assessment instead of confirming L0.

Positive SELF evidence is retained under partial coverage. Incomplete blame,
unresolved GitHub identity, missing line evidence, or incomplete repository
fact coverage cannot be converted to `OTHER`, L0, or a confirmed insufficient
level.

## Missing-scope values produced by C

- `BLAME_HISTORY_INCOMPLETE`
- `EVIDENCE_LINE_UNAVAILABLE`
- `AUTHOR_IDENTITY_UNRESOLVED`
- `TARGET_IDENTITY_UNRESOLVED`
- `REPOSITORY_FACT_COVERAGE_INCOMPLETE`
- `RULE_PACK_COVERAGE_PARTIAL` or `RULE_PACK_COVERAGE_UNSUPPORTED`
- `DECISIVE_FACT_EVIDENCE_INCOMPLETE:<rule_id>`
- `DECISIVE_FACT_ATTRIBUTION_INCOMPLETE:<rule_id>`

The executable strict contract is `analysis.results.RepositoryAnalysisResultV4`.
The B resolver implementation, B persistence mapping, and production topic/env
wiring are intentionally outside C ownership and remain integration work.
