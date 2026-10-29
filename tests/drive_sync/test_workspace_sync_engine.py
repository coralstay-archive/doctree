"""드라이브 ⟷ 로컬 contents/ 고속 스캔·3-Way 비교 및 도서 가져오기(pull) 엔진(workspace_sync_engine.py) 단위·통합 테스트."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from doctree.doctree_cli import command_dispatcher as cli
from doctree.drive_sync.workspace_sync_engine import (
    compare_drive_and_local,
    format_sync_report,
    load_local_contents_cache,
    pull_drive_pdf_to_project,
    resolve_drive_record_for_pull,
    save_local_contents_cache,
    scan_workspace_contents,
)
from doctree.runtime_env.boundary_errors import (
    ClassificationError,
    DriveListError,
    SnapshotStorageError,
)


def _make_pdf(path: Path, text: str = "hello") -> str:
    data = f"%PDF-1.7\n({text})\n%%EOF\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_local_contents_cache_load_save_and_error_handling(tmp_path: Path):
    """로컬 contents/ 해시 캐시 로드·원자적 저장 및 손상/오류 분기를 검증한다."""
    # 1) None 또는 없는 파일 또는 디렉터리일 때 빈 dict 반환
    assert load_local_contents_cache(None) == {}
    assert load_local_contents_cache(tmp_path / "missing.json") == {}
    assert load_local_contents_cache(tmp_path) == {}

    # 2) 손상된 JSON 또는 배열 JSON일 때 빈 dict 반환
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{corrupt", encoding="utf-8")
    assert load_local_contents_cache(bad_json) == {}
    bad_json.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_local_contents_cache(bad_json) == {}

    # 3) 유효한 엔트리와 무효한 엔트리(짧은 해시, bool size 등) 혼합 시 유효 엔트리만 로드
    valid_sha = "a" * 64
    mixed_cache = tmp_path / "mixed.json"
    mixed_cache.write_text(
        json.dumps(
            {
                "databases/contents/a.pdf": {
                    "project": "databases",
                    "name": "a.pdf",
                    "size_bytes": 100,
                    "mtime_ns": 123456,
                    "sha256": valid_sha,
                },
                "invalid_sha": {
                    "project": "databases",
                    "name": "b.pdf",
                    "size_bytes": 100,
                    "mtime_ns": 123456,
                    "sha256": "short",
                },
                "invalid_bool_size": {
                    "project": "databases",
                    "name": "c.pdf",
                    "size_bytes": True,
                    "mtime_ns": 123456,
                    "sha256": valid_sha,
                },
                "not_a_dict": "string_val",
            }
        ),
        encoding="utf-8",
    )
    loaded = load_local_contents_cache(mixed_cache)
    assert list(loaded.keys()) == ["databases/contents/a.pdf"]
    assert loaded["databases/contents/a.pdf"]["sha256"] == valid_sha

    # 4) save_local_contents_cache 원자적 저장 및 os.replace / write_text 실패 분기
    cache_out = tmp_path / "sub" / ".local_contents_cache.json"
    save_local_contents_cache(cache_out, loaded)
    assert cache_out.is_file()

    with (
        patch.object(Path, "replace", side_effect=OSError("disk full")),
        pytest.raises(SnapshotStorageError, match="로컬 해시 캐시 저장 실패"),
    ):
        save_local_contents_cache(cache_out, loaded)
    assert not (cache_out.parent / f".{cache_out.name}.tmp").exists()

    with (
        patch.object(Path, "write_bytes", side_effect=OSError("ro fs")),
        pytest.raises(SnapshotStorageError, match="로컬 해시 캐시 저장 실패"),
    ):
        save_local_contents_cache(cache_out, loaded)


def test_scan_workspace_contents_and_3way_comparison_and_report(tmp_path: Path):
    """고속 로컬 스캔(캐시 미스 -> 캐시 히트) 및 3-Way 정합성 비교·터미널 리포트 포매팅을 검증한다."""
    # 존재하지 않는 워크스페이스
    assert scan_workspace_contents(tmp_path / "no_ws") == ([], 0, 0)

    ws = tmp_path / "ws"
    (ws / ".hidden" / "contents").mkdir(parents=True)
    sha_matched = _make_pdf(ws / "databases" / "contents" / "친절한-SQL-튜닝.pdf", "sql book")
    _make_pdf(ws / "handcrafted-cpp" / "contents" / "로컬전용.pdf", "local cpp")
    cache_file = tmp_path / ".local_contents_cache.json"

    # 1차 스캔: 캐시 미스(recomputed=2, hits=0)
    entries1, hits1, recomp1 = scan_workspace_contents(ws, cache_path=cache_file)
    assert len(entries1) == 2
    assert hits1 == 0
    assert recomp1 == 2
    assert cache_file.is_file()

    # 2차 스캔: 파일 변경 없음 -> 캐시 히트(hits=2, recomputed=0), cache_path=None 분기 포함
    entries2, hits2, recomp2 = scan_workspace_contents(ws, cache_path=cache_file)
    assert len(entries2) == 2
    assert hits2 == 2
    assert recomp2 == 0
    entries_no_save, _, _ = scan_workspace_contents(ws, cache_path=None)
    assert len(entries_no_save) == 2

    # 3-Way 비교 (Matched 1, Drive Only 2(해시 있음 1 + 해시 없음 1), Local Only 1)
    drive_records = [
        {"id": "d1", "name": "친절한-SQL-튜닝.pdf", "folder_path": "DB", "sha256": sha_matched},
        {"id": "d2", "name": "드라이브전용.pdf", "folder_path": "CS", "sha256": "b" * 64},
        {"id": "d3", "name": "해시없는문서.pdf", "folder_path": "", "sha256": ""},
    ]
    comp = compare_drive_and_local(drive_records, entries2, cache_hits=hits2, recomputed=recomp2)
    assert len(comp.matched) == 1
    assert comp.matched[0].sha256 == sha_matched
    assert len(comp.drive_only) == 2
    assert len(comp.local_only) == 1

    report = format_sync_report(comp, len(drive_records), len(entries2))
    assert "양쪽 일치 1권 · 드라이브 전용 2권 · 로컬 전용 1개" in report
    assert "databases/contents/친절한-SQL-튜닝.pdf" in report
    assert "path=CS/드라이브전용.pdf" in report
    assert "path=해시없는문서.pdf" in report
    assert "handcrafted-cpp/contents/로컬전용.pdf" in report

    # 빈 결과 리포트 분기 검증
    empty_comp = compare_drive_and_local([], [])
    empty_report = format_sync_report(empty_comp, 0, 0)
    assert "양쪽 일치하는 도서가 없습니다." in empty_report
    assert "드라이브 전용 도서가 없습니다." in empty_report
    assert "로컬 전용 도서가 없습니다." in empty_report


def test_resolve_drive_record_and_pull_pdf_to_project(tmp_path: Path):
    """resolve_drive_record_for_pull의 모든 매칭·오류 분기와 pull_drive_pdf_to_project 다운로드를 검증한다."""
    ws = tmp_path / "ws"
    pdf_bytes = b"%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n"
    sha_sql = hashlib.sha256(pdf_bytes).hexdigest()

    records = [
        {"id": "id-sql", "name": "친절한-SQL-튜닝.pdf", "folder_path": "DB", "sha256": sha_sql},
        {"id": "id-cpp-1", "name": "A/B-C++.pdf", "folder_path": "CPP", "sha256": "c" * 64},
        {"id": "id-cpp-2", "name": "Effective-C++.pdf", "folder_path": "CPP", "sha256": "d" * 64},
        {"id": "id-dup-1", "name": "중복제목.pdf", "folder_path": "A", "sha256": "e" * 64},
        {"id": "id-dup-2", "name": "중복제목.pdf", "folder_path": "B", "sha256": "f" * 64},
    ]

    # 1) 빈 질의 오류
    with pytest.raises(ClassificationError, match="가져올 도서 식별자"):
        resolve_drive_record_for_pull(records, "   ")

    # 2) ID 정확 일치, SHA-256 정확 일치, 파일명(.pdf 유무) 정확 일치, 부분 문자열 유일 일치
    assert resolve_drive_record_for_pull(records, "id-sql")["id"] == "id-sql"
    assert resolve_drive_record_for_pull(records, sha_sql)["id"] == "id-sql"
    assert resolve_drive_record_for_pull(records, "친절한-SQL-튜닝")["id"] == "id-sql"
    assert resolve_drive_record_for_pull(records, "Effective")["id"] == "id-cpp-2"

    # 3) 동명 도서 복수 존재 및 부분 일치 복수 존재, 미존재 오류
    with pytest.raises(ClassificationError, match="동일한 이름의 도서가 2권"):
        resolve_drive_record_for_pull(records, "중복제목.pdf")
    with pytest.raises(ClassificationError, match="일치하는 도서가 2권"):
        resolve_drive_record_for_pull(records, "C++")
    with pytest.raises(ClassificationError, match="찾을 수 없습니다"):
        resolve_drive_record_for_pull(records, "존재하지않는책")

    # 4) pull_drive_pdf_to_project: 잘못된 프로젝트명 차단
    drive = MagicMock()
    drive.service = MagicMock()
    drive.service.files.return_value.get_media.return_value.execute.return_value = pdf_bytes

    with pytest.raises(ClassificationError, match="유효하지 않은 대상 프로젝트"):
        pull_drive_pdf_to_project(drive, records, "id-sql", "../escape", workspace_dir=ws)

    # 5) pull 정상 다운로드 (.pdf 확장자 자동 보정 + 캐시 갱신) 및 cache_path=None 분기
    cache_file = tmp_path / ".local_contents_cache.json"
    _rec, dest = pull_drive_pdf_to_project(
        drive,
        records,
        "id-sql",
        "databases",
        workspace_dir=ws,
        output_name="커스텀이름",
        cache_path=cache_file,
    )
    assert dest == ws / "databases" / "contents" / "커스텀이름.pdf"
    assert dest.read_bytes() == pdf_bytes
    assert cache_file.is_file()

    # sha256가 비어 있는 레코드 다운로드 및 cache_path=None 분기
    records_no_sha = [{"id": "id-nosha", "name": "nosha.pdf", "folder_path": "", "sha256": ""}]
    _, dest2 = pull_drive_pdf_to_project(
        drive,
        records_no_sha,
        "id-nosha",
        "databases",
        workspace_dir=ws,
        cache_path=None,
    )
    assert dest2.is_file()

    # 6) Drive 서비스 미활성화, API 예외, SHA-256 불일치 시 DriveListError 검증
    drive_no_svc = MagicMock(service=None)
    with pytest.raises(DriveListError, match="활성화되지 않았습니다"):
        pull_drive_pdf_to_project(drive_no_svc, records, "id-sql", "databases", workspace_dir=ws)

    drive_err = MagicMock()
    drive_err.service.files.return_value.get_media.return_value.execute.side_effect = RuntimeError("net fail")
    with pytest.raises(DriveListError, match="다운로드 실패"):
        pull_drive_pdf_to_project(drive_err, records, "id-sql", "databases", workspace_dir=ws)

    drive_bad_sha = MagicMock()
    drive_bad_sha.service.files.return_value.get_media.return_value.execute.return_value = b"corrupted"
    with pytest.raises(DriveListError, match="SHA-256 해시가 스냅샷과 일치하지 않습니다"):
        pull_drive_pdf_to_project(drive_bad_sha, records, "id-sql", "databases", workspace_dir=ws)


def test_cli_sync_and_pull_commands(tmp_path: Path):
    """CLI `doctree sync` 및 `doctree pull` 명령의 성공(0) 및 실패(1) 흐름을 검증한다."""
    ws = tmp_path / "ws"
    pdf_bytes = b"%PDF-1.7\n(sync test)\n%%EOF\n"
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    (ws / "databases" / "contents").mkdir(parents=True)
    (ws / "databases" / "contents" / "친절한-SQL-튜닝.pdf").write_bytes(pdf_bytes)

    snaps_dir = tmp_path / "snapshots"
    snaps_dir.mkdir()
    snap_file = snaps_dir / "2026-10-28.json"
    snap_file.write_text(
        json.dumps(
            {
                "count": 1,
                "records": [
                    {
                        "id": "b1",
                        "name": "친절한-SQL-튜닝.pdf",
                        "folder_path": "DB",
                        "size_bytes": len(pdf_bytes),
                        "sha256": sha,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    buf = io.StringIO()
    test_console = Console(file=buf, width=120, force_terminal=False, color_system=None)

    with patch.object(cli, "console", test_console):
        # 1) sync (최신 스냅샷 자동 탐색 및 --snapshot 명시)
        assert (
            cli.main(
                [
                    "sync",
                    "--snapshots-dir",
                    str(snaps_dir),
                    "--workspace-dir",
                    str(ws),
                ]
            )
            == 0
        )
        assert "양쪽 일치 1권" in buf.getvalue()

        buf.truncate(0)
        buf.seek(0)
        assert (
            cli.main(
                [
                    "sync",
                    "--snapshot",
                    str(snap_file),
                    "--workspace-dir",
                    str(ws),
                    "--cache-file",
                    str(tmp_path / "explicit_cache.json"),
                ]
            )
            == 0
        )
        assert "양쪽 일치 1권" in buf.getvalue()

        with patch("doctree.doctree_cli.command_dispatcher.SNAPSHOTS_DIR", str(snaps_dir)), \
                patch("doctree.doctree_cli.command_dispatcher.LOCAL_CONTENTS_CACHE_FILE", str(tmp_path / "default_cache.json")):
            assert cli.main(["sync", "--workspace-dir", str(ws)]) == 0
            assert cli.main(["sync", "--snapshot", str(snap_file), "--workspace-dir", str(ws)]) == 0

        # 2) 스냅샷이 없는 빈 폴더에서 sync 실패 (종료 코드 1)
        empty_snaps = tmp_path / "empty_snaps"
        assert cli.main(["sync", "--snapshots-dir", str(empty_snaps), "--workspace-dir", str(ws)]) == 1

        # 3) pull 성공 및 인증 실패 시 종료 코드 1
        fake_drive = MagicMock()
        fake_drive.service = MagicMock()
        fake_drive.service.files.return_value.get_media.return_value.execute.return_value = pdf_bytes
        buf.truncate(0)
        buf.seek(0)
        with patch("doctree.doctree_cli.command_dispatcher.build_drive", return_value=fake_drive):
            assert (
                cli.main(
                    [
                        "pull",
                        "b1",
                        "handcrafted-cpp",
                        "--snapshots-dir",
                        str(snaps_dir),
                        "--workspace-dir",
                        str(ws),
                    ]
                )
                == 0
            )
        assert "📥 도서 가져오기 완료:" in buf.getvalue()
        assert (ws / "handcrafted-cpp" / "contents" / "친절한-SQL-튜닝.pdf").is_file()

        unauth_drive = MagicMock(service=None)
        with patch("doctree.doctree_cli.command_dispatcher.build_drive", return_value=unauth_drive):
            assert (
                cli.main(
                    [
                        "pull",
                        "b1",
                        "handcrafted-cpp",
                        "--snapshots-dir",
                        str(snaps_dir),
                        "--workspace-dir",
                        str(ws),
                    ]
                )
                == 1
            )
