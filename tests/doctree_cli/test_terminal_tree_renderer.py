"""터미널 출력 포맷터 및 대시보드(src.doctree_cli.terminal_tree_renderer) 단위 테스트."""
import io
from unittest.mock import patch

import pytest
from rich.console import Console

from doctree.content_taxonomy.category_classifier import (
    Category,
    ClassificationCatalog,
    ClassificationResult,
    ClassifiedContent,
    Subcategory,
)
from doctree.doctree_cli import terminal_tree_renderer as ui


def test_format_classification_summary_renders_tree_and_unclassified_paths():
    catalog = ClassificationCatalog(
        categories=(
            Category(
                id="cs",
                name="컴퓨터\n과학\x7f",
                subcategories=(
                    Subcategory(id="cs.algo", name="알고리즘"),
                    Subcategory(id="cs.os", name="운영체제"),
                ),
            ),
        ),
        assignments=(),
    )
    result = ClassificationResult(
        catalog=catalog,
        contents=(
            ClassifiedContent(record={"id": "1", "name": "알고리즘.pdf", "folder_path": "CS"}, category_id="cs.algo"),
            ClassifiedContent(record={"id": "2", "name": "미분류_폴더.pdf", "folder_path": "기타/"}, category_id=None),
            ClassifiedContent(record={"id": "3", "name": "미분류_루트.pdf", "folder_path": ""}, category_id=None),
        ),
    )

    summary = ui.format_classification_summary(result)
    assert "파일 3개 · 분류 1권 · 미분류 2권" in summary
    assert "1. 컴퓨터 과학" in summary
    assert "알고리즘 (1)" in summary
    assert "운영체제 (0)" in summary
    assert "알고리즘.pdf" in summary
    assert "- 미분류_루트.pdf (id=3, path=미분류_루트.pdf)" in summary
    assert "- 미분류_폴더.pdf (id=2, path=기타/미분류_폴더.pdf)" in summary

    # 분류표에 존재하지 않는 category_id가 들어오면 ValueError 발생
    bad_result = ClassificationResult(
        catalog=catalog,
        contents=(ClassifiedContent(record={"id": "9", "name": "이상값.pdf"}, category_id="unknown.sub"),),
    )
    with pytest.raises(ValueError, match="분류표에 없는 세부분야 ID"):
        ui.format_classification_summary(bad_result)


def test_print_account_dashboard_outputs_none_limited_and_unlimited_storage():
    buf = io.StringIO()
    with patch("doctree.doctree_cli.terminal_tree_renderer.console", Console(file=buf, width=120, color_system=None)):
        ui.print_account_dashboard(None)
        ui.print_account_dashboard({
            "name": "Flynn",
            "email": "flynn@example.com",
            "limit_gb": 100.0,
            "usage_gb": 25.0,
            "drive_usage_gb": 20.0,
            "usage_percent": 25.0,
        })
        ui.print_account_dashboard({
            "name": "OrgUser",
            "email": "org@example.com",
            "limit_gb": None,
            "usage_gb": 50.0,
            "drive_usage_gb": 45.0,
            "usage_percent": 0.0,
        })
    out = buf.getvalue()
    assert "건너뜁니다" in out
    assert "Flynn" in out
    assert "25.0 GB / 100.0 GB" in out
    assert "50.0 GB (무제한/기관)" in out
