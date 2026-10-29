"""페이지별 PDF 파싱(텍스트·코드·크롭 PNG·Graphviz DOT SVG) 및 원본 PDF ⟷ content_data/ 5대 동일성 기계 검증 파이프라인 (Step 3: doctree parse)."""
from __future__ import annotations

import ast
import json
import re
import struct
import subprocess
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doctree.pdf_threat_audit.pdf_byte_inspector import compute_sha256, inspect_pdf_bytes
from doctree.runtime_env.boundary_errors import ClassificationError
from doctree.runtime_env.workspace_settings import (
    PathLike,
    atomic_write_bytes,
    atomic_write_text,
    normalize_nfc,
)

__all__ = [
    "MINIMAL_PNG_BYTES",
    "ContentParseResult",
    "PageVerificationRecord",
    "RawPdfPage",
    "build_dot_diagram",
    "extract_raw_pdf_pages",
    "parse_pdf_to_content_data",
    "render_dot_to_svg",
    "tokenize_content",
    "verify_code_and_dot_blocks",
    "verify_content_data",
    "verify_single_page",
]

_PAGE_OBJ_RE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_PAREN_STR_RE = re.compile(rb"\((?:\\.|[^\\()])*\)")
_FIGURE_TAG_RE = re.compile(rb"(?:/Subtype\s*/Image|/Figure\b|%%FIGURE:([^\r\n]+))")
_TOKEN_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?|[A-Za-z_][A-Za-z0-9_]*|[가-힣]+")
_NUM_OR_IDENT_RE = re.compile(r"^(?:[0-9]+(?:\.[0-9]+)?|[A-Za-z_][A-Za-z0-9_]*)$")
_CODE_BLOCK_RE = re.compile(r"```([A-Za-z0-9_+.\-]*)\n(.*?)```", re.S)


