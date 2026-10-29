"""로컬 PDF 정적 무결성 및 위험 태그(/JavaScript, /Launch 등) 바이트 검사기."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from doctree.runtime_env.workspace_settings import PathLike

__all__ = [
    "DANGEROUS_PDF_TAGS",
    "LocalPdfAudit",
    "compute_sha256",
    "discover_local_pdfs",
    "inspect_pdf_bytes",
]

if TYPE_CHECKING:
    from doctree.pdf_threat_audit.threat_intel_client import VtVerdict

# PDF 사전(Dictionary) 내부에서 자동 실행·스크립트·외부 명령 실행에 악용되는 위험 PDF 객체 패턴
DANGEROUS_PDF_TAGS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(rb"/JavaScript(?![A-Za-z0-9_])"), "/JavaScript"),
    (re.compile(rb"/S\s*/JS(?![A-Za-z0-9_])"), "/JS"),
    (re.compile(rb"/Launch(?![A-Za-z0-9_])"), "/Launch"),
    (re.compile(rb"/EmbeddedFiles(?![A-Za-z0-9_])"), "/EmbeddedFiles"),
    (re.compile(rb"/RichMedia(?![A-Za-z0-9_])"), "/RichMedia"),
    (re.compile(rb"/XFA(?![A-Za-z0-9_])"), "/XFA"),
)


@dataclass(frozen=True, slots=True)
class LocalPdfAudit:
    """로컬 PDF 파일 1개의 정적 보안 및 무결성 점검 결과."""

    path: str
    sha256: str
    valid_pdf_header: bool
    valid_pdf_eof: bool
    dangerous_tags: tuple[str, ...] = ()
    vt_verdict: VtVerdict | None = None

    @property
    def is_safe(self) -> bool:
        if not self.valid_pdf_header or not self.valid_pdf_eof:
            return False
        if self.dangerous_tags:
            return False
        return not (self.vt_verdict and self.vt_verdict.status in ("malicious", "suspicious"))


def compute_sha256(path: PathLike, chunk_size: int = 1024 * 1024) -> str:
    """로컬 파일의 SHA-256 해시(64자리 소문자 hex)를 계산한다."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def inspect_pdf_bytes(path: PathLike) -> tuple[bool, bool, tuple[str, ...]]:
    """로컬 PDF 바이트를 스캔해 (%PDF- 헤더 유무, %%EOF 유무, 위험 태그 목록)을 반환한다."""
    p = Path(path)
    size = p.stat().st_size
    if size < 8:
        return False, False, ()

    with p.open("rb") as f:
        head = f.read(1024)
        valid_header = b"%PDF-" in head

        tail_len = min(size, 65536)
        f.seek(size - tail_len)
        tail = f.read(tail_len)
        valid_eof = b"%%EOF" in tail

        found_tags = set()
        f.seek(0)
        prev = b""
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            window = prev + chunk
            for pattern, label in DANGEROUS_PDF_TAGS:
                if label not in found_tags and pattern.search(window):
                    found_tags.add(label)
            prev = chunk[-64:]

    ordered_tags = tuple(label for _, label in DANGEROUS_PDF_TAGS if label in found_tags)
    return valid_header, valid_eof, ordered_tags


def discover_local_pdfs(roots: Iterable[PathLike]) -> list[Path]:
    """지정된 루트(또는 워크스페이스 하위 contents/ 폴더)에서 모든 로컬 PDF를 찾는다."""
    pdfs: list[Path] = []
    seen = set()
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        if base.is_file() and base.suffix.lower() == ".pdf":
            resolved = base.resolve()
            if resolved not in seen:
                seen.add(resolved)
                pdfs.append(base)
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix.lower() == ".pdf":
                resolved = p.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    pdfs.append(p)
    return pdfs
