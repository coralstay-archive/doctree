import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
from src.validator import ConversionValidator


class TestConversionValidator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pdf_file = Path(self.temp_dir) / "sample.pdf"
        self.md_file = Path(self.temp_dir) / "sample.md"

        self.pdf_file.write_text("Dummy PDF content", encoding="utf-8")
        self.md_file.write_text("# Title\n\nThis is sample markdown text for test.", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_normalize_text(self):
        validator = ConversionValidator(self.pdf_file, self.md_file)
        text = "Hello   world!\n\nThis   is   a test. \n"
        normalized = validator._normalize_text(text)
        self.assertEqual(normalized, "Hello world! This is a test.")

    def test_extract_md_text(self):
        validator = ConversionValidator(self.pdf_file, self.md_file)
        text = validator.extract_md_text()
        self.assertIn("Title", text)
        self.assertIn("This is sample markdown text for test.", text)
        self.assertNotIn("#", text)

    @patch("src.validator.pdfplumber")
    def test_extract_pdf_text(self, mock_pdfplumber):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page content from PDF."
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        validator = ConversionValidator(self.pdf_file, self.md_file)
        extracted = validator.extract_pdf_text()
        self.assertEqual(extracted, "Page content from PDF.")

    @patch.object(ConversionValidator, "extract_pdf_text")
    @patch.object(ConversionValidator, "extract_md_text")
    def test_check_similarity_high(self, mock_md, mock_pdf):
        mock_pdf.return_value = "This is a detailed chapter about deep learning neural networks and computer vision."
        mock_md.return_value = "This is a detailed chapter about deep learning neural networks and computer vision."

        validator = ConversionValidator(self.pdf_file, self.md_file)
        is_valid, score = validator.check_similarity(threshold=0.85)

        self.assertTrue(is_valid)
        self.assertAlmostEqual(score, 1.0, places=2)

    @patch.object(ConversionValidator, "extract_pdf_text")
    @patch.object(ConversionValidator, "extract_md_text")
    def test_check_similarity_low(self, mock_md, mock_pdf):
        mock_pdf.return_value = "This is a detailed chapter about deep learning neural networks and computer vision."
        mock_md.return_value = "Completely different text with entirely distinct contents and words."

        validator = ConversionValidator(self.pdf_file, self.md_file)
        is_valid, score = validator.check_similarity(threshold=0.85)

        self.assertFalse(is_valid)
        self.assertLess(score, 0.85)

    @patch.object(ConversionValidator, "extract_pdf_text")
    @patch.object(ConversionValidator, "extract_md_text")
    def test_check_similarity_scanned_pdf(self, mock_md, mock_pdf):
        # 원본 PDF에 내장 텍스트가 거의 없는 스캔본 시나리오
        mock_pdf.return_value = "short"
        mock_md.return_value = "This is OCR converted text with plenty of words extracted from high resolution pages."

        validator = ConversionValidator(self.pdf_file, self.md_file)
        is_valid, score = validator.check_similarity(threshold=0.85)

        self.assertTrue(is_valid)
        self.assertEqual(score, 1.0)

    def test_move_to_failed(self):
        failed_dir = Path(self.temp_dir) / "failed"
        validator = ConversionValidator(self.pdf_file, self.md_file)

        dest = validator.move_to_failed(failed_dir)
        self.assertTrue(dest.exists())
        self.assertFalse(self.md_file.exists())
        self.assertEqual(dest.parent, failed_dir)

    def test_empty_md_file_check(self):
        empty_md = Path(self.temp_dir) / "empty.md"
        empty_md.write_text("", encoding="utf-8")
        validator = ConversionValidator(self.pdf_file, empty_md)
        is_valid, score = validator.check_similarity()
        self.assertFalse(is_valid)
        self.assertEqual(score, 0.0)

    def test_normalize_nfd_korean(self):
        import unicodedata
        # '한글' in NFD (자모 분리)
        nfd_text = unicodedata.normalize('NFD', "한글 테스트")
        validator = ConversionValidator(self.pdf_file, self.md_file)
        normalized = validator._normalize_text(nfd_text)
        # Check normalized form is NFC
        self.assertEqual(normalized, "한글 테스트")
        self.assertEqual(unicodedata.normalize('NFC', normalized), normalized)


if __name__ == "__main__":
    unittest.main()
