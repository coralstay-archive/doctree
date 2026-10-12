import argparse
import os
import sys
import time
import shutil
from pathlib import Path
from typing import List, Optional

from config.settings import (
    INPUT_PDF_DIR,
    TEMP_MD_DIR,
    FAILED_MD_DIR,
    OUTPUT_MD_DIR,
    SIMILARITY_THRESHOLD,
    GOOGLE_SERVICE_ACCOUNT_FILE,
    GOOGLE_DRIVE_FOLDER_ID,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_BASE_URL,
)
from src.google_drive import GoogleDriveManager
from src.converter import PDFConverter
from src.validator import ConversionValidator
from src.summarizer import LLMSummarizer
from src.ui import print_account_dashboard, print_drive_tree, print_local_status, console


# ==========================================
# 📊 상태 점검 및 실시간 모니터링
# ==========================================

def show_status(drive: GoogleDriveManager, show_tree: bool = True):
    """현재 구글 드라이브 계정 정보, 스토리지, 로컬 상태 및 전체 디렉토리 트리를 출력합니다."""
    console.print("\n[bold cyan]📊 [GDrive Book Markdown Pipeline] 시스템 및 파이프라인 상태 점검[/bold cyan]")
    
    # 1. 로컬 데이터 폴더 현황
    print_local_status(INPUT_PDF_DIR, TEMP_MD_DIR, FAILED_MD_DIR, OUTPUT_MD_DIR)
    
    # 2. 구글 드라이브 계정 및 스토리지
    if not drive.service:
        console.print("\n[yellow]⚠️ 구글 드라이브 서비스가 활성화되지 않았습니다. (인증 파일 확인 필요)[/yellow]")
        return

    account_info = drive.get_account_and_quota()
    print_account_dashboard(account_info)
    
    # 3. 구글 드라이브 디렉토리 트리
    if show_tree:
        console.print("\n[bold magenta]📂 [구글 드라이브 전체 디렉토리 및 도서 목록]:[/bold magenta]")
        print_drive_tree(drive)


def watch_mode(drive: GoogleDriveManager, interval: int = 30):
    """구글 드라이브 변경 감지(Changes API)를 모니터링하여 새 파일 업로드 시 자동 실행합니다."""
    console.print(f"\n[bold green]👀 [Watch Mode] 구글 드라이브 실시간 모니터링 시작 (주기: {interval}초)[/bold green]")
    console.print("[dim]종료하려면 Ctrl+C를 누르세요.[/dim]\n")

    drive.get_start_page_token()

    try:
        while True:
            changes, _ = drive.check_changes()
            if changes:
                pdf_changes = [
                    c for c in changes
                    if not c.get('removed') and c.get('file', {}).get('mimeType') == 'application/pdf'
                ]
                if pdf_changes:
                    console.print(f"\n[bold yellow]🔔 {len(pdf_changes)}개의 신규/수정된 PDF 도서 감지됨! 파이프라인 가동...[/bold yellow]")
                    run_pipeline(skip_drive_sync=False)
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]모니터링이 중단되었습니다.[/yellow]")


# ==========================================
# 🛠️ 각 단계별 핵심 실행 함수 (Subcommands)
# ==========================================

def step_sync(force_recheck_md5: bool = False, target_dir: Optional[Path] = None) -> GoogleDriveManager:
    """1단계: 구글 드라이브 동기화 및 도서 PDF 청크 다운로드"""
    dest_dir = target_dir or INPUT_PDF_DIR
    console.print("\n[bold blue]📥 [Step 1: Sync] 구글 드라이브 PDF 동기화 및 다운로드 시작...[/bold blue]")
    drive = GoogleDriveManager(
        service_account_file=GOOGLE_SERVICE_ACCOUNT_FILE,
        folder_id=GOOGLE_DRIVE_FOLDER_ID
    )
    if drive.service:
        account_info = drive.get_account_and_quota()
        if account_info:
            console.print(f"  👤 [cyan]{account_info.get('email')}[/cyan] ({account_info.get('usage_gb')}GB / {account_info.get('limit_gb')}GB)")
        downloaded = drive.download_new_pdfs(target_dir=dest_dir, force_recheck_md5=force_recheck_md5)
        console.print(f"[bold green]✔️ Step 1 완료: 총 {len(downloaded)}개 파일 동기화[/bold green]")
    else:
        console.print("[yellow]⚠️ 구글 드라이브 연동 불가 (로컬 모드로 전환합니다)[/yellow]")
    return drive


