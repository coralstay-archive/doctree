import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil
import main


class TestMainPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_dir = Path(self.temp_dir) / "01_input"
        self.temp_md_dir = Path(self.temp_dir) / "02_temp"
        self.failed_md_dir = Path(self.temp_dir) / "03_failed"
        self.output_md_dir = Path(self.temp_dir) / "04_output"

        for d in [self.input_dir, self.temp_md_dir, self.failed_md_dir, self.output_md_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("main.INPUT_PDF_DIR")
    @patch("main.GoogleDriveManager")
    def test_run_pipeline_no_pdfs(self, mock_drive_cls, mock_input_dir):
        mock_input_dir.rglob.return_value = []
        main.run_pipeline()
        mock_drive_cls.return_value.download_new_pdfs.assert_called_once()

    @patch("main.TEMP_MD_DIR")
    @patch("main.FAILED_MD_DIR")
    @patch("main.OUTPUT_MD_DIR")
    @patch("main.GoogleDriveManager")
    @patch("main.PDFConverter")
    @patch("main.ConversionValidator")
    @patch("main.LLMSummarizer")
    def test_run_pipeline_full_success(
        self,
        mock_summarizer_cls,
        mock_validator_cls,
        mock_converter_cls,
        mock_drive_cls,
        mock_output_dir,
        mock_failed_dir,
        mock_temp_dir,
    ):
        sample_pdf_path = self.input_dir / "sample.pdf"
        sample_pdf_path.write_text("dummy", encoding="utf-8")

        # Converter mock
        mock_conv_instance = MagicMock()
        mock_conv_instance.convert.return_value = self.temp_md_dir / "sample.md"
        mock_conv_instance.language = "ko"
        mock_conv_instance.engine_name = "MinerU"
        mock_converter_cls.return_value = mock_conv_instance

        # Validator mock (성공)
        mock_val_instance = MagicMock()
        mock_val_instance.check_similarity.return_value = (True, 0.95)
        mock_validator_cls.return_value = mock_val_instance

        # Summarizer mock
        mock_sum_instance = MagicMock()
        mock_sum_instance.generate_index.return_value = "## 목차\n"
        mock_sum_instance.generate_chapter_summaries.return_value = "## 요약\n"
        mock_sum_instance.save_final_markdown.return_value = self.output_md_dir / "sample.md"
        mock_summarizer_cls.return_value = mock_sum_instance

        with patch("main.INPUT_PDF_DIR", self.input_dir):
            main.run_pipeline()

            mock_conv_instance.convert.assert_called_once()
            mock_val_instance.check_similarity.assert_called_once()
            mock_sum_instance.generate_index.assert_called_once()
            mock_sum_instance.generate_chapter_summaries.assert_called_once()
            mock_sum_instance.save_final_markdown.assert_called_once()

    @patch("main.TEMP_MD_DIR")
    @patch("main.FAILED_MD_DIR")
    @patch("main.OUTPUT_MD_DIR")
    @patch("main.GoogleDriveManager")
    @patch("main.PDFConverter")
    @patch("main.ConversionValidator")
    @patch("main.LLMSummarizer")
    def test_run_pipeline_validation_failed(
        self,
        mock_summarizer_cls,
        mock_validator_cls,
        mock_converter_cls,
        mock_drive_cls,
        mock_output_dir,
        mock_failed_dir,
        mock_temp_dir,
    ):
        sample_pdf_path = self.input_dir / "sample.pdf"
        sample_pdf_path.write_text("dummy", encoding="utf-8")

        # Converter mock
        mock_conv_instance = MagicMock()
        mock_conv_instance.convert.return_value = self.temp_md_dir / "sample.md"
        mock_converter_cls.return_value = mock_conv_instance

        # Validator mock (실패)
        mock_val_instance = MagicMock()
        mock_val_instance.check_similarity.return_value = (False, 0.40)
        mock_validator_cls.return_value = mock_val_instance

        mock_sum_instance = MagicMock()
        mock_summarizer_cls.return_value = mock_sum_instance

        with patch("main.INPUT_PDF_DIR", self.input_dir):
            main.run_pipeline()

            mock_conv_instance.convert.assert_called_once()
            mock_val_instance.check_similarity.assert_called_once()
            mock_val_instance.move_to_failed.assert_called_once()
            # 검증 실패 시 요약 및 저장은 호출되지 않아야 함
            mock_sum_instance.save_final_markdown.assert_not_called()

    @patch("main.GoogleDriveManager")
    def test_step_sync(self, mock_drive_cls):
        mock_drive_instance = MagicMock()
        mock_drive_instance.service = True
        mock_drive_instance.get_account_and_quota.return_value = {"email": "test@gmail.com", "usage_gb": 10, "limit_gb": 100}
        mock_drive_instance.download_new_pdfs.return_value = [Path(self.input_dir) / "test.pdf"]
        mock_drive_cls.return_value = mock_drive_instance

        drive = main.step_sync(target_dir=self.input_dir)
        self.assertIsNotNone(drive)
        mock_drive_instance.download_new_pdfs.assert_called_once()

    @patch("main.PDFConverter")
    def test_step_convert(self, mock_converter_cls):
        sample_pdf = self.input_dir / "sample.pdf"
        sample_pdf.write_text("dummy", encoding="utf-8")

        mock_conv_instance = MagicMock()
        mock_conv_instance.convert.return_value = self.temp_md_dir / "sample.md"
        mock_converter_cls.return_value = mock_conv_instance

        paths = main.step_convert(input_path=sample_pdf, output_dir=self.temp_md_dir, engine="MinerU", lang="ko")
        self.assertEqual(len(paths), 1)
        mock_conv_instance.convert.assert_called_once()

    @patch("main.ConversionValidator")
    def test_step_validate_pass_and_fail(self, mock_validator_cls):
        sample_pdf = self.input_dir / "sample.pdf"
        sample_md = self.temp_md_dir / "sample.md"
        sample_pdf.write_text("dummy", encoding="utf-8")
        sample_md.write_text("dummy md", encoding="utf-8")

        mock_val_instance = MagicMock()
        mock_val_instance.check_similarity.return_value = (True, 0.90)
        mock_validator_cls.return_value = mock_val_instance

        is_valid = main.step_validate(sample_pdf, sample_md, threshold=0.85)
        self.assertTrue(is_valid)

        # Failure case
        mock_val_instance.check_similarity.return_value = (False, 0.50)
        is_valid = main.step_validate(sample_pdf, sample_md, threshold=0.85, isolate_failed=True, failed_dir=self.failed_md_dir)
        self.assertFalse(is_valid)
        mock_val_instance.move_to_failed.assert_called_once()

    @patch("main.LLMSummarizer")
    def test_step_summarize(self, mock_summarizer_cls):
        sample_md = self.temp_md_dir / "sample.md"
        sample_md.write_text("# Chapter 1\nHello", encoding="utf-8")

        mock_sum_instance = MagicMock()
        mock_sum_instance.generate_index.return_value = "- [Chapter 1](#chapter-1)"
        mock_sum_instance.generate_chapter_summaries.return_value = "Summary"
        mock_summarizer_cls.return_value = mock_sum_instance

        res = main.step_summarize(sample_md, skip_llm=False)
        self.assertIn("index", res)
        self.assertIn("summary", res)
        mock_sum_instance.generate_index.assert_called_once()
        mock_sum_instance.generate_chapter_summaries.assert_called_once()

    @patch("main.LLMSummarizer")
    def test_step_assemble(self, mock_summarizer_cls):
        sample_md = self.temp_md_dir / "sample.md"
        sample_md.write_text("# Content", encoding="utf-8")

        mock_sum_instance = MagicMock()
        mock_sum_instance.save_final_markdown.return_value = self.output_md_dir / "sample.md"
        mock_summarizer_cls.return_value = mock_sum_instance

        res = main.step_assemble(
            md_path=sample_md,
            index_content="TOC",
            summary_content="Summary",
            metadata={"title": "Test Book"},
            output_dir=self.output_md_dir
        )
        self.assertEqual(res, self.output_md_dir / "sample.md")
        mock_sum_instance.save_final_markdown.assert_called_once()

    def test_clean_data(self):
        test_file = self.temp_md_dir / "dummy.md"
        test_file.write_text("temp", encoding="utf-8")
        self.assertTrue(test_file.exists())

        with patch("main.TEMP_MD_DIR", self.temp_md_dir):
            # Without confirm flag, should not delete
            main.clean_data(target="temp", confirm=False)
            self.assertTrue(test_file.exists())

            # With confirm flag, should delete
            main.clean_data(target="temp", confirm=True)
            self.assertFalse(test_file.exists())

    @patch("main.show_status")
    @patch("main.step_sync")
    @patch("main.step_convert")
    def test_cli_entry_subcommands(self, mock_convert, mock_sync, mock_status):
        parser = main.build_parser()
        
        args = parser.parse_args(["status", "--no-tree"])
        self.assertEqual(args.command, "status")
        self.assertTrue(args.no_tree)

        args = parser.parse_args(["sync", "--force-md5"])
        self.assertEqual(args.command, "sync")
        self.assertTrue(args.force_md5)

        args = parser.parse_args(["convert", "test.pdf", "--engine", "MinerU", "--lang", "ko"])
        self.assertEqual(args.command, "convert")
        self.assertEqual(str(args.input), "test.pdf")
        self.assertEqual(args.engine, "MinerU")
        self.assertEqual(args.lang, "ko")

        args = parser.parse_args(["validate", "--pdf", "a.pdf", "--md", "a.md", "-t", "0.9"])
        self.assertEqual(args.command, "validate")
        self.assertEqual(args.threshold, 0.9)


if __name__ == "__main__":
    unittest.main()
