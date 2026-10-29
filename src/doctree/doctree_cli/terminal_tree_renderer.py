"""터미널 분류 트리 포맷터 및 구글 드라이브 스토리지 Rich 대시보드 렌더러."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from doctree.content_taxonomy.category_classifier import ClassificationResult, ClassifiedContent
from doctree.runtime_env.workspace_settings import normalize_nfc

__all__ = [
    "console",
    "format_classification_summary",
    "print_account_dashboard",
]

console = Console()


def _single_line(value: str) -> str:
    value = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in value)
    return " ".join(value.split())


def _content_key(content: ClassifiedContent) -> tuple:
    return (normalize_nfc(content.record["name"]).casefold(), content.record["id"])


def _source_path(content: ClassifiedContent) -> str:
    record = content.record
    folder_path = record.get("folder_path")
    if isinstance(folder_path, str) and folder_path:
        return folder_path.rstrip("/") + "/" + record["name"]
    return record["name"]


def format_classification_summary(result: ClassificationResult) -> str:
    """고정 분류 트리 순서(빈 세부분야 포함)와 미분류 검토 목록을 터미널 출력용 텍스트로 만든다."""
    grouped: dict[str, list[ClassifiedContent]] = {
        subcategory.id: []
        for category in result.catalog.categories
        for subcategory in category.subcategories
    }
    for content in result.contents:
        if content.category_id is not None:
            if content.category_id not in grouped:
                raise ValueError("분류표에 없는 세부분야 ID: " + content.category_id)
            grouped[content.category_id].append(content)

    unclassified = result.unclassified
    lines = [
        f"파일 {len(result.contents)}개 · 분류 {len(result.contents) - len(unclassified)}권 · 미분류 {len(unclassified)}권",
        "",
        "콘텐츠 목록",
    ]
    categories = result.catalog.categories
    for category_number, category in enumerate(categories, start=1):
        category_last = category_number == len(categories)
        lines.append(
            ("└── " if category_last else "├── ")
            + f"{category_number}. {_single_line(category.name)}"
        )
        category_prefix = "    " if category_last else "│   "
        for subcategory_number, subcategory in enumerate(category.subcategories, start=1):
            subcategory_last = subcategory_number == len(category.subcategories)
            contents = sorted(grouped[subcategory.id], key=_content_key)
            lines.append(
                category_prefix
                + ("└── " if subcategory_last else "├── ")
                + f"{_single_line(subcategory.name)} ({len(contents)})"
            )
            content_prefix = category_prefix + ("    " if subcategory_last else "│   ")
            for content_number, content in enumerate(contents, start=1):
                lines.append(
                    content_prefix
                    + ("└── " if content_number == len(contents) else "├── ")
                    + _single_line(content.record["name"])
                )

    lines.extend(["", "[미분류·검토 대기]"])
    if unclassified:
        for content in sorted(unclassified, key=_content_key):
            lines.append(
                f"- {_single_line(content.record['name'])} "
                f"(id={_single_line(content.record['id'])}, path={_single_line(_source_path(content))})"
            )
    else:
        lines.append("미분류 콘텐츠가 없습니다.")
    return "\n".join(lines) + "\n"


def print_account_dashboard(account_info: dict | None):
    """구글 계정 및 드라이브 스토리지 현황을 rich 대시보드로 출력합니다."""
    if not account_info:
        console.print("[yellow]⚠️ 구글 계정 정보 조회를 건너뜁니다 (인증 필요).[/yellow]")
        return

    table = Table(title="📊 [bold cyan]Google Drive 계정 & 스토리지 상태[/bold cyan]", show_header=True, header_style="bold magenta")
    table.add_column("항목", style="cyan", width=20)
    table.add_column("상태 / 정보", style="green")

    table.add_row("👤 사용자", account_info.get("name", "Unknown"))
    table.add_row("📧 계정 이메일", account_info.get("email", "Unknown"))

    limit_gb = account_info.get("limit_gb")
    usage_gb = account_info.get("usage_gb", 0)
    usage_percent = account_info.get("usage_percent", 0.0)

    if limit_gb:
        gauge_bar = f"[{'█' * int(usage_percent // 5)}{'░' * (20 - int(usage_percent // 5))}] {usage_percent}%"
        table.add_row("💾 전체 스토리지", f"{usage_gb} GB / {limit_gb} GB ({gauge_bar})")
    else:
        table.add_row("💾 전체 스토리지 사용량", f"{usage_gb} GB (무제한/기관)")

    table.add_row("📁 드라이브 순수 사용", f"{account_info.get('drive_usage_gb', 0)} GB")

    console.print(table)
