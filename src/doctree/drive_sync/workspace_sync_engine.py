"""구글 드라이브 스냅샷(SHA-256) ⟷ 로컬 워크스페이스 contents/(SHA-256) 고속 스캔·3-Way 비교 및 도서 가져오기(pull) 엔진."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doctree.pdf_threat_audit.pdf_byte_inspector import compute_sha256, discover_local_pdfs
from doctree.runtime_env.boundary_errors import (
    ClassificationError,
    DriveListError,
    SnapshotStorageError,
)
from doctree.runtime_env.workspace_settings import (
    PathLike,
    atomic_write_bytes,
    atomic_write_text,
    normalize_nfc,
)

__all__ = [
    "LocalPdfEntry",
    "MatchedPdfGroup",
    "SyncComparisonResult",
    "compare_drive_and_local",
    "discover_workspace_content_dirs",
    "format_sync_report",
    "load_local_contents_cache",
    "pull_drive_pdf_to_project",
    "resolve_drive_record_for_pull",
    "save_local_contents_cache",
    "scan_workspace_contents",
]

Record = Mapping[str, Any]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class LocalPdfEntry:
    """로컬 워크스페이스 프로젝트의 contents/ 하위 PDF 메타데이터 및 SHA-256 레코드."""

    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class MatchedPdfGroup:
    """드라이브 스냅샷과 로컬 contents/ 양쪽 모두에 존재하는 동일 SHA-256 도서 묶음."""

    sha256: str
    drive_records: tuple[dict, ...]
    local_entries: tuple[LocalPdfEntry, ...]


@dataclass(frozen=True, slots=True)
class SyncComparisonResult:
    """드라이브 ⟷ 로컬 contents/ 3-Way 정합성 비교 결과."""

    drive_only: tuple[dict, ...]
    local_only: tuple[LocalPdfEntry, ...]
    matched: tuple[MatchedPdfGroup, ...]
    cache_hits: int
    recomputed: int


def load_local_contents_cache(cache_path: PathLike | None) -> dict[str, dict]:
    """로컬 contents/ 해시 캐시(snapshots/.local_contents_cache.json)를 로드한다."""
    if not cache_path:
        return {}
    p = Path(cache_path)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for key, val in raw.items():
        if isinstance(key, str) and isinstance(val, dict):
            sha = str(val.get("sha256", "")).lower()
            size = val.get("size_bytes")
            mtime_ns = val.get("mtime_ns")
            if (
                _SHA256_RE.match(sha)
                and type(size) is int
                and type(mtime_ns) is int
            ):
                out[normalize_nfc(key)] = {
                    "size_bytes": size,
                    "mtime_ns": mtime_ns,
                    "sha256": sha,
                }
    return out


def save_local_contents_cache(cache_path: PathLike, cache: Mapping[str, dict]) -> Path:
    """로컬 contents/ 해시 캐시를 임시 파일(.tmp) + replace로 원자적으로 저장한다."""
    target = Path(cache_path)
    payload = {normalize_nfc(k): dict(v) for k, v in sorted(cache.items())}
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        return atomic_write_text(target, text)
    except OSError as exc:
        raise SnapshotStorageError(f"{target}: 로컬 해시 캐시 저장 실패: {exc}") from exc


def discover_workspace_content_dirs(workspace_dir: PathLike) -> list[Path]:
    """워크스페이스 하위 프로젝트들의 contents/ 디렉터리 목록을 정렬해 반환한다."""
    ws = Path(workspace_dir).resolve()
    if not ws.is_dir():
        return []
    return sorted(
        p / "contents"
        for p in ws.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "contents").is_dir()
    )


def scan_workspace_contents(
    workspace_dir: PathLike,
    *,
    cache_path: PathLike | None = None,
) -> tuple[list[LocalPdfEntry], int, int]:
    """워크스페이스 하위 프로젝트들의 contents/ 폴더를 고속 스캔하여 (LocalPdfEntry 목록, 캐시 적중 수, 재계산 수)를 반환한다."""
    ws = Path(workspace_dir).resolve()
    content_roots = discover_workspace_content_dirs(ws)
    if not content_roots:
        return [], 0, 0

    pdf_paths = discover_local_pdfs(content_roots)
    prior_cache = load_local_contents_cache(cache_path)
    next_cache: dict[str, dict] = {}
    entries: list[LocalPdfEntry] = []
    cache_hits = 0
    recomputed = 0

    for pdf_path in pdf_paths:
        stat = pdf_path.stat()
        rel_path = normalize_nfc(pdf_path.resolve().relative_to(ws).as_posix())
        size_bytes = int(stat.st_size)
        mtime_ns = int(stat.st_mtime_ns)

        cached = prior_cache.get(rel_path)
        if (
            cached is not None
            and cached["size_bytes"] == size_bytes
            and cached["mtime_ns"] == mtime_ns
        ):
            sha256 = cached["sha256"]
            cache_hits += 1
        else:
            sha256 = compute_sha256(pdf_path)
            recomputed += 1

        entry = LocalPdfEntry(
            relative_path=rel_path,
            sha256=sha256,
        )
        entries.append(entry)
        next_cache[rel_path] = {
            "size_bytes": size_bytes,
            "mtime_ns": mtime_ns,
            "sha256": sha256,
        }

    entries.sort(key=lambda e: e.relative_path)
    if cache_path:
        save_local_contents_cache(cache_path, next_cache)
    return entries, cache_hits, recomputed


def compare_drive_and_local(
    drive_records: Iterable[Record],
    local_entries: Iterable[LocalPdfEntry],
    *,
    cache_hits: int = 0,
    recomputed: int = 0,
) -> SyncComparisonResult:
    """드라이브 스냅샷 레코드와 로컬 PDF 엔트리를 SHA-256 해시 기준으로 3-Way 대조한다."""
    drive_by_sha: dict[str, list[dict]] = {}
    drive_without_sha: list[dict] = []

    for raw in drive_records:
        rec = {
            **dict(raw),
            "name": normalize_nfc(raw.get("name")),
            "folder_path": normalize_nfc(raw.get("folder_path")),
        }
        sha = str(rec.get("sha256") or "").strip().lower()
        if sha:
            drive_by_sha.setdefault(sha, []).append(rec)
        else:
            drive_without_sha.append(rec)

    local_by_sha: dict[str, list[LocalPdfEntry]] = {}
    for entry in local_entries:
        local_by_sha.setdefault(entry.sha256.lower(), []).append(entry)

    drive_shas = set(drive_by_sha.keys())
    local_shas = set(local_by_sha.keys())

    drive_only: list[dict] = list(drive_without_sha)
    for sha in drive_shas - local_shas:
        drive_only.extend(drive_by_sha[sha])
    drive_only.sort(key=lambda r: (r["folder_path"], r["name"], str(r.get("id", ""))))

    local_only: list[LocalPdfEntry] = []
    for sha in local_shas - drive_shas:
        local_only.extend(local_by_sha[sha])
    local_only.sort(key=lambda e: e.relative_path)

    matched: list[MatchedPdfGroup] = []
    for sha in drive_shas & local_shas:
        d_recs = sorted(
            drive_by_sha[sha],
            key=lambda r: (r["folder_path"], r["name"], str(r.get("id", ""))),
        )
        l_ents = sorted(local_by_sha[sha], key=lambda e: e.relative_path)
        matched.append(
            MatchedPdfGroup(
                sha256=sha,
                drive_records=tuple(d_recs),
                local_entries=tuple(l_ents),
            )
        )
    matched.sort(key=lambda g: (g.drive_records[0]["name"], g.sha256))

    return SyncComparisonResult(
        drive_only=tuple(drive_only),
        local_only=tuple(local_only),
        matched=tuple(matched),
        cache_hits=cache_hits,
        recomputed=recomputed,
    )


def format_sync_report(result: SyncComparisonResult, total_drive: int, total_local: int) -> str:
    """3-Way 동기화 비교 결과를 터미널 출력용 문자열로 포맷한다."""
    lines = [
        (
            f"🔄 3-Way 동기화 현황: 드라이브 스냅샷 {total_drive}권 · "
            f"로컬 {total_local}개 (캐시 적중 {result.cache_hits} · 재계산 {result.recomputed}) ➔ "
            f"양쪽 일치 {len(result.matched)}권 · 드라이브 전용 {len(result.drive_only)}권 · 로컬 전용 {len(result.local_only)}개"
        ),
        "",
        f"[양쪽 일치 (Matched: {len(result.matched)}권)]",
    ]
    if result.matched:
        for group in result.matched:
            d_name = group.drive_records[0]["name"]
            locs = ", ".join(e.relative_path for e in group.local_entries)
            lines.append(f"- {d_name} ⟷ {locs} (sha256={group.sha256[:12]}...)")
    else:
        lines.append("양쪽 일치하는 도서가 없습니다.")

    lines.append("")
    lines.append(f"[드라이브에만 있는 것 (Drive Only: {len(result.drive_only)}권)]")
    if result.drive_only:
        for rec in result.drive_only:
            folder = rec["folder_path"]
            loc = f"{folder}/{rec['name']}" if folder else rec["name"]
            lines.append(f"- {rec['name']} (id={rec.get('id', '')}, path={loc})")
    else:
        lines.append("드라이브 전용 도서가 없습니다.")

    lines.append("")
    lines.append(f"[로컬에만 있는 것 (Local Only: {len(result.local_only)}개)]")
    if result.local_only:
        for entry in result.local_only:
            lines.append(f"- {entry.relative_path} (sha256={entry.sha256[:12]}...)")
    else:
        lines.append("로컬 전용 도서가 없습니다.")

    return "\n".join(lines) + "\n"


def resolve_drive_record_for_pull(records: Iterable[Record], query: str) -> dict:
    """사용자 질의(file_id, sha256, 파일명 또는 제목 키워드)로 스냅샷에서 단일 도서 레코드를 찾는다."""
    norm_q = normalize_nfc(query).strip()
    if not norm_q:
        raise ClassificationError("가져올 도서 식별자(파일 ID, SHA-256 또는 도서명)를 지정하세요.")

    recs = [
        {
            **dict(r),
            "name": normalize_nfc(r.get("name")),
            "folder_path": normalize_nfc(r.get("folder_path")),
        }
        for r in records
    ]

    for rec in recs:
        if str(rec.get("id", "")) == norm_q:
            return rec
        if str(rec.get("sha256", "")).lower() == norm_q.lower() and norm_q:
            return rec

    q_lower = norm_q.lower()
    q_pdf = q_lower if q_lower.endswith(".pdf") else f"{q_lower}.pdf"
    exact_name_matches = [
        r for r in recs if r["name"].lower() in (q_lower, q_pdf)
    ]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]
    if len(exact_name_matches) > 1:
        ids = ", ".join(str(r.get("id", "")) for r in exact_name_matches)
        raise ClassificationError(
            f"동일한 이름의 도서가 {len(exact_name_matches)}권 있습니다. 파일 ID로 지정하세요: {ids}"
        )

    sub_matches = [r for r in recs if q_lower in r["name"].lower()]
    if len(sub_matches) == 1:
        return sub_matches[0]
    if len(sub_matches) > 1:
        candidates = ", ".join(f"{r['name']}({r.get('id', '')})" for r in sub_matches[:5])
        raise ClassificationError(
            f"검색어 {norm_q!r}와 일치하는 도서가 {len(sub_matches)}권 있습니다. 더 구체적으로 지정하세요: {candidates}"
        )
    raise ClassificationError(f"스냅샷에서 {norm_q!r} 도서를 찾을 수 없습니다.")


def pull_drive_pdf_to_project(
    drive: Any,
    records: Iterable[Record],
    query: str,
    project: str,
    *,
    workspace_dir: PathLike,
    output_name: str | None = None,
    cache_path: PathLike | None = None,
) -> tuple[dict, Path]:
    """스냅샷에서 도서를 찾아 지정한 로컬 프로젝트의 contents/ 폴더로 내려받고 해시 캐시를 갱신한다."""
    rec = resolve_drive_record_for_pull(records, query)
    ws = Path(workspace_dir).resolve()
    proj_norm = normalize_nfc(project).strip().strip("/")
    if not proj_norm or ".." in Path(proj_norm).parts:
        raise ClassificationError(f"유효하지 않은 대상 프로젝트 이름입니다: {project!r}")

    target_contents_dir = ws / proj_norm / "contents"
    raw_filename = normalize_nfc(output_name or rec["name"]).strip()
    safe_filename = raw_filename.replace("/", "-")
    if not safe_filename.lower().endswith(".pdf"):
        safe_filename = f"{safe_filename}.pdf"

    dest_path = target_contents_dir / safe_filename
    file_id = str(rec["id"])
    expected_sha256 = str(rec.get("sha256") or "").strip().lower()

    if not getattr(drive, "service", None):
        raise DriveListError("구글 드라이브 서비스가 활성화되지 않았습니다 (자격 증명 파일 확인 필요).")
    try:
        raw_bytes = drive.service.files().get_media(fileId=file_id).execute()
        data = bytes(raw_bytes)
    except Exception as exc:
        raise DriveListError(f"구글 드라이브 파일 다운로드 실패 ({file_id}): {exc}") from exc

    if expected_sha256:
        actual_sha = hashlib.sha256(data).hexdigest()
        if actual_sha != expected_sha256:
            raise DriveListError(
                f"다운로드한 파일의 SHA-256 해시가 스냅샷과 일치하지 않습니다 ({actual_sha} != {expected_sha256})."
            )

    atomic_write_bytes(dest_path, data)

    if cache_path:
        scan_workspace_contents(ws, cache_path=cache_path)

    return rec, dest_path
