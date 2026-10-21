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


class TestListingOnly(unittest.TestCase):
    """KBI-2#2 다운로드·Changes API·로컬 MD5 대조 코드 제거."""

    SRC = Path(__file__).resolve().parent.parent / "src" / "google_drive.py"

    def test_kbi_2_2_download_and_changes_api_removed(self):
        """KBI-2#2 download_new_pdfs·get_start_page_token·check_changes·sync_token_file이 없다."""
        for attr in ("download_new_pdfs", "get_start_page_token", "check_changes"):
            self.assertFalse(hasattr(GoogleDriveManager, attr), attr)
        drive = make_drive([])
        self.assertFalse(hasattr(drive, "sync_token_file"))

    def test_kbi_2_2_local_md5_helpers_removed(self):
        """KBI-2#2 로컬 MD5 대조 헬퍼(calculate_file_md5·is_valid_pdf_file)가 없다."""
        import src.google_drive as gd
        for name in ("calculate_file_md5", "is_valid_pdf_file", "MediaIoBaseDownload"):
            self.assertFalse(hasattr(gd, name), name)

    def test_kbi_2_2_source_has_no_download_or_changes_calls(self):
        """KBI-2#2 소스에 get_media·changes()·.drive_sync_token 참조가 남아 있지 않다."""
        text = self.SRC.read_text()
        for needle in ("get_media", "changes()", ".drive_sync_token", "MediaIoBaseDownload", "hashlib"):
            self.assertNotIn(needle, text)

    def test_kbi_2_2_auth_and_quota_kept(self):
        """KBI-2#2 인증(_authenticate·token_file)과 get_account_and_quota는 유지된다."""
        self.assertTrue(callable(getattr(GoogleDriveManager, "_authenticate", None)))
        self.assertTrue(callable(getattr(GoogleDriveManager, "get_account_and_quota", None)))
        self.assertEqual(make_drive([]).token_file.name, "token.json")


class TestSlashInFileName(unittest.TestCase):
    """KBI-2#3 KBI-2#B1 파일명 속 '/'는 폴더 구분자가 아니다."""

    ITEMS = [
        {"id": "f_kb", "name": "knowledge-base", "mimeType": FOLDER, "parents": ["root_id"]},
        {"id": "f_raw", "name": "raw-data", "mimeType": FOLDER, "parents": ["f_kb"]},
        {"id": "ab", "name": "A/B-테스트", "mimeType": PDF, "parents": ["f_raw"]},
        {"id": "c", "name": "C/D/E.pdf", "mimeType": PDF, "parents": ["root_id"]},
    ]

    def test_kbi_2_3_slash_name_split_correctly(self):
        """KBI-2#3 KBI-2#B1 knowledge-base/raw-data 안의 'A/B-테스트' → folder_path와 name이 올바르게 분리된다."""
        files = {f["id"]: f for f in make_drive(self.ITEMS).list_pdf_files()}
        self.assertEqual(files["ab"]["folder_path"], "knowledge-base/raw-data")
        self.assertEqual(files["ab"]["name"], "A/B-테스트")

    def test_kbi_2_b1_folder_path_only_from_parent_folders(self):
        """KBI-2#B1 KBI-2#3 folder_path는 상위 폴더 이름만으로 만들며 파일명을 쪼개지 않는다 (루트 파일 'C/D/E.pdf' → "")."""
        files = {f["id"]: f for f in make_drive(self.ITEMS).list_pdf_files()}
        self.assertEqual(files["c"]["folder_path"], "")
        self.assertEqual(files["c"]["name"], "C/D/E.pdf")
        self.assertNotIn("knowledge-base/raw-data/A", {f["folder_path"] for f in files.values()})

    def test_kbi_2_b1_slash_in_folder_name_kept_whole(self):
        """KBI-2#B1 KBI-2#3 폴더 이름의 '/'도 이름 그대로 이어붙일 뿐 별도 해석하지 않는다."""
        items = [
            {"id": "f1", "name": "I/O", "mimeType": FOLDER, "parents": ["root_id"]},
            {"id": "b", "name": "b.pdf", "mimeType": PDF, "parents": ["f1"]},
        ]
        self.assertEqual(make_drive(items).list_pdf_files()[0]["folder_path"], "I/O")