def step_convert(
    input_path: Path,
    output_dir: Optional[Path] = None,
    engine: Optional[str] = None,
    lang: Optional[str] = None
) -> List[Path]:
    """2단계: PDF 언어 분석 및 Marker/MinerU 맞춤형 마크다운 변환"""
    out_dir = output_dir or TEMP_MD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_files = []
    if input_path.is_file():
        pdf_files = [input_path]
    elif input_path.is_dir():
        pdf_files = sorted(list(set(list(input_path.rglob("*.pdf")) + list(input_path.rglob("*.PDF")))))

    if not pdf_files:
        console.print(f"[yellow]⚠️ {input_path} 에서 변환할 PDF 파일을 찾을 수 없습니다.[/yellow]")
        return []

    converted_paths = []
    console.print(f"\n[bold blue]⚙️ [Step 2: Convert] {len(pdf_files)}권 PDF 변환 시작 -> {out_dir}[/bold blue]")

    for idx, pdf in enumerate(pdf_files, 1):
        rel_path = pdf.relative_to(input_path) if input_path.is_dir() else pdf.name
        target_sub_dir = (out_dir / Path(rel_path).parent) if input_path.is_dir() else out_dir
        
        console.print(f"[{idx}/{len(pdf_files)}] [bold]변환 대상:[/bold] {pdf.name}")
        converter = PDFConverter(pdf)
        if lang:
            converter.language = lang
        if engine and engine.lower() != "auto":
            converter.engine_name = engine

        md_path = converter.convert(output_dir=target_sub_dir)
        converted_paths.append(md_path)
        console.print(f"  └─ [green]생성 완료:[/green] {md_path}")

    return converted_paths


def step_validate(
    pdf_path: Path,
    md_path: Path,
    threshold: float = SIMILARITY_THRESHOLD,
    isolate_failed: bool = True,
    failed_dir: Optional[Path] = None
) -> bool:
    """3단계: 원본 PDF와 변환 MD 간 텍스트 유사도 검증 (Validation Gate)"""
    target_failed_dir = failed_dir or FAILED_MD_DIR
    console.print(f"\n[bold blue]🔍 [Step 3: Validate] 텍스트 유사도 검증... (임계치: {threshold:.2%})[/bold blue]")
    console.print(f"  • PDF: {pdf_path}")
    console.print(f"  • MD : {md_path}")

    validator = ConversionValidator(pdf_path, md_path)
    is_valid, score = validator.check_similarity(threshold=threshold)

    if not is_valid:
        console.print(f"[red]❌ [검증 실패] 일치율: {score:.2%} (기준치 {threshold:.2%} 미달)[/red]")
        if isolate_failed:
            moved = validator.move_to_failed(target_dir=target_failed_dir)
            console.print(f"[yellow]  └─ 격리 폴더로 이동됨: {moved}[/yellow]")
        return False

    console.print(f"[green]✔️ [검증 통과] 일치율: {score:.2%}[/green]")
    return True


def step_summarize(
    md_path: Path,
    skip_llm: bool = False,
    model: str = OPENAI_MODEL
) -> dict:
    """4단계: 목차(TOC) 파싱 및 LLM 챕터별 비동기 요약"""
    console.print(f"\n[bold blue]🧠 [Step 4: Summarize] 목차 분석 및 요약 생성... (대상: {md_path.name})[/bold blue]")
    summarizer = LLMSummarizer(
        md_path=md_path,
        api_key=OPENAI_API_KEY,
        model=model,
        base_url=OPENAI_BASE_URL
    )
    book_index = summarizer.generate_index()
    console.print(f"  • [cyan]자동 생성 목차:[/cyan] {len(book_index.splitlines())}개 헤더 추출")

    chapter_summaries = ""
    if not skip_llm:
        chapter_summaries = summarizer.generate_chapter_summaries()
        console.print("  • [cyan]LLM 장별 요약:[/cyan] 생성 완료")
    else:
        console.print("  • [yellow]LLM 요약 단계를 건너뜁니다 (--skip-llm).[/yellow]")

    return {
        "index": book_index,
        "summary": chapter_summaries,
        "summarizer": summarizer
    }


