from pathlib import Path
from src.google_drive import GoogleDriveManager
from src.ui import print_account_dashboard, print_drive_tree, console


def authenticate_google_drive():
    console.print("\n[bold cyan]🔑 [GDrive Book Markdown Pipeline] Google Drive OAuth 2.0 인증 및 대시보드[/bold cyan]")
    drive = GoogleDriveManager()
    
    if not drive.service:
        console.print("[red]❌ 구글 드라이브 인증에 실패했거나 credentials.json이 없습니다.[/red]")
        return

    console.print("\n[bold green]✅ 구글 드라이브 연동 성공![/bold green]\n")
    
    # 1. 스토리지 현황 대시보드
    account_info = drive.get_account_and_quota()
    print_account_dashboard(account_info)

    # 2. 계층 디렉토리 트리 출력
    console.print("\n[bold magenta]📂 [구글 드라이브 전체 디렉토리 및 도서 목록]:[/bold magenta]")
    print_drive_tree(drive)


if __name__ == "__main__":
    authenticate_google_drive()
