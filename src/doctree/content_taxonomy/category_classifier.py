"""Validate the fixed taxonomy and classify Drive files by their persistent IDs.

Names and folder paths are metadata only. A file receives a category exclusively
through an explicit entry in ``content_category_map.yaml``.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from doctree.runtime_env.boundary_errors import ClassificationError
from doctree.runtime_env.layout_profile_store import read_strict_yaml
from doctree.runtime_env.workspace_settings import PathLike, normalize_nfc

__all__ = [
    "Category",
    "ClassificationCatalog",
    "ClassificationError",
    "ClassificationResult",
    "ClassifiedContent",
    "ContentAssignment",
    "Subcategory",
    "classify_records",
    "load_catalog",
]


@dataclass(frozen=True, slots=True)
class Subcategory:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Category:
    id: str
    name: str
    subcategories: tuple[Subcategory, ...]


@dataclass(frozen=True, slots=True)
class ContentAssignment:
    file_id: str
    title: str
    category_id: str


@dataclass(frozen=True, slots=True)
class ClassificationCatalog:
    categories: tuple[Category, ...]
    assignments: tuple[ContentAssignment, ...]


@dataclass(frozen=True, slots=True)
class ClassifiedContent:
    record: dict[str, Any]
    category_id: str | None


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    catalog: ClassificationCatalog
    contents: tuple[ClassifiedContent, ...]

    @property
    def unclassified(self) -> tuple[ClassifiedContent, ...]:
        return tuple(content for content in self.contents if content.category_id is None)


_CATEGORY_ID = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")


def _mapping(value: Any, fields: set, location: str) -> dict:
    if not isinstance(value, dict):
        raise ClassificationError(f"{location}: 객체여야 합니다.")
    if set(value) != fields:
        missing = fields - set(value)
        extra = set(value) - fields
        details = []
        if missing:
            details.append(f"필수 필드 누락: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"허용하지 않는 필드: {', '.join(sorted(map(str, extra)))}")
        raise ClassificationError(f"{location}: {'; '.join(details)}")
    return value


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClassificationError(f"{location}: 비어 있지 않은 문자열이어야 합니다.")
    return value


def _node_id(value: Any, location: str) -> str:
    value = _string(value, location)
    if not _CATEGORY_ID.fullmatch(value):
        raise ClassificationError(
            f"{location}: 분류 ID는 영문 소문자로 시작하고 영문 소문자, 숫자, '.', '_', '-'만 사용해야 합니다."
        )
    return value


def _list(value: Any, location: str, *, nonempty: bool = False) -> list:
    if not isinstance(value, list) or (nonempty and not value):
        qualifier = "비어 있지 않은 " if nonempty else ""
        raise ClassificationError(f"{location}: {qualifier}목록이어야 합니다.")
    return value


def _document(value: Any, collection: str, location: str) -> list:
    value = _mapping(value, {"schema_version", collection}, location)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ClassificationError(f"{location}.schema_version: 지원하는 버전은 정수 1입니다.")
    return _list(value[collection], f"{location}.{collection}", nonempty=collection == "categories")


def _unique(value: str, seen: set, location: str) -> None:
    normalized = normalize_nfc(value)
    if normalized in seen:
        raise ClassificationError(f"{location}: 중복 값 {value!r}")
    seen.add(normalized)


def load_catalog(category_tree_path: PathLike, content_category_map_path: PathLike) -> ClassificationCatalog:
    """Load both configuration files, rejecting invalid or ambiguous mappings."""
    raw_categories = _document(read_strict_yaml(category_tree_path), "categories", str(category_tree_path))
    categories = []
    all_node_ids = set()
    root_names = set()
    leaf_ids = set()
    for index, raw_category in enumerate(raw_categories):
        location = f"categories[{index}]"
        item = _mapping(raw_category, {"id", "name", "subcategories"}, location)
        category_id = _node_id(item["id"], f"{location}.id")
        name = _string(item["name"], f"{location}.name")
        _unique(category_id, all_node_ids, f"{location}.id")
        _unique(name, root_names, f"{location}.name")
        raw_subcategories = _list(item["subcategories"], f"{location}.subcategories", nonempty=True)
        subcategories = []
        sibling_names = set()
        for child_index, raw_subcategory in enumerate(raw_subcategories):
            child_location = f"{location}.subcategories[{child_index}]"
            child = _mapping(raw_subcategory, {"id", "name"}, child_location)
            child_id = _node_id(child["id"], f"{child_location}.id")
            child_name = _string(child["name"], f"{child_location}.name")
            _unique(child_id, all_node_ids, f"{child_location}.id")
            _unique(child_name, sibling_names, f"{child_location}.name")
            leaf_ids.add(child_id)
            subcategories.append(Subcategory(id=child_id, name=child_name))
        categories.append(Category(id=category_id, name=name, subcategories=tuple(subcategories)))

    raw_contents = _document(read_strict_yaml(content_category_map_path), "contents", str(content_category_map_path))
    assignments = []
    file_ids = set()
    for index, raw_content in enumerate(raw_contents):
        location = f"contents[{index}]"
        item = _mapping(raw_content, {"file_id", "title", "category_id"}, location)
        file_id = _string(item["file_id"], f"{location}.file_id")
        title = _string(item["title"], f"{location}.title")
        category_id = _node_id(item["category_id"], f"{location}.category_id")
        if file_id in file_ids:
            raise ClassificationError(f"{location}.file_id: 중복 파일 ID {file_id!r}")
        file_ids.add(file_id)
        if category_id not in leaf_ids:
            raise ClassificationError(
                f"{location}.category_id: 등록된 세부분야 ID가 아닙니다: {category_id!r}"
            )
        assignments.append(ContentAssignment(file_id=file_id, title=title, category_id=category_id))

    return ClassificationCatalog(categories=tuple(categories), assignments=tuple(assignments))


def classify_records(
    records: Iterable[dict], catalog: ClassificationCatalog, *, strict: bool = False
) -> ClassificationResult:
    """Assign known Drive IDs and leave every new ID pending explicit review."""
    by_file_id = {assignment.file_id: assignment.category_id for assignment in catalog.assignments}
    contents = []
    file_ids = set()
    for index, record in enumerate(records):
        location = f"records[{index}]"
        if not isinstance(record, dict):
            raise ClassificationError(f"{location}: 객체여야 합니다.")
        file_id = _string(record.get("id"), f"{location}.id")
        _string(record.get("name"), f"{location}.name")
        if file_id in file_ids:
            raise ClassificationError(f"{location}.id: 중복 파일 ID {file_id!r}")
        file_ids.add(file_id)
        contents.append(ClassifiedContent(record=dict(record), category_id=by_file_id.get(file_id)))

    result = ClassificationResult(catalog=catalog, contents=tuple(contents))
    if strict and result.unclassified:
        pending = ", ".join(repr(content.record["id"]) for content in result.unclassified)
        raise ClassificationError(f"미분류 콘텐츠 {len(result.unclassified)}권: {pending}")
    return result