def step_assemble(
    md_path: Path,
    index_content: str,
    summary_content: str,
    metadata: dict,
    output_dir: Optional[Path] = None
) -> Path:
    """5단계: YAML 프론트매터 결합 및 최종 마크다운 생성"""
    out_dir = output_dir or OUTPUT_MD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"\n[bold blue]📑 [Step 5: Assemble] 최종 마크다운 결합 및 저장... -> {out_dir}[/bold blue]")

    summarizer = LLMSummarizer(md_path=md_path)
    final_file = summarizer.save_final_markdown(
        metadata=metadata,
        index_content=index_content,
        summary_content=summary_content,
        target_dir=out_dir
    )
    console.print(f"[bold green]✨ [최종 완료] {final_file}[/bold green]")
    return final_file


# ==========================================
# 🚀 전체 파이프라인 제어 (Run)
# ==========================================

def run_pipeline(
    skip_drive_sync: bool = False,
    force_recheck_md5: bool = False,
    target_single_pdf: Optional[Path] = None,
    limit: Optional[int] = None,
    threshold: float = SIMILARITY_THRESHOLD,
    model: str = OPENAI_MODEL
):
    """전체 5단계 자동화 파이프라인을 가동합니다."""
    console.print("=" * 65)
    console.print("🚀 [bold green][GDrive Book Markdown Pipeline] 5단계 자동화 파이프라인 가동[/bold green]")
    console.print("=" * 65)

    # 1. 구글 드라이브 동기화
    if not skip_drive_sync and not target_single_pdf:
        step_sync(force_recheck_md5=force_recheck_md5)

    # 처리할 PDF 파일 목록 탐색
    if target_single_pdf:
        if not target_single_pdf.exists():
            console.print(f"[red]❌ 지정한 PDF 파일이 존재하지 않습니다: {target_single_pdf}[/red]")
            return
        pdf_files = [target_single_pdf]
    else:
        pdf_files = list(INPUT_PDF_DIR.rglob("*.pdf")) + list(INPUT_PDF_DIR.rglob("*.PDF"))
        pdf_files = sorted(list(set(pdf_files)))

    if not pdf_files:
        console.print(f"[yellow][Info] {INPUT_PDF_DIR} 에 처리할 PDF 파일이 없습니다.[/yellow]")
        return

    if limit and limit > 0:
        pdf_files = pdf_files[:limit]

    console.print(f"\n[bold cyan][Info] 총 {len(pdf_files)}권의 대상 도서를 순차 처리합니다.[/bold cyan]")

    for idx, pdf_path in enumerate(pdf_files, 1):
        rel_pdf_path = pdf_path.relative_to(INPUT_PDF_DIR) if pdf_path.is_relative_to(INPUT_PDF_DIR) else Path(pdf_path.name)
        console.print(f"\n────────────────────────────────────────────────────────────")
        console.print(f"[{idx}/{len(pdf_files)}] [bold]대상 도서:[/bold] {rel_pdf_path}")

        # 2. 변환
        converter = PDFConverter(pdf_path)
        target_temp_dir = (TEMP_MD_DIR / rel_pdf_path.parent)
        temp_md_path = converter.convert(output_dir=target_temp_dir)

        # 3. 검증
        validator = ConversionValidator(pdf_path, temp_md_path)
        is_valid, score = validator.check_similarity(threshold=threshold)

        if not is_valid:
            console.print(f"[red][Result ❌] 검증 실패 (일치율: {score:.2%}, 기준: {threshold:.2%}) -> 격리 폴더로 이동.[/red]")
            target_failed_dir = (FAILED_MD_DIR / rel_pdf_path.parent)
            validator.move_to_failed(target_dir=target_failed_dir)
            continue

        console.print(f"[green][Result ✔️] 검증 통과 (일치율: {score:.2%}). 구조 분석 및 요약 단계를 진행합니다.[/green]")

        # 4. 요약 & 목차
        summarizer = LLMSummarizer(
            md_path=temp_md_path,
            api_key=OPENAI_API_KEY,
            model=model,
            base_url=OPENAI_BASE_URL
        )
        book_index = summarizer.generate_index()
        chapter_summaries = summarizer.generate_chapter_summaries()

        # 5. 프론트매터 결합 및 최종 마크다운 생성
        target_out_dir = (OUTPUT_MD_DIR / rel_pdf_path.parent)
        final_file = summarizer.save_final_markdown(
            metadata={
                "title": pdf_path.stem,
                "relative_path": str(rel_pdf_path),
                "language": converter.language,
                "engine": converter.engine_name,
                "validation_score": round(score, 4),
            },
            index_content=book_index,
            summary_content=chapter_summaries,
            target_dir=target_out_dir
        )

        console.print(f"[bold green]✨ [Complete] {rel_pdf_path} 완료 -> {final_file}[/bold green]")

    console.print("\n" + "=" * 65)
    console.print("🎉 [bold green][Pipeline] 모든 도서 처리 작업이 완료되었습니다.[/bold green]")
    console.print("=" * 65)


