"""프로젝트 레이아웃 프로필 저장소(layout_profile_store.py) 및 `doctree layout` CLI 입출력 단위·통합 테스트."""
from __future__ import annotations

import io
import json
import unicodedata
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from doctree.doctree_cli import command_dispatcher as cli
from doctree.runtime_env.boundary_errors import ClassificationError, SnapshotStorageError
from doctree.runtime_env.layout_profile_store import (
    add_layout_items,
    format_layout_value,
    get_layout_value,
    load_layout_profiles,
    remove_layout_items,
    save_layout_profiles,
    set_layout_field,
    validate_layout_profiles,
)
from doctree.runtime_env.workspace_settings import BASE_DIR, PROJECT_LAYOUT_PROFILES_FILE


@pytest.fixture
def sample_layout_file(tmp_path: Path) -> Path:
    src = BASE_DIR / "config" / "project_layout_profiles.yaml"
    dst = tmp_path / "project_layout_profiles.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


def test_load_real_project_layout_profiles_and_query_formats():
    """실제 config/project_layout_profiles.yaml 로드 및 yaml/json/lines 3종 포맷 직렬화를 검증한다."""
    data = load_layout_profiles(PROJECT_LAYOUT_PROFILES_FILE)
    assert data["schema_version"] == 1
    assert set(data["profiles"].keys()) == {"handcrafted", "research", "toolchain"}

    # 1) 전체 문서 조회
    full_val = get_layout_value(data)
    assert "profiles:" in format_layout_value(full_val, fmt="yaml")
    assert json.loads(format_layout_value(full_val, fmt="json"))["schema_version"] == 1
    assert format_layout_value(full_val, fmt="lines").splitlines() == [
        "handcrafted",
        "research",
        "toolchain",
    ]

    # 2) 단일 프로필 조회
    hc_val = get_layout_value(data, profile="handcrafted")
    assert hc_val["content_dir"] == "contents"
    assert "content_dir" in format_layout_value(hc_val, fmt="lines").splitlines()

    # 3) 스칼라 및 목록 필드 조회
    c_dir = get_layout_value(data, profile="handcrafted", field="content_dir")
    assert format_layout_value(c_dir, fmt="yaml") == "contents\n"
    assert format_layout_value(c_dir, fmt="lines") == "contents\n"

    dirs = get_layout_value(data, profile="handcrafted", field="directories")
    assert format_layout_value(dirs, fmt="lines").splitlines() == [
        "contents",
        "content_data",
        "practice",
        "scripts",
        "tips",
    ]


def test_set_add_remove_layout_operations_and_nfd_normalization(sample_layout_file: Path):
    """set_layout_field, add_layout_items, remove_layout_items가 NFC 정규화 및 원자적 저장을 수행한다."""
    # 1) 스칼라 필드 수정
    updated_prof = set_layout_field(sample_layout_file, "handcrafted", "content_dir", ["books_pdf"])
    assert updated_prof["content_dir"] == "books_pdf"

    # 2) 목록 필드 전체 교체
    updated_prof = set_layout_field(
        sample_layout_file,
        "research",
        "directories",
        ["contents", "content_data", "papers"],
    )
    assert updated_prof["directories"] == ["contents", "content_data", "papers"]

    # 3) 목록 필드에 항목 추가 (NFD 입력 시 NFC 정규화 및 중복 추가 방지 확인)
    nfd_item = unicodedata.normalize("NFD", "실습노트")
    added = add_layout_items(
        sample_layout_file,
        "research",
        "directories",
        [nfd_item, "papers"],  # papers는 이미 있으므로 중복 추가되지 않음
    )
    assert added == ["contents", "content_data", "papers", "실습노트"]
    assert unicodedata.is_normalized("NFC", added[-1])

    # 4) 목록 필드에서 항목 제거
    removed = remove_layout_items(sample_layout_file, "research", "directories", ["실습노트"])
    assert removed == ["contents", "content_data", "papers"]


