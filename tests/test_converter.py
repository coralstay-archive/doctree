import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.converter import PDFConverter


class TestPDFConverter(unittest.TestCase):
    def setUp(self):
        self.dummy_pdf = Path("test_sample.pdf")

    def test_init(self):
        converter = PDFConverter(self.dummy_pdf)
        self.assertEqual(converter.pdf_path, self.dummy_pdf)
        self.assertIsNone(converter.language)
        self.assertEqual(converter.engine_name, "Unknown")

    @patch("src.converter.LANGDETECT_AVAILABLE", True)
    @patch("src.converter.pdfplumber")
    @patch("src.converter.detect")
    def test_detect_language_korean(self, mock_detect, mock_pdfplumber):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "이것은 한국어 도서 텍스트 샘플입니다."
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        mock_detect.return_value = "ko"

        converter = PDFConverter(self.dummy_pdf)
        lang = converter.detect_language()

        self.assertEqual(lang, "ko")
        self.assertEqual(converter.language, "ko")

    @patch("src.converter.LANGDETECT_AVAILABLE", True)
    @patch("src.converter.pdfplumber")
    @patch("src.converter.detect")
    def test_detect_language_english(self, mock_detect, mock_pdfplumber):
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is an English book sample text for testing."
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        mock_detect.return_value = "en"

        converter = PDFConverter(self.dummy_pdf)
        lang = converter.detect_language()

        self.assertEqual(lang, "en")
        self.assertEqual(converter.language, "en")

    @patch("src.converter.PDFConverter.detect_language")
    def test_select_engine_cjk(self, mock_detect):
        converter = PDFConverter(self.dummy_pdf)

        for lang in ["ko", "ja", "zh-cn", "zh-tw"]:
            mock_detect.return_value = lang
            engine = converter.select_engine()
            self.assertEqual(engine, "MinerU")
            self.assertEqual(converter.engine_name, "MinerU")

    @patch("src.converter.PDFConverter.detect_language")
    def test_select_engine_non_cjk(self, mock_detect):
        converter = PDFConverter(self.dummy_pdf)

        for lang in ["en", "fr", "de", "es"]:
            mock_detect.return_value = lang
            engine = converter.select_engine()
            self.assertEqual(engine, "Marker")
            self.assertEqual(converter.engine_name, "Marker")

    @patch("src.converter.PDFConverter.select_engine")
    @patch("src.converter.PDFConverter._convert_with_mineru")
    @patch("src.converter.PDFConverter._convert_with_marker")
    def test_convert_dispatch(self, mock_marker, mock_mineru, mock_select_engine):
        converter = PDFConverter(self.dummy_pdf)
        output_dir = Path("tmp_output")

        # Test MinerU dispatch
        mock_select_engine.return_value = "MinerU"
        with patch.object(converter, "is_valid_pdf", return_value=(True, "정상")):
            result_path = converter.convert(output_dir)
            self.assertEqual(result_path, output_dir / f"{self.dummy_pdf.stem}.md")
            mock_mineru.assert_called_once()
            mock_marker.assert_not_called()

        mock_mineru.reset_mock()
        mock_marker.reset_mock()

        # Test Marker dispatch
        mock_select_engine.return_value = "Marker"
        with patch.object(converter, "is_valid_pdf", return_value=(True, "정상")):
            result_path = converter.convert(output_dir)
            self.assertEqual(result_path, output_dir / f"{self.dummy_pdf.stem}.md")
            mock_marker.assert_called_once()
            mock_mineru.assert_not_called()

    @patch("src.converter.shutil.which")
    @patch("src.converter.subprocess.run")
    def test_convert_with_marker_cli(self, mock_subproc, mock_which):
        import tempfile
        mock_which.return_value = "/usr/local/bin/marker_single"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_out = Path(temp_dir)
            temp_md = temp_out / "test.md"
            temp_md.write_text("# Test", encoding="utf-8")
            converter = PDFConverter(self.dummy_pdf)
            converter._convert_with_marker(temp_out, temp_md)
            mock_subproc.assert_called_once()

    @patch("src.converter.shutil.which")
    @patch("src.converter.PDFConverter._fallback_text_extraction")
    def test_convert_with_marker_fallback(self, mock_fallback, mock_which):
        mock_which.return_value = None
        converter = PDFConverter(self.dummy_pdf)
        converter._convert_with_marker(Path("tmp_out"), Path("tmp_out/test.md"))
        mock_fallback.assert_called_once_with(Path("tmp_out/test.md"))

    @patch("src.converter.pdfplumber")
    def test_fallback_text_extraction(self, mock_pdfplumber, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_md = Path(temp_dir) / "output.md"
            mock_pdf = MagicMock()
            mock_page1 = MagicMock()
            mock_page1.extract_text.return_value = "Sample page 1 text"
            mock_pdf.pages = [mock_page1]
            mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

            converter = PDFConverter(self.dummy_pdf)
            converter._fallback_text_extraction(temp_md)

            self.assertTrue(temp_md.exists())
            content = temp_md.read_text(encoding="utf-8")
            self.assertIn("Sample page 1 text", content)
            self.assertIn(f"# {self.dummy_pdf.stem}", content)

    def test_is_valid_pdf_not_found(self):
        converter = PDFConverter(Path("non_existent_file.pdf"))
        is_valid, reason = converter.is_valid_pdf()
        self.assertFalse(is_valid)
        self.assertIn("존재하지 않습니다", reason)

    def test_is_valid_pdf_empty_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            converter = PDFConverter(Path(f.name))
            is_valid, reason = converter.is_valid_pdf()
            self.assertFalse(is_valid)
            self.assertIn("0바이트", reason)


if __name__ == "__main__":
    unittest.main()