class TestScope(unittest.TestCase):
    """KBI-2#4 KBI-2#B3 GOOGLE_DRIVE_FOLDER_ID 범위와 휴지통 제외."""

    ITEMS = [
        {"id": "f_kb", "name": "knowledge-base", "mimeType": FOLDER, "parents": ["root_id"]},
        {"id": "f_raw", "name": "raw-data", "mimeType": FOLDER, "parents": ["f_kb"]},
        {"id": "f_lang", "name": "어학", "mimeType": FOLDER, "parents": ["f_raw"]},
        {"id": "f_other", "name": "Saved from Chrome", "mimeType": FOLDER, "parents": ["root_id"]},
        {"id": "in_raw", "name": "raw.pdf", "mimeType": PDF, "parents": ["f_raw"]},
        {"id": "in_lang", "name": "lang.pdf", "mimeType": PDF, "parents": ["f_lang"]},
        {"id": "in_other", "name": "other.pdf", "mimeType": PDF, "parents": ["f_other"]},
        {"id": "at_root", "name": "root.pdf", "mimeType": PDF, "parents": ["root_id"]},
        {"id": "shared", "name": "shared.pdf", "mimeType": PDF, "parents": ["unknown_folder"]},
        {"id": "orphan", "name": "orphan.pdf", "mimeType": PDF},
    ]

    def paths(self, folder_id):
        return {f["id"]: f["folder_path"] for f in make_drive(self.ITEMS, folder_id=folder_id).list_pdf_files()}

    def test_kbi_2_4_folder_id_limits_to_subtree(self):
        """KBI-2#4 folder_id가 지정되면 그 폴더의 하위 트리만, 그 폴더 기준 상대 경로로 반환한다."""
        self.assertEqual(self.paths("f_raw"), {"in_raw": "", "in_lang": "어학"})

    def test_kbi_2_4_folder_id_excludes_unknown_parents(self):
        """KBI-2#4 folder_id가 지정되면 부모를 알 수 없는 공유 항목·부모 없는 항목은 제외한다."""
        paths = self.paths("f_kb")
        self.assertEqual(paths, {"in_raw": "raw-data", "in_lang": "raw-data/어학"})

    def test_kbi_2_4_whole_drive_when_folder_id_empty(self):
        """KBI-2#4 folder_id가 비어 있으면(None·"") 드라이브 전체를 내 드라이브 루트 기준 경로로 반환한다."""
        expected = {
            "in_raw": "knowledge-base/raw-data",
            "in_lang": "knowledge-base/raw-data/어학",
            "in_other": "Saved from Chrome",
            "at_root": "",
            "shared": "",
            "orphan": "",
        }
        self.assertEqual(self.paths(None), expected)
        self.assertEqual(self.paths(""), expected)

    def test_kbi_2_4_cyclic_parents_do_not_hang(self):
        """KBI-2#4 폴더 부모 관계가 순환해도 무한 루프 없이 끝난다."""
        items = [
            {"id": "x", "name": "x", "mimeType": FOLDER, "parents": ["y"]},
            {"id": "y", "name": "y", "mimeType": FOLDER, "parents": ["x"]},
            {"id": "b", "name": "b.pdf", "mimeType": PDF, "parents": ["x"]},
        ]
        self.assertEqual(len(make_drive(items).list_pdf_files()), 1)
        self.assertEqual(make_drive(items, folder_id="z").list_pdf_files(), [])

    def test_kbi_2_b3_query_excludes_trashed(self):
        """KBI-2#B3 KBI-2#4 files().list 쿼리 q에 trashed=false가 들어가 휴지통 파일을 제외한다."""
        for folder_id in (None, "f_raw"):
            drive = make_drive(self.ITEMS, folder_id=folder_id)
            drive.list_pdf_files()
            self.assertIn("trashed=false", list_kwargs(drive)["q"].replace(" ", ""))


if __name__ == "__main__":
    unittest.main()
