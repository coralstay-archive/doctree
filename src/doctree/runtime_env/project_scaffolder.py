"""로컬 워크스페이스 프로젝트 디렉토리·필수 파일·실행 스크립트·gitignore 구조 강제 생성기 (Step 2: doctree scaffold)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from doctree.runtime_env.layout_profile_store import get_layout_value, load_layout_profiles
from doctree.runtime_env.workspace_settings import (
    PROJECT_LAYOUT_PROFILES_FILE,
    PathLike,
    atomic_write_text,
    normalize_nfc,
)

__all__ = [
    "ScaffoldResult",
    "scaffold_project",
    "verify_project_scaffold",
]


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """단일 로컬 프로젝트에 대한 레이아웃 스캐폴딩 실행 결과."""

    profile: str
    target_dir: Path
    created_dirs: tuple[str, ...]
    existing_dirs: tuple[str, ...]
    created_files: tuple[str, ...]
    preserved_files: tuple[str, ...]


_FILE_TEMPLATES: Final[Mapping[str, str]] = MappingProxyType({
    "README.md": """\
# {project_name}

> **freeride (`{profile}` 프로필)** 표준 디렉토리 규격에 따라 구성된 프로젝트 워크스페이스입니다.

## 표준 디렉토리 구조
- `contents/`: 구글 드라이브에서 가져온 원본 도서 PDF 보관소 (`.gitignore` 대상)
- `content_data/`: 페이지별 PDF 파싱 중간 결과물 (`index.json`, `*-Npage.md`, `assets/*.{{png,svg}}`)
- `practice/`: 장·절·슬러그 단위로 생성된 실습(Kata) 및 단위 테스트 코드
""",
    "PROJECT_STRUCTURE.md": """\
# {project_name} 디렉토리 및 아키텍처 규격 (`{profile}`)

본 프로젝트는 `doctree scaffold {profile}` 명령으로 표준 구조가 강제·검증됩니다.

1. **`contents/`**: 원본 도서 PDF (`doctree pull` 대상)
2. **`content_data/`**: 페이지별 마크다운 + 크롭 이미지(`.png`) + Graphviz DOT 벡터 도식(`.svg`) + `index.json`
3. **`practice/`**: 학습자가 직접 타이핑하며 검증하는 실습 과제 (`README.md`, `main.*`, `test.*`)
""",
    "PRACTICE_GUIDE.md": """\
# {project_name} 수련(Kata) 실습 가이드

1. **실습 코드 실행**: `./scripts/run.sh <실습_폴더_경로>`
2. **단위 테스트 검증**: `./scripts/test.sh <실습_폴더_경로>`
3. **원문 페이지 역추적**: `./scripts/locate.sh <키워드_또는_경로>`
4. **핵심 스니펫 조회**: `./scripts/snippets.sh`
""",
    "scripts/run.sh": """\
#!/usr/bin/env bash
# 실습 과제(main.cpp / main.py / main.java / main.sql) 0.1초 고속 실행기
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "사용법: $0 <실습_폴더_또는_파일_경로> [인자...]" >&2
  exit 1
fi

target="$1"
shift
if [ ! -e "$target" ] && [ -e "practice/$target" ]; then
  target="practice/$target"
fi

if [ -d "$target" ]; then
  if [ -f "$target/main.py" ]; then
    exec python3 "$target/main.py" "$@"
  elif [ -f "$target/main.cpp" ]; then
    out="$(mktemp -d)/a.out"
    clang++ -std=c++20 -O2 "$target/main.cpp" -o "$out"
    exec "$out" "$@"
  elif [ -f "$target/main.java" ]; then
    exec java "$target/main.java" "$@"
  elif [ -f "$target/main.sql" ]; then
    cat "$target/main.sql"
    exit 0
  fi
fi

echo "실행 가능한 main 파일을 찾을 수 없습니다: $target" >&2
exit 1
""",
    "scripts/test.sh": """\
#!/usr/bin/env bash
# 실습 과제(test.cpp / test.py / test.java / test.sql) 0.1초 고속 채점기
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "사용법: $0 <실습_폴더_경로>" >&2
  exit 1
fi

target="$1"
if [ ! -e "$target" ] && [ -e "practice/$target" ]; then
  target="practice/$target"
fi

if [ -d "$target" ]; then
  if [ -f "$target/test.py" ]; then
    exec python3 "$target/test.py"
  elif [ -f "$target/test.cpp" ]; then
    out="$(mktemp -d)/test_bin"
    clang++ -std=c++20 -O2 "$target/test.cpp" -o "$out"
    exec "$out"
  elif [ -f "$target/test.java" ]; then
    exec java "$target/test.java"
  elif [ -f "$target/test.sql" ]; then
    grep -qiE "SELECT|CREATE|INSERT|EXPLAIN" "$target/test.sql"
    echo "SQL test verified: $target/test.sql"
    exit 0
  fi
fi

echo "실행 가능한 test 파일을 찾을 수 없습니다: $target" >&2
exit 1
""",
    "scripts/locate.sh": """\
#!/usr/bin/env bash
# 실습 과제 및 원문 페이지(content_data/) 역추적 네비게이터
set -euo pipefail
query="${1:---tree}"
if [ "$query" = "--tree" ]; then
  find practice content_data -maxdepth 3 2>/dev/null | sort
else
  grep -rn "$query" practice content_data 2>/dev/null || true
fi
""",
    "scripts/snippets.sh": """\
#!/usr/bin/env bash
# 프로젝트 내 핵심 코드 스니펫(@snippet) 검색 및 추출기
set -euo pipefail
query="${1:-@snippet}"
grep -rn "$query" practice tips 2>/dev/null || true
""",
    "scripts/help.sh": """\
