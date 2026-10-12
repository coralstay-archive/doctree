import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path
import tempfile
import shutil
from src.summarizer import LLMSummarizer


class TestLLMSummarizer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.sample_md = Path(self.temp_dir) / "sample.md"
        self.sample_text = (
            "# Introduction to AI\n\n"
            "This is the introduction section.\n\n"
            "## Chapter 1: Machine Learning Basics\n\n"
            "Supervised and unsupervised learning are fundamental concepts.\n\n"
            "### Section 1.1: Supervised Learning\n\n"
            "Supervised learning uses labeled datasets.\n\n"
            "## Chapter 2: Deep Learning\n\n"
            "Deep learning utilizes multi-layer neural networks.\n"
        )
        self.sample_md.write_text(self.sample_text, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_index(self):
        summarizer = LLMSummarizer(self.sample_md)
        index = summarizer.generate_index()

        self.assertIn("## 목차", index)
        self.assertIn("- [Introduction to AI](#introduction-to-ai)", index)
        self.assertIn("  - [Chapter 1: Machine Learning Basics](#chapter-1-machine-learning-basics)", index)
        self.assertIn("    - [Section 1.1: Supervised Learning](#section-11-supervised-learning)", index)

    def test_generate_index_empty(self):
        empty_md = Path(self.temp_dir) / "empty.md"
        empty_md.write_text("Just plain text with no headers.", encoding="utf-8")
        summarizer = LLMSummarizer(empty_md)
        index = summarizer.generate_index()

        self.assertIn("목차가 존재하지 않습니다", index)

    def test_split_into_chapters(self):
        summarizer = LLMSummarizer(self.sample_md)
        chapters = summarizer.split_into_chapters()

        self.assertEqual(len(chapters), 3)
        self.assertEqual(chapters[0]["title"], "Introduction to AI")
        self.assertEqual(chapters[1]["title"], "Chapter 1: Machine Learning Basics")
        self.assertEqual(chapters[2]["title"], "Chapter 2: Deep Learning")

    def test_summarize_single_chapter_fallback(self):
        # API 클라이언트가 없을 때
        summarizer = LLMSummarizer(self.sample_md, api_key="")
        import asyncio
        result = asyncio.run(
            summarizer._summarize_single_chapter("Test Chapter", "This is some chapter text content.")
        )
        self.assertEqual(result["title"], "Test Chapter")
        self.assertIn("This is some chapter text content.", result["summary"])

    @patch("src.summarizer.AsyncOpenAI")
    def test_summarize_single_chapter_llm(self, mock_openai_cls):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "- 요약 1: 머신러닝 기초\n- 요약 2: 데이터셋 중요성"
        mock_completion.choices = [mock_choice]

        mock_client.chat.completions.create = AsyncMock(return_value=mock_completion)

        summarizer = LLMSummarizer(self.sample_md, api_key="sk-test-key")
        summarizer.client = mock_client

        import asyncio
        result = asyncio.run(
            summarizer._summarize_single_chapter("Chapter 1", "본문 텍스트 내용...")
        )

        self.assertEqual(result["title"], "Chapter 1")
        self.assertIn("머신러닝 기초", result["summary"])

    def test_generate_chapter_summaries(self):
        summarizer = LLMSummarizer(self.sample_md)
        summary_result = summarizer.generate_chapter_summaries()

        self.assertIn("## AI 챕터별 핵심 요약", summary_result)
        self.assertIn("### Introduction to AI", summary_result)
        self.assertIn("### Chapter 1: Machine Learning Basics", summary_result)

    def test_save_final_markdown(self):
        summarizer = LLMSummarizer(self.sample_md)
        out_dir = Path(self.temp_dir) / "output"

        metadata = {
            "title": "sample",
            "language": "en",
            "engine": "Marker",
            "validation_score": 0.95
        }
        index_content = summarizer.generate_index()
        summary_content = summarizer.generate_chapter_summaries()

        final_path = summarizer.save_final_markdown(
            metadata=metadata,
            index_content=index_content,
            summary_content=summary_content,
            target_dir=out_dir
        )

        self.assertTrue(final_path.exists())
        content = final_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---"))
        self.assertIn("title: sample", content)
        self.assertIn("## 목차", content)
        self.assertIn("## AI 챕터별 핵심 요약", content)
        self.assertIn("## 본문", content)


if __name__ == "__main__":
    unittest.main()