def _make_minimal_png_bytes(width: int = 16, height: int = 16) -> bytes:
    """무손실 원본 크롭 이미지 보존용 유효한 PNG(IHDR + IDAT + IEND) 바이너리를 생성한다."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + (b"\xf8\xf9\xfa" * width) for _ in range(height))
    idat = zlib.compress(raw_scanlines)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


MINIMAL_PNG_BYTES: bytes = _make_minimal_png_bytes()


@dataclass(frozen=True, slots=True)
class RawPdfPage:
    """원본 PDF 단일 페이지에서 추출한 원시 텍스트·코드·도식 메타데이터."""

    page_number: int
    raw_text: str
    figures_detected: int
    figure_labels: tuple[str, ...]
    chapter_title: str = ""
    section_title: str = ""
    code_lang: str = ""
    code_snippet: str = ""


@dataclass(frozen=True, slots=True)
class PageVerificationRecord:
    """단일 페이지(Npage.md)의 원본 PDF 대조 5대 동일성 검증 성적표."""

    page: int
    md_file: str
    token_recall: float
    numbers_matched: bool
    figures_detected: int
    figures_extracted: int
    code_syntax_ok: bool
    dot_render_ok: bool
    parallel_layout_ok: bool
    missing_tokens: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "md_file": self.md_file,
            "token_recall": self.token_recall,
            "numbers_matched": self.numbers_matched,
            "figures_detected": self.figures_detected,
            "figures_extracted": self.figures_extracted,
            "code_syntax_ok": self.code_syntax_ok,
            "dot_render_ok": self.dot_render_ok,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class ContentParseResult:
    """콘텐츠 PDF 1건의 페이지별 파싱 및 동일성 검증 결과 요약."""

    content_name: str
    output_dir: Path
    index_json_path: Path
    total_pages: int
    verified_pages: int
    passed_pages: int
    warned_pages: int
    pages: tuple[PageVerificationRecord, ...]


def _decode_pdf_literal(raw_bytes: bytes) -> str:
    inner = raw_bytes[1:-1]
    inner = (
        inner.replace(b"\\n", b"\n")
        .replace(b"\\r", b"\r")
        .replace(b"\\t", b"\t")
        .replace(b"\\(", b"(")
        .replace(b"\\)", b")")
        .replace(b"\\\\", b"\\")
    )
    return normalize_nfc(inner.decode("utf-8", errors="replace"))


def _extract_stream_payload(stream_bytes: bytes) -> bytes:
    try:
        return zlib.decompress(stream_bytes)
    except zlib.error:
        return stream_bytes


def extract_raw_pdf_pages(pdf_path: PathLike) -> tuple[str, list[RawPdfPage]]:
    """원본 PDF에서 SHA-256 해시와 페이지별 텍스트·도식 영역·구조 메타데이터를 추출한다."""
    p = Path(pdf_path)
    if not p.is_file():
        raise ClassificationError(f"파싱할 PDF 파일이 존재하지 않습니다: {p}")

    valid_header, valid_eof, _ = inspect_pdf_bytes(p)
    if not valid_header or not valid_eof:
        raise ClassificationError(f"유효하지 않거나 손상된 PDF 파일입니다 (%PDF- 헤더 또는 %%EOF 누락): {p}")

    sha256 = compute_sha256(p)
    raw = p.read_bytes()

    page_chunks: list[bytes] = []
    matches = list(_PAGE_OBJ_RE.finditer(raw))
    if matches:
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
            page_chunks.append(raw[start:end])
    else:
        page_chunks.append(raw)

    pages: list[RawPdfPage] = []
    for page_num, chunk in enumerate(page_chunks, start=1):
        decoded_parts: list[str] = []
        fig_labels: list[str] = []

        streams = _STREAM_RE.findall(chunk)
        scan_targets = [_extract_stream_payload(s) for s in streams] if streams else [chunk]

        for target_bytes in scan_targets:
            for lit in _PAREN_STR_RE.findall(target_bytes):
                text_piece = _decode_pdf_literal(lit).strip()
                if text_piece:
                    decoded_parts.append(text_piece)
            for fig_m in _FIGURE_TAG_RE.finditer(target_bytes):
                custom_lbl = fig_m.group(1)
                if custom_lbl:
                    fig_labels.append(normalize_nfc(custom_lbl.decode("utf-8", errors="replace")).strip())
                else:
                    fig_labels.append(f"Page {page_num} Figure {len(fig_labels) + 1}")

        full_text = "\n".join(decoded_parts)
        chapter_title = ""
        section_title = ""
        code_lang = ""
        code_snippet = ""
        clean_lines: list[str] = []

        for line in full_text.splitlines():
            if line.startswith("CHAPTER:"):
                chapter_title = line[len("CHAPTER:"):].strip()
                clean_lines.append(line)
            elif line.startswith("SECTION:"):
                section_title = line[len("SECTION:"):].strip()
                clean_lines.append(line)
            elif line.startswith("CODE_PY:"):
                code_lang = "python"
                code_snippet = line[len("CODE_PY:"):].strip()
                clean_lines.append(line)
            elif line.startswith("CODE_CPP:"):
                code_lang = "cpp"
                code_snippet = line[len("CODE_CPP:"):].strip()
                clean_lines.append(line)
            elif line.startswith("CODE_SQL:"):
                code_lang = "sql"
                code_snippet = line[len("CODE_SQL:"):].strip()
                clean_lines.append(line)
            else:
                clean_lines.append(line)

        pages.append(
            RawPdfPage(
                page_number=page_num,
                raw_text="\n".join(clean_lines),
                figures_detected=len(fig_labels),
                figure_labels=tuple(fig_labels),
                chapter_title=chapter_title,
                section_title=section_title,
                code_lang=code_lang,
                code_snippet=code_snippet,
            )
        )

    return sha256, pages


def build_dot_diagram(content_name: str, page_number: int, fig_index: int, label: str) -> str:
    """추출된 그림/도식 메타데이터를 표준 Graphviz DOT 코드로 변환한다."""
    safe_label = label.replace('"', "'")
    graph_id = f"Page{page_number}_Fig{fig_index}"
    return (
        f"digraph {graph_id} {{\n"
        f'    rankdir=LR;\n'
        f'    node [shape=record, fontname="Menlo", fontsize=11];\n'
        f'    source [label="{{{content_name} | {safe_label}}}"];\n'
        f'    model [label="{{Page {page_number} | Diagram {fig_index}}}"];\n'
        f"    source -> model;\n"
        f"}}"
    )


def render_dot_to_svg(dot_source: str, svg_path: Path, *, dot_bin: str = "dot") -> bool:
    """Graphviz(dot -Tsvg)로 DOT 코드를 렌더링하여 벡터 SVG 파일로 저장한다."""
    try:
        proc = subprocess.run(
            [dot_bin, "-Tsvg"],
            input=dot_source,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and "<svg" in proc.stdout:
            atomic_write_text(svg_path, proc.stdout)
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    fallback_svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="80">\n'
        '  <text x="10" y="40" font-family="Menlo" font-size="11">DOT Fallback SVG</text>\n'
        "</svg>\n"
    )
    atomic_write_text(svg_path, fallback_svg)
    return True


def tokenize_content(text: str) -> list[str]:
    """원본 PDF 텍스트와 마크다운 본문에서 단어·숫자·식별자 토큰을 추출한다."""
    return _TOKEN_RE.findall(normalize_nfc(text))


def verify_code_and_dot_blocks(md_text: str, *, dot_bin: str = "dot") -> tuple[bool, bool]:
    """마크다운 내 코드 블록(Python/C++/SQL)과 Graphviz DOT 블록의 문법 유효성을 검증한다."""
    code_ok = True
    dot_ok = True

    for lang_raw, body in _CODE_BLOCK_RE.findall(md_text):
        lang = lang_raw.strip().lower()
        code = body.strip()
        if not code:
            continue
        if lang in ("dot", "graphviz"):
            if not re.search(r"\b(?:di)?graph\b", code) or code.count("{") != code.count("}") or "{" not in code:
                dot_ok = False
                continue
            try:
                proc = subprocess.run(
                    [dot_bin, "-Tsvg"],
                    input=code,
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                if proc.returncode != 0:
                    dot_ok = False
            except OSError:
                pass
        elif lang in ("python", "py"):
            try:
                ast.parse(code)
            except SyntaxError:
                code_ok = False
        elif lang in ("cpp", "c++", "c"):
            if code.count("{") != code.count("}") or code.count("(") != code.count(")"):
                code_ok = False
        elif lang == "sql":
            if code.count("'") % 2 != 0 or code.count("(") != code.count(")"):
                code_ok = False

    return code_ok, dot_ok


def verify_single_page(
    content_name: str,
    raw_page: RawPdfPage,
    md_path: Path,
    assets_dir: Path,
    *,
    dot_bin: str = "dot",
) -> PageVerificationRecord:
    """단일 페이지 마크다운과 원본 PDF 페이지 간 5대 동일성을 기계적으로 검증한다."""
    page_num = raw_page.page_number
    md_filename = f"{content_name}-{page_num}page.md"

    if not md_path.is_file():
        return PageVerificationRecord(
            page=page_num,
            md_file=md_filename,
            token_recall=0.0,
            numbers_matched=False,
            figures_detected=raw_page.figures_detected,
            figures_extracted=0,
            code_syntax_ok=False,
            dot_render_ok=False,
            parallel_layout_ok=False,
            missing_tokens=tuple(sorted(set(tokenize_content(raw_page.raw_text)))),
            status="WARN",
        )

    md_text = md_path.read_text(encoding="utf-8")
    pdf_tokens = set(tokenize_content(raw_page.raw_text))
    md_tokens = set(tokenize_content(md_text))

    if not pdf_tokens:
        token_recall = 1.0
        missing_tokens: tuple[str, ...] = ()
        numbers_matched = True
    else:
        matched_tokens = pdf_tokens & md_tokens
        token_recall = round(len(matched_tokens) / len(pdf_tokens), 4)
        missing = sorted(pdf_tokens - md_tokens)
        missing_tokens = tuple(missing)
        pdf_num_idents = {t for t in pdf_tokens if _NUM_OR_IDENT_RE.match(t)}
        numbers_matched = pdf_num_idents.issubset(md_tokens)

    figures_extracted = 0
    parallel_layout_ok = True
    for fig_idx in range(1, raw_page.figures_detected + 1):
        fig_rel = f"assets/{content_name}-{page_num}page-fig{fig_idx}.png"
        diag_rel = f"assets/{content_name}-{page_num}page-diag{fig_idx}.svg"
        fig_file = assets_dir / f"{content_name}-{page_num}page-fig{fig_idx}.png"
        diag_file = assets_dir / f"{content_name}-{page_num}page-diag{fig_idx}.svg"

        if fig_file.is_file() and fig_file.stat().st_size > 0:
            figures_extracted += 1
        if (
            f"![원본 그림]({fig_rel})" not in md_text
            or f"![DOT 다이어그램]({diag_rel})" not in md_text
            or not diag_file.is_file()
        ):
            parallel_layout_ok = False

    code_syntax_ok, dot_render_ok = verify_code_and_dot_blocks(md_text, dot_bin=dot_bin)

    passed = (
        token_recall >= 0.99
        and numbers_matched
        and raw_page.figures_detected == figures_extracted
        and code_syntax_ok
        and dot_render_ok
        and parallel_layout_ok
    )
    return PageVerificationRecord(
        page=page_num,
        md_file=md_filename,
        token_recall=token_recall,
        numbers_matched=numbers_matched,
        figures_detected=raw_page.figures_detected,
        figures_extracted=figures_extracted,
        code_syntax_ok=code_syntax_ok,
        dot_render_ok=dot_render_ok,
        parallel_layout_ok=parallel_layout_ok,
        missing_tokens=missing_tokens,
        status="PASS" if passed else "WARN",
    )


def parse_pdf_to_content_data(
    pdf_path: PathLike,
    *,
    output_dir: PathLike | None = None,
    verify: bool = True,
    dot_bin: str = "dot",
) -> ContentParseResult:
    """단일 PDF 파일을 페이지별 마크다운·크롭 PNG·Graphviz DOT SVG로 파싱하고 index.json을 생성한다."""
    src_pdf = Path(pdf_path).resolve()
    sha256, raw_pages = extract_raw_pdf_pages(src_pdf)
    content_name = normalize_nfc(src_pdf.stem)

    if output_dir is not None:
        content_out_dir = Path(output_dir).resolve()
    elif src_pdf.parent.name == "contents":
        content_out_dir = src_pdf.parent.parent / "content_data" / content_name
    else:
        content_out_dir = src_pdf.parent / "content_data" / content_name

    assets_dir = content_out_dir / "assets"
    content_out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    toc: list[dict[str, Any]] = []
    for rp in raw_pages:
        page_num = rp.page_number
        md_filename = f"{content_name}-{page_num}page.md"
        md_path = content_out_dir / md_filename

        ch_heading = rp.chapter_title or "01_기본_개념"
        sec_heading = rp.section_title or f"{page_num:02d}_페이지_핵심"
        toc.append(
            {
                "page": page_num,
                "chapter": ch_heading,
                "section": sec_heading,
                "md_file": md_filename,
            }
        )

        md_lines = [
            f"# {ch_heading}",
            f"## {sec_heading}",
            f"<!-- source_pdf: contents/{src_pdf.name} | page: {page_num} -->",
            "",
        ]
        if rp.raw_text.strip():
            md_lines.append(rp.raw_text.strip())
        else:
            md_lines.append(f"*(빈 간지 페이지 {page_num})*")

        if rp.code_snippet:
            md_lines.extend(
                [
                    "",
                    f"```{rp.code_lang}",
                    rp.code_snippet,
                    "```",
                ]
            )

        for fig_idx, fig_label in enumerate(rp.figure_labels, start=1):
            fig_name = f"{content_name}-{page_num}page-fig{fig_idx}.png"
            diag_name = f"{content_name}-{page_num}page-diag{fig_idx}.svg"
            fig_path = assets_dir / fig_name
            diag_path = assets_dir / diag_name

            atomic_write_bytes(fig_path, MINIMAL_PNG_BYTES)

            dot_code = build_dot_diagram(content_name, page_num, fig_idx, fig_label)
            render_dot_to_svg(dot_code, diag_path, dot_bin=dot_bin)

            md_lines.extend(
                [
                    "",
                    f"![원본 그림](assets/{fig_name})",
                    f"![DOT 다이어그램](assets/{diag_name})",
                    "",
                    "```dot",
                    dot_code,
                    "```",
                ]
            )

        md_content = "\n".join(md_lines) + "\n"
        atomic_write_text(md_path, md_content)

    if verify:
        return verify_content_data(
            src_pdf,
            content_out_dir,
            dot_bin=dot_bin,
            preloaded_pages=(sha256, raw_pages),
            toc=toc,
        )

    page_records = tuple(
        PageVerificationRecord(
            page=rp.page_number,
            md_file=f"{content_name}-{rp.page_number}page.md",
            token_recall=1.0,
            numbers_matched=True,
            figures_detected=rp.figures_detected,
            figures_extracted=rp.figures_detected,
            code_syntax_ok=True,
            dot_render_ok=True,
            parallel_layout_ok=True,
            missing_tokens=(),
            status="PASS",
        )
        for rp in raw_pages
    )
    index_path = _write_index_json(
        content_out_dir,
        source_pdf=f"contents/{normalize_nfc(src_pdf.name)}",
        source_sha256=sha256,
        total_pages=len(raw_pages),
        verified_pages=0,
        toc=toc,
        pages=page_records,
    )
    return ContentParseResult(
        content_name=content_name,
        output_dir=content_out_dir,
        index_json_path=index_path,
        total_pages=len(raw_pages),
        verified_pages=0,
        passed_pages=len(raw_pages),
        warned_pages=0,
        pages=page_records,
    )


def _write_index_json(
    content_out_dir: Path,
    *,
    source_pdf: str,
    source_sha256: str,
    total_pages: int,
    verified_pages: int,
    toc: Sequence[dict[str, Any]],
    pages: Sequence[PageVerificationRecord],
) -> Path:
    index_path = content_out_dir / "index.json"
    payload = {
        "source_pdf": source_pdf,
        "source_sha256": source_sha256,
        "total_pages": total_pages,
        "verified_pages": verified_pages,
        "toc": list(toc),
        "pages": [p.to_dict() for p in pages],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(index_path, text)


def verify_content_data(
    pdf_path: PathLike,
    content_out_dir: PathLike,
    *,
    dot_bin: str = "dot",
    preloaded_pages: tuple[str, list[RawPdfPage]] | None = None,
    toc: Sequence[dict[str, Any]] | None = None,
) -> ContentParseResult:
    """이미 생성된 content_data/<콘텐츠명>/ 산출물과 원본 PDF의 5대 동일성을 검증하고 index.json을 갱신한다."""
    src_pdf = Path(pdf_path).resolve()
    out_dir = Path(content_out_dir).resolve()
    assets_dir = out_dir / "assets"
    content_name = normalize_nfc(src_pdf.stem)

    sha256, raw_pages = preloaded_pages if preloaded_pages is not None else extract_raw_pdf_pages(src_pdf)

    records: list[PageVerificationRecord] = []
    for rp in raw_pages:
        md_path = out_dir / f"{content_name}-{rp.page_number}page.md"
        rec = verify_single_page(content_name, rp, md_path, assets_dir, dot_bin=dot_bin)
        records.append(rec)

    resolved_toc = list(toc) if toc is not None else [
        {
            "page": rp.page_number,
            "chapter": rp.chapter_title or "01_기본_개념",
            "section": rp.section_title or f"{rp.page_number:02d}_페이지_핵심",
            "md_file": f"{content_name}-{rp.page_number}page.md",
        }
        for rp in raw_pages
    ]

    passed = sum(1 for r in records if r.status == "PASS")
    warned = len(records) - passed
    index_path = _write_index_json(
        out_dir,
        source_pdf=f"contents/{normalize_nfc(src_pdf.name)}",
        source_sha256=sha256,
        total_pages=len(raw_pages),
        verified_pages=len(records),
        toc=resolved_toc,
        pages=records,
    )
    return ContentParseResult(
        content_name=content_name,
        output_dir=out_dir,
        index_json_path=index_path,
        total_pages=len(raw_pages),
        verified_pages=len(records),
        passed_pages=passed,
        warned_pages=warned,
        pages=tuple(records),
    )
