"""중복·파일명 점검 (KBI-5)."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
