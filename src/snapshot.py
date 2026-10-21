"""목록 스냅샷 저장과 변경 이력 누적 (KBI-4).

ledger/
  snapshots/YYYY-MM-DD.json   실행 시점의 PDF 목록 (같은 날 재실행 시 덮어씀)
  변경이력.md                  실행마다 맨 위에 블록을 추가하는 누적 이력
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

PathLike = Union[str, Path]
Record = dict

SNAPSHOT_DIRNAME = "snapshots"
CHANGELOG_FILENAME = "변경이력.md"
CHANGELOG_HEADER = "# 변경 이력\n\n"
_SNAPSHOT_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")


def _snapshot_dir(ledger_dir: PathLike) -> Path:
    return Path(ledger_dir) / SNAPSHOT_DIRNAME


def save_snapshot(records: Iterable[Record], ledger_dir: PathLike, now: datetime) -> Path:
    """records를 ledger_dir/snapshots/<now의 날짜>.json으로 저장하고 경로를 돌려준다.

    같은 날짜 파일이 있으면 덮어쓴다. 레코드는 id 순으로, 키는 사전순으로 정렬해
    같은 입력이면 같은 바이트가 나오게 한다(UTF-8, ensure_ascii=False).
    """
    recs = sorted((dict(r) for r in records), key=lambda r: str(r.get("id", "")))
    payload = {"taken_at": now.isoformat(), "count": len(recs), "records": recs}
    d = _snapshot_dir(ledger_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.date().isoformat()}.json"
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def load_latest_snapshot(ledger_dir: PathLike) -> Optional[Tuple[date, List[Record]]]:
    """ledger_dir/snapshots에서 날짜가 가장 최근인 스냅샷의 (날짜, records)를 돌려준다.

    없으면 None. 'YYYY-MM-DD.json' 형식(유효한 날짜)이 아닌 파일은 무시한다.
    오늘 날짜 파일도 후보이므로, 이번 실행분을 저장하기 전에 호출해야 한다(B4).
    """
    d = _snapshot_dir(ledger_dir)
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
    data = json.loads(path.read_text(encoding="utf-8"))
    return day, list(data.get("records", []))


@dataclass(frozen=True)
class Change:
    """같은 id 파일의 한 가지 속성 변경. name은 현재(새) 파일명, old/new는 바뀐 값."""

    id: str
    name: str
    old: str
    new: str


@dataclass
class Changes:
    """직전 스냅샷 대비 변경 묶음.

    같은 책 판정은 id만 쓴다(B1). 한 파일에 이름 변경과 폴더 이동이 함께 일어나면
    renamed와 moved 양쪽에 각각 기록된다(B2).
    """

    added: List[Record] = field(default_factory=list)
    removed: List[Record] = field(default_factory=list)
    renamed: List[Change] = field(default_factory=list)
    moved: List[Change] = field(default_factory=list)
    content_changed: List[Change] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.renamed or self.moved or self.content_changed)


def _record_sort_key(r: Record):
    return (str(r.get("folder_path", "")), str(r.get("name", "")), str(r.get("id", "")))


def _change_sort_key(c: Change):
    return (c.name, c.id)


def _content_change(old: Record, new: Record) -> Optional[Tuple[str, str]]:
    """내용 변경이면 (old, new) 표시값을, 아니면 None.

    MD5가 양쪽 다 있으면 MD5로, 한쪽이라도 비어 있으면 크기(size_bytes)로 판단한다.
    """
    om, nm = old.get("md5") or "", new.get("md5") or ""
    if om and nm:
        return (om, nm) if om != nm else None
    os_, ns = old.get("size_bytes"), new.get("size_bytes")
    return (str(os_), str(ns)) if os_ != ns else None


def diff_snapshots(old_records: Iterable[Record], new_records: Iterable[Record]) -> Changes:
    """두 레코드 목록을 파일 id 기준으로 비교한다."""
    old = {r["id"]: r for r in old_records}
    new = {r["id"]: r for r in new_records}
    ch = Changes()
    ch.added = sorted((new[i] for i in new.keys() - old.keys()), key=_record_sort_key)
    ch.removed = sorted((old[i] for i in old.keys() - new.keys()), key=_record_sort_key)
    for i in new.keys() & old.keys():
        o, n = old[i], new[i]
        name = str(n.get("name", ""))
        if o.get("name") != n.get("name"):
            ch.renamed.append(Change(i, name, str(o.get("name", "")), name))
        if o.get("folder_path") != n.get("folder_path"):
            ch.moved.append(Change(i, name, str(o.get("folder_path", "")), str(n.get("folder_path", ""))))
        cc = _content_change(o, n)
        if cc:
            ch.content_changed.append(Change(i, name, cc[0], cc[1]))
    for lst in (ch.renamed, ch.moved, ch.content_changed):
        lst.sort(key=_change_sort_key)
    return ch


def _display_path(r: Record) -> str:
    folder = str(r.get("folder_path") or "")
    name = str(r.get("name") or "")
    return f"{folder}/{name}" if folder else name


def render_changelog_block(run_at: datetime, changes: Changes, total: int, first_run: bool = False) -> str:
    """한 번의 실행을 나타내는 변경 이력 블록(마크다운)을 만든다. 끝은 줄바꿈 하나.

    first_run이면 파일별 변경 없이 '최초 등록 N권'만 쓴다(AC #4).
    """
    lines = [f"## {run_at.strftime('%Y-%m-%d %H:%M')} · 총 {total}권", ""]
    if first_run:
        lines.append(f"- 최초 등록 {total}권")
    elif changes.is_empty:
        lines.append("- 변경 없음")
    else:
        groups = [
            ("추가", [f"- {_display_path(r)}" for r in changes.added]),
            ("삭제", [f"- {_display_path(r)}" for r in changes.removed]),
            ("이름 변경", [f"- {c.old} → {c.new}" for c in changes.renamed]),
            ("폴더 이동", [f"- {c.name}: {c.old or '(루트)'} → {c.new or '(루트)'}" for c in changes.moved]),
            ("내용 변경", [f"- {c.name} ({c.old} → {c.new})" for c in changes.content_changed]),
        ]
        first = True
        for title, items in groups:
            if not items:
                continue
            if not first:
                lines.append("")
            lines.append(f"### {title} ({len(items)})")
            lines.extend(items)
            first = False
    return "\n".join(lines) + "\n"


def append_changelog(
    ledger_dir: PathLike, run_at: datetime, changes: Changes, total: int, first_run: bool = False
) -> Path:
    """ledger_dir/변경이력.md의 제목 바로 아래에 이번 실행 블록을 끼워 넣는다.

    기존 내용은 한 바이트도 고치지 않고 새 블록 아래에 그대로 둔다(B3).
    파일이 고정 제목으로 시작하지 않으면(손으로 고친 경우 등) 제목+새 블록을 앞에 붙이고
    기존 내용 전체를 그 아래에 보존한다.
    """
    path = Path(ledger_dir) / CHANGELOG_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    header = CHANGELOG_HEADER.encode("utf-8")
    block = render_changelog_block(run_at, changes, total, first_run).encode("utf-8")
    existing = path.read_bytes() if path.exists() else b""
    if not existing:
        data = header + block
    else:
        rest = existing[len(header):] if existing.startswith(header) else existing
        data = header + block + b"\n" + rest
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


@dataclass
class RunResult:
    """record_run 결과. baseline_date는 비교 기준 스냅샷 날짜(최초 실행이면 None)."""

    changes: Changes
    total: int
    first_run: bool
    baseline_date: Optional[date]
    snapshot_path: Path
    changelog_path: Path


def record_run(records: Iterable[Record], ledger_dir: PathLike, now: datetime) -> RunResult:
    """한 번의 실행을 기록한다: 직전 스냅샷 읽기 → 비교 → 이력 블록 추가 → 스냅샷 저장.

    비교 기준은 저장 전에 읽으므로 같은 날 앞선 실행이 남긴 오늘 스냅샷도 기준이 된다(B4).
    직전 스냅샷이 없으면 '최초 등록 N권'으로 기록한다(AC #4).
    """
    recs = list(records)
    prior = load_latest_snapshot(ledger_dir)
    if prior is None:
        changes, baseline = Changes(), None
    else:
        baseline, old = prior
        changes = diff_snapshots(old, recs)
    first_run = prior is None
    changelog = append_changelog(ledger_dir, now, changes, len(recs), first_run=first_run)
    snap = save_snapshot(recs, ledger_dir, now)
    return RunResult(changes, len(recs), first_run, baseline, snap, changelog)
