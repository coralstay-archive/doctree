"""도서 분야 분류: 제목 키 정규화와 config/categories.yaml 기반 매핑."""
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import yaml

from config.settings import CATEGORIES_FILE

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


Place = Tuple[str, str]  # (분야, 세부분야)


class CategoryConfigError(ValueError):
    """categories.yaml 구조 오류·제목 키 중복 등 설정 오류. CLI는 이 메시지를 출력하고 비정상 종료한다."""


@dataclass
class Categories:
    """분야 > 세부분야 > 제목 목록 체계와 제목 키 색인."""

    tree: "OrderedDict[str, OrderedDict[str, List[str]]]"
    index: Dict[str, Place]
    notes: Dict[str, str] = field(default_factory=dict)

    def lookup(self, name: str) -> Optional[Place]:
        """파일명(또는 제목)의 (분야, 세부분야). 매핑이 없으면 None."""
        return self.index.get(title_key(name))

    def note(self, name: str) -> Optional[str]:
        return self.notes.get(title_key(name))


class _UniqueKeyLoader(yaml.SafeLoader):
    """같은 매핑 키가 두 번 나오면 조용히 덮어쓰지 않고 오류를 낸다."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise CategoryConfigError(
                    f"categories.yaml: 같은 이름 '{key}'이(가) 한 매핑 안에 두 번 있습니다 "
                    f"(줄 {key_node.start_mark.line + 1})"
                )
            seen.add(key)
        return OrderedDict(super().construct_mapping(node, deep=deep))


def _fmt(place: Place) -> str:
    return f"{place[0]} > {place[1]}"


def load_categories(path: Union[str, Path, None] = None) -> Categories:
    """config/categories.yaml(기본값)을 읽어 Categories를 만든다.

    구조: ``categories: {분야: {세부분야: [제목, ...]}}``, 선택 항목 ``notes: {제목: 비고}``.
    제목은 title_key()로 정규화해 색인하며, 한 키가 두 곳 이상(같은 세부분야 안 포함)에
    나오면 키와 두 위치를 담은 CategoryConfigError를 낸다.
    """
    path = Path(path or CATEGORIES_FILE)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CategoryConfigError(f"분류 설정 파일을 읽을 수 없습니다: {path} ({e})") from e
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as e:
        raise CategoryConfigError(f"분류 설정 파일 YAML 오류: {path} ({e})") from e

    if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
        raise CategoryConfigError(f"{path}: 최상위에 'categories: {{분야: {{세부분야: [제목]}}}}' 매핑이 필요합니다")

    tree: "OrderedDict[str, OrderedDict[str, List[str]]]" = OrderedDict()
    index: Dict[str, Place] = {}
    for cat, subs in data["categories"].items():
        if not isinstance(subs, dict):
            raise CategoryConfigError(f"{path}: 분야 '{cat}'의 값은 세부분야 매핑이어야 합니다")
        tree[str(cat)] = OrderedDict()
        for sub, titles in subs.items():
            place = (str(cat), str(sub))
            if not isinstance(titles, list):
                raise CategoryConfigError(f"{path}: '{_fmt(place)}'의 값은 제목 목록이어야 합니다")
            for t in titles:
                if not isinstance(t, str):
                    raise CategoryConfigError(f"{path}: '{_fmt(place)}'의 제목 {t!r}은(는) 문자열이어야 합니다")
                k = title_key(t)
                if not k:
                    raise CategoryConfigError(f"{path}: '{_fmt(place)}'의 제목 {t!r}의 제목 키가 비어 있습니다")
                if k in index:
                    raise CategoryConfigError(
                        f"{path}: 제목 키 '{k}'가 중복 매핑됐습니다: "
                        f"'{_fmt(index[k])}'와(과) '{_fmt(place)}' (제목 {t!r})"
                    )
                index[k] = place
            tree[place[0]][place[1]] = list(titles)

    raw_notes = data.get("notes") or {}
    if not isinstance(raw_notes, dict):
        raise CategoryConfigError(f"{path}: 'notes'는 제목 → 비고 매핑이어야 합니다")
    notes = {title_key(str(t)): str(v) for t, v in raw_notes.items()}
    return Categories(tree=tree, index=index, notes=notes)
