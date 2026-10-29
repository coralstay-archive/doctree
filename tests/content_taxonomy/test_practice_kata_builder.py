"""중간 결과물(content_data/) 기반 실습·테스트 프레임워크 빌더(practice_kata_builder.py) 및 `doctree practice` CLI 테스트."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from doctree.content_taxonomy.practice_kata_builder import (
    _slugify,
    build_practice_katas,
    resolve_language_extension,
)
from doctree.doctree_cli import command_dispatcher as cli
from doctree.pdf_threat_audit.pdf_page_ingestor import parse_pdf_to_content_data
from doctree.runtime_env.boundary_errors import ClassificationError


def _create_parsed_content(proj_dir: Path, content_name: str = "테스트도서") -> Path:
    pdf_path = proj_dir / "contents" / f"{content_name}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = (
        b"%PDF-1.7\n"
        b"1 0 obj << /Type /Page >>\nstream\n"
        b"(CHAPTER: 01_Basics)\n(SECTION: 01_Intro)\n(Core concept 1)\n"
        b"endstream\nendobj\n"
        b"2 0 obj << /Type /Page >>\nstream\n"
        b"(CHAPTER: 01_Basics)\n(SECTION: 01_Intro)\n(Core concept 2)\n(CODE_PY: x = 1)\n%%FIGURE:Diag1\n"
        b"endstream\nendobj\n"
        b"3 0 obj << /Type /Page >>\nstream\n"
        b"(CHAPTER: 01_Basics)\n(SECTION: 01_Intro)\n(Core concept 3)\n(CODE_PY: y = 2)\n%%FIGURE:Diag2\n"
        b"endstream\nendobj\n"
        b"%%EOF\n"
    )
    pdf_path.write_bytes(pdf_bytes)
    res = parse_pdf_to_content_data(pdf_path, verify=True)
    return res.output_dir


def test_resolve_language_and_slugify_and_error_branches(tmp_path: Path):
    """언어 추론(py/cpp/java/sql), 슬러그 정규화 및 잘못된 입력 예외 분기를 검증한다."""
    assert _slugify("   ", 1) == "01_section_01"
    assert _slugify("02_이미번호있음", 1) == "02_이미번호있음"
    assert _slugify("한글 제목!", 3) == "03_한글_제목"

    assert resolve_language_extension(Path("/ws/handcrafted-cpp/content_data/b")) == "cpp"
    assert resolve_language_extension(Path("/ws/handcrafted-java/content_data/b")) == "java"
    assert resolve_language_extension(Path("/ws/databases/content_data/b")) == "sql"
    assert resolve_language_extension(Path("/ws/handcrafted-python/content_data/b")) == "py"
    assert resolve_language_extension(Path("/ws/any"), explicit_lang="C++") == "cpp"

    with pytest.raises(ClassificationError, match="지원하지 않는 실습 언어"):
        resolve_language_extension(Path("/ws/any"), explicit_lang="rust")

    # 없는 폴더, 깨진 index.json, 빈 pages 배열 오류 검증
    with pytest.raises(ClassificationError, match="유효한 content_data"):
        build_practice_katas(tmp_path / "no_such_dir")

    bad_dir = tmp_path / "bad_book"
    bad_dir.mkdir()
    (bad_dir / "index.json").write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ClassificationError, match=r"index\.json을 읽을 수 없습니다"):
        build_practice_katas(bad_dir)

    (bad_dir / "index.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
    with pytest.raises(ClassificationError, match="유효한 pages 목록이 없습니다"):
        build_practice_katas(bad_dir)


def test_build_practice_katas_across_languages_and_idempotency(tmp_path: Path):
    """content_data/로부터 4종 언어(py/cpp/java/sql) 실습 패키지 생성, 파일 보존 및 덮어쓰기를 검증한다."""
    proj = tmp_path / "handcrafted-python"
    content_dir = _create_parsed_content(proj, "파이썬마스터")

    # 1) 기본(py) 생성: 2페이지가 동일한 장·절(01_Basics / 01_Intro)로 묶여 1개 실습 과제가 생성됨
    res_py = build_practice_katas(content_dir)
    assert res_py.lang_ext == "py"
    assert res_py.chapters_count == 1
    assert res_py.katas_count == 1
    kata_dir = res_py.kata_dirs[0]
    assert (kata_dir / "README.md").is_file()
    assert (kata_dir / "main.py").is_file()
    assert (kata_dir / "test.py").is_file()
    assert "1p ~ 3p" in (kata_dir / "README.md").read_text(encoding="utf-8")

    # 2) overwrite=False일 때 기존 파일 보존, overwrite=True일 때 덮어쓰기
    (kata_dir / "main.py").write_text("# user typed solution\n", encoding="utf-8")
    build_practice_katas(content_dir, overwrite=False)
    assert (kata_dir / "main.py").read_text(encoding="utf-8") == "# user typed solution\n"

    build_practice_katas(content_dir, overwrite=True)
    assert "@snippet" in (kata_dir / "main.py").read_text(encoding="utf-8")

    # 3) cpp, java, sql 언어 지정 및 custom practice_root, toc 없는 index.json 분기
    index_path = content_dir / "index.json"
    idx_data = json.loads(index_path.read_text(encoding="utf-8"))
    idx_data.pop("toc", None)
    # 마크다운 파일이 없는 페이지도 안전하게 기본 템플릿으로 생성되는지 확인하기 위해 2페이지 md 삭제
    (content_dir / "파이썬마스터-2page.md").unlink()
    index_path.write_text(json.dumps(idx_data), encoding="utf-8")

    for lang in ("cpp", "java", "sql"):
        custom_prac = tmp_path / f"prac_{lang}"
        res_lang = build_practice_katas(content_dir, practice_root=custom_prac, lang=lang, overwrite=True)
        assert res_lang.lang_ext == lang
        assert (res_lang.kata_dirs[0] / f"main.{lang}").is_file()
        assert (res_lang.kata_dirs[0] / f"test.{lang}").is_file()

    # content_data 폴더 아래가 아닌 독립 폴더일 때 기본 practice 경로 분기
    standalone_content = tmp_path / "standalone_content"
    standalone_content.mkdir()
    (standalone_content / "index.json").write_text(
        json.dumps({"pages": [{"page": 1, "md_file": "missing.md"}]}),
        encoding="utf-8",
    )
    res_standalone = build_practice_katas(standalone_content)
    assert res_standalone.practice_content_dir == tmp_path / "practice" / "standalone_content"


def test_cli_practice_subcommand(tmp_path: Path):
    """CLI `doctree practice` 명령(단일 도서 폴더, 프로젝트 루트, content_data 루트, 오류 분기)을 검증한다."""
    proj = tmp_path / "handcrafted-cpp"
    content_dir = _create_parsed_content(proj, "모던CPP")

    buf = io.StringIO()
    test_console = Console(file=buf, width=120, force_terminal=False, color_system=None)

    with patch.object(cli, "console", test_console):
        # 1) 프로젝트 루트 지정 시 하위 content_data/* 자동 탐색
        assert cli.main(["practice", str(proj)]) == 0
        assert "🎯 실습(Kata) 생성 완료: 모던CPP" in buf.getvalue()

        # 2) 단일 도서 content_data/<도서명> 직접 지정
        assert cli.main(["practice", str(content_dir), "--overwrite"]) == 0

        # 3) content_data 폴더 자체 지정
        assert cli.main(["practice", str(proj / "content_data")]) == 0

        # 4) index.json이 없는 빈 디렉터리 또는 존재하지 않는 경로 지정 시 종료 코드 1
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        assert cli.main(["practice", str(empty)]) == 1
        assert cli.main(["practice", str(tmp_path / "non_existent_path")]) == 1
