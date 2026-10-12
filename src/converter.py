import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

try:
    import pdfplumber
    from langdetect import detect
    from langdetect.lang_detect_exception import LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    pdfplumber = None
    detect = None
    LangDetectException = Exception
    LANGDETECT_AVAILABLE = False


def check_pdf_validity(pdf_path: Path) -> Tuple[bool, str]:
    """PDF 파일의 유효성 및 암호화 여부 검사"""
    if not pdf_path.exists():
        return False, "파일이 존재하지 않습니다."
    if pdf_path.stat().st_size == 0:
        return False, "0바이트 빈 파일입니다."

    try:
        with open(pdf_path, "rb") as f:
            header = f.read(5)
            if not header.startswith(b"%PDF-"):
                return False, "유효한 PDF 헤더(%PDF-)가 아닙니다."
    except Exception as e:
        return False, f"파일 읽기 오류: {e}"

    if pdfplumber:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # pypdf / pdfplumber 암호화 여부 체크
                if getattr(pdf.doc, 'is_encrypted', False):
                    return False, "암호로 보호된(Encrypted) PDF입니다."
                if len(pdf.pages) == 0:
                    return False, "페이지가 없는 PDF입니다."
        except Exception as e:
            err_msg = str(e).lower()
            if "password" in err_msg or "encrypt" in err_msg:
                return False, "암호로 보호된(Encrypted) PDF입니다."
            return False, f"PDF 파싱 손상: {e}"

    return True, "정상"


