"""분야 분류 검증 (KBI-3)."""
import tempfile
import textwrap
import unicodedata
import unittest
from pathlib import Path

from src.classify import UNCLASSIFIED, CategoryConfigError, assign, classify, load_categories, title_key


def _write_yaml(text: str) -> Path:
    d = tempfile.mkdtemp()
    path = Path(d) / "categories.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


class TestTitleKey(unittest.TestCase):
    def test_kbi_3_4_nfc(self):
        """KBI-3#4 NFD(자모 분리)와 NFC 제목은 같은 키가 된다."""
        nfd = unicodedata.normalize("NFD", "토비의-스프링-1")
        self.assertEqual(title_key(nfd), title_key("토비의-스프링-1"))
        self.assertEqual(title_key(nfd), unicodedata.normalize("NFC", "토비의스프링1"))

    def test_kbi_3_4_strip_pdf_case_insensitive(self):
        """KBI-3#4 끝의 .pdf는 대소문자와 무관하게 제거된다."""
        for name in ("클린코드.pdf", "클린코드.PDF", "클린코드.Pdf", "클린코드"):
            self.assertEqual(title_key(name), "클린코드")

    def test_kbi_3_4_pdf_only_at_end(self):
        """KBI-3#4 .pdf는 끝에 있을 때만 제거된다."""
        self.assertEqual(title_key("a.pdf.notes"), "a.pdf.notes")

    def test_kbi_3_4_strip_copy_of(self):
        """KBI-3#4 앞의 'Copy of '는 제거된다."""
        self.assertEqual(title_key("Copy of 리얼몽고디비.pdf"), title_key("리얼몽고디비"))

    def test_kbi_3_4_ignore_hyphen_space_case(self):
        """KBI-3#4 하이픈·공백은 무시되고 소문자화된다."""
        self.assertEqual(title_key("Trouble-shooting java"), "troubleshootingjava")
        self.assertEqual(title_key("Clean  Code\t- 2nd"), "cleancode2nd")

    def test_kbi_3_4_slash_kept(self):
        """KBI-3#4 '/'는 키에 그대로 남는다(A/B-테스트가 A/B테스트로 매칭)."""
        self.assertEqual(title_key("A/B-테스트"), "a/b테스트")
        self.assertEqual(title_key("A/B 테스트.pdf"), title_key("A/B-테스트"))

    def test_kbi_3_b1_cosmetic_renames_keep_key(self):
        """KBI-3#B1 KBI-3#4 .pdf 추가, 하이픈/공백·대소문자 변경만으로는 키가 바뀌지 않는다."""
        base = title_key("Effective-Java")
        for variant in ("Effective-Java.pdf", "effective java", "EFFECTIVE JAVA.PDF", "EffectiveJava", "Copy of Effective-Java.pdf"):
            self.assertEqual(title_key(variant), base, variant)


