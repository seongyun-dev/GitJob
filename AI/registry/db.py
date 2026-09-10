"""PostgreSQL source for immutable Technology Registry snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter, ValidationError

from registry.contracts import (
    TECHNOLOGY_REGISTRY_SCHEMA_VERSION,
    RegistryVersion,
    TechnologyRegistry,
    load_registry,
)
from registry.normalization import normalize_mapping_value

_REGISTRY_VERSION_ADAPTER = TypeAdapter(RegistryVersion)


class RegistryStoreError(RuntimeError):
    """Base class for an operational Registry source failure."""


class RegistryVersionUnavailable(RegistryStoreError):
    """The requested immutable snapshot or active family alias is absent."""


class ImmutableRegistryConflict(RegistryStoreError):
    """An immutable content version already names different content."""


class RegistryIntegrityError(RegistryStoreError):
    """Persisted rows do not reconstruct the recorded immutable content."""


@dataclass(frozen=True)
class RegistrySnapshotRef:
    schema_version: str
    registry_version: str
    content_sha256: str
    source_ref: str
    imported_at: datetime


def registry_content_sha256(registry: TechnologyRegistry) -> str:
    """Hash a validated snapshot using stable, UTF-8 canonical JSON."""

    canonical = json.dumps(
        registry.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class PostgresRegistryStore:
    """Import and read Registry snapshots without a file fallback."""

    def __init__(self, dsn: str) -> None:
        if not dsn.strip():
            raise ValueError("Registry database DSN must not be blank")
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(
            self._dsn,
            connect_timeout=5,
            options="-c statement_timeout=15000 -c lock_timeout=5000",
            row_factory=dict_row,
        )

    @staticmethod
    def _snapshot_ref(row: dict) -> RegistrySnapshotRef:
        if not all(
            row.get(field)
            for field in (
                "schema_version",
                "registry_version",
                "content_sha256",
                "source_ref",
                "imported_at",
            )
        ):
            raise RegistryIntegrityError(
                "Registry snapshot is missing immutable import metadata"
            )
        return RegistrySnapshotRef(
            schema_version=row["schema_version"],
            registry_version=row["registry_version"],
            content_sha256=row["content_sha256"].strip(),
            source_ref=row["source_ref"],
            imported_at=row["imported_at"],
        )

    def _find_snapshot_ref(self, registry_version: str) -> RegistrySnapshotRef:
        try:
            _REGISTRY_VERSION_ADAPTER.validate_python(registry_version)
        except ValidationError as exc:
            raise RegistryVersionUnavailable(
                f"not an immutable Registry content version: {registry_version}"
            ) from exc
        with self._connect() as conn:
            return self._find_snapshot_ref_in(conn, registry_version)

    @classmethod
    def _find_snapshot_ref_in(
        cls, conn, registry_version: str, *, lock: bool = False
    ) -> RegistrySnapshotRef:
        row = conn.execute(
            """SELECT schema_version, registry_version, content_sha256,
                      source_ref, imported_at
               FROM public.technology_registry
               WHERE registry_version = %s"""
            + (" FOR SHARE" if lock else ""),
            (registry_version,),
        ).fetchone()
        if row is None:
            raise RegistryVersionUnavailable(
                f"Registry snapshot is not available: {registry_version}"
            )
        return cls._snapshot_ref(row)

    @staticmethod
    def _lock_content_tables(conn, *, for_import: bool = False) -> None:
        # All paths lock the child tables in the same order. Imports take the
        # write-conflicting mode before their first write so concurrent imports
        # serialize instead of deadlocking while upgrading ROW EXCLUSIVE to SHARE.
        mode = "SHARE ROW EXCLUSIVE" if for_import else "SHARE"
        conn.execute(
            "LOCK TABLE public.technology, public.technology_category, "
            f"public.technology_mapping IN {mode} MODE"
        )

    def resolve_version(
        self,
        requested_version: str,
        *,
        pinned_version: str | None = None,
    ) -> RegistrySnapshotRef:
        """Resolve once for a new request, or verify a concrete retry pin.

        A supplied pin is never replaced by the current family alias. This lets a
        retry remain on the original immutable content after an alias activation.
        """

        if pinned_version is not None:
            pinned = self._find_snapshot_ref(pinned_version)
            if requested_version == TECHNOLOGY_REGISTRY_SCHEMA_VERSION:
                if pinned.schema_version != requested_version:
                    raise RegistryVersionUnavailable(
                        "pinned Registry does not belong to the requested schema"
                    )
            elif requested_version != pinned_version:
                raise RegistryVersionUnavailable(
                    "pinned Registry differs from requested immutable version"
                )
            return pinned

        try:
            _REGISTRY_VERSION_ADAPTER.validate_python(requested_version)
        except ValidationError:
            pass
        else:
            return self._find_snapshot_ref(requested_version)

        if requested_version != TECHNOLOGY_REGISTRY_SCHEMA_VERSION:
            raise RegistryVersionUnavailable(
                f"unsupported Registry family token: {requested_version}"
            )
        with self._connect() as conn:
            row = conn.execute(
                """SELECT snapshot.schema_version, snapshot.registry_version,
                          snapshot.content_sha256, snapshot.source_ref,
                          snapshot.imported_at
                   FROM public.technology_registry_alias alias
                   JOIN public.technology_registry snapshot
                     ON snapshot.schema_version = alias.schema_version
                    AND snapshot.registry_version = alias.registry_version
                   WHERE alias.schema_version = %s""",
                (requested_version,),
            ).fetchone()
        if row is None:
            raise RegistryVersionUnavailable(
                f"Registry family has no active snapshot: {requested_version}"
            )
        return self._snapshot_ref(row)

    def import_registry(
        self,
        registry: TechnologyRegistry,
        *,
        source_ref: str,
        activate_alias: bool = False,
    ) -> RegistrySnapshotRef:
        """Insert a new immutable snapshot and optionally move its family alias."""

        if not source_ref.strip():
            raise ValueError("Registry source_ref must not be blank")
        content_sha256 = registry_content_sha256(registry)
        with self._connect() as conn:
            self._lock_content_tables(conn, for_import=True)
            inserted = conn.execute(
                """INSERT INTO public.technology_registry
                       (registry_version, schema_version, status, published_at,
                        content_sha256, source_ref, imported_at)
                   VALUES (%s, %s, 'RETIRED', clock_timestamp(), %s, %s,
                           clock_timestamp())
                   ON CONFLICT (registry_version) DO NOTHING
                   RETURNING schema_version, registry_version, content_sha256,
                             source_ref, imported_at""",
                (
                    registry.registry_version,
                    registry.schema_version,
                    content_sha256,
                    source_ref,
                ),
            ).fetchone()
            if inserted is None:
                existing = conn.execute(
                    """SELECT schema_version, registry_version, content_sha256,
                              source_ref, imported_at
                       FROM public.technology_registry
                       WHERE registry_version = %s FOR UPDATE""",
                    (registry.registry_version,),
                ).fetchone()
                if (
                    existing is None
                    or existing["schema_version"] != registry.schema_version
                    or not existing["content_sha256"]
                    or existing["content_sha256"].strip() != content_sha256
                    or existing["source_ref"] != source_ref
                ):
                    raise ImmutableRegistryConflict(
                        "Registry content version already exists with different "
                        "content or provenance"
                    )
                result = self._snapshot_ref(existing)
            else:
                self._insert_snapshot_rows(conn, registry)
                result = self._snapshot_ref(inserted)

            loaded = self._load_registry_from_connection(conn, result)
            if loaded != registry:
                raise RegistryIntegrityError(
                    "persisted Registry rows differ from the imported snapshot"
                )
            if activate_alias:
                self._activate_alias(conn, result)

        return result

    @staticmethod
    def _insert_snapshot_rows(conn, registry: TechnologyRegistry) -> None:
        with conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO public.technology
                       (tech_id, registry_version, display_name, status,
                        registry_order, provenance_refs)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [
                    (
                        technology.tech_id,
                        registry.registry_version,
                        technology.display_name,
                        technology.status.value,
                        order,
                        Jsonb(list(technology.provenance_refs)),
                    )
                    for order, technology in enumerate(registry.technologies)
                ],
            )
            cursor.executemany(
                """INSERT INTO public.technology_category
                       (registry_version, tech_id, job_domain, category_order)
                   VALUES (%s, %s, %s, %s)""",
                [
                    (
                        registry.registry_version,
                        technology.tech_id,
                        category.value,
                        order,
                    )
                    for technology in registry.technologies
                    for order, category in enumerate(technology.categories)
                ],
            )
            cursor.executemany(
                """INSERT INTO public.technology_mapping
                       (registry_version, tech_id, mapping_type, ecosystem, value,
                        match_mode, status, registry_order, normalized_value,
                        provenance_refs)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        registry.registry_version,
                        mapping.tech_id,
                        mapping.mapping_type.value,
                        mapping.ecosystem.value if mapping.ecosystem else None,
                        mapping.value,
                        mapping.match_mode.value,
                        mapping.status.value,
                        order,
                        normalize_mapping_value(
                            mapping.mapping_type.value,
                            mapping.ecosystem.value if mapping.ecosystem else None,
                            mapping.value,
                        ),
                        Jsonb(list(mapping.provenance_refs)),
                    )
                    for order, mapping in enumerate(registry.mappings)
                ],
            )

    @staticmethod
    def _activate_alias(conn, snapshot: RegistrySnapshotRef) -> None:
        conn.execute(
            """INSERT INTO public.technology_registry_alias
                   (schema_version, registry_version, activated_at)
               VALUES (%s, %s, clock_timestamp())
               ON CONFLICT (schema_version) DO UPDATE
               SET registry_version = EXCLUDED.registry_version,
                   activated_at = EXCLUDED.activated_at""",
            (snapshot.schema_version, snapshot.registry_version),
        )

    def activate_alias(self, registry_version: str) -> RegistrySnapshotRef:
        """Explicitly make an imported snapshot current for its schema family."""

        try:
            _REGISTRY_VERSION_ADAPTER.validate_python(registry_version)
        except ValidationError as exc:
            raise RegistryVersionUnavailable(
                f"not an immutable Registry content version: {registry_version}"
            ) from exc
        with self._connect() as conn:
            self._lock_content_tables(conn)
            snapshot = self._find_snapshot_ref_in(conn, registry_version, lock=True)
            self._load_registry_from_connection(conn, snapshot)
            self._activate_alias(conn, snapshot)
        return snapshot

    def load_registry(self, registry_version: str) -> TechnologyRegistry:
        """Read and integrity-check one exact immutable snapshot."""

        try:
            _REGISTRY_VERSION_ADAPTER.validate_python(registry_version)
        except ValidationError as exc:
            raise RegistryVersionUnavailable(
                f"not an immutable Registry content version: {registry_version}"
            ) from exc
        with self._connect() as conn:
            self._lock_content_tables(conn)
            expected = self._find_snapshot_ref_in(conn, registry_version, lock=True)
            return self._load_registry_from_connection(conn, expected)

    @staticmethod
    def _load_registry_from_connection(
        conn, expected: RegistrySnapshotRef
    ) -> TechnologyRegistry:
        registry_version = expected.registry_version
        technologies = conn.execute(
            """SELECT tech_id, display_name, status, provenance_refs
               FROM public.technology
               WHERE registry_version = %s
               ORDER BY registry_order""",
            (registry_version,),
        ).fetchall()
        categories = conn.execute(
            """SELECT tech_id, job_domain
               FROM public.technology_category
               WHERE registry_version = %s
               ORDER BY tech_id, category_order""",
            (registry_version,),
        ).fetchall()
        mappings = conn.execute(
            """SELECT tech_id, mapping_type, ecosystem, value, match_mode,
                      status, provenance_refs
               FROM public.technology_mapping
               WHERE registry_version = %s
               ORDER BY registry_order""",
            (registry_version,),
        ).fetchall()

        categories_by_tech: dict[str, list[str]] = {}
        for row in categories:
            categories_by_tech.setdefault(row["tech_id"], []).append(row["job_domain"])
        payload = {
            "schema_version": expected.schema_version,
            "registry_version": expected.registry_version,
            "technologies": tuple(
                {
                    "tech_id": row["tech_id"],
                    "display_name": row["display_name"],
                    "categories": tuple(categories_by_tech.get(row["tech_id"], [])),
                    "status": row["status"],
                    "provenance_refs": tuple(row["provenance_refs"]),
                }
                for row in technologies
            ),
            "mappings": tuple(
                {
                    "tech_id": row["tech_id"],
                    "mapping_type": row["mapping_type"],
                    "ecosystem": row["ecosystem"],
                    "value": row["value"],
                    "match_mode": row["match_mode"],
                    "status": row["status"],
                    "provenance_refs": tuple(row["provenance_refs"]),
                }
                for row in mappings
            ),
        }
        try:
            registry = TechnologyRegistry.model_validate_json(
                json.dumps(payload, ensure_ascii=False)
            )
        except ValidationError as exc:
            raise RegistryIntegrityError(
                "persisted Registry rows violate the Registry contract"
            ) from exc
        if registry_content_sha256(registry) != expected.content_sha256:
            raise RegistryIntegrityError(
                "persisted Registry content does not match its recorded hash"
            )
        return registry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    importer = subparsers.add_parser("import", help="import one validated snapshot")
    importer.add_argument("--dsn", required=True)
    importer.add_argument("--path", type=Path, required=True)
    importer.add_argument("--repository-root", type=Path, required=True)
    importer.add_argument("--source-ref", required=True)
    importer.add_argument("--activate-alias", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    registry = load_registry(args.path, repository_root=args.repository_root)
    snapshot = PostgresRegistryStore(args.dsn).import_registry(
        registry,
        source_ref=args.source_ref,
        activate_alias=args.activate_alias,
    )
    print(
        json.dumps(
            {**snapshot.__dict__, "imported_at": snapshot.imported_at.isoformat()}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
