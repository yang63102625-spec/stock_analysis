# -*- coding: utf-8 -*-
"""Configuration field metadata registry.

This package is the single source of truth for configuration UI metadata,
validation hints, and category grouping. The internal modules split the
data along functional axes:

- :mod:`.categories` — schema version + category-level metadata.
- :mod:`.fields_a` / :mod:`.fields_b` — field-level definitions, kept in
  two halves so each file stays under the 800-line ceiling
  (``code-quality.mdc`` rule §1).
- :mod:`._inference` — fallback inference helpers for keys without an
  explicit definition.

The public surface (``get_*`` / ``build_schema_response``) is unchanged
and re-exported from this module.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from ._inference import (
    _infer_category,
    _infer_data_type,
    _infer_ui_control,
    _is_sensitive_key,
)
from .categories import SCHEMA_VERSION, _CATEGORY_DEFINITIONS
from .fields_a import _FIELD_DEFS_A
from .fields_b import _FIELD_DEFS_B

# Merge the two halves into the canonical registry exposed to the rest of
# the codebase. Order is preserved for stable iteration.
_FIELD_DEFINITIONS: Dict[str, Dict[str, Any]] = {**_FIELD_DEFS_A, **_FIELD_DEFS_B}


def get_category_definitions() -> List[Dict[str, Any]]:
    """Return deep-copied category metadata."""
    return deepcopy(_CATEGORY_DEFINITIONS)


def get_registered_field_keys() -> List[str]:
    """Return all explicitly registered keys."""
    return list(_FIELD_DEFINITIONS.keys())


def get_field_definition(key: str, value_hint: Optional[str] = None) -> Dict[str, Any]:
    """Return field definition for key, including inferred fallback metadata."""
    key_upper = key.upper()
    if key_upper in _FIELD_DEFINITIONS:
        field = deepcopy(_FIELD_DEFINITIONS[key_upper])
        field["key"] = key_upper
        return field

    category = _infer_category(key_upper)
    data_type = _infer_data_type(key_upper, value_hint)
    field = {
        "key": key_upper,
        "title": key_upper.replace("_", " ").title(),
        "description": "Auto-inferred field metadata.",
        "category": category,
        "data_type": data_type,
        "ui_control": _infer_ui_control(data_type, key_upper),
        "is_sensitive": _is_sensitive_key(key_upper),
        "is_required": False,
        "is_editable": True,
        "default_value": None,
        "options": [],
        "validation": {},
        "display_order": 9000,
    }
    return field


def build_schema_response() -> Dict[str, Any]:
    """Build schema payload grouped by category."""
    category_map: Dict[str, Dict[str, Any]] = {}
    for category in get_category_definitions():
        category_map[category["category"]] = {**category, "fields": []}

    for key in sorted(_FIELD_DEFINITIONS.keys()):
        field = get_field_definition(key)
        category_map[field["category"]]["fields"].append(field)

    categories = sorted(category_map.values(), key=lambda item: item["display_order"])
    for category in categories:
        category["fields"] = sorted(
            category["fields"],
            key=lambda item: (item.get("display_order", 9999), item["key"]),
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "categories": categories,
    }


__all__ = [
    "SCHEMA_VERSION",
    "build_schema_response",
    "get_category_definitions",
    "get_field_definition",
    "get_registered_field_keys",
]
