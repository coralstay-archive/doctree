"""중복·파일명 점검 (KBI-5)."""
import copy
import inspect
import types
import unittest
from unittest import mock

from src import checks


def _rec(id_, name, folder="IT/개발", md5="m", size=1):
    return {
        "id": id_,
        "name": name,
        "folder_path": folder,
        "size_bytes": size,
        "md5": md5,
        "modified_time": "2026-01-01T00:00:00Z",
        "web_view_link": f"https://drive/{id_}",
    }


def _ids(w):
    return [f["id"] for f in w.files]


class TestExactDuplicates(unittest.TestCase):
    def test_kbi_5_1_groups_same_md5(self):
        """KBI-5#1 MD5가 같은 파일 묶음마다 '완전 중복' 경고 하나를 만든다."""
        recs = [
            _rec("a", "클린코드.pdf", md5="x"),
            _rec("b", "클린코드.pdf", folder="백업", md5="x"),
            _rec("c", "리팩터링.pdf", md5="y"),
            _rec("d", "리팩터링 2판.pdf", md5="z"),
        ]
        ws = checks.find_exact_duplicates(recs)
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0].kind, "exact_duplicate")
        self.assertEqual(sorted(_ids(ws[0])), ["a", "b"])
        self.assertIn("완전 중복", ws[0].message)

    def test_kbi_5_b1_md5_only_names_irrelevant(self):
        """KBI-5#B1 완전 중복은 MD5만으로 판정한다(이름 무관)."""
        recs = [
            _rec("a", "전혀다른이름.pdf", md5="x"),
            _rec("b", "다른책.pdf", md5="x"),
            _rec("c", "같은이름.pdf", md5="p"),
            _rec("d", "같은이름.pdf", md5="q"),
        ]
        ws = checks.find_exact_duplicates(recs)
        self.assertEqual([sorted(_ids(w)) for w in ws], [["a", "b"]])

    def test_kbi_5_1_empty_md5_never_grouped(self):
        """KBI-5#1 MD5가 비어 있는 파일은 중복으로 묶지 않는다."""
        recs = [_rec("a", "a.pdf", md5=""), _rec("b", "b.pdf", md5=""),
                _rec("c", "c.pdf", md5=None)]
        self.assertEqual(checks.find_exact_duplicates(recs), [])


class TestSameTitleDifferentContent(unittest.TestCase):
    def test_kbi_5_2_same_title_key_different_md5(self):
        """KBI-5#2 제목 키가 같지만 MD5가 다른 묶음을 '동명 다른 파일'로 보고한다."""
        recs = [
            _rec("a", "Clean Code.pdf", md5="p"),
            _rec("b", "Copy of clean-code.PDF", folder="백업", md5="q"),
            _rec("c", "리팩터링.pdf", md5="r"),
        ]
        ws = checks.find_same_title_different_content(recs)
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0].kind, "same_title_different_content")
        self.assertEqual(sorted(_ids(ws[0])), ["a", "b"])
        self.assertIn("동명 다른 파일", ws[0].message)

    def test_kbi_5_2_all_same_md5_is_exact_duplicate_only(self):
        """KBI-5#2 묶음 전체가 MD5 하나를 공유하면 완전 중복(#1)으로만 보고한다."""
        recs = [_rec("a", "클린코드.pdf", md5="x"),
                _rec("b", "클린 코드.pdf", folder="백업", md5="x")]
        self.assertEqual(checks.find_same_title_different_content(recs), [])

    def test_kbi_5_2_mixed_group_reported_whole(self):
        """KBI-5#2 MD5 값이 2종 이상인 묶음은 묶음 전체를 보고한다."""
        recs = [_rec("a", "클린코드.pdf", md5="x"),
                _rec("b", "클린코드.pdf", folder="백업", md5="x"),
                _rec("c", "클린코드.pdf", folder="기타", md5="y")]
        ws = checks.find_same_title_different_content(recs)
        self.assertEqual([sorted(_ids(w)) for w in ws], [["a", "b", "c"]])