class TestLoadCategories(unittest.TestCase):
    SAMPLE = """
        categories:
          "1. 컴퓨터 과학 기초":
            "이론·고전":
              - "SICP"
              - "C.O.D.E"
            "알고리즘·자료구조":
              - "종만북-1권"
          "4. 웹·백엔드 프레임워크":
            "Spring·JPA":
              - "토비의-스프링-1"
        notes:
          "SICP": "고전"
    """

    def test_kbi_3_1_reads_category_subcategory_titles(self):
        """KBI-3#1 분야 > 세부분야 > 제목 목록 구조를 순서대로 읽는다."""
        cats = load_categories(_write_yaml(self.SAMPLE))
        self.assertEqual(list(cats.tree), ["1. 컴퓨터 과학 기초", "4. 웹·백엔드 프레임워크"])
        self.assertEqual(list(cats.tree["1. 컴퓨터 과학 기초"]), ["이론·고전", "알고리즘·자료구조"])
        self.assertEqual(cats.tree["1. 컴퓨터 과학 기초"]["이론·고전"], ["SICP", "C.O.D.E"])

    def test_kbi_3_1_index_maps_title_key_to_place(self):
        """KBI-3#1 로더는 제목을 제목 키로 정규화해 (분야, 세부분야)로 색인한다."""
        cats = load_categories(_write_yaml(self.SAMPLE))
        self.assertEqual(cats.lookup("토비의 스프링 1.pdf"), ("4. 웹·백엔드 프레임워크", "Spring·JPA"))
        self.assertEqual(cats.index[title_key("종만북-1권")], ("1. 컴퓨터 과학 기초", "알고리즘·자료구조"))
        self.assertIsNone(cats.lookup("없는 책"))

    def test_kbi_3_1_notes_by_title_key(self):
        """KBI-3#1 notes(제목 → 비고)는 선택 항목이며 제목 키로 조회된다."""
        cats = load_categories(_write_yaml(self.SAMPLE))
        self.assertEqual(cats.note("sicp.pdf"), "고전")
        self.assertIsNone(cats.note("C.O.D.E"))
        no_notes = load_categories(_write_yaml('categories:\n  "A":\n    "B":\n      - "x"\n'))
        self.assertEqual(no_notes.notes, {})

    def test_kbi_3_1_invalid_structure_is_config_error(self):
        """KBI-3#1 구조가 분야 > 세부분야 > 제목 목록이 아니면 설정 오류다."""
        bad = (
            "[]",
            "categories: []",
            'categories:\n  "A": ["x"]',
            'categories:\n  "A":\n    "B": "x"',
            'categories:\n  "A":\n    "B":\n      - 1',
            'categories:\n  "A":\n    "B":\n      - "  -  "',
        )
        for text in bad:
            with self.assertRaises(CategoryConfigError, msg=text):
                load_categories(_write_yaml(text))

    def test_kbi_3_1_missing_file_is_config_error(self):
        """KBI-3#1 설정 파일이 없으면 경로를 담은 설정 오류다."""
        with self.assertRaises(CategoryConfigError) as cm:
            load_categories(Path(tempfile.mkdtemp()) / "nope.yaml")
        self.assertIn("nope.yaml", str(cm.exception))

    def test_kbi_3_b3_duplicate_key_across_subcategories(self):
        """KBI-3#B3 KBI-3#1 다른 세부분야에 같은 제목 키가 있으면 키와 두 위치를 담은 설정 오류다."""
        path = _write_yaml("""
            categories:
              "1. 컴퓨터 과학 기초":
                "이론·고전":
                  - "Clean-Code"
              "3. 소프트웨어 설계·품질":
                "클린 코드·리팩터링":
                  - "clean code"
        """)
        with self.assertRaises(CategoryConfigError) as cm:
            load_categories(path)
        msg = str(cm.exception)
        self.assertIn("cleancode", msg)
        self.assertIn("1. 컴퓨터 과학 기초 > 이론·고전", msg)
        self.assertIn("3. 소프트웨어 설계·품질 > 클린 코드·리팩터링", msg)

    def test_kbi_3_b3_duplicate_key_within_subcategory(self):
        """KBI-3#B3 KBI-3#1 같은 세부분야 안에서 정규화 키가 겹쳐도 설정 오류다."""
        path = _write_yaml("""
            categories:
              "A":
                "B":
                  - "토비의-스프링-1"
                  - "Copy of 토비의 스프링 1.pdf"
        """)
        with self.assertRaises(CategoryConfigError) as cm:
            load_categories(path)
        self.assertIn(title_key("토비의-스프링-1"), str(cm.exception))
        self.assertIn("A > B", str(cm.exception))

    def test_kbi_3_b3_duplicate_yaml_mapping_key(self):
        """KBI-3#B3 YAML에서 같은 분야/세부분야 이름이 두 번 나오면(덮어쓰기 대신) 설정 오류다."""
        path = _write_yaml("""
            categories:
              "A":
                "B":
                  - "x"
                "B":
                  - "y"
        """)
        with self.assertRaises(CategoryConfigError) as cm:
            load_categories(path)
        self.assertIn("B", str(cm.exception))

    def test_kbi_3_b3_config_error_is_value_error(self):
        """KBI-3#B3 설정 오류는 ValueError 하위 타입이라 CLI가 잡아 비정상 종료할 수 있다."""
        self.assertTrue(issubclass(CategoryConfigError, ValueError))