# ==========================================
# 🧹 데이터 정리 (Clean)
# ==========================================

def clean_data(target: str = "temp", confirm: bool = False):
    """파이프라인 생성 데이터 정리"""
    targets = {
        "temp": [TEMP_MD_DIR],
        "failed": [FAILED_MD_DIR],
        "output": [OUTPUT_MD_DIR],
        "all": [TEMP_MD_DIR, FAILED_MD_DIR, OUTPUT_MD_DIR],
    }
    target_dirs = targets.get(target, [TEMP_MD_DIR])
    
    if not confirm:
        console.print(f"[yellow]⚠️ 다음 디렉터리의 데이터가 삭제됩니다: {[str(d) for d in target_dirs]}[/yellow]")
        console.print("[dim]실행하려면 --yes / -y 플래그를 추가하세요.[/dim]")
        return

    for d in target_dirs:
        if d.exists():
            for item in d.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            console.print(f"[green]🧹 정리 완료: {d}[/green]")


# ==========================================
# 🎮 CLI 파서 및 서브커맨드 라우팅
# ==========================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gdrive-book-markdown-pipeline",
        description="📚 GDrive Book Markdown Pipeline: 400 DPI 도서 PDF ➔ 인덱스/요약 포함 마크다운 변환 자동화 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # 이전 버전 호환을 위한 최상위 옵션들
    parser.add_argument("--status", "--info", action="store_true", help="구글 드라이브 계정 및 디렉토리 상태 대시보드 출력")
    parser.add_argument("--sync-only", action="store_true", help="변환 없이 구글 드라이브 PDF 다운로드만 수행")
    parser.add_argument("--local-only", action="store_true", help="구글 드라이브 동기화 없이 로컬 data/01_input_pdf 도서만 변환")
    parser.add_argument("--watch", action="store_true", help="구글 드라이브 실시간 변경 감지 모니터링 모드 실행")
    parser.add_argument("--recheck-md5", action="store_true", help="기존 파일도 MD5 해시를 대조하여 변경된 경우 재다운로드")

    subparsers = parser.add_subparsers(dest="command", help="실행할 파이프라인 단계 또는 관리 명령어를 선택하세요")

    # 1. run (전체 파이프라인 실행)
    p_run = subparsers.add_parser("run", help="전체 5단계 자동화 파이프라인 실행 (동기화 ➔ 변환 ➔ 검증 ➔ 요약 ➔ 결합)")
    p_run.add_argument("--skip-sync", action="store_true", help="구글 드라이브 동기화 건너뛰기 (로컬 모드)")
    p_run.add_argument("--force-md5", action="store_true", help="MD5 해시 재대조 강제 수행")
    p_run.add_argument("--pdf", type=Path, default=None, help="특정 단일 PDF 파일만 지정하여 처리")
    p_run.add_argument("--limit", type=int, default=None, help="처리할 최대 도서 권수")
    p_run.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD, help=f"유사도 검증 임계치 (기본: {SIMILARITY_THRESHOLD})")
    p_run.add_argument("--model", type=str, default=OPENAI_MODEL, help=f"요약 모델 (기본: {OPENAI_MODEL})")

    # 2. sync / download (1단계)
    p_sync = subparsers.add_parser("sync", aliases=["download"], help="[1단계] 구글 드라이브로부터 신규/수정된 PDF 도서 동기화 및 다운로드")
    p_sync.add_argument("--force-md5", action="store_true", help="MD5 해시 재대조 강제 수행")
    p_sync.add_argument("--target-dir", type=Path, default=INPUT_PDF_DIR, help="저장할 로컬 디렉터리 경로")

    # 3. convert (2단계)
    p_conv = subparsers.add_parser("convert", help="[2단계] PDF 도서를 언어 분석 후 Marker/MinerU 엔진으로 마크다운 변환")
    p_conv.add_argument("input", nargs="?", type=Path, default=INPUT_PDF_DIR, help="변환할 PDF 파일 또는 디렉터리 (기본: data/01_input_pdf)")
    p_conv.add_argument("--output-dir", "-o", type=Path, default=TEMP_MD_DIR, help="임시 MD 저장 디렉터리 (기본: data/02_temp_md)")
    p_conv.add_argument("--engine", "-e", choices=["auto", "MinerU", "Marker"], default="auto", help="사용할 변환 엔진 (기본: auto)")
    p_conv.add_argument("--lang", "-l", type=str, default=None, help="수동 지정 언어 코드 (예: ko, en, ja, zh)")

    # 4. validate (3단계)
    p_val = subparsers.add_parser("validate", help="[3단계] 원본 PDF와 변환된 마크다운 간 텍스트 유사도 검증 Gate")
    p_val.add_argument("--pdf", type=Path, required=True, help="대조할 원본 PDF 파일 경로")
    p_val.add_argument("--md", type=Path, required=True, help="대조할 변환된 마크다운 파일 경로")
    p_val.add_argument("--threshold", "-t", type=float, default=SIMILARITY_THRESHOLD, help=f"유사도 통과 임계치 (기본: {SIMILARITY_THRESHOLD})")
    p_val.add_argument("--no-isolate", action="store_true", help="검증 실패 시 격리 폴더로 이동하지 않음")

    # 5. summarize (4단계)
    p_sum = subparsers.add_parser("summarize", help="[4단계] 마크다운 목차(TOC) 파싱 및 LLM 챕터별 비동기 요약 생성")
    p_sum.add_argument("input_md", type=Path, help="요약할 마크다운 파일 경로")
    p_sum.add_argument("--skip-llm", action="store_true", help="LLM API 호출 없이 목차(TOC)만 생성")
    p_sum.add_argument("--model", "-m", type=str, default=OPENAI_MODEL, help=f"요약에 사용할 LLM 모델 (기본: {OPENAI_MODEL})")

    # 6. assemble / build (5단계)
    p_ass = subparsers.add_parser("assemble", aliases=["build"], help="[5단계] YAML 프론트매터 + AI 요약 + TOC + 본문을 결합하여 최종본 생성")
    p_ass.add_argument("input_md", type=Path, help="본문 마크다운 파일 경로")
    p_ass.add_argument("--output-dir", "-o", type=Path, default=OUTPUT_MD_DIR, help="최종 마크다운 저장 폴더 (기본: data/04_output_md)")
    p_ass.add_argument("--title", type=str, default=None, help="도서 제목 메타데이터")
    p_ass.add_argument("--score", type=float, default=1.0, help="검증 점수 메타데이터")

    # 7. status / info (상태 점검)
    p_stat = subparsers.add_parser("status", aliases=["info"], help="구글 드라이브 계정, 스토리지 및 로컬 데이터 현황 대시보드 출력")
    p_stat.add_argument("--no-tree", action="store_true", help="구글 드라이브 디렉토리 트리 출력 생략")

    # 8. watch (실시간 모니터링)
    p_watch = subparsers.add_parser("watch", help="구글 드라이브 변경 감지(Changes API) 실시간 모니터링 데몬 실행")
    p_watch.add_argument("--interval", "-i", type=int, default=30, help="폴링 주기 (초 단위, 기본: 30초)")

    # 9. auth / login (구글 인증)
    p_auth = subparsers.add_parser("auth", aliases=["login"], help="Google OAuth 2.0 대화형 로그인 및 token.json 생성")

    # 10. clean (데이터 정리)
    p_clean = subparsers.add_parser("clean", help="임시 및 작업 데이터 디렉터리 정리")
    p_clean.add_argument("--target", choices=["temp", "failed", "output", "all"], default="temp", help="정리할 대상 폴더 (기본: temp)")
    p_clean.add_argument("--yes", "-y", action="store_true", help="확인 절차 없이 즉시 삭제")

    return parser


