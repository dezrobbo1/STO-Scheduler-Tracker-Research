from __future__ import annotations


def _duration(seconds: int) -> dict[str, object]:
    return {"raw": f"PT{seconds}S", "seconds": seconds, "parse_status": "parsed"}


def _week(intervals: list[tuple[str, str]]) -> list[dict[str, object]]:
    return [
        {
            "day_type": day,
            "working": bool(intervals),
            "working_times": [
                {"from": start, "to": finish} for start, finish in intervals
            ],
            "extensions": [],
        }
        for day in range(1, 8)
    ]


def _calendar(
    uid: int,
    intervals: list[tuple[str, str]],
    *,
    base_ref: str | None = None,
    exceptions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": f"calendar:{uid}",
        "source_order": uid,
        "external_references": [],
        "name": f"Calendar {uid}",
        "is_base": base_ref is None,
        "is_baseline": False,
        "base_calendar_ref": base_ref,
        "week_days": _week(intervals) if intervals else [],
        "exceptions": exceptions or [],
        "extension_refs": [],
    }


def _activity(
    uid: int,
    *,
    start: str,
    finish: str,
    duration_seconds: int,
    calendar_ref: str | None = None,
    milestone: bool = False,
    active: bool = True,
    duration_format: str = "5",
    ignore_resource_calendar: str = "0",
) -> tuple[dict[str, object], list[dict[str, object]]]:
    activity_id = f"task:{uid}"
    extensions = []
    extension_refs = []
    values = {
        "DurationFormat": duration_format,
        "EffortDriven": "0",
        "Recurring": "0",
        "ExternalTask": "0",
        "IsSubproject": "0",
        "IgnoreResourceCalendar": ignore_resource_calendar,
        "LevelingDelay": "0",
    }
    for name, value in values.items():
        extension_id = f"extension:{uid}:{name}"
        extension_refs.append(extension_id)
        extensions.append(
            {
                "id": extension_id,
                "source_order": len(extensions),
                "owner_kind": "Activity",
                "owner_ref": activity_id,
                "classification": "preserved-only",
                "payload": {"name": name, "text": value},
            }
        )
    activity = {
        "id": activity_id,
        "source_order": uid,
        "external_references": [],
        "name": f"Sensitive task {uid}",
        "notes": f"Sensitive notes {uid}",
        "parent_wbs_id": None,
        "wbs": None,
        "outline_number": str(uid),
        "outline_level": 0,
        "active": active,
        "manual": False,
        "is_null_source": False,
        "source_task_type": 0,
        "created_at": None,
        "priority": 500,
        "start": start,
        "finish": finish,
        "duration": _duration(duration_seconds),
        "work": _duration(0),
        "calendar_ref": calendar_ref,
        "estimated": False,
        "milestone_source": milestone,
        "milestone": milestone,
        "critical_source": False,
        "early_start_source": start,
        "early_finish_source": finish,
        "late_start_source": start,
        "late_finish_source": finish,
        "free_slack_tenths_minutes_source": 0,
        "total_slack_tenths_minutes_source": 0,
        "percent_complete_source": 0,
        "percent_work_complete_source": 0,
        "physical_percent_complete_source": 0,
        "actual_start_source": None,
        "actual_finish_source": None,
        "actual_duration_source": _duration(0),
        "actual_work_source": _duration(0),
        "remaining_duration_source": _duration(duration_seconds),
        "remaining_work_source": _duration(0),
        "constraint_type_source": 0,
        "constraint_date_source": None,
        "deadline_source": None,
        "custom_fields": [],
        "extension_refs": extension_refs,
    }
    return activity, extensions


def _relationship(uid: int, predecessor: int, successor: int, lag: int = 0) -> dict[str, object]:
    return {
        "id": f"relationship:{uid}",
        "source_order": uid,
        "predecessor_ref": f"task:{predecessor}",
        "successor_ref": f"task:{successor}",
        "type": "FS",
        "source_type_code": 1,
        "lag_tenths_minutes": lag,
        "lag_seconds": lag * 6,
        "lag_format_source": 7,
        "cross_project": False,
        "cross_project_name": None,
        "extensions": [],
    }


def _document(
    activities: list[tuple[dict[str, object], list[dict[str, object]]]],
    *,
    relationships: list[dict[str, object]] | None = None,
    calendars: list[dict[str, object]] | None = None,
    resources: list[dict[str, object]] | None = None,
    assignments: list[dict[str, object]] | None = None,
    project_start: str = "2026-01-05T08:00:00",
    project_finish: str = "2026-01-10T23:59:00",
) -> dict[str, object]:
    activity_rows = [item[0] for item in activities]
    extensions = [extension for item in activities for extension in item[1]]
    calendars = calendars or [_calendar(1, [("08:00:00", "16:00:00")])]
    return {
        "schema_version": "0.1.1",
        "importer_profile": "mspdi-import-v0.1.1",
        "source": {
            "system": "MicrosoftProject",
            "format": "MSPDI",
            "namespace": "http://schemas.microsoft.com/project",
            "sha256": "a" * 64,
            "byte_length": 1,
            "identity_scope": "document-local-v0.1",
            "document_key": f"sha256:{'a' * 64}",
            "durable_cross_snapshot_identity": "not_implemented",
        },
        "project": {
            "id": "project:test",
            "schedule_from_start": True,
            "start": project_start,
            "finish": project_finish,
            "status_date": None,
            "calendar_ref": "calendar:1",
        },
        "wbs_nodes": [],
        "work_packages": [],
        "activities": activity_rows,
        "relationships": relationships or [],
        "calendars": calendars,
        "resources": resources or [],
        "assignments": assignments or [],
        "baselines": [],
        "custom_field_definitions": [],
        "vendor_extensions": extensions,
        "source_inventory": {
            "tasks": len(activity_rows),
            "summary_tasks": 0,
            "leaf_activities": len(activity_rows),
            "milestones": sum(bool(item["milestone"]) for item in activity_rows),
            "activity_milestones": sum(bool(item["milestone"]) for item in activity_rows),
            "summary_milestones": 0,
            "relationships": len(relationships or []),
            "relationship_types": {"FS": len(relationships or [])},
            "calendars": len(calendars),
            "resources": len(resources or []),
            "assignments": len(assignments or []),
            "baselines": 0,
            "custom_field_definitions": 0,
            "vendor_extensions": len(extensions),
            "preserved_extension_element_counts": {},
        },
        "compatibility": {},
        "import_validation": {"valid": True, "errors": [], "warnings": []},
    }
