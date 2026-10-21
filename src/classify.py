"""도서 분야 분류: 제목 키 정규화와 config/categories.yaml 기반 매핑."""
import re
import unicodedata

_PDF_SUFFIX = re.compile(r"\.pdf$", re.IGNORECASE)
_COPY_OF_PREFIX = re.compile(r"^Copy of ")
_IGNORED = re.compile(r"[-\s]+")


def title_key(name: str) -> str:
    """파일명(또는 제목)을 분류·중복 점검용 제목 키로 정규화한다.

    순서: NFC 정규화 → 끝의 '.pdf'(대소문자 무시) 제거 → 앞의 'Copy of ' 제거
    → 하이픈·공백 제거 → 소문자화.

    '/'는 키에 그대로 남긴다. 드라이브 파일명에는 '/'가 들어갈 수 있고
    (예: 'A/B-테스트' → 'a/b테스트'), 폴더 경로는 키 계산에 쓰지 않으므로
    폴더 구분자와 혼동될 일이 없다. 인자는 파일명(name)만 받으며 folder_path는 넘기지 않는다.
    """
    s = unicodedata.normalize("NFC", name or "")
    s = _PDF_SUFFIX.sub("", s)
    s = _COPY_OF_PREFIX.sub("", s)
    s = _IGNORED.sub("", s)
    return s.lower()
