"""페이지별 PDF 파싱·크롭 PNG·Graphviz DOT SVG 및 5대 동일성 기계 검증(pdf_page_ingestor.py) 단위·통합 테스트."""
from __future__ import annotations

import io
import json
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from doctree.doctree_cli import command_dispatcher as cli
from doctree.pdf_threat_audit.pdf_page_ingestor import (
    RawPdfPage,
    extract_raw_pdf_pages,
    parse_pdf_to_content_data,
    render_dot_to_svg,
    verify_code_and_dot_blocks,
    verify_content_data,
    verify_single_page,
)
from doctree.runtime_env.boundary_errors import ClassificationError


def _build_multi_page_pdf(path: Path) -> Path:
    """FlateDecode 압축 스트림, 일반 스트림, 빈 간지 페이지, 그림 태그, Python/C++/SQL 코드를 포함한 4페이지 PDF 생성."""
    p1_stream = zlib.compress(
        (
            "(CHAPTER: 01_인덱스_튜닝)\n"
            "(SECTION: 01_BTree_구조)\n"
            "(BTree index depth 3 and key 50.)\n"
            "(CODE_PY: def calc\\(x\\): return x + 1)\n"
            "%%FIGURE:B+Tree Root to Leaf\n"
        ).encode()
    )
    p2_stream = (
        b"(CHAPTER: 01_\xec\x9d\xb8\xeb\x8d\xb1\xec\x8a\xa4_\xed\x8a\x9c\xeb\x8b\x9d)\n"
        b"(SECTION: 02_CPP_\xec\x8a\xac\xeb\xa1\xaf)\n"
        b"(CODE_CPP: int main\\(\\) { return 0; })\n"
        b"/Subtype /Image\n"
    )
    p3_stream = (
        b"(CHAPTER: 02_SQL_\xec\x8b\xa4\xed\x96\x89\xea\xb3\x84\xed\x9a\x8d)\n"
        b"(SECTION: 01_SELECT_\xec\xbf\xbc\xb8\xac)\n"
        b"(CODE_SQL: SELECT id FROM users WHERE id = 1;)\n"
    )
    # Page 4: 빈 간지 페이지
    p4_stream = b"()"

    pdf_bytes = (
        b"%PDF-1.7\n"
        b"1 0 obj << /Type /Page >>\nstream\n" + p1_stream + b"\nendstream\nendobj\n"
        b"2 0 obj << /Type /Page >>\nstream\n" + p2_stream + b"\nendstream\nendobj\n"
        b"3 0 obj << /Type /Page >>\nstream\n" + p3_stream + b"\nendstream\nendobj\n"
        b"4 0 obj << /Type /Page >>\nstream\n" + p4_stream + b"\nendstream\nendobj\n"
        b"%%EOF\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return path


def test_extract_and_parse_pdf_to_content_data_and_verify(tmp_path: Path):
    """다중 페이지 PDF 파싱(verify=True / False) 및 5대 동일성 검증(PASS / WARN) 전 분기를 검증한다."""
    # 1) 존재하지 않거나 손상된 PDF 예외 검증
    with pytest.raises(ClassificationError, match="존재하지 않습니다"):
        extract_raw_pdf_pages(tmp_path / "missing.pdf")

    bad_pdf = tmp_path / "corrupt.pdf"
    bad_pdf.write_bytes(b"NOT_A_PDF")
    with pytest.raises(ClassificationError, match="유효하지 않거나 손상된 PDF"):
        extract_raw_pdf_pages(bad_pdf)

    # /Type /Page가 없고 stream도 없는 최소 단일 청크 PDF 추출
    single_chunk_pdf = tmp_path / "single.pdf"
    single_chunk_pdf.write_bytes(b"%PDF-1.7\n(Single page literal text 100)\n%%EOF\n")
    _, single_pages = extract_raw_pdf_pages(single_chunk_pdf)
    assert len(single_pages) == 1
    assert "Single page literal text 100" in single_pages[0].raw_text

    # 2) 4페이지 표준 PDF 파싱 (contents/ 폴더 아래 배치 & 기본 출력 경로 & verify=False)
    proj = tmp_path / "databases"
    pdf_path = _build_multi_page_pdf(proj / "contents" / "친절한-SQL-튜닝.pdf")

    res_no_verify = parse_pdf_to_content_data(pdf_path, verify=False)
    assert res_no_verify.total_pages == 4
    assert res_no_verify.verified_pages == 0
    assert res_no_verify.passed_pages == 4

    # 3) verify=True 실행 및 index.json 검증
    res_verified = parse_pdf_to_content_data(pdf_path, verify=True)
    assert res_verified.total_pages == 4
    assert res_verified.verified_pages == 4
    assert res_verified.passed_pages == 4
    assert res_verified.warned_pages == 0
    index_data = json.loads(res_verified.index_json_path.read_text(encoding="utf-8"))
    assert index_data["total_pages"] == 4
    assert index_data["pages"][0]["figures_detected"] == 1
    assert index_data["pages"][0]["figures_extracted"] == 1
    assert index_data["pages"][0]["status"] == "PASS"

    # preloaded_pages=None 및 toc=None으로 verify_content_data 단독 호출
    re_verified = verify_content_data(pdf_path, res_verified.output_dir)
    assert re_verified.passed_pages == 4

    # contents/ 폴더가 아닌 경로 및 명시적 output_dir 지정 분기
    custom_out = tmp_path / "custom_content_data"
    res_single = parse_pdf_to_content_data(single_chunk_pdf, output_dir=custom_out, verify=True)
    assert res_single.output_dir == custom_out
    res_non_contents = parse_pdf_to_content_data(single_chunk_pdf, verify=False)
    assert res_non_contents.output_dir == tmp_path / "content_data" / "single"


def test_verify_code_and_dot_blocks_and_single_page_warn_branches(tmp_path: Path):
    """코드 블록(Python/C++/SQL)·DOT 구문 검증 실패 및 페이지 누락/도식 누락 WARN 분기를 검증한다."""
    # 1) 빈 코드 블록, 잘못된 DOT 블록, dot 실행 실패(returncode != 0), dot 바이너리 없음(OSError)
    md_bad_dot = "```\n\n```\n```dot\ninvalid_dot_without_braces\n```\n"
    code_ok, dot_ok = verify_code_and_dot_blocks(md_bad_dot)
    assert code_ok is True
    assert dot_ok is False

    md_dot_syntax_err = "```dot\ndigraph G { a -> ; }\n```\n"
    _, dot_ok2 = verify_code_and_dot_blocks(md_dot_syntax_err, dot_bin="dot")
    assert dot_ok2 is False

    md_valid_dot = "```dot\ndigraph G { a -> b; }\n```\n"
    _, dot_ok3 = verify_code_and_dot_blocks(md_valid_dot, dot_bin="non_existent_dot_binary_xyz")
    assert dot_ok3 is True

    # 2) Python / C++ / SQL 문법 오류 및 정상 분기
    assert verify_code_and_dot_blocks("```python\ndef broken(:\n```\n") == (False, True)
    assert verify_code_and_dot_blocks("```cpp\nint main() { return 0;\n```\n") == (False, True)
    assert verify_code_and_dot_blocks("```sql\nSELECT 'unterminated FROM t;\n```\n") == (False, True)
    assert verify_code_and_dot_blocks("```sql\nSELECT * FROM t;\n```\n") == (True, True)
    assert verify_code_and_dot_blocks("```txt\nplain text\n```\n") == (True, True)

    # 3) render_dot_to_svg 폴백(존재하지 않는 dot 바이너리 지정 또는 잘못된 DOT 구문으로 returncode != 0일 때 fallback SVG 생성)
    fallback_svg = tmp_path / "assets" / "fallback.svg"
    assert render_dot_to_svg("digraph G { a -> b; }", fallback_svg, dot_bin="non_existent_dot_xyz") is True
    assert "DOT Fallback SVG" in fallback_svg.read_text(encoding="utf-8")
    fallback_svg2 = tmp_path / "assets" / "fallback2.svg"
    assert render_dot_to_svg("digraph G { broken -> ; }", fallback_svg2, dot_bin="dot") is True
    assert "DOT Fallback SVG" in fallback_svg2.read_text(encoding="utf-8")

    # 4) verify_single_page: 마크다운 파일이 삭제된 경우 및 도식 링크/파일이 누락된 경우 WARN 판정
    raw_page = RawPdfPage(
        page_number=1,
        raw_text="Important token 1024",
        figures_detected=1,
        figure_labels=("Fig1",),
    )
    missing_md_rec = verify_single_page("Book", raw_page, tmp_path / "missing.md", tmp_path / "assets")
    assert missing_md_rec.status == "WARN"
    assert missing_md_rec.token_recall == 0.0

    incomplete_md = tmp_path / "Book-1page.md"
    incomplete_md.write_text("# Only partial text without numbers or figure links\n", encoding="utf-8")
    warn_rec = verify_single_page("Book", raw_page, incomplete_md, tmp_path / "assets")
    assert warn_rec.status == "WARN"
    assert warn_rec.numbers_matched is False
    assert warn_rec.parallel_layout_ok is False
    assert "1024" in warn_rec.missing_tokens


def test_cli_parse_subcommand(tmp_path: Path):
    """CLI `doctree parse` 명령(--verify, --strict, 디렉터리/파일 대상, 오류 처리)을 검증한다."""
    proj = tmp_path / "databases"
    pdf_path = _build_multi_page_pdf(proj / "contents" / "친절한-SQL-튜닝.pdf")

    buf = io.StringIO()
    test_console = Console(file=buf, width=120, force_terminal=False, color_system=None)

    with patch.object(cli, "console", test_console):
        # 1) 프로젝트 디렉터리 지정 시 하위 contents/*.pdf 자동 탐색 및 --verify 통과
        assert cli.main(["parse", str(proj), "--verify", "--strict"]) == 0
        assert "📄 PDF 파싱 완료: 친절한-SQL-튜닝" in buf.getvalue()

        # 2) 단일 PDF 파일 직접 지정
        assert cli.main(["parse", str(pdf_path)]) == 0

        # 3) PDF가 없는 빈 폴더 지정 시 종료 코드 1
        empty_dir = tmp_path / "empty_proj"
        empty_dir.mkdir()
        assert cli.main(["parse", str(empty_dir)]) == 1

        # 4) --strict 모드에서 WARN 페이지 발생 시 종료 코드 1 반환
        warn_res = parse_pdf_to_content_data(pdf_path, verify=True)
        warn_record = warn_res.pages[0].__class__(
            page=1,
            md_file="x.md",
            token_recall=0.5,
            numbers_matched=False,
            figures_detected=1,
            figures_extracted=0,
            code_syntax_ok=False,
            dot_render_ok=False,
            parallel_layout_ok=False,
            missing_tokens=("a",),
            status="WARN",
        )
        fake_content_res = warn_res.__class__(
            content_name="ContentDoc",
            output_dir=warn_res.output_dir,
            index_json_path=warn_res.index_json_path,
            total_pages=1,
            verified_pages=1,
            passed_pages=0,
            warned_pages=1,
            pages=(warn_record,),
        )
        with patch(
            "doctree.doctree_cli.command_dispatcher.parse_pdf_to_content_data",
            return_value=fake_content_res,
        ):
            assert cli.main(["parse", str(pdf_path), "--strict"]) == 1
