import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree
from rich import print as rprint

from src.google_drive import GoogleDriveManager, normalize_str

console = Console()


def print_account_dashboard(account_info: Optional[dict]):
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


def print_drive_tree(drive: GoogleDriveManager, max_depth: int = 4):
    """구글 드라이브 내 디렉토리 및 PDF 도서 트리를 rich.Tree로 시각화합니다."""
    if not drive.service:
        return

    with console.status("[bold green]드라이브 디렉토리 구조 스캔 중..."):
        all_items = []
        page_token = None
        while True:
            response = drive.service.files().list(
                q="trashed=false",
                spaces='drive',
                pageSize=1000,
                fields='nextPageToken, files(id, name, mimeType, parents, size)',
                pageToken=page_token
            ).execute()
            all_items.extend(response.get('files', []))
            page_token = response.get('nextPageToken')
            if not page_token:
                break

    folders = {}
    children_map = defaultdict(list)
    items_by_id = {}

    for item in all_items:
        item_id = item['id']
        items_by_id[item_id] = item
        parents = item.get('parents', ['root'])
        parent_id = parents[0] if parents else 'root'
        children_map[parent_id].append(item_id)
        if item.get('mimeType') == 'application/vnd.google-apps.folder':
            folders[item_id] = item

    all_folder_ids = set(folders.keys())
    top_level_ids = [fid for fid in all_folder_ids if not folders[fid].get('parents') or folders[fid]['parents'][0] not in all_folder_ids]
    direct_files = [item['id'] for item in all_items if item.get('mimeType') != 'application/vnd.google-apps.folder' and (not item.get('parents') or item.get('parents')[0] not in all_folder_ids)]

    root_tree = Tree(f"📁 [bold blue]Google Drive Root[/bold blue] (총 {len(all_items)}개 항목)")

    def add_children(tree_node, node_id, current_depth):
        if current_depth > max_depth:
            return
        children = sorted(
            children_map.get(node_id, []),
            key=lambda cid: (
                items_by_id.get(cid, {}).get('mimeType') != 'application/vnd.google-apps.folder',
                normalize_str(items_by_id.get(cid, {}).get('name', ''))
            )
        )
        for child_id in children:
            child = items_by_id.get(child_id)
            if not child:
                continue
            is_folder = child.get('mimeType') == 'application/vnd.google-apps.folder'
            name = normalize_str(child.get('name', ''))
            if is_folder:
                sub_tree = tree_node.add(f"📂 [bold yellow]{name}[/bold yellow]")
                add_children(sub_tree, child_id, current_depth + 1)
            else:
                size_str = f" [dim]({int(child['size'])/(1024*1024):.1f} MB)[/dim]" if 'size' in child and child['size'] else ""
                tree_node.add(f"📄 [cyan]{name}[/cyan]{size_str}")

    top_nodes = sorted(top_level_ids + direct_files, key=lambda nid: (items_by_id.get(nid, {}).get('mimeType') != 'application/vnd.google-apps.folder', normalize_str(items_by_id.get(nid, {}).get('name', ''))))
    for top_id in top_nodes:
        top_item = items_by_id.get(top_id)
        if not top_item:
            continue
        is_folder = top_item.get('mimeType') == 'application/vnd.google-apps.folder'
        name = normalize_str(top_item.get('name', ''))
        if is_folder:
            sub_tree = root_tree.add(f"📂 [bold yellow]{name}[/bold yellow]")
            add_children(sub_tree, top_id, 1)
        else:
            size_str = f" [dim]({int(top_item['size'])/(1024*1024):.1f} MB)[/dim]" if 'size' in top_item and top_item['size'] else ""
            root_tree.add(f"📄 [cyan]{name}[/cyan]{size_str}")

    console.print(root_tree)
