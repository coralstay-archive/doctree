"""목록 스냅샷 저장과 변경 이력 누적 (KBI-4).

ledger/
  snapshots/YYYY-MM-DD.json   실행 시점의 PDF 목록 (같은 날 재실행 시 덮어씀)
  변경이력.md                  실행마다 맨 위에 블록을 추가하는 누적 이력
"""
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

PathLike = Union[str, Path]
Record = dict

SNAPSHOT_DIRNAME = "snapshots"
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
