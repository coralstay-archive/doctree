import difflib
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Tuple

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


class ConversionValidator:
    """PDF 원본 텍스트와 변환된 마크다운 텍스트 간 유사도 검증 및 격리 처리"""

    def __init__(self, pdf_path: str or Path, md_path: str or Path):
        self.pdf_path = Path(pdf_path)
        self.md_path = Path(md_path)

    def _normalize_text(self, text: str) -> str:
        """한글 자모 분리(NFD) 교정, 공백 및 특수문자 정규화"""
        if not text:
            return ""
        # 1. NFC 완성형 유니코드 정규화 (macOS NFD 현상 방어)
        text = unicodedata.normalize('NFC', text)
        # 2. 연속된 공백 및 개행 정리
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def extract_pdf_text(self) -> str:
        """pdfplumber를 통해 원본 PDF 텍스트 추출"""
        if not self.pdf_path.exists() or self.pdf_path.stat().st_size == 0:
            return ""
        text_chunks = []
        if pdfplumber:
            try:
                with pdfplumber.open(self.pdf_path) as pdf:
                    for page in pdf.pages:
                        extracted = page.extract_text()
                        if extracted:
                            text_chunks.append(extracted)
            except Exception as e:
                print(f"[ConversionValidator] PDF 텍스트 추출 실패: {e}")
        return self._normalize_text(" ".join(text_chunks))

    def extract_md_text(self) -> str:
        """마크다운 파일에서 순수 텍스트 추출 (마크다운 기호 제거)"""
        if not self.md_path.exists() or self.md_path.stat().st_size == 0:
            return ""
        try:
            content = self.md_path.read_text(encoding="utf-8", errors="replace")
            # 헤더, 링크, 이미지 태그, 코드 블록 등 기본 마크다운 문법 제거
            cleaned = re.sub(r'```.*?```', '', content, flags=re.DOTALL)
            cleaned = re.sub(r'#+\s*', '', cleaned)
            cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', cleaned)
            cleaned = re.sub(r'\[.*?\]\(.*?\)', '', cleaned)
            cleaned = re.sub(r'[`*_~]', '', cleaned)
            return self._normalize_text(cleaned)
        except Exception as e:
            print(f"[ConversionValidator] MD 텍스트 추출 실패: {e}")
            return ""

    def check_similarity(self, threshold: float = 0.85) -> Tuple[bool, float]:
        """원본 PDF 텍스트와 변환 MD 텍스트 유사도(일치율)를 계산하여 통과 여부 반환"""
        if not self.md_path.exists() or self.md_path.stat().st_size == 0:
            print(f"[ConversionValidator] ❌ 변환된 MD 파일이 없거나 0바이트입니다: {self.md_path.name}")
            return False, 0.0

        pdf_text = self.extract_pdf_text()
        md_text = self.extract_md_text()

        if not md_text or "[변환 실패" in md_text:
            print(f"[ConversionValidator] ❌ 변환 실패 내용이 포함되었거나 MD 내용이 비어있습니다: {self.md_path.name}")
            return False, 0.0

        # 원본 PDF에 텍스트가 거의 없는 스캔본인 경우 (이미지 전용)
        if len(pdf_text) < 50:
            print("[ConversionValidator] 원본 PDF에 내장된 텍스트가 적어 유사도 검증을 조건부 통과합니다 (스캔본 추정).")
            # MD 파일에 내용이 있으면 통과 처리
            is_valid = len(md_text) >= 50
            return is_valid, 1.0 if is_valid else 0.0

        # difflib SequenceMatcher로 유사도 측정
        matcher = difflib.SequenceMatcher(None, pdf_text, md_text)
        similarity = matcher.ratio()

        is_valid = similarity >= threshold
        return is_valid, similarity

    def move_to_failed(self, target_dir: str or Path) -> Path:
        """검증에 실패한 MD 파일을 failed 폴더로 격리 이동"""
        target_path = Path(target_dir)
        target_path.mkdir(parents=True, exist_ok=True)
        dest = target_path / self.md_path.name
        if self.md_path.exists():
            shutil.move(str(self.md_path), str(dest))
            print(f"[ConversionValidator] 실패 파일 격리 완료: {dest}")
        return dest
