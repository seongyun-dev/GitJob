"""The fixed JobKorea duty scopes a v3 active-scope run collects.

Separated from the crawler because this list *is* the v3 population. Reading
it should not require reading a 1,000-line crawler, and changing it is a
change to what a snapshot means -- `job.jobkorea_contract.active_snapshot_metadata`
hashes the codes and roles a manifest reports into a `scope_key`, so two
snapshots are only comparable while this list is unchanged.

The codes are JobKorea's own duty ids, carried over verbatim from the
2026-09-15 operational run that produced
`JOBKOREA-ACTIVE-2026-09-15-50b4a6593c62` (S15P21E102-335). They are the
site's identifiers, not ours, so they are written out rather than derived.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DUTY_PRESETS",
    "SERVICE_ROLE_DUTIES",
    "DutyScope",
    "resolve_duty_preset",
]


@dataclass(frozen=True)
class DutyScope:
    """One JobKorea duty list, and the service role it answers for.

    ``target_role`` is ours, ``code`` and ``name`` are the site's. Several
    duties map to one role -- eight of them to ``AI_DATA`` -- so the role is
    not recoverable from the code and has to travel with it.
    """

    code: str
    name: str
    target_role: str


# 16 duty codes over 5 target roles. The counts are asserted in
# `tests/test_jobkorea_v3_active.py`: a duty added or removed here changes the
# v3 population and must be a deliberate, reviewed change.
SERVICE_ROLE_DUTIES: dict[str, tuple[tuple[str, str], ...]] = {
    "BACKEND": (("1000229", "백엔드개발자"),),
    "FRONTEND": (("1000230", "프론트엔드개발자"),),
    "AI_DATA": (
        ("1000236", "데이터엔지니어"),
        ("1000237", "데이터사이언티스트"),
        ("1000242", "AI/ML엔지니어"),
        ("1000417", "AI/ML연구원"),
        ("1000418", "데이터분석가"),
        ("1000420", "프롬프트엔지니어"),
        ("1000422", "MLOps엔지니어"),
        ("1000423", "AI서비스개발자"),
    ),
    "INFRASTRUCTURE": (
        ("1000233", "시스템엔지니어"),
        ("1000234", "네트워크엔지니어"),
        ("1000235", "DBA"),
        ("1000238", "보안엔지니어"),
        ("1000244", "클라우드엔지니어"),
    ),
    "MOBILE": (("1000232", "앱개발자"),),
}

DUTY_PRESETS: dict[str, tuple[DutyScope, ...]] = {
    "service-roles": tuple(
        DutyScope(code=code, name=name, target_role=role)
        for role, duties in SERVICE_ROLE_DUTIES.items()
        for code, name in duties
    )
}


def resolve_duty_preset(name: str) -> tuple[DutyScope, ...]:
    """Look up a named preset, refusing an unknown name.

    Returning an empty tuple for a typo would start a run that collects
    nothing and still reports a clean finish, which is the same class of
    silent-success failure as an empty first page.
    """

    try:
        return DUTY_PRESETS[name]
    except KeyError:
        known = ", ".join(sorted(DUTY_PRESETS))
        raise ValueError(f"unknown duty preset {name!r}; known presets: {known}") from None
