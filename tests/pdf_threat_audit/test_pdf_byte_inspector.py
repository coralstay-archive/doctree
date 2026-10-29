"""로컬 PDF 바이트 정적 무결성 및 위험 태그 검사기(doctree.pdf_threat_audit.pdf_byte_inspector) 단위 테스트."""
import dataclasses
import hashlib
from pathlib import Path

import pytest

from doctree.pdf_threat_audit.pdf_byte_inspector import (
    LocalPdfAudit,
    compute_sha256,
    discover_local_pdfs,
    inspect_pdf_bytes,
)
from doctree.pdf_threat_audit.threat_intel_client import VerdictStatus, VtVerdict


def _make_pdf(path: Path, body: bytes = b"1 0 obj << /Type /Catalog >> endobj\n", valid: bool = True) -> str:
    content = (b"%PDF-1.7\n" + body + b"\n%%EOF\n") if valid else b"NOT A PDF"
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def test_compute_sha256_and_clean_pdf_inspection(tmp_path):
    pdf = tmp_path / "clean.pdf"
    expected_sha = _make_pdf(pdf)

    # 작은 chunk_size로 여러 번 나눠 읽어도 동일한 SHA-256 해시를 반환해야 한다
    assert compute_sha256(pdf, chunk_size=7) == expected_sha
    header_ok, eof_ok, tags = inspect_pdf_bytes(pdf)
    assert (header_ok, eof_ok, tags) == (True, True, ())


def test_inspect_pdf_size_boundaries_and_partial_corruption(tmp_path):
    # 경계값: 0바이트 및 7바이트(< 8) 파일은 즉시 (False, False, ()) 반환
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"")
    assert inspect_pdf_bytes(empty_pdf) == (False, False, ())

    seven_bytes = tmp_path / "seven.pdf"
    seven_bytes.write_bytes(b"%PDF-1.")
    assert inspect_pdf_bytes(seven_bytes) == (False, False, ())

    # 경계값: 정확히 8바이트(== 8) 파일은 헤더 검사를 수행한다 (< 8 vs <= 8 뮤테이션 검증)
    eight_bytes = tmp_path / "eight.pdf"
    eight_bytes.write_bytes(b"%PDF-1.7")
    assert inspect_pdf_bytes(eight_bytes) == (True, False, ())

    # 헤더만 있고 %%EOF가 없는 손상 파일
    no_eof = tmp_path / "no_eof.pdf"
    no_eof.write_bytes(b"%PDF-1.7\n1 0 obj <<>> endobj\n")
    assert inspect_pdf_bytes(no_eof) == (True, False, ())

    # %%EOF만 있고 %PDF- 헤더가 없는 손상 파일
    no_header = tmp_path / "no_header.pdf"
    no_header.write_bytes(b"CORRUPT_HEADER\n1 0 obj <<>> endobj\n%%EOF\n")
    assert inspect_pdf_bytes(no_header) == (False, True, ())


def test_inspect_pdf_detects_all_dangerous_tags_and_rejects_lookalikes(tmp_path):
    mal_pdf = tmp_path / "exploit.pdf"
    _make_pdf(
        mal_pdf,
        body=(
            b"1 0 obj << /OpenAction << /S /JavaScript /S /JS (app.launchURL) >> "
            b"/Launch (cmd.exe) /EmbeddedFiles <<>> /RichMedia <<>> /XFA [] >> endobj"
        ),
    )

    header_ok, eof_ok, tags = inspect_pdf_bytes(mal_pdf)
    assert header_ok is True
    assert eof_ok is True
    assert tags == ("/JavaScript", "/JS", "/Launch", "/EmbeddedFiles", "/RichMedia", "/XFA")

    # 접두사만 같고 뒤에 영숫자/밑줄이 이어지는 정상 식별자나 압축 스트림 내 '/JS'는 오탐하지 않는다
    benign_pdf = tmp_path / "benign_lookalikes.pdf"
    _make_pdf(
        benign_pdf,
        body=(
            b"stream\n\x89\x50/JS\x00\xff\nendstream\n"
            b"<< /JavaScriptEngine 1 /S /JScript /LaunchPad 2 /EmbeddedFilesList 3 /RichMediaPlayer 4 /XFA_Form 5 >>"
        ),
    )
    assert inspect_pdf_bytes(benign_pdf) == (True, True, ())


def test_inspect_pdf_detects_tag_split_across_1mb_chunk_boundary(tmp_path):
    """1MB(1048576B) 청크 경계에 걸쳐 쪼개진 위험 태그('/Java' + 'Script')도 슬라이딩 윈도우로 탐지한다."""
    chunk_boundary_pdf = tmp_path / "split_boundary.pdf"
    prefix = b"%PDF-1.7\n/Launch "
    # 첫 번째 1MB 청크의 끝부분에 b"/Java"가 위치하고 두 번째 청크 시작에 b"Script\n"이 오도록 패딩
    pad_len = (1024 * 1024) - len(prefix) - len(b"/Java")
    payload = prefix + (b"A" * pad_len) + b"/JavaScript\n/Launch\n%%EOF\n"
    chunk_boundary_pdf.write_bytes(payload)

    header_ok, eof_ok, tags = inspect_pdf_bytes(chunk_boundary_pdf)
    assert header_ok is True
    assert eof_ok is True
    assert tags == ("/JavaScript", "/Launch")


@pytest.mark.parametrize(
    "header,eof,tags,verdict,expected_safe",
    [
        (True, True, (), None, True),
        (False, True, (), None, False),
        (True, False, (), None, False),
        (True, True, ("/Launch",), None, False),
        (True, True, (), VtVerdict(sha256="a", status=VerdictStatus.CLEAN), True),
        (True, True, (), VtVerdict(sha256="a", status=VerdictStatus.NOT_FOUND), True),
        (True, True, (), VtVerdict(sha256="a", status=VerdictStatus.MALICIOUS, malicious=1), False),
        (True, True, (), VtVerdict(sha256="a", status=VerdictStatus.SUSPICIOUS, suspicious=1), False),
    ],
)
def test_local_pdf_audit_is_safe_truth_table_and_immutability(header, eof, tags, verdict, expected_safe):
    audit = LocalPdfAudit(
        path="/tmp/test.pdf",
        sha256="a" * 64,
        valid_pdf_header=header,
        valid_pdf_eof=eof,
        dangerous_tags=tags,
        vt_verdict=verdict,
    )
    assert audit.is_safe is expected_safe
    with pytest.raises(dataclasses.FrozenInstanceError):
        audit.path = "/tmp/mutated.pdf"  # type: ignore[misc]


def test_discover_local_pdfs_deduplicates_and_skips_missing_or_non_pdf(tmp_path):
    sub = tmp_path / "contents"
    sub.mkdir()
    pdf1 = sub / "a_sample.pdf"
    pdf2 = sub / "b_upper.PDF"
    txt = sub / "ignore.txt"
    nested_dir = sub / "nested.pdf"  # 디렉터리 이름이 .pdf여도 파일이 아니면 제외
    nested_dir.mkdir()

    _make_pdf(pdf1)
    _make_pdf(pdf2)
    txt.write_text("not a pdf", encoding="utf-8")

    missing_root = tmp_path / "non_existent_root"
    # 동일 파일 직접 경로 중복 전달 + 상위 폴더 전달 시에도 중복 없이 정렬된 목록 반환
    found = discover_local_pdfs([missing_root, pdf1, pdf1, txt, sub])
    assert found == [pdf1, pdf2]
