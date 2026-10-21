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


# ---------- 서식 도우미 ----------

def mb(size_bytes: int) -> str:
    """B1: 개별 용량은 MB(10^6) 소수 1자리."""
    return f"{(size_bytes or 0) / 1e6:.1f} MB"


def gb(size_bytes: int) -> str:
    """B1: 합계는 GB(10^9) 소수 1자리."""
    return f"{(size_bytes or 0) / 1e9:.1f} GB"


def _one_line(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", str(text or ""))


def cell(text: str) -> str:
    r"""B3: 표 셀용 — 줄바꿈은 공백으로, '|'는 '\|'로 이스케이프."""
    return _one_line(text).replace("|", "\\|")


def code(text: str) -> str:
    """인라인 코드 스팬. 내용의 가장 긴 백틱 연속보다 긴 펜스를 쓰고, 백틱이 있으면 양끝에 공백을 둔다."""
    text = _one_line(text)
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if longest else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def code_cell(text: str) -> str:
    """표 셀 안의 코드 스팬 (GFM 표는 코드 스팬 안에서도 '|'를 열 구분자로 보므로 이스케이프)."""
    return code(text).replace("|", "\\|")


def file_path(rec: Record) -> str:
    folder = rec.get("folder_path") or ""
    name = rec.get("name") or ""
    return f"{folder}/{name}" if folder else name


def _table(header: List[str], align: List[str], rows: List[List[str]]) -> List[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join(align) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


WARNING_LABELS = {
    "exact_duplicate": ("완전 중복", "MD5가 같은 파일 묶음입니다. 하나만 남기면 됩니다."),
    "same_title_different_content": ("동명 다른 파일", "제목은 같지만 내용(MD5)이 다른 파일 묶음입니다. 판본·스캔본 차이인지 확인하세요."),
    "missing_pdf_extension": (".pdf 확장자 누락", "파일명이 .pdf로 끝나지 않습니다."),
    "copy_of_prefix": ("Copy of 접두어", "파일명이 'Copy of '로 시작합니다. 사본 정리 대상인지 확인하세요."),
    "surrounding_whitespace": ("파일명 앞뒤 공백", "파일명 앞이나 뒤에 공백이 있습니다."),
}
WARNING_NOTES = {
    "exact_duplicate": "⚠️ 완전 중복",
    "same_title_different_content": "⚠️ 동명 다른 파일",
    "missing_pdf_extension": "⚠️ .pdf 확장자 없음",
    "copy_of_prefix": "⚠️ Copy of 접두어",
    "surrounding_whitespace": "⚠️ 앞뒤 공백",
}


def _nonempty(groups: Groups):
    """빈 세부분야·빈 분야를 뺀 (분야, [(세부분야, 레코드)]) 목록."""
    out = []
    for cat, subs in groups.items():
        kept = [(sub, recs) for sub, recs in subs.items() if recs]
        if kept:
            out.append((cat, kept))
    return out


# ---------- 절 ----------

def _storage(account: Optional[dict]) -> List[str]:
    lines = ["## 스토리지 현황", ""]
    if not account:
        return lines + ["- 조회 실패 (계정·스토리지 정보를 가져오지 못했습니다)", ""]
    limit = account.get("limit_gb")
    usage = account.get("usage_gb", 0)
    total = (f"{float(usage):.1f} GB / {float(limit):.1f} GB ({account.get('usage_percent', 0.0)}%)"
             if limit else f"{float(usage):.1f} GB (한도 없음)")
    rows = [
        ["계정", cell(f"{account.get('name', '')} ({account.get('email', '')})")],
        ["전체 사용량", cell(total)],
        ["드라이브 사용량", cell(f"{float(account.get('drive_usage_gb', 0)):.1f} GB")],
    ]
    return lines + _table(["항목", "값"], ["---", "---"], rows) + [""]


def _summary(records: List[Record], unclassified: int, warnings: List) -> List[str]:
    total = sum(r.get("size_bytes") or 0 for r in records)
    return [
        "## 요약", "",
        f"- 파일 {len(records)}개 · 총 {gb(total)}",
        f"- 분류 {len(records) - unclassified}권 · 미분류 {unclassified}권",
        f"- 경고 {len(warnings)}건",
        "",
    ]


def _folders(records: List[Record]) -> List[str]:
    stats: Dict[str, List[int]] = {}
    for r in records:
        st = stats.setdefault(r.get("folder_path") or "", [0, 0])
        st[0] += 1
        st[1] += r.get("size_bytes") or 0
    rows = [[code_cell(f) if f else "(루트)", str(n), gb(size)] for f, (n, size) in sorted(stats.items())]
    return ["## 폴더 구성", ""] + _table(["폴더", "파일 수", "용량"], ["---", "---:", "---:"], rows) + [""]


def _category_table(cats) -> List[str]:
    rows = []
    for cat, subs in cats:
        recs = [r for _, rs in subs for r in rs]
        rows.append([cell(cat), str(len(recs)), gb(sum(r.get("size_bytes") or 0 for r in recs))])
    return ["## 분야별 권수·용량", ""] + _table(["분야", "권수", "용량"], ["---", "---:", "---:"], rows) + [""]


def _tree(cats) -> List[str]:
    body = ["도서 목록"]
    for ci, (cat, subs) in enumerate(cats):
        last_cat = ci == len(cats) - 1
        body.append(f"{'└── ' if last_cat else '├── '}{_one_line(cat)}")
        p1 = "    " if last_cat else "│   "
        for si, (sub, recs) in enumerate(subs):
            last_sub = si == len(subs) - 1
            body.append(f"{p1}{'└── ' if last_sub else '├── '}{_one_line(sub)} ({len(recs)})")
            p2 = p1 + ("    " if last_sub else "│   ")
            for ri, r in enumerate(recs):
                branch = "└── " if ri == len(recs) - 1 else "├── "
                body.append(f"{p2}{branch}{_one_line(display_title(r.get('name', '')))}")
    longest = max((len(m) for line in body for m in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest + 1)
    return ["## 분류 트리", "", f"{fence}text"] + body + [fence, ""]


def _title_cell(rec: Record) -> str:
    return cell(display_title(rec.get("name", "")))


def _details(cats, categories, file_warnings: Dict[str, List[str]]) -> List[str]:
    lines = ["## 분야별 상세", ""]
    for cat, subs in cats:
        lines += [f"### {_one_line(cat)}", ""]
        for sub, recs in subs:
            rows = []
            for r in recs:
                notes = []
                note = categories.note(r.get("name") or "") if categories is not None else None
                if note:
                    notes.append(note)
                notes += file_warnings.get(r.get("id"), [])
                rows.append([_title_cell(r), mb(r.get("size_bytes") or 0), code_cell(file_path(r)),
                             cell(" · ".join(notes))])
            lines += [f"#### {_one_line(sub)}", ""]
            lines += _table(["제목", "용량", "경로", "비고"], ["---", "---:", "---", "---"], rows) + [""]
    return lines


def _warnings(warnings: List) -> List[str]:
    lines = ["## 경고", ""]
    if not warnings:
        return lines + ["- 경고 없음", ""]
    by_kind: Dict[str, List] = {}
    for w in warnings:
        by_kind.setdefault(w.kind, []).append(w)
    for kind, ws in by_kind.items():
        label, desc = WARNING_LABELS.get(kind, (kind, ""))
        lines += [f"### {label} ({len(ws)})", ""]
        if desc:
            lines += [desc, ""]
        for w in ws:
            lines.append("- " + ", ".join(f"{code(file_path(r))} ({mb(r.get('size_bytes') or 0)})" for r in w.files))
        lines.append("")
    return lines


def _recent(run: RunResult, changelog_link: str) -> List[str]:
    base = run.baseline_date.isoformat() if run.baseline_date else "없음 (최초 실행)"
    return [
        "## 최근 변경", "",
        f"- 비교 기준 스냅샷: {base}",
        f"- {change_summary(run)}",
        f"- 자세한 내용: [{changelog_link}]({changelog_link})",
        "",
    ]


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
    """대장 마크다운 전체를 만든다 (순수 함수).

    groups는 classify() 결과, warnings는 run_checks() 결과, run은 record_run() 결과,
    account는 get_account_and_quota() 결과(None이면 '조회 실패'). categories가 있으면 비고에 분류 비고를 넣는다.
    빈 세부분야·빈 분야(미분류 포함)는 표·트리·상세에서 뺀다.
    """
    from src.classify import UNCLASSIFIED

    records = [r for subs in groups.values() for recs in subs.values() for r in recs]
    unclassified = len(groups.get(UNCLASSIFIED[0], {}).get(UNCLASSIFIED[1], []))
    cats = _nonempty(groups)
    file_warnings: Dict[str, List[str]] = {}
    for w in warnings:
        for r in w.files:
            notes = file_warnings.setdefault(r.get("id"), [])
            label = WARNING_NOTES.get(w.kind, w.kind)
            if label not in notes:
                notes.append(label)

    lines: List[str] = [
        "# 구글 드라이브 도서 목록", "",
        f"- 기준 시각: {format_timestamp(now)}",
        "- `doctree update`가 생성한 문서입니다. 직접 고치지 말고 `config/categories.yaml`을 고친 뒤 다시 실행하세요.",
        "",
    ]
    lines += _storage(account)
    lines += _summary(records, unclassified, warnings)
    lines += _folders(records)
    lines += _category_table(cats)
    lines += _tree(cats)
    lines += _details(cats, categories, file_warnings)
    lines += _warnings(warnings)
    lines += _recent(run, changelog_link)
    return "\n".join(lines).rstrip("\n") + "\n"
