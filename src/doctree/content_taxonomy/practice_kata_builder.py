"""중간 결과물(content_data/<도서명>/*page.md)을 장·절·주제별로 묶어 실습·테스트 프레임워크(practice/)를 생성하는 빌더 (Step 4: doctree practice)."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from doctree.pdf_threat_audit.pdf_page_ingestor import render_dot_to_svg
from doctree.runtime_env.boundary_errors import ClassificationError
from doctree.runtime_env.workspace_settings import PathLike, atomic_write_text, normalize_nfc

__all__ = [
    "SUPPORTED_LANG_MAP",
    "PracticeBuildResult",
    "build_practice_katas",
    "resolve_language_extension",
]

SUPPORTED_LANG_MAP: Final[Mapping[str, str]] = MappingProxyType(
    {
        "py": "py",
        "python": "py",
        "cpp": "cpp",
        "c++": "cpp",
        "c": "cpp",
        "java": "java",
        "sql": "sql",
    }
)

_DOT_BLOCK_RE = re.compile(r"```dot\n(.*?)```", re.S)
_CODE_BLOCK_RE = re.compile(r"```(python|py|cpp|c\+\+|c|java|sql)\n(.*?)```", re.S)
_UNSAFE_SLUG_RE = re.compile(r"[^\w가-힣\-]+")


def _slugify(text: str, index: int) -> str:
    cleaned = _UNSAFE_SLUG_RE.sub("_", normalize_nfc(text).strip()).strip("_")
    if not cleaned:
        cleaned = f"section_{index:02d}"
    if re.match(r"^\d{2,}_", cleaned):
        return cleaned
    return f"{index:02d}_{cleaned}"


@dataclass(frozen=True, slots=True)
class PracticeBuildResult:
    """콘텐츠 1건의 practice/ 실습 프레임워크 생성 결과."""

    content_name: str
    practice_content_dir: Path
    lang_ext: str
    chapters_count: int
    katas_count: int
    kata_dirs: tuple[Path, ...]


def resolve_language_extension(
    content_data_dir: Path,
    explicit_lang: str | None = None,
) -> str:
    """명시적 언어 옵션 또는 프로젝트 경로명으로부터 실습 코드 확장자(py/cpp/java/sql)를 결정한다."""
    if explicit_lang is not None:
        key = explicit_lang.strip().lower()
        if key not in SUPPORTED_LANG_MAP:
            raise ClassificationError(
                f"지원하지 않는 실습 언어입니다: {explicit_lang!r} (지원: py, cpp, java, sql)"
            )
        return SUPPORTED_LANG_MAP[key]

    parts_lower = "/".join(p.lower() for p in content_data_dir.parts)
    if "cpp" in parts_lower:
        return "cpp"
    if "java" in parts_lower:
        return "java"
    if "databases" in parts_lower or "sql" in parts_lower:
        return "sql"
    return "py"


def _default_main_and_test_templates(
    content_name: str,
    chapter_dir: str,
    section_slug: str,
    pages_label: str,
    target_code: str,
    lang_ext: str,
) -> tuple[str, str, str]:
    """언어별(py/cpp/java/sql) 목표 코드, 스켈레톤 main.<ext>, 단위 테스트 test.<ext>를 반환한다."""
    header = f"content={content_name} | chapter={chapter_dir} | section={section_slug} | pages={pages_label}"
    if lang_ext == "cpp":
        ref_code = target_code or (
            "#include <iostream>\n\n"
            "int solve_kata() {\n"
            "    return 42;\n"
            "}\n\n"
            "int main() {\n"
            "    std::cout << solve_kata() << std::endl;\n"
            "    return 0;\n"
            "}"
        )
        main_code = f"// @snippet {section_slug}\n// {header}\n{ref_code}\n"
        test_code = (
            f"// Unit test: {header}\n"
            "#include <cassert>\n"
            "#include <iostream>\n\n"
            "int main() {\n"
            '    std::cout << "PASS: ' + section_slug + '" << std::endl;\n'
            "    return 0;\n"
            "}\n"
        )
        return ref_code, main_code, test_code

    if lang_ext == "java":
        ref_code = target_code or (
            "public class Main {\n"
            "    public static int solveKata() {\n"
            "        return 42;\n"
            "    }\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(solveKata());\n"
            "    }\n"
            "}"
        )
        main_code = f"// @snippet {section_slug}\n// {header}\n{ref_code}\n"
        test_code = (
            f"// Unit test: {header}\n"
            "public class Test {\n"
            "    public static void main(String[] args) {\n"
            f'        System.out.println("PASS: {section_slug}");\n'
            "    }\n"
            "}\n"
        )
        return ref_code, main_code, test_code

    if lang_ext == "sql":
        ref_code = target_code or "SELECT 42 AS kata_result;"
        main_code = f"-- @snippet {section_slug}\n-- {header}\n{ref_code}\n"
        test_code = f"-- Unit test: {header}\nEXPLAIN {ref_code}\n"
        return ref_code, main_code, test_code

    ref_code = target_code or (
        "def solve_kata() -> int:\n"
        "    return 42\n\n\n"
        'if __name__ == "__main__":\n'
        "    print(solve_kata())"
    )
    main_code = f"# @snippet {section_slug}\n# {header}\n{ref_code}\n"
    test_code = (
        f"# Unit test: {header}\n"
        "import pathlib\n\n"
        'if __name__ == "__main__":\n'
        '    main_file = pathlib.Path(__file__).with_name("main.py")\n'
        "    assert main_file.is_file()\n"
        f'    print("PASS: {section_slug}")\n'
    )
    return ref_code, main_code, test_code


def build_practice_katas(
    content_data_dir: PathLike,
    *,
    practice_root: PathLike | None = None,
    lang: str | None = None,
    overwrite: bool = False,
    dot_bin: str = "dot",
) -> PracticeBuildResult:
    """content_data/<콘텐츠명>/ 중간 결과물을 읽어 practice/<콘텐츠명>/<장>/<절>/ 실습 패키지를 생성한다."""
    c_dir = Path(content_data_dir).resolve()
    index_path = c_dir / "index.json"
    if not c_dir.is_dir() or not index_path.is_file():
        raise ClassificationError(
            f"유효한 content_data 도서 디렉터리(index.json 포함)가 아닙니다: {c_dir}"
        )

    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClassificationError(f"{index_path}: index.json을 읽을 수 없습니다: {exc}") from exc

    if not isinstance(index_data, dict) or not isinstance(index_data.get("pages"), list) or not index_data["pages"]:
        raise ClassificationError(f"{index_path}: 유효한 pages 목록이 없습니다.")

    content_name = normalize_nfc(c_dir.name)
    lang_ext = resolve_language_extension(c_dir, explicit_lang=lang)

    if practice_root is not None:
        practice_content_dir = Path(practice_root).resolve() / content_name
    elif c_dir.parent.name == "content_data":
        practice_content_dir = c_dir.parent.parent / "practice" / content_name
    else:
        practice_content_dir = c_dir.parent / "practice" / content_name

    raw_toc = index_data.get("toc")
    if isinstance(raw_toc, list) and raw_toc:
        toc_entries = raw_toc
    else:
        toc_entries = [
            {
                "page": int(p.get("page", idx + 1)),
                "chapter": "01_기본_개념",
                "section": f"{int(p.get('page', idx + 1)):02d}_페이지_실습",
                "md_file": str(p.get("md_file", f"{content_name}-{idx + 1}page.md")),
            }
            for idx, p in enumerate(index_data["pages"])
        ]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    chapter_order: dict[str, int] = {}
    section_order: dict[tuple[str, str], int] = {}

    for entry in toc_entries:
        raw_ch = str(entry.get("chapter") or "01_기본_개념")
        raw_sec = str(entry.get("section") or f"{entry.get('page', 1):02d}_페이지_실습")
        if raw_ch not in chapter_order:
            chapter_order[raw_ch] = len(chapter_order) + 1
        ch_slug = _slugify(raw_ch, chapter_order[raw_ch])

        sec_key = (ch_slug, raw_sec)
        if sec_key not in section_order:
            section_order[sec_key] = sum(1 for k in section_order if k[0] == ch_slug) + 1
        sec_slug = _slugify(raw_sec, section_order[sec_key])

        grouped.setdefault((ch_slug, sec_slug), []).append(entry)

    kata_dirs: list[Path] = []
    chapters_seen = set()

    for (ch_slug, sec_slug), entries in grouped.items():
        chapters_seen.add(ch_slug)
        pages = tuple(int(e.get("page", 1)) for e in entries)
        md_files = tuple(
            str(e.get("md_file", f"{content_name}-{p}page.md"))
            for e, p in zip(entries, pages, strict=True)
        )

        body_snippets: list[str] = []
        extracted_dot = ""
        extracted_code = ""

        for md_name in md_files:
            md_path = c_dir / md_name
            if md_path.is_file():
                md_text = md_path.read_text(encoding="utf-8")
                if not extracted_dot:
                    dot_m = _DOT_BLOCK_RE.search(md_text)
                    if dot_m:
                        extracted_dot = dot_m.group(1).strip()
                if not extracted_code:
                    code_m = _CODE_BLOCK_RE.search(md_text)
                    if code_m:
                        extracted_code = code_m.group(2).strip()
                for line in md_text.splitlines():
                    s = line.strip()
                    if s and not s.startswith(("#", "!", "<!--", "```")):
                        body_snippets.append(s)

        concept_summary = "\n".join(body_snippets[:6]) if body_snippets else f"{content_name} {ch_slug} {sec_slug} 핵심 개념 요약"
        dot_code = extracted_dot or (
            f"digraph Kata_{sec_slug} {{\n"
            f'    rankdir=LR;\n'
            f'    node [shape=record, fontname="Menlo", fontsize=11];\n'
            f'    concept [label="{{{content_name} | {ch_slug}}}"];\n'
            f'    kata [label="{{{sec_slug} | Pages {pages[0]}..{pages[-1]}}}"];\n'
            f"    concept -> kata;\n"
            f"}}"
        )

        kata_dir = practice_content_dir / ch_slug / sec_slug
        assets_dir = kata_dir / "assets"
        svg_filename = f"{sec_slug}-diag1.svg"
        render_dot_to_svg(dot_code, assets_dir / svg_filename, dot_bin=dot_bin)

        pages_label = f"{pages[0]}p" if len(pages) == 1 else f"{pages[0]}p ~ {pages[-1]}p"
        ref_code, main_code, test_code = _default_main_and_test_templates(
            content_name,
            ch_slug,
            sec_slug,
            pages_label,
            extracted_code,
            lang_ext,
        )

        page_links = "\n".join(
            f"- [{md_f}](../../../../content_data/{content_name}/{md_f})"
            for md_f in md_files
        )
        readme_text = (
            f"# {content_name} — {ch_slug} / {sec_slug}\n\n"
            f"## 1. 원문 페이지 링크 ({pages_label})\n\n"
            f"{page_links}\n\n"
            f"## 2. 핵심 개념 요약 및 DOT 다이어그램\n\n"
            f"{concept_summary}\n\n"
            f"![DOT 다이어그램](assets/{svg_filename})\n\n"
            f"```dot\n{dot_code}\n```\n\n"
            f"## 3. 따라 칠 목표 코드 및 예상 출력\n\n"
            f"```{lang_ext}\n{ref_code}\n```\n\n"
            f"```text\nPASS: {sec_slug}\n```\n"
        )

        readme_path = kata_dir / "README.md"
        main_path = kata_dir / f"main.{lang_ext}"
        test_path = kata_dir / f"test.{lang_ext}"

        if overwrite or not readme_path.is_file():
            atomic_write_text(readme_path, readme_text)
        if overwrite or not main_path.is_file():
            atomic_write_text(main_path, main_code)
        if overwrite or not test_path.is_file():
            atomic_write_text(test_path, test_code)

        kata_dirs.append(kata_dir)

    return PracticeBuildResult(
        content_name=content_name,
        practice_content_dir=practice_content_dir,
        lang_ext=lang_ext,
        chapters_count=len(chapters_seen),
        katas_count=len(kata_dirs),
        kata_dirs=tuple(kata_dirs),
    )
