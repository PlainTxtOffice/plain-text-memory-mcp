"""Build and version the taxonomy of the memory server's formats and tools.

- `build_content` reads everything from the code: record fields from the
  record writers; tools, resources, and prompts from the running server's
  listings; and enums from the typed literals.
- `update_document` compares new content with the committed document and
  bumps `taxonomy_version`: removals and changed values are major, additions
  are minor, description and version text changes are patch.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import version as package_version
from pathlib import Path
from typing import get_args

import anyio
from mcp import Client

from plain_text_memory_mcp import agent, records, server
from plain_text_memory_mcp.graph import (
    UNTAGGED,
    Access,
    Entity,
    Header,
    Observation,
    Relation,
    Source,
    Tag,
)

PACKAGE_NAME = "plain-text-memory-mcp"
CONTENT_KEYS = (
    "package",
    "record_types",
    "enums",
    "tools",
    "resources",
    "prompts",
)
FIRST_VERSION = "1.0.0"
_META_KEYS = {"taxonomy_version", "changelog"}

# Leaf keys whose changes only reword or re-version, never break a reader.
_DESCRIPTIVE_KEYS = {
    "description",
    "purpose",
    "title",
    "version",
}
_BUMP_ORDER = ("patch", "minor", "major")
_SAMPLE_TAG = Tag("2026-01-01T00:00:00+00:00", "codex")
_JSON_TYPE_NAMES = {str: "string", type(None): "null"}


def _map_field_type(key: str, values: list[object]) -> str:
    if key == "type":
        return f'"{values[0]}"'
    names: list[str] = []
    for value in values:
        if isinstance(value, list):
            name = f"{key.removesuffix('s')}[]"
        else:
            name = _JSON_TYPE_NAMES[type(value)]
        if name not in names:
            names.append(name)
    return "|".join(names)


def _map_record_fields(samples: list[Mapping[str, object]]) -> dict[str, str]:
    """Map each field to its types; a field some samples lack is optional."""
    keys = dict.fromkeys(key for sample in samples for key in sample)
    fields: dict[str, str] = {}
    for key in keys:
        values = [sample[key] for sample in samples if key in sample]
        kind = _map_field_type(key, values)
        optional = len(values) < len(samples)
        fields[key] = f"{kind} (optional)" if optional else kind
    return fields


def _build_record_types() -> dict[str, object]:
    samples: dict[str, list[Mapping[str, object]]] = {
        "header": [
            records.to_header_record(Header("repo", "D:/repo", tag))
            for tag in (_SAMPLE_TAG, UNTAGGED)
        ],
        "entity": [
            records.to_entity_record(Entity("name", "kind", [], tag))
            for tag in (_SAMPLE_TAG, UNTAGGED)
        ],
        "relation": [
            records.to_relation_record(Relation("a", "b", "uses", tag))
            for tag in (_SAMPLE_TAG, UNTAGGED)
        ],
        "observation": [
            records.to_observation_record(
                Observation(
                    "text", tag, edited, superseded, replaced_by, sources
                )
            )
            for tag in (_SAMPLE_TAG, UNTAGGED)
            for edited in (None, tag)
            for superseded, replaced_by in ((None, None), (tag, "new text"))
            for sources in ((), (Source("name", "text"),))
        ],
        "tombstone": [
            records.to_tombstone_record(records.Tombstone(entity_name="a")),
            records.to_tombstone_record(
                records.Tombstone(relation_key=("a", "b", "uses"))
            ),
        ],
        "access": [
            records.to_access_record(Access(str(_SAMPLE_TAG.added_at), "a"))
        ],
    }
    return {
        kind: {
            "purpose": records.RECORD_PURPOSES[kind],
            "fields": _map_record_fields(values),
        }
        for kind, values in samples.items()
    }


def _map_schema(schema: dict, defs: dict) -> object:
    if "$ref" in schema:
        return _map_schema(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "const" in schema:
        return f'"{schema["const"]}"'
    if "enum" in schema:
        return "|".join(str(value) for value in schema["enum"])
    if "anyOf" in schema:
        return "|".join(
            str(_map_schema(part, defs)) for part in schema["anyOf"]
        )
    if schema.get("type") == "array":
        return [_map_schema(schema["items"], defs)]
    if "properties" in schema:
        return {
            name: _map_schema(part, defs)
            for name, part in schema["properties"].items()
        }
    return schema.get("type", "any")


async def _fetch_listing() -> tuple[list, list, list]:
    app = server.build_server(Path("taxonomy.jsonl"), None, Path("taxonomy"))
    async with Client(app) as client:
        tools = (await client.list_tools()).tools
        resources = (await client.list_resources()).resources
        prompts = (await client.list_prompts()).prompts
        return tools, resources, prompts


def _build_tools(listed: list) -> dict[str, dict[str, object]]:
    tools = sorted(listed, key=lambda tool: tool.name)
    return {
        tool.name: {
            "description": (tool.description or "").strip().splitlines()[0],
            "params": _map_schema(
                tool.input_schema, tool.input_schema.get("$defs", {})
            ),
            "returns": _map_schema(
                tool.output_schema or {},
                (tool.output_schema or {}).get("$defs", {}),
            ),
        }
        for tool in tools
    }


def _build_resources(listed: list) -> dict[str, dict[str, object]]:
    resources = sorted(listed, key=lambda resource: str(resource.uri))
    return {
        str(resource.uri): {
            "name": resource.name,
            "title": resource.title,
            "description": resource.description,
            "mime_type": resource.mime_type,
        }
        for resource in resources
    }


def _build_prompts(listed: list) -> dict[str, dict[str, object]]:
    prompts = sorted(listed, key=lambda prompt: prompt.name)
    return {
        prompt.name: {
            "title": prompt.title,
            "description": prompt.description,
            "arguments": [argument.name for argument in prompt.arguments or []],
        }
        for prompt in prompts
    }


_JSON_TYPES = {
    "string",
    "number",
    "integer",
    "boolean",
    "object",
    "array",
    "null",
}


def _build_enums(
    tools: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    agent_names = list(dict.fromkeys(name for _, name in agent.KNOWN_AGENTS))
    enums: dict[str, list[str]] = {
        "agent": [*agent_names, agent.UNKNOWN_AGENT],
    }
    for tool_name, tool in tools.items():
        params = tool["params"]
        if not isinstance(params, dict):
            continue
        for param, kind in params.items():
            if not isinstance(kind, str) or "|" not in kind:
                continue
            values = kind.split("|")
            # "string|null" is an optional type, not a set of choices.
            if not set(values) <= _JSON_TYPES:
                enums[f"{tool_name}.{param}"] = values
    enums["initialize_memory.status"] = list(get_args(server.InitStatus))
    return enums


def build_content() -> dict[str, object]:
    """Return the taxonomy content for the installed server."""
    listed_tools, listed_resources, listed_prompts = anyio.run(_fetch_listing)
    tools = _build_tools(listed_tools)
    return {
        "package": {
            "name": PACKAGE_NAME,
            "version": package_version(PACKAGE_NAME),
        },
        "record_types": _build_record_types(),
        "enums": _build_enums(tools),
        "tools": tools,
        "resources": _build_resources(listed_resources),
        "prompts": _build_prompts(listed_prompts),
    }


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        leaves: dict[str, object] = {}
        for key, part in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_flatten(part, path))
        return leaves
    if isinstance(value, list):
        if all(isinstance(part, str) for part in value):
            return {f"{prefix}[{part}]": True for part in value}
        leaves = {}
        for part in value:
            leaves.update(_flatten(part, f"{prefix}[]"))
        return leaves
    return {prefix: value}


def _has_path(tree: object, segments: list[str]) -> bool:
    node = tree
    for segment in segments:
        name, _, rest = segment.partition("[")
        if not isinstance(node, dict) or name not in node:
            return False
        node = node[name]
        if rest and isinstance(node, list):
            node = node[0] if node and isinstance(node[0], dict) else {}
    return True


def _calc_reported_path(key: str, other_tree: dict[str, object]) -> str:
    """Return the shortest ancestor of `key` missing from `other_tree`.

    - A whole new tool reports as `tools.<name>`, not one line per field.
    """
    segments = key.split(".")
    for end in range(1, len(segments)):
        if not _has_path(other_tree, segments[:end]):
            return ".".join(segments[:end])
    return key


def _calc_changes(
    old: dict[str, object], new: dict[str, object]
) -> tuple[list[str], str | None]:
    old_leaves, new_leaves = _flatten(old), _flatten(new)
    changes: list[str] = []
    levels: list[str] = []
    removed = {
        _calc_reported_path(key, new)
        for key in old_leaves.keys() - new_leaves.keys()
    }
    added = {
        _calc_reported_path(key, old)
        for key in new_leaves.keys() - old_leaves.keys()
    }
    changes += [f"removed: {path}" for path in sorted(removed)]
    changes += [f"added: {path}" for path in sorted(added)]
    levels += ["major"] * len(removed) + ["minor"] * len(added)
    for key in sorted(old_leaves.keys() & new_leaves.keys()):
        before, after = old_leaves[key], new_leaves[key]
        if before == after:
            continue
        if key.rsplit(".", 1)[-1] in _DESCRIPTIVE_KEYS:
            changes.append(f"changed: {key}")
            levels.append("patch")
        else:
            changes.append(f"changed: {key} ({before} -> {after})")
            levels.append("major")
    if not levels:
        return changes, None
    return changes, max(levels, key=_BUMP_ORDER.index)


def _calc_next_version(current: str, level: str) -> str:
    major, minor, patch = (int(part) for part in current.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def update_document(
    document: dict | None, content: dict[str, object], today: str
) -> dict | None:
    """Return the next taxonomy document, or None when nothing changed.

    - A missing document starts at version 1.0.0.
    - The changelog lists the newest entry first.
    """
    if document is None:
        entry = {
            "version": FIRST_VERSION,
            "date": today,
            "changes": ["initial taxonomy"],
        }
        return {
            "taxonomy_version": FIRST_VERSION,
            **content,
            "changelog": [entry],
        }
    # Sections the code no longer builds still count, as removals.
    old_keys = [*CONTENT_KEYS, *(k for k in document if k not in _META_KEYS)]
    old_content = {
        key: document.get(key, {}) for key in dict.fromkeys(old_keys)
    }
    changes, level = _calc_changes(old_content, content)
    if level is None:
        return None
    next_version = _calc_next_version(document["taxonomy_version"], level)
    entry = {"version": next_version, "date": today, "changes": changes}
    return {
        "taxonomy_version": next_version,
        **content,
        "changelog": [entry, *document.get("changelog", [])],
    }
