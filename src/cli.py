"""doctree: 구글 드라이브 도서 PDF 목록 대장 생성 CLI."""
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from config.settings import CATEGORIES_FILE, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_SERVICE_ACCOUNT_FILE, LEDGER_DIR
from src.checks import run_checks
from src.classify import UNCLASSIFIED, CategoryConfigError, classify, load_categories
from src.google_drive import DriveListError, GoogleDriveManager
from src.render import change_summary, render_ledger
from src.snapshot import record_run
from src.ui import console, print_account_dashboard

LEDGER_FILENAME = "도서목록.md"


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


def _now() -> datetime:
    """시간대가 붙은 로컬 현재 시각 (테스트에서 바꿔 끼운다)."""
    return datetime.now().astimezone()


def _fail(message: str) -> int:
    console.print(f"[red]❌ {message}[/red]")
    console.print("[yellow]기존 대장·스냅샷·변경 이력은 그대로 두었습니다.[/yellow]")
    return 1


def cmd_update(args: argparse.Namespace) -> int:
    """조회 → 분류 → 점검 → 스냅샷/이력 → ledger/도서목록.md 생성.

    B2: 인증 실패, 목록 조회 실패, 조회 결과 0개, categories.yaml 오류 중 하나라도 있으면
    파일을 하나도 쓰지 않고 1로 끝난다. 0개는 API 오류가 없어도 실패로 본다 — 드라이브에서 도서가
    정말 모두 사라졌을 가능성보다 폴더 ID 오설정·권한 문제일 가능성이 커서, 빈 대장으로 기존 대장과
    스냅샷을 덮어쓰는 것을 막기 위함이다.
    """
    ledger_dir = Path(args.ledger_dir or LEDGER_DIR)
    console.print("\n[bold cyan]📚 도서 목록 대장 갱신[/bold cyan]")

    drive = build_drive()
    if not drive.service:
        return _fail("구글 드라이브 인증에 실패했거나 credentials.json / token.json이 없습니다. `doctree auth`를 먼저 실행하세요.")
    try:
        records = drive.list_pdf_files()
    except DriveListError as e:
        return _fail(f"드라이브 목록 조회 실패: {e}")
    if not records:
        return _fail("드라이브에서 PDF를 0개 조회했습니다. 빈 대장을 막기 위해 중단합니다 (폴더 ID·권한 확인).")
    try:
        categories = load_categories(CATEGORIES_FILE)
    except CategoryConfigError as e:
        return _fail(f"분류 설정 오류: {e}")

    account = drive.get_account_and_quota()
    groups = classify(records, categories)
    warnings = run_checks(records)
    now = _now()

    # 여기부터 파일을 쓴다 (앞의 검증을 모두 통과한 경우에만).
    run = record_run(records, ledger_dir, now)
    text = render_ledger(
        groups=groups, warnings=warnings, run=run, account=account, now=now,
        categories=categories, changelog_link=run.changelog_path.name,
    )
    ledger_path = ledger_dir / LEDGER_FILENAME
    tmp = ledger_path.with_name(ledger_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ledger_path)

    unclassified = len(groups.get(UNCLASSIFIED[0], {}).get(UNCLASSIFIED[1], []))
    console.print(
        f"[bold green]✅ 총 {run.total}권[/bold green] · 분류 {run.total - unclassified}권 · "
        f"미분류 {unclassified}권 · 경고 {len(warnings)}건"
    )
    console.print(f"🔄 최근 변경: {change_summary(run)}")
    console.print(f"📄 대장: {ledger_path}")
    console.print(f"🕘 변경 이력: {run.changelog_path}")
    console.print(f"🗂️ 스냅샷: {run.snapshot_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doctree",
        description="구글 드라이브 도서 PDF 목록 대장 생성 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    p_auth = subparsers.add_parser("auth", help="Google OAuth 2.0 로그인 및 token.json 생성")
    p_auth.set_defaults(func=cmd_auth)

    p_status = subparsers.add_parser("status", help="구글 드라이브 계정·스토리지 용량 출력")
    p_status.set_defaults(func=cmd_status)

    p_update = subparsers.add_parser("update", help="드라이브 도서 목록을 조회해 ledger/도서목록.md 대장 갱신")
    p_update.add_argument("--ledger-dir", default=None, help="대장 출력 디렉터리 (기본: settings.LEDGER_DIR)")
    p_update.set_defaults(func=cmd_update)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
