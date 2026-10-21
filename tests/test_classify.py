"""분야 분류 검증 (KBI-3)."""
import tempfile
import textwrap
import unicodedata
import unittest
from pathlib import Path

from src.classify import CategoryConfigError, load_categories, title_key


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


if __name__ == "__main__":
    unittest.main()
