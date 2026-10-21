"""booktree CLI 검증 (KBI-1#3, KBI-1#B1)."""
import contextlib
import io
import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.ui as ui
from config.settings import BASE_DIR, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SERVICE_ACCOUNT_FILE
from src import cli
from src.google_drive import GoogleDriveManager

ROOT = Path(__file__).resolve().parent.parent

ACCOUNT = {"name": "tester", "email": "t@example.com", "limit_gb": 15, "usage_gb": 3, "usage_percent": 20.0, "drive_usage_gb": 2}


def _section(text: str, header: str) -> str:
    m = re.search(rf"^\[{re.escape(header)}\]\s*$(.*?)(?=^\[|\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


class TestPackaging(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "pyproject.toml").read_text()

    def test_kbi_1_3_package_name(self):
        """KBI-1#3 패키지명은 booktree다."""
        self.assertRegex(_section(self.text, "project"), r'(?m)^name\s*=\s*"booktree"\s*$')

    def test_kbi_1_3_single_booktree_entry_point(self):
        """KBI-1#3 CLI 진입점은 booktree 하나이고 옛 진입점은 없다."""
        scripts = _section(self.text, "project.scripts")
        entries = dict(re.findall(r'(?m)^\s*"?([\w\-]+)"?\s*=\s*"([^"]+)"', scripts))
        self.assertEqual(entries, {"booktree": "src.cli:main"})
        for old in ("gdrive-book-markdown-pipeline", "gdrive-md", "book2md", "pdf2md", "kb" + "-index", "knowledge-base" + "-index"):
            self.assertNotIn(old, self.text)

    def test_kbi_1_3_setuptools_has_no_deleted_modules(self):
        """KBI-1#3 [tool.setuptools]에 삭제된 main·auth_login 모듈이 없다."""
        setuptools = _section(self.text, "tool.setuptools")
        self.assertNotIn("main", setuptools)
        self.assertNotIn("auth_login", setuptools)

    def test_kbi_1_3_no_old_names_left(self):
        """KBI-1#3 README·src·tests·pyproject에 옛 이름(kb·index 계열)이 남지 않는다."""
        old_names = ("kb" + "-index", "knowledge-base" + "-index")
        files = [ROOT / "README.md", ROOT / "pyproject.toml"]
        files += list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py"))
        for path in files:
            text = path.read_text()
            for old in old_names:
                self.assertNotIn(old, text, str(path))


class TestParser(unittest.TestCase):
    def test_kbi_1_3_help_lists_auth_and_status(self):
        """KBI-1#3 booktree --help에 auth·status 명령이 보인다."""
        parser = cli.build_parser()
        self.assertEqual(parser.prog, "booktree")
        help_text = parser.format_help()
        self.assertIn("auth", help_text)
        self.assertIn("status", help_text)

    def test_kbi_1_3_pipeline_commands_gone(self):
        """KBI-1#3 옛 파이프라인 서브커맨드(run·convert 등)는 없다."""
        parser = cli.build_parser()
        for old in ("run", "sync", "convert", "validate", "summarize", "assemble", "watch", "clean"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args([old])

    def test_kbi_1_3_command_required(self):
        """KBI-1#3 명령 없이 실행하면 사용법을 보여주고 실패한다."""
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            cli.main([])
        self.assertNotEqual(ctx.exception.code, 0)


class TestCommands(unittest.TestCase):
    def _fake_drive(self, service=True):
        drive = MagicMock()
        drive.service = MagicMock() if service else None
        drive.get_account_and_quota.return_value = ACCOUNT
        return drive

    @patch("src.cli.print_account_dashboard")
    @patch("src.cli.GoogleDriveManager")
    def test_kbi_1_3_auth_prints_account_dashboard(self, mock_cls, mock_dash):
        """KBI-1#3 booktree auth는 인증 후 계정 대시보드를 출력한다."""
        mock_cls.return_value = self._fake_drive()
        self.assertEqual(cli.main(["auth"]), 0)
        mock_dash.assert_called_once_with(ACCOUNT)

    @patch("src.cli.print_account_dashboard")
    @patch("src.cli.GoogleDriveManager")
    def test_kbi_1_3_status_prints_account_dashboard(self, mock_cls, mock_dash):
        """KBI-1#3 booktree status는 계정·용량 대시보드를 출력한다."""
        mock_cls.return_value = self._fake_drive()
        self.assertEqual(cli.main(["status"]), 0)
        mock_dash.assert_called_once_with(ACCOUNT)

    @patch("src.cli.print_account_dashboard")
    @patch("src.cli.GoogleDriveManager")
    def test_kbi_1_3_auth_and_status_fail_without_service(self, mock_cls, mock_dash):
        """KBI-1#3 인증이 안 되면 auth·status 모두 0이 아닌 코드로 끝난다."""
        mock_cls.return_value = self._fake_drive(service=False)
        for cmd in ("auth", "status"):
            self.assertNotEqual(cli.main([cmd]), 0)
        mock_dash.assert_not_called()

    def test_kbi_1_3_local_data_status_removed(self):
        """KBI-1#3 로컬 data/ 폴더 현황 UI는 제거됐다."""
        self.assertFalse(hasattr(ui, "print_local_status"))
        self.assertTrue(hasattr(ui, "print_account_dashboard"))


class TestCredentialLocation(unittest.TestCase):
    @patch("src.cli.print_account_dashboard")
    @patch("src.cli.GoogleDriveManager")
    def test_kbi_1_b1_auth_status_use_existing_credentials(self, mock_cls, _dash):
        """KBI-1#B1 KBI-1#3 auth·status는 기존 credentials.json 경로로 GoogleDriveManager를 만든다."""
        mock_cls.return_value = MagicMock(service=None)
        for cmd in ("auth", "status"):
            mock_cls.reset_mock()
            cli.main([cmd])
            mock_cls.assert_called_once_with(
                service_account_file=GOOGLE_SERVICE_ACCOUNT_FILE,
                folder_id=GOOGLE_DRIVE_FOLDER_ID,
            )

    @patch("src.google_drive.GOOGLE_API_AVAILABLE", False)
    def test_kbi_1_b1_token_path_unchanged(self):
        """KBI-1#B1 KBI-1#3 token.json 위치는 저장소 루트 그대로라 재로그인이 필요 없다."""
        drive = cli.build_drive()
        self.assertIsInstance(drive, GoogleDriveManager)
        self.assertEqual(Path(drive.token_file).resolve(), (BASE_DIR / "token.json").resolve())
        self.assertEqual(Path(drive.service_account_file).resolve(), (BASE_DIR / "credentials.json").resolve())


if __name__ == "__main__":
    unittest.main()
