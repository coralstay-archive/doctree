"""프로젝트 레이아웃 프로필(config/project_layout_profiles.yaml) 스키마 검증 및 원자적 입출력 저장소."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import yaml

from doctree.runtime_env.boundary_errors import ClassificationError, SnapshotStorageError
from doctree.runtime_env.workspace_settings import PathLike, atomic_write_text, normalize_nfc

__all__ = [
    "ALL_PROFILE_FIELDS",
    "LIST_FIELDS",
    "OUTPUT_FORMATS",
    "REQUIRED_PROFILE_FIELDS",
    "SCALAR_FIELDS",
    "add_layout_items",
    "format_layout_value",
    "get_layout_value",
    "load_layout_profiles",
    "read_strict_yaml",
    "remove_layout_items",
    "save_layout_profiles",
    "set_layout_field",
    "validate_layout_profiles",
]


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """YAML 기본 안전 타입을 유지하면서 중복 키 덮어쓰기를 ClassificationError로 차단한다."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in result:
                    raise ClassificationError(
                        f"YAML 중복 키 {key!r} (줄 {key_node.start_mark.line + 1})"
                    )
                result[key] = self.construct_object(value_node, deep=deep)
            except TypeError as exc:
                raise ClassificationError("YAML 매핑 키는 단일 값이어야 합니다.") from exc
        return result


_PROFILE_ID_RE: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")

SCALAR_FIELDS: Final[tuple[str, ...]] = ("content_dir", "content_data_dir", "practice_dir")
LIST_FIELDS: Final[tuple[str, ...]] = ("directories", "required_files", "gitignore_entries")
ALL_PROFILE_FIELDS: Final[frozenset[str]] = frozenset(SCALAR_FIELDS + LIST_FIELDS)
REQUIRED_PROFILE_FIELDS: Final[frozenset[str]] = frozenset(LIST_FIELDS)
OUTPUT_FORMATS: Final[tuple[str, ...]] = ("yaml", "json", "lines")