def _rec(name, folder_path="knowledge-base/raw-data", id_=None):
    return {"id": id_ or name, "name": name, "folder_path": folder_path, "size_bytes": 1}


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.cats = load_categories(_write_yaml(TestLoadCategories.SAMPLE))

    def test_kbi_3_3_unmapped_goes_to_unclassified(self):
        """KBI-3#3 매핑되지 않은 책은 ('미분류', '미분류')로 분류된다."""
        self.assertEqual(UNCLASSIFIED, ("미분류", "미분류"))
        self.assertEqual(assign(_rec("새로-산-책.pdf"), self.cats), UNCLASSIFIED)
        self.assertEqual(assign(_rec("SICP.pdf"), self.cats), ("1. 컴퓨터 과학 기초", "이론·고전"))

    def test_kbi_3_3_groups_in_config_order_with_unclassified_last(self):
        """KBI-3#3 결과는 YAML의 분야·세부분야 순서를 따르고 '미분류'가 마지막에 온다."""
        groups = classify([_rec("SICP.pdf")], self.cats)
        self.assertEqual(list(groups), ["1. 컴퓨터 과학 기초", "4. 웹·백엔드 프레임워크", "미분류"])
        self.assertEqual(list(groups["1. 컴퓨터 과학 기초"]), ["이론·고전", "알고리즘·자료구조"])
        self.assertEqual(groups["미분류"]["미분류"], [])

    def test_kbi_3_3_preserves_input_order_within_group(self):
        """KBI-3#3 같은 세부분야 안에서는 입력 순서를 유지한다."""
        recs = [_rec("C.O.D.E.pdf"), _rec("zzz.pdf"), _rec("SICP.pdf"), _rec("aaa.pdf")]
        groups = classify(recs, self.cats)
        self.assertEqual([r["name"] for r in groups["1. 컴퓨터 과학 기초"]["이론·고전"]], ["C.O.D.E.pdf", "SICP.pdf"])
        self.assertEqual([r["name"] for r in groups["미분류"]["미분류"]], ["zzz.pdf", "aaa.pdf"])

    def test_kbi_3_b2_no_record_dropped(self):
        """KBI-3#B2 KBI-3#3 매핑 없는 책을 포함해 입력 레코드가 하나도 빠지지 않는다(중복 이름 포함)."""
        recs = [_rec("SICP.pdf", id_="a"), _rec("SICP.pdf", "other", id_="b"), _rec("미지의-책", id_="c"),
                _rec("", id_="d"), _rec("토비의-스프링-1.pdf", id_="e")]
        groups = classify(recs, self.cats)
        out = [r["id"] for subs in groups.values() for rs in subs.values() for r in rs]
        self.assertEqual(sorted(out), ["a", "b", "c", "d", "e"])
        self.assertEqual([r["id"] for r in groups["미분류"]["미분류"]], ["c", "d"])

    def test_kbi_3_b2_unclassified_name_in_config_is_still_one_group(self):
        """KBI-3#B2 YAML에 '미분류' 분야가 있어도 매핑 없는 책은 같은 '미분류 > 미분류'에 합쳐진다."""
        cats = load_categories(_write_yaml('categories:\n  "미분류":\n    "미분류":\n      - "x"\n'))
        groups = classify([_rec("x.pdf"), _rec("y.pdf")], cats)
        self.assertEqual(list(groups), ["미분류"])
        self.assertEqual([r["name"] for r in groups["미분류"]["미분류"]], ["x.pdf", "y.pdf"])

    def test_kbi_3_b1_folder_path_ignored(self):
        """KBI-3#B1 KBI-3#4 폴더를 옮겨도 분류가 바뀌지 않는다(folder_path는 쓰지 않음)."""
        for folder in ("", "책들/ref-doc", "knowledge-base/raw-data/새 폴더", "1. 컴퓨터 과학 기초"):
            self.assertEqual(assign(_rec("SICP.pdf", folder), self.cats), ("1. 컴퓨터 과학 기초", "이론·고전"))
        self.assertEqual(assign(_rec("새 책", "4. 웹·백엔드 프레임워크/Spring·JPA"), self.cats), UNCLASSIFIED)

    def test_kbi_3_b1_cosmetic_rename_keeps_category(self):
        """KBI-3#B1 KBI-3#4 .pdf 추가·하이픈/공백·대소문자 변경만으로는 분류가 바뀌지 않는다."""
        for name in ("토비의-스프링-1", "토비의-스프링-1.pdf", "토비의 스프링 1.PDF", "Copy of 토비의스프링1.pdf"):
            self.assertEqual(assign(_rec(name), self.cats), ("4. 웹·백엔드 프레임워크", "Spring·JPA"), name)


