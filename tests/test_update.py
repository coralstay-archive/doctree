"""doctree update 명령 검증 (KBI-6#1, KBI-6#B2)."""
import contextlib
import io
import tempfile
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from src import cli
from src.google_drive import DriveListError, GoogleDriveManager

KST = timezone(timedelta(hours=9), "KST")
NOW = datetime(2026, 10, 21, 22, 30, tzinfo=KST)

ACCOUNT = {"name": "tester", "email": "t@example.com", "limit_gb": 100.0, "usage_gb": 70.0,
           "drive_usage_gb": 68.0, "usage_percent": 70.0}

CATEGORIES_YAML = """\
categories:
  컴퓨터 과학:
    알고리즘:
      - 종만북-1권
"""


def _rec(id_, name, folder="books", size=1_000_000, md5=None):
    return {"id": id_, "name": name, "folder_path": folder, "size_bytes": size,
            "md5": md5 if md5 is not None else f"md5-{id_}", "modified_time": "2026-01-01T00:00:00Z",
            "web_view_link": f"https://drive/{id_}"}


def _console(out):
    return patch("src.cli.console", Console(file=out, width=200, color_system=None))


RECORDS = [_rec("a", "종만북-1권.pdf"), _rec("b", "모르는책.pdf")]


class UpdateTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = self.tmp / "ledger"
        self.cats = self.tmp / "categories.yaml"
        self.cats.write_text(textwrap.dedent(CATEGORIES_YAML), encoding="utf-8")
        p_cats = patch("src.cli.CATEGORIES_FILE", str(self.cats))
        p_now = patch("src.cli._now", return_value=NOW)
        p_cats.start()
        p_now.start()
        self.addCleanup(p_cats.stop)
        self.addCleanup(p_now.stop)

    def _drive(self, records=RECORDS, service=True, account=ACCOUNT, error=None):
        drive = MagicMock()
        drive.service = MagicMock() if service else None
        drive.get_account_and_quota.return_value = account
        if error is not None:
            drive.list_pdf_files.side_effect = error
        else:
            drive.list_pdf_files.return_value = list(records)
        return drive

    def run_update(self, drive, *extra):
        out = io.StringIO()
        with patch("src.cli.build_drive", return_value=drive), \
                _console(out), contextlib.redirect_stdout(out):
            code = cli.main(["update", "--ledger-dir", str(self.ledger), *extra])
        return code, out.getvalue()

    def ledger_files(self):
        if not self.ledger.exists():
            return {}
        return {str(p.relative_to(self.ledger)): p.read_bytes() for p in self.ledger.rglob("*") if p.is_file()}


class TestUpdateCommand(UpdateTestBase):
    def test_kbi_6_1_update_listed_in_help(self):
        """KBI-6#1 doctree --help에 update 명령이 보인다."""
        self.assertIn("update", cli.build_parser().format_help())

    def test_kbi_6_1_update_writes_ledger_snapshot_and_changelog(self):
        """KBI-6#1 update는 조회 → 분류 → 점검 → 스냅샷/이력 → ledger/도서목록.md를 만든다."""
        code, out = self.run_update(self._drive())
        self.assertEqual(code, 0, out)
        ledger_md = self.ledger / "도서목록.md"
        self.assertTrue(ledger_md.exists())
        self.assertTrue((self.ledger / "변경이력.md").exists())
        self.assertTrue((self.ledger / "snapshots" / "2026-10-21.json").exists())
        text = ledger_md.read_text(encoding="utf-8")
        self.assertIn("종만북 1권", text)
        self.assertIn("미분류", text)

    def test_kbi_6_1_ledger_header_shows_local_time_with_timezone(self):
        """KBI-6#1 대장 머리에 로컬 기준 시각과 시간대(KST, UTC+09:00)가 나온다."""
        self.run_update(self._drive())
        text = (self.ledger / "도서목록.md").read_text(encoding="utf-8")
        self.assertIn("2026-10-21 22:30", text)
        self.assertIn("KST", text)
        self.assertIn("UTC+09:00", text)

    def test_kbi_6_1_default_ledger_dir_from_settings(self):
        """KBI-6#1 --ledger-dir가 없으면 settings.LEDGER_DIR에 쓴다."""
        out = io.StringIO()
        with patch("src.cli.LEDGER_DIR", str(self.ledger)), \
                patch("src.cli.build_drive", return_value=self._drive()), \
                _console(out):
            self.assertEqual(cli.main(["update"]), 0)
        self.assertTrue((self.ledger / "도서목록.md").exists())

    def test_kbi_6_1_console_summary(self):
        """KBI-6#1 성공하면 총 권수·분류/미분류·경고 수·변경 요약·출력 경로를 콘솔에 요약한다."""
        code, out = self.run_update(self._drive())
        self.assertEqual(code, 0)
        flat = " ".join(out.split())
        self.assertIn("총 2권", flat)
        self.assertIn("분류 1권", flat)
        self.assertIn("미분류 1권", flat)
        self.assertIn("경고 0건", flat)
        self.assertIn("최초 등록 2권", flat)
        self.assertIn("도서목록.md", flat)
        self.assertIn("변경이력.md", flat)

    def test_kbi_6_1_output_paths_not_wrapped(self):
        """KBI-6#1 좁은 터미널에서도 출력 경로가 줄바꿈으로 잘리지 않아 복사할 수 있다."""
        out = io.StringIO()
        with patch("src.cli.build_drive", return_value=self._drive()), \
                patch("src.cli.console", Console(file=out, width=30, color_system=None)):
            self.assertEqual(cli.main(["update", "--ledger-dir", str(self.ledger)]), 0)
        self.assertIn(str(self.ledger / "도서목록.md"), out.getvalue())
        self.assertIn(str(self.ledger / "변경이력.md"), out.getvalue())

    def test_kbi_6_1_second_run_reports_no_changes(self):
        """KBI-6#1 같은 목록으로 다시 돌리면 '변경 없음'으로 요약한다."""
        self.run_update(self._drive())
        code, out = self.run_update(self._drive())
        self.assertEqual(code, 0)
        self.assertIn("변경 없음", out)
        self.assertIn("변경 없음", (self.ledger / "도서목록.md").read_text(encoding="utf-8"))