def read_strict_yaml(path: PathLike) -> Any:
    """중복 키를 허용하지 않는 안전 YAML 로더(_UniqueKeySafeLoader)로 설정 파일을 읽는다."""
    target = Path(path)
    try:
        with target.open(encoding="utf-8") as stream:
            return yaml.load(stream, Loader=_UniqueKeySafeLoader)
    except ClassificationError as exc:
        raise ClassificationError(f"{target}: {exc}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ClassificationError(f"{target}: 레이아웃 YAML 설정을 읽을 수 없습니다: {exc}") from exc


def _norm_nonempty_str(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ClassificationError(f"{location}: 비어 있지 않은 문자열이어야 합니다.")
    return normalize_nfc(value.strip())


def validate_layout_profiles(data: Any, location: str = "project_layout_profiles.yaml") -> dict[str, Any]:
    """레이아웃 프로필 YAML 문서를 검증하고 NFC 정규화된 사전을 반환한다."""
    if not isinstance(data, dict):
        raise ClassificationError(f"{location}: 최상위 루트는 매핑 객체여야 합니다.")
    expected_root = {"schema_version", "profiles"}
    if set(data.keys()) != expected_root:
        missing = expected_root - set(data.keys())
        extra = set(data.keys()) - expected_root
        details = []
        if missing:
            details.append(f"필수 필드 누락: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"허용하지 않는 필드: {', '.join(sorted(map(str, extra)))}")
        raise ClassificationError(f"{location}: {'; '.join(details)}")

    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ClassificationError(f"{location}.schema_version: 지원하는 버전은 정수 1입니다.")

    raw_profiles = data["profiles"]
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ClassificationError(f"{location}.profiles: 비어 있지 않은 프로필 매핑이어야 합니다.")

    normalized_profiles: dict[str, dict[str, Any]] = {}
    for raw_name, raw_profile in raw_profiles.items():
        profile_name = _norm_nonempty_str(raw_name, f"{location}.profiles")
        if not _PROFILE_ID_RE.fullmatch(profile_name):
            raise ClassificationError(
                f"{location}.profiles.{profile_name}: 프로필 이름은 영문 소문자로 시작하고 소문자, 숫자, '.', '_', '-'만 사용해야 합니다."
            )
        p_loc = f"{location}.profiles.{profile_name}"
        if not isinstance(raw_profile, dict):
            raise ClassificationError(f"{p_loc}: 프로필 정의는 매핑 객체여야 합니다.")

        keys = set(raw_profile.keys())
        missing_req = REQUIRED_PROFILE_FIELDS - keys
        unknown = keys - ALL_PROFILE_FIELDS
        if missing_req or unknown:
            details = []
            if missing_req:
                details.append(f"필수 필드 누락: {', '.join(sorted(missing_req))}")
            if unknown:
                details.append(f"허용하지 않는 필드: {', '.join(sorted(map(str, unknown)))}")
            raise ClassificationError(f"{p_loc}: {'; '.join(details)}")

        clean_profile: dict[str, Any] = {}
        for s_field in SCALAR_FIELDS:
            if s_field in raw_profile:
                clean_profile[s_field] = _norm_nonempty_str(raw_profile[s_field], f"{p_loc}.{s_field}")

        for l_field in LIST_FIELDS:
            raw_list = raw_profile[l_field]
            l_loc = f"{p_loc}.{l_field}"
            if not isinstance(raw_list, list) or not raw_list:
                raise ClassificationError(f"{l_loc}: 비어 있지 않은 문자열 목록이어야 합니다.")
            seen: set[str] = set()
            clean_list: list[str] = []
            for idx, item in enumerate(raw_list):
                norm_item = _norm_nonempty_str(item, f"{l_loc}[{idx}]")
                if norm_item in seen:
                    raise ClassificationError(f"{l_loc}[{idx}]: 중복 항목 {norm_item!r}")
                seen.add(norm_item)
                clean_list.append(norm_item)
            clean_profile[l_field] = clean_list

        normalized_profiles[profile_name] = clean_profile

    return {
        "schema_version": 1,
        "profiles": normalized_profiles,
    }


def load_layout_profiles(path: PathLike) -> dict[str, Any]:
    """project_layout_profiles.yaml 파일을 읽어 중복 키 및 스키마를 검증한 뒤 반환한다."""
    target = Path(path)
    raw = read_strict_yaml(target)
    return validate_layout_profiles(raw, str(target))


def save_layout_profiles(data: dict[str, Any], path: PathLike) -> Path:
    """레이아웃 프로필 데이터를 검증한 뒤 임시 파일(.tmp) + replace로 원자적으로 저장한다."""
    target = Path(path)
    validated = validate_layout_profiles(data, str(target))
    rendered = (
        "# 프로젝트 유형별 디렉토리 및 파일 구조 규격 정의서\n"
        + yaml.safe_dump(validated, allow_unicode=True, sort_keys=False)
    )
    try:
        return atomic_write_text(target, rendered)
    except OSError as exc:
        raise SnapshotStorageError(f"{target}: 레이아웃 설정 저장 실패: {exc}") from exc


def get_layout_value(
    data: dict[str, Any],
    profile: str | None = None,
    field: str | None = None,
) -> Any:
    """전체 레이아웃 문서, 특정 프로필, 또는 특정 프로필의 필드 값을 조회한다."""
    validated = validate_layout_profiles(data)
    if profile is None:
        return validated
    norm_profile = _norm_nonempty_str(profile, "profile")
    profiles = validated["profiles"]
    if norm_profile not in profiles:
        raise ClassificationError(f"등록되지 않은 레이아웃 프로필입니다: {norm_profile!r}")
    profile_obj = profiles[norm_profile]
    if field is None:
        return profile_obj
    norm_field = _norm_nonempty_str(field, "field")
    if norm_field not in profile_obj:
        raise ClassificationError(
            f"프로필 {norm_profile!r}에 존재하지 않는 필드입니다: {norm_field!r}"
        )
    return profile_obj[norm_field]


def format_layout_value(value: Any, fmt: str = "yaml") -> str:
    """조회된 레이아웃 값을 yaml, json, lines 포맷 문자열로 직렬화한다."""
    if fmt not in OUTPUT_FORMATS:
        raise ClassificationError(f"지원하지 않는 출력 포맷입니다: {fmt!r} (지원: {', '.join(OUTPUT_FORMATS)})")
    if fmt == "json":
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if fmt == "lines":
        if isinstance(value, str):
            return f"{value}\n"
        if isinstance(value, list):
            return "".join(f"{item}\n" for item in value)
        if "profiles" in value and "schema_version" in value:
            return "".join(f"{k}\n" for k in value["profiles"])
        return "".join(f"{k}\n" for k in value)
    if isinstance(value, str):
        return f"{value}\n"
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False)


def set_layout_field(
    path: PathLike,
    profile: str,
    field: str,
    values: Iterable[str],
) -> dict[str, Any]:
    """특정 프로필의 스칼라 또는 목록 필드를 새 값으로 교체하고 원자적으로 저장한다."""
    data = load_layout_profiles(path)
    norm_profile = _norm_nonempty_str(profile, "profile")
    if norm_profile not in data["profiles"]:
        raise ClassificationError(f"등록되지 않은 레이아웃 프로필입니다: {norm_profile!r}")
    norm_field = _norm_nonempty_str(field, "field")
    value_list = [_norm_nonempty_str(v, f"{norm_profile}.{norm_field}") for v in values]
    if not value_list:
        raise ClassificationError(f"{norm_profile}.{norm_field}: 설정할 값을 1개 이상 지정해야 합니다.")

    if norm_field in SCALAR_FIELDS:
        if len(value_list) != 1:
            raise ClassificationError(
                f"{norm_profile}.{norm_field}: 단일 문자열 필드는 값을 1개만 지정해야 합니다."
            )
        data["profiles"][norm_profile][norm_field] = value_list[0]
    elif norm_field in LIST_FIELDS:
        data["profiles"][norm_profile][norm_field] = value_list
    else:
        raise ClassificationError(f"허용하지 않는 레이아웃 필드입니다: {norm_field!r}")

    save_layout_profiles(data, path)
    return data["profiles"][norm_profile]


def add_layout_items(
    path: PathLike,
    profile: str,
    field: str,
    items: Iterable[str],
) -> list[str]:
    """특정 프로필의 목록 필드(directories, required_files, gitignore_entries)에 항목을 추가하고 원자적으로 저장한다."""
    data = load_layout_profiles(path)
    norm_profile = _norm_nonempty_str(profile, "profile")
    if norm_profile not in data["profiles"]:
        raise ClassificationError(f"등록되지 않은 레이아웃 프로필입니다: {norm_profile!r}")
    norm_field = _norm_nonempty_str(field, "field")
    if norm_field not in LIST_FIELDS:
        raise ClassificationError(
            f"{norm_profile}.{norm_field}: 항목 추가(add)는 목록 필드({', '.join(LIST_FIELDS)})에만 사용할 수 있습니다."
        )
    normalized_items = [_norm_nonempty_str(item, f"{norm_profile}.{norm_field}") for item in items]
    if not normalized_items:
        raise ClassificationError(f"{norm_profile}.{norm_field}: 추가할 항목을 1개 이상 지정해야 합니다.")

    current: list[str] = list(data["profiles"][norm_profile][norm_field])
    for item in normalized_items:
        if item not in current:
            current.append(item)
    data["profiles"][norm_profile][norm_field] = current
    save_layout_profiles(data, path)
    return current


def remove_layout_items(
    path: PathLike,
    profile: str,
    field: str,
    items: Iterable[str],
) -> list[str]:
    """특정 프로필의 목록 필드에서 항목을 제거하고 원자적으로 저장한다."""
    data = load_layout_profiles(path)
    norm_profile = _norm_nonempty_str(profile, "profile")
    if norm_profile not in data["profiles"]:
        raise ClassificationError(f"등록되지 않은 레이아웃 프로필입니다: {norm_profile!r}")
    norm_field = _norm_nonempty_str(field, "field")
    if norm_field not in LIST_FIELDS:
        raise ClassificationError(
            f"{norm_profile}.{norm_field}: 항목 제거(remove)는 목록 필드({', '.join(LIST_FIELDS)})에만 사용할 수 있습니다."
        )
    normalized_items = [_norm_nonempty_str(item, f"{norm_profile}.{norm_field}") for item in items]
    if not normalized_items:
        raise ClassificationError(f"{norm_profile}.{norm_field}: 제거할 항목을 1개 이상 지정해야 합니다.")

    current: list[str] = list(data["profiles"][norm_profile][norm_field])
    for item in normalized_items:
        if item not in current:
            raise ClassificationError(
                f"프로필 {norm_profile!r}.{norm_field}에 존재하지 않는 항목입니다: {item!r}"
            )
    updated = [entry for entry in current if entry not in set(normalized_items)]
    data["profiles"][norm_profile][norm_field] = updated
    save_layout_profiles(data, path)
    return updated