CATEGORY_NAMES = [
    "1. 컴퓨터 과학 기초", "2. 프로그래밍 언어", "3. 소프트웨어 설계·품질", "4. 웹·백엔드 프레임워크",
    "5. 데이터베이스", "6. 인프라·DevOps·클라우드", "7. AI·데이터 과학", "8. 수학",
    "9. 기술 면접·코딩 테스트", "10. IT 자격증", "11. 부동산·감정평가·법", "12. 건축·건설 관리",
    "13. 경영·금융·회계", "14. 학습·글쓰기·교양", "15. 어학", "16. 논문(Saved from Chrome)",
]


class TestMigratedCategories(unittest.TestCase):
    """실제 config/categories.yaml(2026-10-21 16분야 수동 분류본 이관)을 오프라인으로 지킨다."""

    @classmethod
    def setUpClass(cls):
        cls.cats = load_categories()  # 기본 경로 config/categories.yaml

    def test_kbi_3_2_sixteen_categories_in_order(self):
        """KBI-3#2 이관된 16분야가 원래 이름·순서 그대로다."""
        self.assertEqual(list(self.cats.tree), CATEGORY_NAMES)
        self.assertEqual(list(self.cats.tree["1. 컴퓨터 과학 기초"]),
                         ["이론·고전", "알고리즘·자료구조", "운영체제·시스템 프로그래밍", "네트워크·통신·멀티미디어"])
        self.assertEqual(sum(len(subs) for subs in self.cats.tree.values()), 55)

    def test_kbi_3_2_structure_valid_and_no_duplicate_keys(self):
        """KBI-3#2 KBI-3#B3 모든 세부분야가 비어 있지 않고 제목 키가 중복 없이 색인된다."""
        titles = [t for subs in self.cats.tree.values() for ts in subs.values() for t in ts]
        for cat, subs in self.cats.tree.items():
            for sub, ts in subs.items():
                self.assertTrue(ts, f"{cat} > {sub}")
        self.assertEqual(len(self.cats.index), len(titles))
        self.assertGreaterEqual(len(titles), 232)  # 2026-10-21 드라이브 도서 232권 + 현재 없는 제목 1개

    def test_kbi_3_2_titles_are_human_readable(self):
        """KBI-3#2 제목은 'Copy of '·'.pdf' 없는 사람이 읽는 형태로 저장돼 있다."""
        for subs in self.cats.tree.values():
            for ts in subs.values():
                for t in ts:
                    self.assertFalse(t.startswith("Copy of "), t)
                    self.assertFalse(t.lower().endswith(".pdf"), t)
                    self.assertEqual(t, unicodedata.normalize("NFC", t))

    def test_kbi_3_2_no_unclassified_in_config(self):
        """KBI-3#2 '미분류'는 설정에 두지 않는다(매핑 없는 책 전용)."""
        self.assertNotIn(UNCLASSIFIED[0], self.cats.tree)

    def test_kbi_3_2_sample_books_classified(self):
        """KBI-3#2 대표 도서(이름 변경된 책·'/' 포함 이름 포함)가 원래 세부분야로 분류된다."""
        expected = {
            "A/B-테스트": ("7. AI·데이터 과학", "데이터 분석·추천·검색"),
            "토비의-스프링-1.pdf": ("4. 웹·백엔드 프레임워크", "Spring·JPA"),
            "이산수학.pdf": ("8. 수학", "이산수학·논리·증명"),
            "SICP.pdf": ("1. 컴퓨터 과학 기초", "이론·고전"),
            "TLPI-1.pdf": ("1. 컴퓨터 과학 기초", "운영체제·시스템 프로그래밍"),
        }
        for name, place in expected.items():
            self.assertEqual(assign(_rec(name), self.cats), place, name)

    def test_kbi_3_2_notes_refer_to_known_titles(self):
        """KBI-3#2 notes의 제목은 모두 분류 체계에 있는 제목이다."""
        for k in self.cats.notes:
            self.assertIn(k, self.cats.index)


if __name__ == "__main__":
    unittest.main()
