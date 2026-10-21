"""분야 분류 검증 (KBI-3)."""
import unicodedata
import unittest

from src.classify import title_key


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


if __name__ == "__main__":
    unittest.main()
