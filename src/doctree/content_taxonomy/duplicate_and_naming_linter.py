"""드라이브 정리용 점검: 중복·파일명 경고 (KBI-5).

모든 점검은 레코드 목록만 읽는 순수 함수다. 드라이브 API를 호출하지 않고,
입력 레코드를 수정하지 않는다 (B2).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from doctree.runtime_env.workspace_settings import normalize_nfc

__all__ = [
    "CheckWarning",
    "WarningKind",
    "find_exact_duplicates",
    "find_filename_issues",
    "find_same_title_different_content",
    "run_checks",
    "title_key",
]

Record = dict

_PDF_SUFFIX = re.compile(r"\.pdf$", re.IGNORECASE)
_COPY_OF_PREFIX = re.compile(r"^Copy of ")
_IGNORED = re.compile(r"[-\s]+")


class WarningKind(StrEnum):
    """점검 경고 종류 식별자 (StrEnum이므로 일반 문자열 비교와 100% 호환)."""

    EXACT_DUPLICATE = "exact_duplicate"
    SAME_TITLE_DIFFERENT_CONTENT = "same_title_different_content"
    MISSING_PDF_EXTENSION = "missing_pdf_extension"
    COPY_OF_PREFIX = "copy_of_prefix"
    SURROUNDING_WHITESPACE = "surrounding_whitespace"


def title_key(name: str) -> str:
    """파일명(또는 제목)을 중복 점검용 제목 키로 정규화한다.

    순서: NFC 정규화 → 끝의 '.pdf'(대소문자 무시) 제거 → 앞의 'Copy of ' 제거
    → 하이픈·공백 제거 → 소문자화.
    """
    s = normalize_nfc(name)
    s = _PDF_SUFFIX.sub("", s)
    s = _COPY_OF_PREFIX.sub("", s)
    s = _IGNORED.sub("", s)
    return s.lower()


@dataclass(slots=True)
class CheckWarning:
    """점검 경고 하나. kind는 안정적인 식별 문자열(WarningKind), files는 관련 레코드, message는 한국어 설명."""

    kind: WarningKind | str
    files: list[Record]
    message: str


def _path(rec: Record) -> str:
    folder = normalize_nfc(rec.get("folder_path"))
    name = normalize_nfc(rec.get("name"))
    return f"{folder}/{name}" if folder else name


def _order(w: CheckWarning):
    return (_path(w.files[0]), w.files[0].get("id") or "")


def _sorted(recs: Iterable[Record]) -> list[Record]:
    return sorted(recs, key=lambda r: (_path(r), r.get("id") or ""))


def _paths(recs: Iterable[Record]) -> str:
    return ", ".join(_path(r) for r in recs)


def find_exact_duplicates(records: Iterable[Record]) -> list[CheckWarning]:
    """SHA-256이 같은 파일 묶음마다 '완전 중복' 경고. SHA-256이 빈 파일은 묶지 않는다 (B1: 이름 무관)."""
    groups: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        sha256 = rec.get("sha256")
        if sha256:
            groups[sha256].append(rec)
    warnings = []
    for members in groups.values():
        if len(members) < 2:
            continue
        files = _sorted(members)
        warnings.append(CheckWarning(
            kind=WarningKind.EXACT_DUPLICATE,
            files=files,
            message=f"완전 중복 {len(files)}개 (SHA-256 동일): {_paths(files)}",
        ))
    return sorted(warnings, key=_order)


def find_same_title_different_content(records: Iterable[Record]) -> list[CheckWarning]:
    """제목 키가 같지만 SHA-256 값이 2종 이상인 묶음마다 '동명 다른 파일' 경고."""
    groups: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        groups[title_key(rec.get("name") or "")].append(rec)
    warnings = []
    for members in groups.values():
        if len(members) < 2 or len({m.get("sha256") or "" for m in members}) < 2:
            continue
        files = _sorted(members)
        warnings.append(CheckWarning(
            kind=WarningKind.SAME_TITLE_DIFFERENT_CONTENT,
            files=files,
            message=f"동명 다른 파일 {len(files)}개 (제목 같고 SHA-256 다름): {_paths(files)}",
        ))
    return sorted(warnings, key=_order)


_FILENAME_KINDS = (
    WarningKind.MISSING_PDF_EXTENSION,
    WarningKind.COPY_OF_PREFIX,
    WarningKind.SURROUNDING_WHITESPACE,
)


def find_filename_issues(records: Iterable[Record]) -> list[CheckWarning]:
    """파일별 파일명 점검: .pdf 확장자 누락, 'Copy of ' 접두어, 앞뒤 공백."""
    found: dict[WarningKind, list[CheckWarning]] = {k: [] for k in _FILENAME_KINDS}
    for rec in records:
        name = normalize_nfc(rec.get("name"))
        path = _path(rec)
        if not name.lower().endswith(".pdf"):
            found[WarningKind.MISSING_PDF_EXTENSION].append(CheckWarning(
                kind=WarningKind.MISSING_PDF_EXTENSION, files=[rec],
                message=f"파일명에 .pdf 확장자가 없음: {path}"))
        if name.startswith("Copy of "):
            found[WarningKind.COPY_OF_PREFIX].append(CheckWarning(
                kind=WarningKind.COPY_OF_PREFIX, files=[rec],
                message=f"파일명에 'Copy of ' 접두어가 있음: {path}"))
        if name != name.strip():
            found[WarningKind.SURROUNDING_WHITESPACE].append(CheckWarning(
                kind=WarningKind.SURROUNDING_WHITESPACE, files=[rec],
                message=f"파일명 앞뒤에 공백이 있음: {path!r}"))
    warnings: list[CheckWarning] = []
    for kind in _FILENAME_KINDS:
        warnings.extend(sorted(found[kind], key=_order))
    return warnings


def run_checks(records: Iterable[Record]) -> list[CheckWarning]:
    """모든 점검을 실행해 종류 순(완전 중복 → 동명 다른 파일 → 파일명 점검) → 경로 순 경고 목록을 반환한다."""
    records = list(records)
    return (
        find_exact_duplicates(records)
        + find_same_title_different_content(records)
        + find_filename_issues(records)
    )
