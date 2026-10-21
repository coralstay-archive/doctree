import unittest
from pathlib import Path

import config.settings as settings
from config.settings import BASE_DIR


class TestSettings(unittest.TestCase):
    def test_base_dir_path(self):
        self.assertIsInstance(BASE_DIR, Path)
        self.assertTrue(BASE_DIR.exists())

    def test_kbi_1_1_no_pipeline_stage_dirs(self):
        """KBI-1#1 settings에 data/ 단계 폴더 설정(01_input_pdf 등)이 없다."""
        for name in ("DATA_DIR", "INPUT_PDF_DIR", "TEMP_MD_DIR", "FAILED_MD_DIR", "OUTPUT_MD_DIR"):
            self.assertFalse(hasattr(settings, name), name)

    def test_kbi_1_2_no_openai_or_similarity_settings(self):
        """KBI-1#2 settings에 OpenAI·유사도 항목이 없다."""
        for name in dir(settings):
            self.assertFalse(name.startswith("OPENAI_"), name)
        self.assertFalse(hasattr(settings, "SIMILARITY_THRESHOLD"))


if __name__ == "__main__":
    unittest.main()