class TestUpdateFailureKeepsLedger(UpdateTestBase):
    """KBI-6#B2 인증·조회·분류 설정 실패 시 기존 대장·스냅샷·이력을 덮어쓰지 않고 오류로 끝난다."""

    def setUp(self):
        super().setUp()
        code, out = self.run_update(self._drive())
        self.assertEqual(code, 0, out)
        self.before = self.ledger_files()
        self.assertIn("도서목록.md", self.before)
        patcher = patch("src.cli._now", return_value=NOW + timedelta(days=1))
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_untouched(self, code, out, expect):
        self.assertNotEqual(code, 0)
        self.assertIn(expect, out)
        self.assertEqual(self.ledger_files(), self.before)

    def test_kbi_6_b2_auth_failure(self):
        """KBI-6#B2 KBI-6#1 인증 실패(service None)면 아무것도 쓰지 않고 실패한다."""
        code, out = self.run_update(self._drive(service=False))
        self.assert_untouched(code, out, "인증")

    def test_kbi_6_b2_listing_error(self):
        """KBI-6#B2 KBI-6#1 목록 조회 API 오류면 아무것도 쓰지 않고 실패한다."""
        code, out = self.run_update(self._drive(error=DriveListError("boom")))
        self.assert_untouched(code, out, "조회")

    def test_kbi_6_b2_zero_records(self):
        """KBI-6#B2 KBI-6#1 인증은 됐지만 PDF가 0개면 빈 대장 방지를 위해 실패로 본다."""
        code, out = self.run_update(self._drive(records=[]))
        self.assert_untouched(code, out, "0개")

    def test_kbi_6_b2_category_config_error(self):
        """KBI-6#B2 KBI-6#1 categories.yaml 오류(CategoryConfigError)면 아무것도 쓰지 않고 실패한다."""
        self.cats.write_text("categories:\n  A:\n    a:\n      - 같은책\n    b:\n      - 같은-책\n", encoding="utf-8")
        code, out = self.run_update(self._drive())
        self.assert_untouched(code, out, "같은책")

    def test_kbi_6_b2_first_run_failure_creates_nothing(self):
        """KBI-6#B2 최초 실행에서 실패해도 ledger 디렉터리에 아무것도 만들지 않는다."""
        empty = self.tmp / "fresh"
        out = io.StringIO()
        with patch("src.cli.build_drive", return_value=self._drive(service=False)), \
                _console(out), contextlib.redirect_stdout(out):
            code = cli.main(["update", "--ledger-dir", str(empty)])
        self.assertNotEqual(code, 0)
        self.assertFalse(empty.exists())


class TestListPdfFilesRaises(unittest.TestCase):
    def test_kbi_6_b2_list_pdf_files_raises_on_api_error(self):
        """KBI-6#B2 목록 API 오류는 빈 목록 대신 DriveListError로 올라온다 (빈 대장 방지)."""
        drive = GoogleDriveManager(service_account_file=str(Path(tempfile.mkdtemp()) / "none.json"))
        service = MagicMock()
        service.files.return_value.list.return_value.execute.side_effect = RuntimeError("quota")
        drive.service = service
        with self.assertRaises(DriveListError) as ctx:
            drive.list_pdf_files()
        self.assertIn("quota", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