class PDFConverter:
    """언어 및 문서 특성 분석 후 Marker 또는 MinerU 엔진으로 Markdown 변환 수행"""

    def __init__(self, pdf_path: str or Path):
        self.pdf_path = Path(pdf_path)
        self.language: Optional[str] = None
        self.engine_name: str = "Unknown"

    def is_valid_pdf(self) -> Tuple[bool, str]:
        """PDF 무결성 및 암호화 상태 확인"""
        return check_pdf_validity(self.pdf_path)

    def detect_language(self) -> str:
        """PDF 초반 페이지의 텍스트를 분석하여 주요 언어를 감지합니다."""
        sample_text = ""
        try:
            if pdfplumber:
                with pdfplumber.open(self.pdf_path) as pdf:
                    # 앞쪽 5개 페이지 내 텍스트 샘플 추출
                    for page in pdf.pages[:5]:
                        text = page.extract_text() or ""
                        sample_text += text + " "
                        if len(sample_text) > 300:
                            break

            if sample_text.strip() and LANGDETECT_AVAILABLE:
                try:
                    self.language = detect(sample_text)
                except LangDetectException:
                    self.language = "ko"
            else:
                self.language = "ko"  # 텍스트가 거의 없는 이미지 PDF 등은 기본 한국어로 처리
        except Exception as e:
            print(f"[PDFConverter] 언어 감지 중 경고 ({self.pdf_path.name}): {e}")
            self.language = "ko"

        return self.language

    def select_engine(self) -> str:
        """언어 및 특성에 따라 적합한 변환 엔진을 결정합니다."""
        lang = self.detect_language()
        # 한국어, 중국어, 일본어 (CJK)는 MinerU 엔진 우선
        if lang in ["ko", "zh-cn", "zh-tw", "ja"]:
            self.engine_name = "MinerU"
        else:
            # 영어 및 수식/기술 도서는 Marker 엔진
            self.engine_name = "Marker"
        return self.engine_name

    def convert(self, output_dir: str or Path, timeout_seconds: int = 1800) -> Path:
        """선택된 엔진으로 변환을 실행하고 생성된 임시 Markdown 파일 경로를 반환합니다."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        target_md_file = output_path / f"{self.pdf_path.stem}.md"

        # 1. PDF 무결성 사전 검사
        is_valid, reason = self.is_valid_pdf()
        if not is_valid:
            print(f"[PDFConverter] ⚠️ {self.pdf_path.name} 유효성 검사 실패: {reason}")
            target_md_file.write_text(f"# {self.pdf_path.stem}\n\n[변환 실패: {reason}]\n", encoding="utf-8")
            return target_md_file

        engine = self.select_engine()
        print(f"[PDFConverter] {self.pdf_path.name} 언어: {self.language} -> 엔진: {engine} 실행")

        if engine == "MinerU":
            self._convert_with_mineru(output_path, target_md_file, timeout_seconds=timeout_seconds)
        else:
            self._convert_with_marker(output_path, target_md_file, timeout_seconds=timeout_seconds)

        return target_md_file

    def _convert_with_marker(self, output_dir: Path, target_md_file: Path, timeout_seconds: int = 1800):
        """Marker CLI / API를 사용한 변환 (타임아웃 및 프로세스 에러 방어)"""
        marker_cmd = shutil.which("marker_single")
        if marker_cmd:
            try:
                cmd = [
                    marker_cmd,
                    str(self.pdf_path),
                    str(output_dir),
                    "--batch_multiplier", "2"
                ]
                proc = subprocess.run(cmd, check=True, timeout=timeout_seconds, capture_output=True, text=True)
                # 만약 출력된 md 파일이 없거나 빈 파일이면 폴백
                if not target_md_file.exists() or target_md_file.stat().st_size == 0:
                    print(f"[PDFConverter] Marker 실행 후 결과 파일 누락, 폴백 추출을 시도합니다.")
                    self._fallback_text_extraction(target_md_file)
            except subprocess.TimeoutExpired:
                print(f"[PDFConverter] Marker 실행 시간 초과 ({timeout_seconds}초), 기본 텍스트 추출로 대체합니다.")
                self._fallback_text_extraction(target_md_file)
            except Exception as e:
                print(f"[PDFConverter] Marker 실행 에러 ({e}), 기본 텍스트 추출로 대체합니다.")
                self._fallback_text_extraction(target_md_file)
        else:
            print("[PDFConverter] Marker CLI가 환경에 설치되어 있지 않아 기본 텍스트 추출로 대체합니다.")
            self._fallback_text_extraction(target_md_file)

    def _convert_with_mineru(self, output_dir: Path, target_md_file: Path, timeout_seconds: int = 1800):
        """MinerU (magic-pdf) CLI를 사용한 변환 (타임아웃 및 프로세스 에러 방어)"""
        magic_pdf_cmd = shutil.which("magic-pdf")
        if magic_pdf_cmd:
            try:
                cmd = [
                    magic_pdf_cmd,
                    "-p", str(self.pdf_path),
                    "-o", str(output_dir),
                    "-m", "auto"
                ]
                subprocess.run(cmd, check=True, timeout=timeout_seconds, capture_output=True, text=True)
                if not target_md_file.exists() or target_md_file.stat().st_size == 0:
                    # MinerU는 하위 디렉토리에 생성할 수도 있으므로 탐색
                    generated_mds = list(output_dir.glob(f"**/{self.pdf_path.stem}*.md"))
                    if generated_mds and generated_mds[0] != target_md_file:
                        shutil.copy(generated_mds[0], target_md_file)
                    else:
                        print(f"[PDFConverter] MinerU 실행 후 결과 파일 누락, 폴백 추출을 시도합니다.")
                        self._fallback_text_extraction(target_md_file)
            except subprocess.TimeoutExpired:
                print(f"[PDFConverter] MinerU 실행 시간 초과 ({timeout_seconds}초), 기본 텍스트 추출로 대체합니다.")
                self._fallback_text_extraction(target_md_file)
            except Exception as e:
                print(f"[PDFConverter] MinerU 실행 에러 ({e}), 기본 텍스트 추출로 대체합니다.")
                self._fallback_text_extraction(target_md_file)
        else:
            print("[PDFConverter] MinerU (magic-pdf) CLI가 환경에 설치되어 있지 않아 기본 텍스트 추출로 대체합니다.")
            self._fallback_text_extraction(target_md_file)

    def _fallback_text_extraction(self, target_md_file: Path):
        """엔진 부재 또는 실패 시 pdfplumber를 이용한 기본 마크다운 폴백 변환"""
        content_lines = [f"# {self.pdf_path.stem}\n"]
        try:
            if pdfplumber:
                with pdfplumber.open(self.pdf_path) as pdf:
                    for idx, page in enumerate(pdf.pages, 1):
                        text = page.extract_text() or ""
                        content_lines.append(f"## Page {idx}\n")
                        content_lines.append(text + "\n")
            else:
                content_lines.append("\n[pdfplumber 모듈 부재로 텍스트 추출 불가]\n")
            target_md_file.write_text("\n".join(content_lines), encoding="utf-8")
        except Exception as e:
            print(f"[PDFConverter] 폴백 텍스트 추출 실패: {e}")
            target_md_file.write_text(f"# {self.pdf_path.stem}\n\n[변환 실패: {e}]\n", encoding="utf-8")