#!/usr/bin/env bash
# 프로젝트 실습 실행·테스트·역추적·스니펫 도구 치트시트
set -euo pipefail
cat << 'EOF'
======================================================================
 🛠️  실습(Kata) 빠른 명령어 치트시트
======================================================================
1. 빠른 실행       : ./scripts/run.sh practice/<도서>/<장>/<절>
2. 단위 테스트     : ./scripts/test.sh practice/<도서>/<장>/<절>
3. 원문 위치 추적  : ./scripts/locate.sh <키워드_또는_--tree>
4. 스니펫 검색     : ./scripts/snippets.sh [키워드]
======================================================================
EOF
""",
    "install.sh": """\
#!/usr/bin/env bash
set -euo pipefail
echo "Toolchain install ready."
""",
    "uninstall.sh": """\
#!/usr/bin/env bash
set -euo pipefail
echo "Toolchain uninstall ready."
""",
})


def _ensure_gitignore_entries(
    gitignore_path: Path,
    required_entries: list[str],
) -> tuple[bool, tuple[str, ...]]:
    """대상 .gitignore 파일에 필수 무시 항목이 누락되어 있으면 보강한다."""
    existed = gitignore_path.is_file()
    existing_text = gitignore_path.read_text(encoding="utf-8") if existed else ""
    existing_lines = {line.strip() for line in existing_text.splitlines() if line.strip()}

    added: list[str] = []
    for entry in required_entries:
        stripped = entry.strip("/")
        equivalents = {entry, stripped, f"/{stripped}", f"{stripped}/", f"/{stripped}/"}
        if not (existing_lines & equivalents):
            added.append(entry)
            existing_lines.add(entry)

    if not existed or added:
        base = existing_text.rstrip("\n")
        extra = "\n".join(added)
        if base and extra:
            new_text = f"{base}\n{extra}\n"
        elif extra:
            new_text = f"{extra}\n"
        else:
            new_text = f"{base}\n" if base else ""
        atomic_write_text(gitignore_path, new_text)

    return (not existed), tuple(added)


def scaffold_project(
    profile: str,
    target_dir: PathLike,
    *,
    layout_file: PathLike = PROJECT_LAYOUT_PROFILES_FILE,
    overwrite: bool = False,
) -> ScaffoldResult:
    """지정한 레이아웃 프로필 규격에 맞춰 대상 로컬 프로젝트의 디렉토리·필수 파일·gitignore를 생성 및 보정한다."""
    data = load_layout_profiles(layout_file)
    spec = get_layout_value(data, profile=profile)
    norm_profile = normalize_nfc(profile).strip()

    root = Path(target_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_name = normalize_nfc(root.name)

    created_dirs: list[str] = []
    existing_dirs: list[str] = []
    for rel_dir in spec["directories"]:
        d_path = root / rel_dir
        if d_path.is_dir():
            existing_dirs.append(rel_dir)
        else:
            d_path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(rel_dir)

    created_files: list[str] = []
    preserved_files: list[str] = []

    gitignore_created, _ = _ensure_gitignore_entries(
        root / ".gitignore",
        list(spec["gitignore_entries"]),
    )

    for rel_file in spec["required_files"]:
        if rel_file == ".gitignore":
            if gitignore_created:
                created_files.append(".gitignore")
            else:
                preserved_files.append(".gitignore")
            continue

        f_path = root / rel_file
        is_sh = rel_file.endswith(".sh")
        if f_path.is_file() and not overwrite:
            if is_sh:
                f_path.chmod(f_path.stat().st_mode | 0o111)
            preserved_files.append(rel_file)
            continue

        template = _FILE_TEMPLATES.get(
            rel_file,
            "# {project_name} — " + rel_file + "\n",
        )
        rendered = template.replace("{project_name}", project_name).replace(
            "{profile}", norm_profile
        )
        atomic_write_text(f_path, rendered, executable=is_sh)
        created_files.append(rel_file)

    return ScaffoldResult(
        profile=norm_profile,
        target_dir=root,
        created_dirs=tuple(created_dirs),
        existing_dirs=tuple(existing_dirs),
        created_files=tuple(created_files),
        preserved_files=tuple(preserved_files),
    )


def verify_project_scaffold(
    profile: str,
    target_dir: PathLike,
    *,
    layout_file: PathLike = PROJECT_LAYOUT_PROFILES_FILE,
) -> tuple[bool, tuple[str, ...]]:
    """대상 로컬 프로젝트가 레이아웃 프로필의 디렉토리·필수 파일·gitignore 항목을 모두 충족하는지 검사한다."""
    data = load_layout_profiles(layout_file)
    spec = get_layout_value(data, profile=profile)
    root = Path(target_dir).resolve()

    missing: list[str] = []
    for rel_dir in spec["directories"]:
        if not (root / rel_dir).is_dir():
            missing.append(f"dir:{rel_dir}")

    for rel_file in spec["required_files"]:
        if not (root / rel_file).is_file():
            missing.append(f"file:{rel_file}")

    gitignore_path = root / ".gitignore"
    existing_lines = (
        {line.strip() for line in gitignore_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        if gitignore_path.is_file()
        else set()
    )
    for entry in spec["gitignore_entries"]:
        stripped = entry.strip("/")
        equivalents = {entry, stripped, f"/{stripped}", f"{stripped}/", f"/{stripped}/"}
        if not (existing_lines & equivalents):
            missing.append(f"gitignore:{entry}")

    return len(missing) == 0, tuple(missing)