def test_cli_layout_subcommands_get_set_add_remove_and_error_handling(sample_layout_file: Path):
    """CLI `doctree layout get|set|add|remove` 명령이 정상 출력(종료 코드 0) 및 경계 오류(종료 코드 1)를 반환한다."""
    buf = io.StringIO()
    test_console = Console(file=buf, width=120, force_terminal=False, color_system=None)

    with patch.object(cli, "console", test_console):
        # 1) get lines
        assert (
            cli.main(
                [
                    "layout",
                    "get",
                    "handcrafted",
                    "directories",
                    "--format",
                    "lines",
                    "--file",
                    str(sample_layout_file),
                ]
            )
            == 0
        )
        assert "practice" in buf.getvalue().splitlines()

        # 2) set
        buf.truncate(0)
        buf.seek(0)
        assert (
            cli.main(
                [
                    "layout",
                    "set",
                    "handcrafted",
                    "practice_dir",
                    "kata_practice",
                    "--file",
                    str(sample_layout_file),
                ]
            )
            == 0
        )
        assert "kata_practice" in buf.getvalue()

        # 3) add
        buf.truncate(0)
        buf.seek(0)
        assert (
            cli.main(
                [
                    "layout",
                    "add",
                    "handcrafted",
                    "directories",
                    "benchmarks",
                    "--file",
                    str(sample_layout_file),
                ]
            )
            == 0
        )
        assert "레이아웃 항목 추가 완료" in buf.getvalue()

        # 4) remove
        buf.truncate(0)
        buf.seek(0)
        assert (
            cli.main(
                [
                    "layout",
                    "remove",
                    "handcrafted",
                    "directories",
                    "benchmarks",
                    "--file",
                    str(sample_layout_file),
                ]
            )
            == 0
        )
        assert "레이아웃 항목 제거 완료" in buf.getvalue()

        # 5) 존재하지 않는 프로필 조회 시 종료 코드 1 및 분류 검증 실패 메시지 출력
        buf.truncate(0)
        buf.seek(0)
        assert (
            cli.main(["layout", "get", "non_existent", "--file", str(sample_layout_file)])
            == 1
        )
        assert "❌ 분류 검증 실패:" in buf.getvalue()