class TestFilenameChecks(unittest.TestCase):
    def _kinds(self, name):
        return [w.kind for w in checks.find_filename_issues([_rec("a", name)])]

    def test_kbi_5_3_missing_pdf_extension(self):
        """KBI-5#3 이름이 .pdf(대소문자 무시)로 끝나지 않으면 확장자 누락 경고."""
        self.assertEqual(self._kinds("클린코드"), ["missing_pdf_extension"])
        self.assertEqual(self._kinds("클린코드.PDF"), [])
        self.assertEqual(self._kinds("클린코드.pdf"), [])

    def test_kbi_5_3_copy_of_prefix(self):
        """KBI-5#3 'Copy of '로 시작하는 이름은 접두어 경고."""
        self.assertEqual(self._kinds("Copy of 클린코드.pdf"), ["copy_of_prefix"])
        self.assertEqual(self._kinds("Copyof 클린코드.pdf"), [])

    def test_kbi_5_3_surrounding_whitespace(self):
        """KBI-5#3 이름 앞뒤 공백은 공백 경고."""
        self.assertEqual(self._kinds(" 클린코드.pdf"), ["surrounding_whitespace"])
        self.assertEqual(self._kinds("클린코드.pdf "),
                         ["missing_pdf_extension", "surrounding_whitespace"])
        self.assertEqual(self._kinds("클린 코드.pdf"), [])

    def test_kbi_5_3_warning_carries_file_and_message(self):
        """KBI-5#3 파일명 경고는 대상 파일 하나와 한국어 메시지를 가진다."""
        rec = _rec("a", "Copy of 클린코드")
        ws = checks.find_filename_issues([rec])
        self.assertEqual([w.kind for w in ws], ["missing_pdf_extension", "copy_of_prefix"])
        for w in ws:
            self.assertEqual(w.files, [rec])
            self.assertIn("IT/개발/Copy of 클린코드", w.message)


class TestRunChecks(unittest.TestCase):
    def _records(self):
        return [
            _rec("a", "클린코드.pdf", md5="x"),
            _rec("b", "다른이름.pdf", folder="백업", md5="x"),
            _rec("c", "리팩터링.pdf", md5="p"),
            _rec("d", "리팩터링.pdf", folder="백업", md5="q"),
            _rec("e", "Copy of 테스트주도개발", md5="t"),
            _rec("f", " 객체지향.pdf", md5="u"),
        ]

    def test_kbi_5_4_structured_list_in_kind_order(self):
        """KBI-5#4 종류·대상 파일·메시지를 가진 경고 목록을 종류 순 → 경로 순으로 반환한다."""
        ws = checks.run_checks(self._records())
        self.assertTrue(all(isinstance(w, checks.CheckWarning) for w in ws))
        self.assertEqual(
            [(w.kind, _ids(w)) for w in ws],
            [
                ("exact_duplicate", ["a", "b"]),
                ("same_title_different_content", ["c", "d"]),
                ("missing_pdf_extension", ["e"]),
                ("copy_of_prefix", ["e"]),
                ("surrounding_whitespace", ["f"]),
            ],
        )
        for w in ws:
            self.assertIsInstance(w.kind, str)
            self.assertIsInstance(w.files, list)
            self.assertTrue(w.message)
        self.assertEqual(checks.run_checks(list(reversed(self._records()))), ws)

    def test_kbi_5_4_empty_records(self):
        """KBI-5#4 레코드가 없으면 빈 목록."""
        self.assertEqual(checks.run_checks([]), [])

    def test_kbi_5_b2_does_not_mutate_records(self):
        """KBI-5#B2 점검은 입력 레코드를 수정하지 않는다."""
        recs = self._records()
        before = copy.deepcopy(recs)
        checks.run_checks(recs)
        self.assertEqual(recs, before)

    def test_kbi_5_b2_never_touches_drive_api(self):
        """KBI-5#B2 점검은 드라이브 API를 호출하지 않는다(경고만 만든다)."""
        src = inspect.getsource(checks)
        self.assertNotIn("googleapiclient", src)
        self.assertNotIn("google_drive", src)
        for value in vars(checks).values():
            if isinstance(value, types.ModuleType):
                self.assertFalse(value.__name__.startswith(("googleapiclient", "src.google_drive")))
        with mock.patch("googleapiclient.discovery.build") as build:
            checks.run_checks(self._records())
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
