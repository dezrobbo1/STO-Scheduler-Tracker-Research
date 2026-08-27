from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from .duration import duration_value
from .opaque import element_to_opaque, local_name

MSPDI_NAMESPACE = "http://schemas.microsoft.com/project"
SCHEMA_VERSION = "0.1.0"
IMPORTER_PROFILE = "mspdi-import-v0.1"
LINK_TYPES = {0: "FF", 1: "FS", 2: "SF", 3: "SS"}


class MspdiImportError(ValueError):
    pass


def _q(name: str, namespace: str = MSPDI_NAMESPACE) -> str:
    return f"{{{namespace}}}{name}"


def _child(element: ET.Element, name: str, namespace: str = MSPDI_NAMESPACE) -> ET.Element | None:
    return element.find(_q(name, namespace))


def _text(element: ET.Element, name: str, default: str | None = None) -> str | None:
    child = _child(element, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _integer(element: ET.Element, name: str, default: int | None = None) -> int | None:
    value = _text(element, name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise MspdiImportError(f"{name} must be an integer, got {value!r}") from exc


def _number(element: ET.Element, name: str, default: float | int | None = None) -> float | int | None:
    value = _text(element, name)
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except ValueError as exc:
        raise MspdiImportError(f"{name} must be numeric, got {value!r}") from exc
    return int(number) if number.is_integer() else number


def _boolean(element: ET.Element, name: str, default: bool | None = None) -> bool | None:
    value = _text(element, name)
    if value in (None, ""):
        return default
    if value in {"1", "true", "True"}:
        return True
    if value in {"0", "false", "False"}:
        return False
    raise MspdiImportError(f"{name} must be a boolean 0/1 value, got {value!r}")


def _calendar_ref(uid: int | None) -> str | None:
    return None if uid is None or uid < 0 else f"calendar:{uid}"


def _resource_ref(uid: int | None, known_resource_uids: set[int]) -> str | None:
    if uid is None:
        return None
    if uid in known_resource_uids:
        return f"resource:{uid}"
    return f"external-resource:{uid}"


def _external_references(
    *,
    entity: str,
    uid: int | None = None,
    row_id: int | None = None,
    guid: str | None = None,
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if uid is not None:
        refs.append({"system": "MicrosoftProject", "entity": entity, "type": "UID", "value": str(uid)})
    if row_id is not None:
        refs.append({"system": "MicrosoftProject", "entity": entity, "type": "ID", "value": str(row_id)})
    if guid:
        refs.append({"system": "MicrosoftProject", "entity": entity, "type": "GUID", "value": guid})
    return refs


def _custom_field_value(element: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in element:
        name = local_name(child.tag)
        text = (child.text or "").strip()
        if name == "FieldID":
            result["field_id"] = text
        elif name == "Value":
            result["value"] = text
        elif name == "DurationFormat":
            result["duration_format"] = text
        elif name in {"ValueGUID", "ValueGuid"}:
            result["value_guid"] = text
        elif name == "LookupValue":
            result["lookup_value"] = text
        else:
            result.setdefault("vendor_fields", {})[name] = text if not list(child) else element_to_opaque(child, MSPDI_NAMESPACE)
    return result


def _baseline_record(owner_kind: str, owner_ref: str, element: ET.Element, index: int) -> dict[str, Any]:
    number = _integer(element, "Number", 0)
    values: dict[str, Any] = {}
    extensions: list[dict[str, Any]] = []
    for child in element:
        name = local_name(child.tag)
        text = (child.text or "").strip()
        if name in {"Duration", "Work"}:
            values[_snake(name)] = duration_value(text)
        elif not list(child):
            values[_snake(name)] = text
        else:
            extensions.append(element_to_opaque(child, MSPDI_NAMESPACE))
    return {
        "id": f"baseline:{owner_kind}:{owner_ref}:{number}:{index}",
        "owner_kind": owner_kind,
        "owner_ref": owner_ref,
        "number": number,
        "values": values,
        "extensions": extensions,
    }


def _snake(name: str) -> str:
    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index and (not name[index - 1].isupper() or (index + 1 < len(name) and name[index + 1].islower())):
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _project_identity(root: ET.Element, source_hash: str) -> tuple[str, list[dict[str, str]]]:
    guid = _text(root, "GUID")
    if guid:
        return f"project:{guid.upper()}", _external_references(entity="Project", guid=guid)
    return f"project:sha256:{source_hash[:24]}", [
        {"system": "MSPDI", "entity": "Project", "type": "SourceSHA256", "value": source_hash}
    ]


def _parse_custom_field_definitions(container: ET.Element | None) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    if container is None:
        return definitions
    for index, element in enumerate(container):
        field_id = _text(element, "FieldID") or f"missing-{index}"
        common = {
            "FieldID": "field_id",
            "FieldName": "field_name",
            "Alias": "alias",
            "Guid": "guid",
            "SecondaryPID": "secondary_pid",
            "SecondaryGuid": "secondary_guid",
            "Ltuid": "lookup_table_uid",
            "Formula": "formula",
            "RollupType": "rollup_type",
            "CalculationType": "calculation_type",
            "RestrictValues": "restrict_values",
            "ValuelistSortOrder": "value_list_sort_order",
        }
        record: dict[str, Any] = {
            "id": f"custom-field:{field_id}",
            "source_order": index,
            "external_references": [
                {"system": "MicrosoftProject", "entity": "ExtendedAttribute", "type": "FieldID", "value": field_id}
            ],
        }
        extensions: list[dict[str, Any]] = []
        for child in element:
            name = local_name(child.tag)
            if name in common and not list(child):
                record[common[name]] = (child.text or "").strip()
            else:
                extensions.append(element_to_opaque(child, MSPDI_NAMESPACE))
        record["extensions"] = extensions
        definitions.append(record)
    return definitions