def cli_entry():
    """CLI 진입점 함수"""
    parser = build_parser()
    args = parser.parse_args()

    drive = GoogleDriveManager(
        service_account_file=GOOGLE_SERVICE_ACCOUNT_FILE,
        folder_id=GOOGLE_DRIVE_FOLDER_ID
    )

    # 1. 최상위 레거시 플래그 처리
    if args.status:
        show_status(drive)
        return
    elif args.watch:
        watch_mode(drive)
        return
    elif args.sync_only:
        step_sync(force_recheck_md5=args.recheck_md5)
        return
    elif args.local_only:
        run_pipeline(skip_drive_sync=True, force_recheck_md5=args.recheck_md5)
        return

    # 2. 서브커맨드 라우팅
    cmd = args.command
    if cmd in ["sync", "download"]:
        step_sync(force_recheck_md5=args.force_md5, target_dir=args.target_dir)

    elif cmd == "convert":
        step_convert(
            input_path=args.input,
            output_dir=args.output_dir,
            engine=args.engine,
            lang=args.lang
        )

    elif cmd == "validate":
        step_validate(
            pdf_path=args.pdf,
            md_path=args.md,
            threshold=args.threshold,
            isolate_failed=not args.no_isolate
        )

    elif cmd == "summarize":
        res = step_summarize(
            md_path=args.input_md,
            skip_llm=args.skip_llm,
            model=args.model
        )
        console.print("\n[bold cyan]📋 생성된 목차 (TOC):[/bold cyan]")
        console.print(res["index"] or "(목차 없음)")
        if res["summary"]:
            console.print("\n[bold cyan]📑 장별 요약:[/bold cyan]")
            console.print(res["summary"])

    elif cmd in ["assemble", "build"]:
        title = args.title or args.input_md.stem
        # 목차 및 요약 생성 후 결합
        res = step_summarize(md_path=args.input_md, skip_llm=False)
        step_assemble(
            md_path=args.input_md,
            index_content=res["index"],
            summary_content=res["summary"],
            metadata={
                "title": title,
                "validation_score": args.score
            },
            output_dir=args.output_dir
        )

    elif cmd in ["status", "info"]:
        show_status(drive, show_tree=not args.no_tree)

    elif cmd == "watch":
        watch_mode(drive, interval=args.interval)

    elif cmd in ["auth", "login"]:
        from auth_login import authenticate_google_drive
        authenticate_google_drive()

    elif cmd == "clean":
        clean_data(target=args.target, confirm=args.yes)

    elif cmd == "run":
        run_pipeline(
            skip_drive_sync=args.skip_sync,
            force_recheck_md5=args.force_md5,
            target_single_pdf=args.pdf,
            limit=args.limit,
            threshold=args.threshold,
            model=args.model
        )

    else:
        # 서브커맨드 미지정 시 기본 5단계 파이프라인 가동
        run_pipeline(skip_drive_sync=False, force_recheck_md5=args.recheck_md5)


if __name__ == "__main__":
    cli_entry()
