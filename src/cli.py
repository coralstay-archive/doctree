"""booktree: 구글 드라이브 도서 PDF 목록 대장 생성 CLI."""
import argparse
from typing import List, Optional

from config.settings import GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SERVICE_ACCOUNT_FILE
from src.google_drive import GoogleDriveManager
from src.ui import console, print_account_dashboard


def build_drive() -> GoogleDriveManager:
    """기존 credentials.json / token.json 위치 그대로 Drive 클라이언트를 만든다 (재로그인 불필요)."""
    return GoogleDriveManager(
        service_account_file=GOOGLE_SERVICE_ACCOUNT_FILE,
        folder_id=GOOGLE_DRIVE_FOLDER_ID,
    )


def _print_account(drive: GoogleDriveManager) -> int:
    if not drive.service:
        console.print("[red]❌ 구글 드라이브 인증에 실패했거나 credentials.json / token.json이 없습니다.[/red]")
        return 1
    print_account_dashboard(drive.get_account_and_quota())
    return 0


def cmd_auth(args: argparse.Namespace) -> int:
    """Google OAuth 2.0 인증(token.json 생성·갱신) 후 계정 대시보드를 출력한다."""
    console.print("\n[bold cyan]🔑 Google Drive OAuth 2.0 인증[/bold cyan]")
    drive = build_drive()
    code = _print_account(drive)
    if code == 0:
        console.print("[bold green]✅ 구글 드라이브 연동 성공[/bold green]")
    return code


def cmd_status(args: argparse.Namespace) -> int:
    """구글 드라이브 계정과 스토리지 용량을 출력한다."""
    console.print("\n[bold cyan]📊 Google Drive 계정 상태[/bold cyan]")
    return _print_account(build_drive())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="booktree",
        description="구글 드라이브 도서 PDF 목록 대장 생성 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    p_auth = subparsers.add_parser("auth", help="Google OAuth 2.0 로그인 및 token.json 생성")
    p_auth.set_defaults(func=cmd_auth)

    p_status = subparsers.add_parser("status", help="구글 드라이브 계정·스토리지 용량 출력")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