def test_layout_validation_and_storage_boundary_errors(tmp_path: Path, sample_layout_file: Path):
    """validate_layout_profiles 및 파일 입출력의 모든 스키마·경계 오류 분기를 검증한다."""
    # 1) 최상위 루트가 dict가 아님
    with pytest.raises(ClassificationError, match="매핑 객체여야 합니다"):
        validate_layout_profiles(["not-a-dict"])

    # 2) 필수 루트 필드 누락 및 허용하지 않는 루트 필드 (단독 및 복합 분기)
    with pytest.raises(ClassificationError, match="필수 필드 누락: profiles"):
        validate_layout_profiles({"schema_version": 1})
    with pytest.raises(ClassificationError, match="허용하지 않는 필드: extra_root"):
        validate_layout_profiles({"schema_version": 1, "profiles": {}, "extra_root": 123})

    # 3) schema_version이 정수 1이 아님 (bool 포함)
    with pytest.raises(ClassificationError, match="지원하는 버전은 정수 1"):
        validate_layout_profiles({"schema_version": True, "profiles": {}})

    # 4) profiles가 비어 있거나 dict가 아님
    with pytest.raises(ClassificationError, match="비어 있지 않은 프로필 매핑"):
        validate_layout_profiles({"schema_version": 1, "profiles": {}})

    # 5) 잘못된 프로필 이름 정규식
    with pytest.raises(ClassificationError, match="프로필 이름은 영문 소문자로 시작"):
        validate_layout_profiles({"schema_version": 1, "profiles": {"Bad_Name": {}}})

    # 6) 프로필 정의가 dict가 아님
    with pytest.raises(ClassificationError, match="프로필 정의는 매핑 객체"):
        validate_layout_profiles({"schema_version": 1, "profiles": {"handcrafted": "invalid"}})

    # 7) 프로필 내 필수 필드 누락 및 미허용 필드 (단독 분기)
    with pytest.raises(ClassificationError, match="필수 필드 누락"):
        validate_layout_profiles(
            {"schema_version": 1, "profiles": {"handcrafted": {"directories": ["contents"]}}}
        )
    with pytest.raises(ClassificationError, match="허용하지 않는 필드: unknown_field"):
        validate_layout_profiles(
            {
                "schema_version": 1,
                "profiles": {
                    "handcrafted": {
                        "directories": ["contents"],
                        "required_files": ["README.md"],
                        "gitignore_entries": ["/contents/"],
                        "unknown_field": "x",
                    }
                },
            }
        )

    # 8) 빈 목록 또는 비문자열 항목 또는 중복 목록 항목
    base_profile = {
        "directories": ["contents"],
        "required_files": ["README.md"],
        "gitignore_entries": ["/contents/"],
    }
    with pytest.raises(ClassificationError, match="비어 있지 않은 문자열 목록"):
        validate_layout_profiles(
            {"schema_version": 1, "profiles": {"handcrafted": {**base_profile, "directories": []}}}
        )
    with pytest.raises(ClassificationError, match="비어 있지 않은 문자열이어야 합니다"):
        validate_layout_profiles(
            {"schema_version": 1, "profiles": {"handcrafted": {**base_profile, "content_dir": "   "}}}
        )
    with pytest.raises(ClassificationError, match="중복 항목"):
        validate_layout_profiles(
            {
                "schema_version": 1,
                "profiles": {"handcrafted": {**base_profile, "directories": ["contents", "contents"]}},
            }
        )

    # 9) load_layout_profiles: 중복 YAML 키 및 파일 없음 오류
    dup_yaml = tmp_path / "dup.yaml"
    dup_yaml.write_text("schema_version: 1\nschema_version: 1\nprofiles: {}\n", encoding="utf-8")
    with pytest.raises(ClassificationError, match="YAML 중복 키"):
        load_layout_profiles(dup_yaml)

    with pytest.raises(ClassificationError, match="레이아웃 YAML 설정을 읽을 수 없습니다"):
        load_layout_profiles(tmp_path / "missing.yaml")

    # 10) get_layout_value / format_layout_value 오류 분기
    valid_data = load_layout_profiles(sample_layout_file)
    with pytest.raises(ClassificationError, match="존재하지 않는 필드"):
        get_layout_value(valid_data, profile="handcrafted", field="no_such_field")
    with pytest.raises(ClassificationError, match="지원하지 않는 출력 포맷"):
        format_layout_value(valid_data, fmt="xml")

    # 11) set_layout_field / add_layout_items / remove_layout_items 오류 분기
    with pytest.raises(ClassificationError, match="등록되지 않은 레이아웃 프로필"):
        set_layout_field(sample_layout_file, "unknown", "content_dir", ["contents"])
    with pytest.raises(ClassificationError, match="설정할 값을 1개 이상"):
        set_layout_field(sample_layout_file, "handcrafted", "content_dir", [])
    with pytest.raises(ClassificationError, match="단일 문자열 필드는 값을 1개만"):
        set_layout_field(sample_layout_file, "handcrafted", "content_dir", ["a", "b"])
    with pytest.raises(ClassificationError, match="허용하지 않는 레이아웃 필드"):
        set_layout_field(sample_layout_file, "handcrafted", "invalid_field", ["a"])

    with pytest.raises(ClassificationError, match="등록되지 않은 레이아웃 프로필"):
        add_layout_items(sample_layout_file, "unknown", "directories", ["x"])
    with pytest.raises(ClassificationError, match=r"목록 필드.*에만 사용할 수 있습니다"):
        add_layout_items(sample_layout_file, "handcrafted", "content_dir", ["x"])
    with pytest.raises(ClassificationError, match="추가할 항목을 1개 이상"):
        add_layout_items(sample_layout_file, "handcrafted", "directories", [])

    with pytest.raises(ClassificationError, match="등록되지 않은 레이아웃 프로필"):
        remove_layout_items(sample_layout_file, "unknown", "directories", ["x"])
    with pytest.raises(ClassificationError, match=r"목록 필드.*에만 사용할 수 있습니다"):
        remove_layout_items(sample_layout_file, "handcrafted", "content_dir", ["x"])
    with pytest.raises(ClassificationError, match="제거할 항목을 1개 이상"):
        remove_layout_items(sample_layout_file, "handcrafted", "directories", [])
    with pytest.raises(ClassificationError, match="존재하지 않는 항목입니다"):
        remove_layout_items(sample_layout_file, "handcrafted", "directories", ["not-there"])

    # 12) save_layout_profiles: Path.replace 실패 시 임시 파일 정리 및 SnapshotStorageError 발생
    with (
        patch.object(Path, "replace", side_effect=OSError("disk full")),
        pytest.raises(SnapshotStorageError, match="레이아웃 설정 저장 실패"),
    ):
        save_layout_profiles(valid_data, sample_layout_file)
    assert not (sample_layout_file.parent / f".{sample_layout_file.name}.tmp").exists()

    # write_bytes 단계에서 실패해 임시 파일이 생성되지 않은 경우 분기
    with (
        patch.object(Path, "write_bytes", side_effect=OSError("read-only fs")),
        pytest.raises(SnapshotStorageError, match="레이아웃 설정 저장 실패"),
    ):
        save_layout_profiles(valid_data, sample_layout_file)
