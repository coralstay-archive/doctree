import os
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
from src.google_drive import GoogleDriveManager


class TestGoogleDriveManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_without_credentials(self):
        non_existent = os.path.join(self.temp_dir, "non_existent.json")
        drive = GoogleDriveManager(service_account_file=non_existent, folder_id="folder_123")
        self.assertIsNone(drive.service)
        self.assertEqual(drive.folder_id, "folder_123")

    @patch("src.google_drive.GOOGLE_API_AVAILABLE", True)
    @patch("src.google_drive.service_account")
    @patch("src.google_drive.build")
    @patch("os.path.exists")
    @patch("builtins.open")
    @patch("json.load")
    def test_init_with_credentials(self, mock_json_load, mock_open, mock_exists, mock_build, mock_sa):
        mock_exists.return_value = True
        mock_json_load.return_value = {"type": "service_account"}
        mock_creds = MagicMock()
        mock_sa.Credentials.from_service_account_file.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        drive = GoogleDriveManager(service_account_file="credentials.json", folder_id="folder_123")
        self.assertEqual(drive.service, mock_service)

    def test_list_pdf_files_service_none(self):
        drive = GoogleDriveManager(service_account_file="fake.json")
        drive.service = None
        files = drive.list_pdf_files()
        self.assertEqual(files, [])

    def test_list_pdf_files_success(self):
        drive = GoogleDriveManager(folder_id="target_folder")
        mock_service = MagicMock()
        mock_files_resource = MagicMock()
        mock_list_req = MagicMock()
        mock_list_req.execute.return_value = {
            "files": [
                {"id": "file_1", "name": "book1.pdf", "mimeType": "application/pdf", "parents": ["target_folder"], "size": "10485760"},
                {"id": "file_2", "name": "book2.pdf", "mimeType": "application/pdf", "parents": ["target_folder"], "size": "20971520"}
            ]
        }
        mock_files_resource.list.return_value = mock_list_req
        mock_service.files.return_value = mock_files_resource
        drive.service = mock_service

        files = drive.list_pdf_files()
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["name"], "book1.pdf")
        self.assertEqual(files[0]["relative_path"], "book1.pdf")
        self.assertEqual(files[1]["id"], "file_2")

    def test_list_pdf_files_nested_folders(self):
        drive = GoogleDriveManager(folder_id=None) # 루트 전체 탐색
        mock_service = MagicMock()
        mock_files_resource = MagicMock()
        mock_list_req = MagicMock()
        mock_list_req.execute.return_value = {
            "files": [
                {"id": "folder_root", "name": "책들", "mimeType": "application/vnd.google-apps.folder", "parents": ["root"]},
                {"id": "folder_sub", "name": "책박스9번", "mimeType": "application/vnd.google-apps.folder", "parents": ["folder_root"]},
                {"id": "file_1", "name": "클린코드.pdf", "mimeType": "application/pdf", "parents": ["folder_sub"], "size": "10485760"}
            ]
        }
        mock_files_resource.list.return_value = mock_list_req
        mock_service.files.return_value = mock_files_resource
        drive.service = mock_service

        files = drive.list_pdf_files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "클린코드.pdf")
        self.assertEqual(files[0]["relative_path"], "책들/책박스9번/클린코드.pdf")

    @patch.object(GoogleDriveManager, "list_pdf_files")
    @patch("src.google_drive.MediaIoBaseDownload")
    @patch("src.google_drive.is_valid_pdf_file", return_value=True)
    def test_download_new_pdfs(self, mock_is_valid, mock_downloader_cls, mock_list):
        mock_list.return_value = [
            {"id": "file_1", "name": "book1.pdf"},
            {"id": "file_2", "name": "book2.pdf"}
        ]

        # First file doesn't exist, second file already exists
        existing_file = Path(self.temp_dir) / "book2.pdf"
        existing_file.write_bytes(b"%PDF-1.4 dummy content")

        mock_downloader_instance = MagicMock()
        # next_chunk returns (status, done)
        mock_status = MagicMock()
        mock_status.progress.return_value = 1.0
        mock_downloader_instance.next_chunk.return_value = (mock_status, True)
        mock_downloader_cls.return_value = mock_downloader_instance

        drive = GoogleDriveManager()
        drive.service = MagicMock()

        downloaded = drive.download_new_pdfs(self.temp_dir)

        self.assertEqual(len(downloaded), 2)
        self.assertTrue((Path(self.temp_dir) / "book1.pdf").exists())
        self.assertTrue((Path(self.temp_dir) / "book2.pdf").exists())

    def test_get_account_and_quota(self):
        drive = GoogleDriveManager()
        mock_service = MagicMock()
        mock_about_req = MagicMock()
        mock_about_req.execute.return_value = {
            "user": {"displayName": "Test User", "emailAddress": "test@example.com"},
            "storageQuota": {"limit": str(100 * 1024**3), "usage": str(50 * 1024**3), "usageInDrive": str(40 * 1024**3)}
        }
        mock_service.about.return_value.get.return_value = mock_about_req
        drive.service = mock_service

        account = drive.get_account_and_quota()
        self.assertIsNotNone(account)
        self.assertEqual(account["name"], "Test User")
        self.assertEqual(account["email"], "test@example.com")
        self.assertEqual(account["limit_gb"], 100.0)
        self.assertEqual(account["usage_gb"], 50.0)
        self.assertEqual(account["usage_percent"], 50.0)

    def test_check_changes(self):
        drive = GoogleDriveManager()
        mock_service = MagicMock()
        mock_start_token_req = MagicMock()
        mock_start_token_req.execute.return_value = {"startPageToken": "token_123"}
        mock_service.changes.return_value.getStartPageToken.return_value = mock_start_token_req

        mock_changes_req = MagicMock()
        mock_changes_req.execute.return_value = {
            "changes": [
                {"fileId": "file_new", "removed": False, "file": {"id": "file_new", "name": "new.pdf", "mimeType": "application/pdf"}}
            ],
            "newStartPageToken": "token_456"
        }
        mock_service.changes.return_value.list.return_value = mock_changes_req
        drive.service = mock_service

        # First call with no existing sync token
        sync_token_path = Path(self.temp_dir) / ".drive_sync_token"
        drive.sync_token_file = sync_token_path

        changes, token = drive.check_changes()
        self.assertEqual(token, "token_123")
        self.assertEqual(changes, [])

        # Second call with existing sync token
        changes, next_token = drive.check_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(next_token, "token_456")


if __name__ == "__main__":
    unittest.main()
