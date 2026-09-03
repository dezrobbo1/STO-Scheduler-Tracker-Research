"""Durable identity across snapshots and source systems.

The research importer keyed everything document-locally (``task:322``), which is
fine for one file and useless the moment the same schedule is re-imported: a
re-numbered task becomes a different object and every link to it breaks. It
recorded that state of affairs as ``durable_cross_snapshot_identity:
not_implemented``.

Here an entity's identity is a UUIDv5 minted from

    (schedule_id, source_system, entity_kind, external_uid)

so it is a pure function of the source. Importing the same file twice produces
the same UUIDs and therefore the same document hash; importing a later snapshot
of the same schedule keeps the UUIDs of every row whose external UID survived.

Reconciliation on re-import tries, in order:

1.  the same ``(system, kind, external_uid)`` -- the ordinary case;
2.  the same GUID under a changed UID;
3.  a configured business key (activity code, WBS code, work-order/operation
    pair) -- for sources that renumber both;

and mints a new UUID only when all three miss. A row that was present before and
matches nothing now is reported ``missing``; it is never deleted, because the
schedule may still reference it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from .enums import EntityKind, ReconciliationOutcome, SourceSystem

#: Namespace for every STO canonical identifier. Changing it re-keys the world.
STO_NAMESPACE = uuid.UUID("5f1b2b4e-9d3a-5c6f-9a21-0f7c9d2e4a10")

#: Joins the parts of a minted name and of serialised map keys. It is a
#: control character so it cannot occur inside a UID, GUID or business key.
SEP = "\x1f"


def normalise_guid(value: str | None) -> str | None:
    """Return a canonical UUID spelling when ``value`` is a UUID.

    Microsoft files and interchange libraries may vary UUID case or brace
    formatting. Those presentation differences must not re-key a project or an
    entity. Non-UUID identifiers are retained verbatim because some source
    adapters use GUID-like opaque strings in tests and intermediate models.
    """

    if value is None:
        return None
    text = str(value)
    try:
        return str(uuid.UUID(text))
    except (ValueError, AttributeError):
        return text


def mint_uid(
    schedule_id: str,
    system: SourceSystem | str,
    kind: EntityKind | str,
    external_uid: str,
) -> uuid.UUID:
    """Derive the stable identifier for one source row.

    ``schedule_id`` scopes the name so that task UID 42 in two different
    projects does not collide.
    """

    name = SEP.join(
        (str(schedule_id), str(system), str(kind), str(external_uid))
    )
    return uuid.uuid5(STO_NAMESPACE, name)


@dataclass(frozen=True, slots=True)
class ReconciliationEntry:
    kind: EntityKind
    external_uid: str
    uid: uuid.UUID
    outcome: ReconciliationOutcome
    matched_by: str | None = None
    previous_external_uid: str | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """What a re-import did to identity, in numbers a planner can check."""

    schedule_id: str
    entries: tuple[ReconciliationEntry, ...] = ()

    def _count(self, outcome: ReconciliationOutcome) -> int:
        return sum(1 for entry in self.entries if entry.outcome is outcome)

    @property
    def matched(self) -> int:
        return self._count(ReconciliationOutcome.MATCHED)

    @property
    def new(self) -> int:
        return self._count(ReconciliationOutcome.NEW)

    @property
    def missing(self) -> int:
        return self._count(ReconciliationOutcome.MISSING)

    @property
    def rekeyed(self) -> int:
        return self._count(ReconciliationOutcome.REKEYED)

    def of_kind(self, kind: EntityKind) -> tuple[ReconciliationEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind is kind)

    def to_dict(self) -> dict[str, object]:
        return {
            "schedule_id": self.schedule_id,
            "matched": self.matched,
            "new": self.new,
            "missing": self.missing,
            "rekeyed": self.rekeyed,
            "entries": [
                {
                    "kind": str(entry.kind),
                    "external_uid": entry.external_uid,
                    "uid": str(entry.uid),
                    "outcome": str(entry.outcome),
                    "matched_by": entry.matched_by,
                    "previous_external_uid": entry.previous_external_uid,
                }
                for entry in self.entries
            ],
        }


@dataclass
class IdentityMap:
    """Persistent map from source keys to canonical UUIDs for one schedule."""

    schedule_id: str
    system: SourceSystem
    #: (kind, external_uid) -> uid
    by_external: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    #: (kind, guid) -> uid, for sources that renumber UIDs but keep GUIDs
    by_guid: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    #: (kind, business_key) -> uid
    by_business_key: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    #: Retired external source keys -> reuse generation.
    #:
    #: A rekeyed entity must release its old external UID so the source can
    #: legitimately reuse it for a different row. The generation is persisted
    #: because minting the reused UID with the original UUIDv5 name would
    #: recreate the retired entity's canonical UUID.
    retired_external: dict[tuple[str, str], int] = field(default_factory=dict)
    #: uid -> the external_uid it was last seen under
    external_of: dict[uuid.UUID, str] = field(default_factory=dict)

    def clone(self) -> IdentityMap:
        """Return an independent copy suitable for transactional migration."""

        return IdentityMap.from_dict(self.to_dict())

    def resolve(
        self,
        kind: EntityKind,
        external_uid: str,
        *,
        guid: str | None = None,
        business_key: str | None = None,
    ) -> tuple[uuid.UUID, ReconciliationEntry]:
        """Return the identifier for a row, recording how it was matched."""

        kind_key = str(kind)
        external_uid = str(external_uid)
        guid = normalise_guid(guid)

        known = self.by_external.get((kind_key, external_uid))
        if known is not None:
            # A later snapshot may add a GUID or business key to a row that was
            # first seen without one. Learn that evidence now so a subsequent
            # source-UID change can still resolve to the same canonical row.
            self._record(kind_key, external_uid, known, guid, business_key)
            return known, ReconciliationEntry(
                kind=kind,
                external_uid=external_uid,
                uid=known,
                outcome=ReconciliationOutcome.MATCHED,
                matched_by="external_uid",
            )

        if guid:
            by_guid = self.by_guid.get((kind_key, guid))
            if by_guid is not None:
                previous = self.external_of.get(by_guid)
                self._record(kind_key, external_uid, by_guid, guid, business_key)
                return by_guid, ReconciliationEntry(
                    kind=kind,
                    external_uid=external_uid,
                    uid=by_guid,
                    outcome=ReconciliationOutcome.REKEYED,
                    matched_by="guid",
                    previous_external_uid=previous,
                )

        if business_key:
            by_key = self.by_business_key.get((kind_key, business_key))
            if by_key is not None:
                previous = self.external_of.get(by_key)
                self._record(kind_key, external_uid, by_key, guid, business_key)
                return by_key, ReconciliationEntry(
                    kind=kind,
                    external_uid=external_uid,
                    uid=by_key,
                    outcome=ReconciliationOutcome.REKEYED,
                    matched_by="business_key",
                    previous_external_uid=previous,
                )

        generation = self.retired_external.get((kind_key, external_uid), 0)
        mint_name = (
            external_uid
            if generation == 0
            else SEP.join((external_uid, "reuse", str(generation)))
        )
        minted = mint_uid(self.schedule_id, self.system, kind, mint_name)
        self._record(kind_key, external_uid, minted, guid, business_key)
        return minted, ReconciliationEntry(
            kind=kind,
            external_uid=external_uid,
            uid=minted,
            outcome=ReconciliationOutcome.NEW,
            matched_by=None,
        )

    def _record(
        self,
        kind_key: str,
        external_uid: str,
        uid: uuid.UUID,
        guid: str | None,
        business_key: str | None,
    ) -> None:
        guid = normalise_guid(guid)
        # Retire the key this entity used to be known by. Without this a
        # rekeyed row is reported as both rekeyed and missing, and if the
        # source later reuses the old UID for a different entity the
        # external-UID lookup would conflate the two.
        previous = self.external_of.get(uid)
        if previous is not None and previous != external_uid:
            retired_key = (kind_key, previous)
            self.by_external.pop(retired_key, None)
            self.retired_external[retired_key] = (
                self.retired_external.get(retired_key, 0) + 1
            )
        self.by_external[(kind_key, external_uid)] = uid
        self.external_of[uid] = external_uid
        if guid:
            self.by_guid[(kind_key, guid)] = uid
        if business_key:
            self.by_business_key[(kind_key, business_key)] = uid

    def missing_since(
        self, kind: EntityKind, seen_external_uids: Iterable[str]
    ) -> tuple[ReconciliationEntry, ...]:
        """Rows known to this map that the current import did not carry."""

        kind_key = str(kind)
        seen = {str(value) for value in seen_external_uids}
        return tuple(
            ReconciliationEntry(
                kind=kind,
                external_uid=external_uid,
                uid=uid,
                outcome=ReconciliationOutcome.MISSING,
            )
            for (entry_kind, external_uid), uid in sorted(self.by_external.items())
            if entry_kind == kind_key and external_uid not in seen
        )

    def to_dict(self) -> dict[str, object]:
        def _join(mapping: dict[tuple[str, str], uuid.UUID]) -> dict[str, str]:
            return {SEP.join(key): str(uid) for key, uid in sorted(mapping.items())}

        return {
            "schedule_id": self.schedule_id,
            "system": str(self.system),
            "by_external": _join(self.by_external),
            "by_guid": _join(self.by_guid),
            "by_business_key": _join(self.by_business_key),
            "retired_external": {
                SEP.join(key): generation
                for key, generation in sorted(self.retired_external.items())
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> IdentityMap:
        def _split(mapping: Mapping[str, str]) -> dict[tuple[str, str], uuid.UUID]:
            out: dict[tuple[str, str], uuid.UUID] = {}
            for key, value in mapping.items():
                kind, _, rest = key.partition(SEP)
                out[(kind, rest)] = uuid.UUID(value)
            return out

        def _split_int(mapping: Mapping[str, int]) -> dict[tuple[str, str], int]:
            out: dict[tuple[str, str], int] = {}
            for key, value in mapping.items():
                kind, _, rest = key.partition(SEP)
                generation = int(value)
                if generation < 1:
                    raise ValueError(
                        f"retired external generation must be positive: {key!r}"
                    )
                out[(kind, rest)] = generation
            return out

        by_external = _split(payload.get("by_external", {}))  # type: ignore[arg-type]
        raw_by_guid = _split(payload.get("by_guid", {}))  # type: ignore[arg-type]
        by_guid = {
            (kind, normalise_guid(guid) or guid): uid
            for (kind, guid), uid in raw_by_guid.items()
        }
        identity = cls(
            schedule_id=str(payload["schedule_id"]),
            system=SourceSystem(str(payload["system"])),
            by_external=by_external,
            by_guid=by_guid,
            by_business_key=_split(payload.get("by_business_key", {})),  # type: ignore[arg-type]
            retired_external=_split_int(
                payload.get("retired_external", {})  # type: ignore[arg-type]
            ),
        )
        identity.external_of = {uid: external for (_, external), uid in by_external.items()}
        return identity
