"""VirusTotal API v3 해시 평판 조회 클라이언트 및 로컬 캐시."""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib import request as urllib_request

from doctree.pdf_threat_audit.pdf_byte_inspector import (
    LocalPdfAudit,
    compute_sha256,
    discover_local_pdfs,
    inspect_pdf_bytes,
)
from doctree.runtime_env.boundary_errors import execute_json_http_get
from doctree.runtime_env.workspace_settings import PathLike, atomic_write_text, normalize_nfc

__all__ = [
    "VT_API_URL",
    "VerdictStatus",
    "VtVerdict",
    "audit_drive_records",
    "audit_local_pdfs",
    "check_hashes_with_vt",
    "load_vt_cache",
    "query_virustotal_hash",
    "save_vt_cache",
]

VT_API_URL = "https://www.virustotal.com/api/v3/files/{sha256}"


class VerdictStatus(StrEnum):
    """해시 평판 조회 상태 (StrEnum이므로 문자열 비교와 100% 호환)."""

    CLEAN = "clean"
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    NOT_FOUND = "not_found"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class VtVerdict:
    """해시 기반 위협 인텔리전스 조회 결과."""

    sha256: str
    status: VerdictStatus | str
    malicious: int = 0
    suspicious: int = 0
    harmless: int = 0
    undetected: int = 0
    detail: str = ""


def load_vt_cache(cache_path: PathLike) -> dict[str, VtVerdict]:
    p = Path(cache_path)
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out: dict[str, VtVerdict] = {}
        for sha, item in raw.items():
            if isinstance(item, dict):
                out[sha] = VtVerdict(
                    sha256=sha,
                    status=str(item.get("status", VerdictStatus.CLEAN)),
                    malicious=int(item.get("malicious", 0)),
                    suspicious=int(item.get("suspicious", 0)),
                    harmless=int(item.get("harmless", 0)),
                    undetected=int(item.get("undetected", 0)),
                    detail=str(item.get("detail", "")),
                )
        return out
    except (OSError, ValueError, TypeError):
        return {}


def save_vt_cache(cache_path: PathLike, cache: dict[str, VtVerdict]) -> None:
    payload = {
        sha: {
            "status": str(v.status),
            "malicious": v.malicious,
            "suspicious": v.suspicious,
            "harmless": v.harmless,
            "undetected": v.undetected,
            "detail": v.detail,
        }
        for sha, v in sorted(cache.items())
    }
    atomic_write_text(cache_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def query_virustotal_hash(sha256: str, api_key: str, timeout: float = 10.0) -> VtVerdict:
    """VirusTotal API v3에서 SHA-256 해시 평판을 조회한다 (파일 업로드 없음)."""
    body, code, detail = execute_json_http_get(
        VT_API_URL.format(sha256=sha256),
        headers={"x-apikey": api_key, "Accept": "application/json"},
        timeout=timeout,
        service_name="VirusTotal",
        urlopen=urllib_request.urlopen,
    )
    if body is None:
        status = VerdictStatus.NOT_FOUND if code == 404 else VerdictStatus.ERROR
        return VtVerdict(sha256=sha256, status=status, detail=detail)

    stats = (
        body.get("data", {})
        .get("attributes", {})
        .get("last_analysis_stats", {})
    )
    malicious = int(stats.get("malicious", 0))
    suspicious = int(stats.get("suspicious", 0))
    harmless = int(stats.get("harmless", 0))
    undetected = int(stats.get("undetected", 0))

    if malicious > 0:
        status = VerdictStatus.MALICIOUS
    elif suspicious > 0:
        status = VerdictStatus.SUSPICIOUS
    else:
        status = VerdictStatus.CLEAN

    return VtVerdict(
        sha256=sha256,
        status=status,
        malicious=malicious,
        suspicious=suspicious,
        harmless=harmless,
        undetected=undetected,
    )


def check_hashes_with_vt(
    sha256_list: Iterable[str],
    api_key: str | None,
    cache_path: PathLike | None = None,
) -> dict[str, VtVerdict]:
    """SHA-256 목록을 캐시 우선으로 조회하고, 미캐시 항목만 VirusTotal로 확인한다."""
    cache = load_vt_cache(cache_path) if cache_path else {}
    results: dict[str, VtVerdict] = {}
    dirty = False

    for sha in dict.fromkeys(s for s in sha256_list if s):
        if sha in cache and cache[sha].status != VerdictStatus.ERROR:
            results[sha] = cache[sha]
            continue
        if not api_key:
            continue
        verdict = query_virustotal_hash(sha, api_key)
        results[sha] = verdict
        if verdict.status != VerdictStatus.ERROR:
            cache[sha] = verdict
            dirty = True

    if dirty and cache_path:
        save_vt_cache(cache_path, cache)
    return results


def audit_drive_records(
    records: Iterable[dict],
    api_key: str | None,
    cache_path: PathLike | None = None,
) -> tuple[int, list[tuple[dict, VtVerdict]]]:
    """드라이브 스냅샷 레코드들의 SHA-256 해시를 VirusTotal(또는 로컬 캐시)로 점검한다."""
    recs = list(records)
    verdicts = check_hashes_with_vt(
        (r.get("sha256") or "" for r in recs),
        api_key=api_key,
        cache_path=cache_path,
    )
    flagged: list[tuple[dict, VtVerdict]] = []
    for rec in recs:
        sha = rec.get("sha256") or ""
        v = verdicts.get(sha)
        if v and v.status in (VerdictStatus.MALICIOUS, VerdictStatus.SUSPICIOUS):
            flagged.append((rec, v))
    return len(verdicts), flagged


def audit_local_pdfs(
    roots: Iterable[PathLike],
    api_key: str | None = None,
    cache_path: PathLike | None = None,
) -> list[LocalPdfAudit]:
    """로컬 PDF 파일들의 SHA-256, 헤더/EOF 무결성, 위험 태그(/JS, /Launch 등), 위협 평판을 점검한다."""
    pdfs = discover_local_pdfs(roots)
    partial: list[tuple[Path, str, bool, bool, tuple[str, ...]]] = []
    for pdf in pdfs:
        sha = compute_sha256(pdf)
        valid_header, valid_eof, tags = inspect_pdf_bytes(pdf)
        partial.append((pdf, sha, valid_header, valid_eof, tags))

    verdicts = check_hashes_with_vt(
        (item[1] for item in partial),
        api_key=api_key,
        cache_path=cache_path,
    )

    audits: list[LocalPdfAudit] = []
    for pdf, sha, valid_header, valid_eof, tags in partial:
        audits.append(
            LocalPdfAudit(
                path=normalize_nfc(pdf),
                sha256=sha,
                valid_pdf_header=valid_header,
                valid_pdf_eof=valid_eof,
                dangerous_tags=tags,
                vt_verdict=verdicts.get(sha),
            )
        )
    return audits
