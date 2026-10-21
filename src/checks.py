"""드라이브 정리용 점검: 중복·파일명 경고 (KBI-5).

모든 점검은 레코드 목록만 읽는 순수 함수다. 드라이브 API를 호출하지 않고,
입력 레코드를 수정하지 않는다 (B2).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

Record = Dict


@dataclass
class CheckWarning:
    """점검 경고 하나. kind는 안정적인 식별 문자열, files는 관련 레코드, message는 한국어 설명."""

    kind: str
    files: List[Record] = field(default_factory=list)
    message: str = ""


def _path(rec: Record) -> str:
    folder = rec.get("folder_path") or ""
    name = rec.get("name") or ""
    return f"{folder}/{name}" if folder else name


def _sorted(recs: Iterable[Record]) -> List[Record]:
    return sorted(recs, key=lambda r: (_path(r), r.get("id") or ""))


def _paths(recs: Iterable[Record]) -> str:
    return ", ".join(_path(r) for r in recs)


def find_exact_duplicates(records: Iterable[Record]) -> List[CheckWarning]:
    """MD5가 같은 파일 묶음마다 '완전 중복' 경고. MD5가 빈 파일은 묶지 않는다 (B1: 이름 무관)."""
    groups: Dict[str, List[Record]] = defaultdict(list)
    for rec in records:
        md5 = rec.get("md5")
        if md5:
            groups[md5].append(rec)
    warnings = []
    for members in groups.values():
        if len(members) < 2:
            continue
        files = _sorted(members)
        warnings.append(CheckWarning(
            kind="exact_duplicate",
            files=files,
            message=f"완전 중복 {len(files)}개 (MD5 동일): {_paths(files)}",
        ))
    return sorted(warnings, key=lambda w: _path(w.files[0]))
