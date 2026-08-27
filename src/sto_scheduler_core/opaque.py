from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET


def split_tag(tag: str) -> tuple[str | None, str]:
    if tag.startswith("{"):
        namespace, local = tag[1:].split("}", 1)
        return namespace, local
    return None, tag


def local_name(tag: str) -> str:
    return split_tag(tag)[1]


def element_to_opaque(
    element: ET.Element, primary_namespace: str | None = None
) -> dict[str, Any]:
    namespace, name = split_tag(element.tag)
    result: dict[str, Any] = {"name": name}
    if namespace and namespace != primary_namespace:
        result["namespace"] = namespace
    text = (element.text or "").strip()
    if text:
        result["text"] = text
    if element.attrib:
        attributes: dict[str, str] = {}
        for key, value in sorted(element.attrib.items()):
            attr_namespace, attr_name = split_tag(key)
            normalized = (
                attr_name if not attr_namespace else f"{{{attr_namespace}}}{attr_name}"
            )
            attributes[normalized] = value
        result["attributes"] = attributes
    children = [element_to_opaque(child, primary_namespace) for child in list(element)]
    if children:
        result["children"] = children
    return result
