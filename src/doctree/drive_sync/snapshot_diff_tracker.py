"""목록 스냅샷 저장과 직전 스냅샷 비교 (KBI-4).

snapshots/
  YYYY-MM-DD.json   실행 시점의 PDF 목록 (같은 날 재실행 시 덮어씀)
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from doctree.runtime_env.boundary_errors import SnapshotStorageError
from doctree.runtime_env.workspace_settings import PathLike, atomic_write_text, normalize_nfc

__all__ = [
    "KST",
    "Change",
    "Changes",
    "RunResult",
    "change_summary",
    "diff_snapshots",
    "load_latest_snapshot",
    "record_run",
    "save_snapshot",
    "snapshot_date",
]

Record = Mapping[str, Any]

KST = timezone(timedelta(hours=9))
_SNAPSHOT_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def snapshot_date(now: datetime) -> date:
    """시간대(tzinfo)가 있는 시각은 항상 한국 표준시(KST, UTC+9) 날짜로 변환한다."""
    if now.tzinfo is not None:
        return now.astimezone(KST).date()
    return now.date()


def save_snapshot(records: Iterable[Record], snapshots_dir: PathLike, now: datetime) -> Path:
    """records를 snapshots_dir/<now의 KST 날짜>.json으로 저장하고 경로를 돌려준다.

    같은 날짜 파일이 있으면 덮어쓴다. 레코드는 id 순으로, 키는 사전순으로 정렬해
    같은 입력이면 같은 바이트가 나오게 한다(UTF-8, ensure_ascii=False).
    """
    recs = sorted((dict(r) for r in records), key=lambda r: str(r.get("id", "")))
    payload = {"taken_at": now.isoformat(), "count": len(recs), "records": recs}
    path = Path(snapshots_dir) / f"{snapshot_date(now).isoformat()}.json"
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    return atomic_write_text(path, text)


def load_latest_snapshot(snapshots_dir: PathLike) -> tuple[date, list[dict]] | None:
    """snapshots_dir에서 날짜가 가장 최근인 스냅샷의 (날짜, records)를 돌려준다.

    없으면 None. 'YYYY-MM-DD.json' 형식(유효한 날짜)이 아닌 파일은 무시한다.
    오늘 날짜 파일도 후보이므로, 이번 실행분을 저장하기 전에 호출해야 한다(B4).
    """
    d = Path(snapshots_dir)
    if not d.is_dir():
        return None
    candidates = []
    for p in d.iterdir():
        m = _SNAPSHOT_NAME.match(p.name)
        if not m or not p.is_file():
            continue
        try:
            day = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        candidates.append((day, p))
    if not candidates:
        return None
    day, path = max(candidates)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotStorageError(f"{path}: 스냅샷 파일을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise SnapshotStorageError(f"{path}: 스냅샷에 유효한 records 배열이 없습니다.")
    return day, list(data.get("records", []))


@dataclass(frozen=True, slots=True)
class Change:
    """같은 id 파일의 한 가지 속성 변경. name은 현재(새) 파일명, old/new는 바뀐 값."""

    id: str
    name: str
    old: str
    new: str


@dataclass(slots=True)
class Changes:
    """직전 스냅샷 대비 변경 묶음.

    같은 책 판정은 id만 쓴다(B1). 한 파일에 이름 변경과 폴더 이동이 동시에 일어나면
    renamed와 moved 양쪽에 각각 기록된다(B2).
    """

    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    renamed: list[Change] = field(default_factory=list)
    moved: list[Change] = field(default_factory=list)
    content_changed: list[Change] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.renamed or self.moved or self.content_changed)


def _record_sort_key(r: Record):
    return (normalize_nfc(r.get("folder_path")), normalize_nfc(r.get("name")), str(r.get("id", "")))


def _change_sort_key(c: Change):
    return (c.name, c.id)


def _content_change(old: Record, new: Record) -> tuple[str, str] | None:
    """내용 변경이면 (old, new) 표시값을, 아니면 None.

    SHA-256이 양쪽 다 있으면 SHA-256으로, 한쪽이라도 비어 있으면 크기(size_bytes)로 판단한다.
    """
    oh, nh = old.get("sha256") or "", new.get("sha256") or ""
    if oh and nh:
        return (oh, nh) if oh != nh else None
    os_, ns = old.get("size_bytes"), new.get("size_bytes")
    return (str(os_), str(ns)) if os_ != ns else None


def diff_snapshots(old_records: Iterable[Record], new_records: Iterable[Record]) -> Changes:
    """두 레코드 목록을 파일 id 기준으로 비교한다 (한글 파일명·폴더 경로는 NFC 정규화 기준으로 대조)."""
    old = {r["id"]: dict(r) for r in old_records}
    new = {r["id"]: dict(r) for r in new_records}
    ch = Changes()
    ch.added = sorted((new[i] for i in new.keys() - old.keys()), key=_record_sort_key)
    ch.removed = sorted((old[i] for i in old.keys() - new.keys()), key=_record_sort_key)
    for i in new.keys() & old.keys():
        o, n = old[i], new[i]
        old_name, name = normalize_nfc(o.get("name")), normalize_nfc(n.get("name"))
        old_folder, new_folder = normalize_nfc(o.get("folder_path")), normalize_nfc(n.get("folder_path"))
        if old_name != name:
            ch.renamed.append(Change(i, name, old_name, name))
        if old_folder != new_folder:
            ch.moved.append(Change(i, name, old_folder, new_folder))
        cc = _content_change(o, n)
        if cc:
            ch.content_changed.append(Change(i, name, cc[0], cc[1]))
    for lst in (ch.renamed, ch.moved, ch.content_changed):
        lst.sort(key=_change_sort_key)
    return ch


@dataclass(frozen=True, slots=True)
class RunResult:
    """record_run 실행 결과."""

    changes: Changes
    total: int
    first_run: bool
    snapshot_path: Path


def change_summary(run: RunResult) -> str:
    """최근 변경 한 줄 요약: '최초 등록 N권' / '변경 없음' / '추가 1 · 삭제 2 …'."""
    if run.first_run:
        return f"최초 등록 {run.total}권"
    ch = run.changes
    if ch.is_empty:
        return "변경 없음"
    parts = [
        ("추가", len(ch.added)),
        ("삭제", len(ch.removed)),
        ("이름 변경", len(ch.renamed)),
        ("폴더 이동", len(ch.moved)),
        ("내용 변경", len(ch.content_changed)),
    ]
    return " · ".join(f"{label} {n}" for label, n in parts if n)


def record_run(records: Iterable[Record], snapshots_dir: PathLike, now: datetime) -> RunResult:
    """한 번의 실행을 기록한다: 직전 스냅샷 읽기 → 비교 → 오늘 스냅샷 저장."""
    recs = [dict(r) for r in records]
    prior = load_latest_snapshot(snapshots_dir)
    if prior is None:
        changes = Changes()
    else:
        _, old = prior
        changes = diff_snapshots(old, recs)
    first_run = prior is None
    snap = save_snapshot(recs, snapshots_dir, now)
    return RunResult(changes, len(recs), first_run, snap)
