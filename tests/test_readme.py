"""README 개편과 수동 분류본 정리 검증 (KBI-6#4)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestReadme(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_kbi_6_4_no_rewrite_banner(self):
        """KBI-6#4 '재작성 중' 안내와 옛 파이프라인 설명이 사라졌다."""
        self.assertNotIn("재작성 중", self.text)
        self.assertNotIn("KBI-6에서", self.text)

    def test_kbi_6_4_setup_and_commands(self):
        """KBI-6#4 설치(venv·pip install -e .·credentials.json)와 auth/status/update 명령을 설명한다."""
        for needle in (".venv", "pip install -e .", "credentials.json", "데스크톱",
                       "doctree auth", "doctree status", "doctree update", "--ledger-dir"):
            self.assertIn(needle, self.text, needle)

    def test_kbi_6_4_outputs(self):
        """KBI-6#4 산출물(ledger/도서목록.md·변경이력.md·snapshots/)과 ledger/ 미커밋을 설명한다."""
        for needle in ("ledger/도서목록.md", "변경이력.md", "snapshots/", "커밋하지 않"):
            self.assertIn(needle, self.text, needle)

    def test_kbi_6_4_categories_guide(self):
        """KBI-6#4 categories.yaml 편집 안내: 새 책 추가·미분류·중복 키 오류."""
        for needle in ("categories.yaml", "새 책", "미분류", "중복"):
            self.assertIn(needle, self.text, needle)

    def test_kbi_6_4_test_mode_token_expiry(self):
        """KBI-6#4 OAuth 테스트 모드에서 7일 뒤 refresh token 만료 시 token.json 삭제 후 재인증 안내."""
        for needle in ("테스트", "7일", "token.json", "doctree auth"):
            self.assertIn(needle, self.text, needle)


class TestManualLedgerRemoved(unittest.TestCase):
    def test_kbi_6_4_root_manual_ledger_deleted(self):
        """KBI-6#4 루트의 수동 분류본 도서목록-분류.md는 삭제됐다 (이제 doctree update가 대장을 만든다)."""
        self.assertFalse((ROOT / "도서목록-분류.md").exists())


if __name__ == "__main__":
    unittest.main()
