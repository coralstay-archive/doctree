"""도서 목록 대장(ledger/도서목록.md) 렌더링 (KBI-6).

render_ledger는 순수 함수다: 입력만 읽어 마크다운 문자열을 돌려주고 파일·API를 건드리지 않는다.
"""
import re
from datetime import datetime
from typing import Dict, List, Optional

from src.snapshot import RunResult

Record = Dict
Groups = "OrderedDict[str, OrderedDict[str, List[dict]]]"

_PDF_SUFFIX = re.compile(r"\.pdf$", re.IGNORECASE)


def display_title(name: str) -> str:
    """파일명 → 표시 제목: 끝의 .pdf(대소문자 무시) 제거, 하이픈을 공백으로."""
    return _PDF_SUFFIX.sub("", name or "").replace("-", " ")


def format_timestamp(now: datetime) -> str:
    """'2026-10-21 22:30 KST (UTC+09:00)' 형식. 시간대 정보가 없으면 시각만."""
    base = now.strftime("%Y-%m-%d %H:%M")
    offset = now.utcoffset()
    if offset is None:
        return base
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hh, mm = divmod(abs(total), 60)
    utc = f"UTC{sign}{hh:02d}:{mm:02d}"
    name = now.tzname() or ""
    if name and name != utc and not name.startswith(("+", "-", "UTC")):
        return f"{base} {name} ({utc})"
    return f"{base} ({utc})"


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


def render_ledger(
    *,
    groups: Groups,
    warnings: List,
    run: RunResult,
    account: Optional[dict],
    now: datetime,
    categories=None,
    changelog_link: str = "변경이력.md",
) -> str:
    lines: List[str] = ["# 구글 드라이브 도서 목록", "", f"- 기준 시각: {format_timestamp(now)}", ""]
    for cat, subs in groups.items():
        recs = [r for items in subs.values() for r in items]
        if not recs:
            continue
        lines.append(f"## {cat}")
        lines.extend(f"- {display_title(r.get('name', ''))}" for r in recs)
        lines.append("")
    lines += ["## 최근 변경", "", f"- {change_summary(run)}", ""]
    return "\n".join(lines)
