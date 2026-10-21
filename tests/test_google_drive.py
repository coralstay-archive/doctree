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
        self.assertEqual(files[0]["folder_path"], "")
        self.assertEqual(files[1]["id"], "file_2")

    def test_list_pdf_files_nested_folders(self):
        drive = GoogleDriveManager(folder_id=None) # 루트 전체 탐색
        drive.folder_id = None  # .env의 GOOGLE_DRIVE_FOLDER_ID 영향 차단
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
        self.assertEqual(files[0]["folder_path"], "책들/책박스9번")

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


FOLDER = "application/vnd.google-apps.folder"
PDF = "application/pdf"


def make_drive(items, folder_id=None, pages=None):
    """Drive API service를 MagicMock으로 대체한 GoogleDriveManager를 만든다.

    pages가 주어지면 files().list().execute()가 페이지별 응답을 차례로 돌려준다.
    """
    tmp = tempfile.mkdtemp()
    drive = GoogleDriveManager(service_account_file=os.path.join(tmp, "none.json"))
    shutil.rmtree(tmp, ignore_errors=True)
    drive.folder_id = folder_id
    service = MagicMock()
    req = MagicMock()
    if pages is not None:
        req.execute.side_effect = pages
    else:
        req.execute.return_value = {"files": items}
    service.files.return_value.list.return_value = req
    drive.service = service
    return drive


def list_kwargs(drive):
    """files().list() 첫 호출의 키워드 인자."""
    return drive.service.files.return_value.list.call_args_list[0].kwargs


class TestRecordShape(unittest.TestCase):
    """KBI-2#1 목록 레코드 형태."""

    ITEMS = [
        {"id": "f_kb", "name": "knowledge-base", "mimeType": FOLDER, "parents": ["root_id"]},
        {"id": "f_raw", "name": "raw-data", "mimeType": FOLDER, "parents": ["f_kb"]},
        {
            "id": "b2", "name": "\u1112\u1161\u11ab.pdf", "mimeType": PDF, "parents": ["f_raw"],
            "size": "2048", "md5Checksum": "abc123", "modifiedTime": "2026-01-02T03:04:05.000Z",
            "webViewLink": "https://drive.google.com/file/d/b2/view",
        },
        {"id": "b1", "name": "a.pdf", "mimeType": PDF, "parents": ["f_raw"]},
        {"id": "b0", "name": "z.pdf", "mimeType": PDF, "parents": ["root_id"], "size": "1"},
    ]

    def test_kbi_2_1_record_has_exact_keys(self):
        """KBI-2#1 레코드는 정확히 id·name·folder_path·size_bytes·md5·modified_time·web_view_link 키를 갖는다."""
        files = make_drive(self.ITEMS).list_pdf_files()
        self.assertEqual(len(files), 3)
        for f in files:
            self.assertEqual(
                set(f.keys()),
                {"id", "name", "folder_path", "size_bytes", "md5", "modified_time", "web_view_link"},
            )

    def test_kbi_2_1_record_values_and_types(self):
        """KBI-2#1 size_bytes는 int, md5는 str(없으면 ""), modified_time은 Drive RFC3339 문자열 그대로, 이름은 NFC."""
        files = {f["id"]: f for f in make_drive(self.ITEMS).list_pdf_files()}
        b2 = files["b2"]
        self.assertEqual(b2["name"], "한.pdf")
        self.assertEqual(b2["folder_path"], "knowledge-base/raw-data")
        self.assertEqual(b2["size_bytes"], 2048)
        self.assertIsInstance(b2["size_bytes"], int)
        self.assertEqual(b2["md5"], "abc123")
        self.assertEqual(b2["modified_time"], "2026-01-02T03:04:05.000Z")
        self.assertEqual(b2["web_view_link"], "https://drive.google.com/file/d/b2/view")
        b1 = files["b1"]
        self.assertEqual(b1["size_bytes"], 0)
        self.assertEqual(b1["md5"], "")
        self.assertEqual(b1["modified_time"], "")
        self.assertEqual(b1["web_view_link"], "")

    def test_kbi_2_1_requests_web_view_link_field(self):
        """KBI-2#1 files().list fields에 webViewLink·md5Checksum·modifiedTime·size를 요청한다."""
        drive = make_drive(self.ITEMS)
        drive.list_pdf_files()
        fields = list_kwargs(drive)["fields"]
        for name in ("webViewLink", "md5Checksum", "modifiedTime", "size", "parents", "mimeType"):
            self.assertIn(name, fields)

    def test_kbi_2_1_sorted_by_folder_path_then_name(self):
        """KBI-2#1 결과는 (folder_path, name) 순으로 결정적으로 정렬된다."""
        files = make_drive(self.ITEMS).list_pdf_files()
        self.assertEqual([(f["folder_path"], f["name"]) for f in files], [
            ("", "z.pdf"),
            ("knowledge-base/raw-data", "a.pdf"),
            ("knowledge-base/raw-data", "한.pdf"),
        ])

    def test_kbi_2_1_paginates(self):
        """KBI-2#1 nextPageToken을 따라 모든 페이지를 수집한다."""
        drive = make_drive(None, pages=[
            {"files": [{"id": "p1", "name": "p1.pdf", "mimeType": PDF, "parents": ["root_id"]}], "nextPageToken": "t2"},
            {"files": [{"id": "p2", "name": "p2.pdf", "mimeType": PDF, "parents": ["root_id"]}]},
        ])
        self.assertEqual([f["id"] for f in drive.list_pdf_files()], ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
