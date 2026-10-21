"""프로젝트 구성 검증 (KBI-1)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestPipelineRemoved(unittest.TestCase):
    def test_kbi_1_1_pipeline_modules_deleted(self):
        """KBI-1#1 파이프라인 모듈(converter·validator·summarizer·auth_login·main)이 삭제돼 있다."""
        for rel in ("src/converter.py", "src/validator.py", "src/summarizer.py", "auth_login.py", "main.py"):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_kbi_1_1_pipeline_tests_deleted(self):
        """KBI-1#1 삭제된 모듈만 검증하던 테스트도 삭제돼 있다."""
        for rel in ("tests/test_converter.py", "tests/test_validator.py", "tests/test_summarizer.py", "tests/test_main.py"):
            self.assertFalse((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
