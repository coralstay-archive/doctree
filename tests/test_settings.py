import unittest
from pathlib import Path
from config.settings import (
    BASE_DIR,
    DATA_DIR,
    INPUT_PDF_DIR,
    TEMP_MD_DIR,
    FAILED_MD_DIR,
    OUTPUT_MD_DIR,
    SIMILARITY_THRESHOLD,
)


class TestSettings(unittest.TestCase):
    def test_directories_creation(self):
        self.assertTrue(DATA_DIR.exists())
        self.assertTrue(INPUT_PDF_DIR.exists())
        self.assertTrue(TEMP_MD_DIR.exists())
        self.assertTrue(FAILED_MD_DIR.exists())
        self.assertTrue(OUTPUT_MD_DIR.exists())

    def test_default_threshold(self):
        self.assertIsInstance(SIMILARITY_THRESHOLD, float)
        self.assertGreaterEqual(SIMILARITY_THRESHOLD, 0.0)
        self.assertLessEqual(SIMILARITY_THRESHOLD, 1.0)

    def test_base_dir_path(self):
        self.assertIsInstance(BASE_DIR, Path)
        self.assertTrue(BASE_DIR.exists())


if __name__ == "__main__":
    unittest.main()
