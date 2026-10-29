"""프로젝트 구조 스캐폴딩 생성기(project_scaffolder.py) 및 `doctree scaffold` CLI 단위·통합 테스트."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from doctree.doctree_cli import command_dispatcher as cli
from doctree.runtime_env.project_scaffolder import (
    _ensure_gitignore_entries,
    scaffold_project,
    verify_project_scaffold,
)


def test_scaffold_handcrafted_research_toolchain_and_idempotency(tmp_path: Path):
    """handcrafted, research, toolchain 프로필 스캐폴딩 생성·보존·덮어쓰기 및 검증을 확인한다."""
    proj = tmp_path / "handcrafted-demo"

    # 1) 최초 스캐폴딩 전에는 verify 실패
    ok_before, missing_before = verify_project_scaffold("handcrafted", proj)
    assert ok_before is False
    assert "dir:contents" in missing_before
    assert "file:README.md" in missing_before
    assert "gitignore:/contents/" in missing_before

    # 2) 최초 스캐폴딩 실행
    res1 = scaffold_project("handcrafted", proj)
    assert res1.profile == "handcrafted"
    assert set(res1.created_dirs) == {"contents", "content_data", "practice", "scripts", "tips"}
    assert res1.existing_dirs == ()
    assert ".gitignore" in res1.created_files
    assert "scripts/run.sh" in res1.created_files
    assert (proj / "scripts" / "run.sh").stat().st_mode & 0o111

    ok_after, missing_after = verify_project_scaffold("handcrafted", proj)
    assert ok_after is True
    assert missing_after == ()

    # 3) 기존 파일 수정 및 실행 권한 제거 후 재실행(overwrite=False): 기존 파일 보존 및 .sh 실행 권한 복구
    readme_path = proj / "README.md"
    readme_path.write_text("# Custom Handcrafted Readme\n", encoding="utf-8")
    run_sh = proj / "scripts" / "run.sh"
    run_sh.chmod(0o644)

    res2 = scaffold_project("handcrafted", proj, overwrite=False)
    assert res2.created_dirs == ()
    assert set(res2.existing_dirs) == {"contents", "content_data", "practice", "scripts", "tips"}
    assert "README.md" in res2.preserved_files
    assert ".gitignore" in res2.preserved_files
    assert readme_path.read_text(encoding="utf-8") == "# Custom Handcrafted Readme\n"
    assert run_sh.stat().st_mode & 0o111

    # 4) overwrite=True로 재실행 시 필수 파일 재생성
    res3 = scaffold_project("handcrafted", proj, overwrite=True)
    assert "README.md" in res3.created_files
    assert "freeride (`handcrafted` 프로필)" in readme_path.read_text(encoding="utf-8")

    # 5) research 및 toolchain 프로필 스캐폴딩
    res_research = scaffold_project("research", tmp_path / "research-demo")
    assert "notes" in res_research.created_dirs
    res_toolchain = scaffold_project("toolchain", tmp_path / "toolchain-demo")
    assert "install.sh" in res_toolchain.created_files


def test_ensure_gitignore_entries_edge_cases(tmp_path: Path):
    """.gitignore가 이미 일부 항목만 가진 경우 및 빈 요구사항 분기를 검증한다."""
    gi = tmp_path / ".gitignore"
    gi.write_text("# existing comment\n", encoding="utf-8")
    created, added = _ensure_gitignore_entries(gi, ["/contents/", "/practice/"])
    assert created is False
    assert added == ("/contents/", "/practice/")
    assert gi.read_text(encoding="utf-8") == "# existing comment\n/contents/\n/practice/\n"

    # 빈 파일이 아직 없을 때 빈 required_entries 전달 분기
    gi_empty = tmp_path / "empty_dir" / ".gitignore"
    created_empty, added_empty = _ensure_gitignore_entries(gi_empty, [])
    assert created_empty is True
    assert added_empty == ()
    assert gi_empty.read_text(encoding="utf-8") == ""


def test_cli_scaffold_subcommand(tmp_path: Path):
    """CLI `doctree scaffold` 명령(--check 포함)의 성공(0) 및 실패(1) 분기를 검증한다."""
    target = tmp_path / "my-proj"
    buf = io.StringIO()
    test_console = Console(file=buf, width=120, force_terminal=False, color_system=None)

    with patch.object(cli, "console", test_console):
        # 1) 스캐폴딩 전 --check 실행 시 누락 항목 오류(1)
        assert cli.main(["scaffold", "handcrafted", str(target), "--check"]) == 1
        assert "레이아웃 누락 항목" in buf.getvalue()

        # 2) 스캐폴딩 실행(0)
        buf.truncate(0)
        buf.seek(0)
        assert cli.main(["scaffold", "handcrafted", str(target)]) == 0
        assert "🏗️ 프로젝트 스캐폴딩 완료:" in buf.getvalue()

        # 3) 스캐폴딩 후 --check 실행 시 통과(0)
        buf.truncate(0)
        buf.seek(0)
        assert cli.main(["scaffold", "handcrafted", str(target), "--check"]) == 0
        assert "✅ 프로젝트 레이아웃 검증 통과:" in buf.getvalue()

        # 4) 알 수 없는 프로필 지정 시 종료 코드 1
        assert cli.main(["scaffold", "unknown_profile", str(target)]) == 1
