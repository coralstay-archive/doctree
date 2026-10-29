"""런타임 환경 변수 및 워크스페이스 경로 설정 (불변 데이터클래스 + 모듈 상수 호환)."""
from __future__ import annotations

import os
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BASE_DIR",
    "CATEGORY_TREE_FILE",
    "CONTENT_CATEGORY_MAP_FILE",
    "GOOGLE_DRIVE_FOLDER_ID",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "LOCAL_CONTENTS_CACHE_FILE",
    "PROJECT_LAYOUT_PROFILES_FILE",
    "SNAPSHOTS_DIR",
    "VIRUSTOTAL_API_KEY",
    "VT_CACHE_FILE",
    "WORKSPACE_DIR",
    "PathLike",
    "WorkspaceSettings",
    "atomic_write_bytes",
    "atomic_write_text",
    "normalize_nfc",
]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PathLike = str | Path
BASE_DIR: Final[Path] = Path(__file__).resolve().parents[3]


def normalize_nfc(value: Any = "") -> str:
    """임의 입력을 문자열로 변환하고 유니코드 완성형(NFC)으로 정규화한다."""
    return unicodedata.normalize("NFC", str(value or ""))


def atomic_write_bytes(target: PathLike, data: bytes, *, executable: bool = False) -> Path:
    """대상 파일 경로에 임시 파일(.<name>.tmp)을 거쳐 바이트 데이터를 원자적으로 기록한다."""
    path = Path(target)
    tmp_path = path.parent / f".{path.name}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(data)
        if executable:
            tmp_path.chmod(0o755)
        tmp_path.replace(path)
    except OSError:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return path


def atomic_write_text(target: PathLike, content: str, *, executable: bool = False) -> Path:
    """대상 파일 경로에 임시 파일(.<name>.tmp)을 거쳐 UTF-8 텍스트를 원자적으로 기록한다."""
    return atomic_write_bytes(target, content.encode(), executable=executable)


@dataclass(frozen=True, slots=True)
class WorkspaceSettings:
    """불변(Immutable) 워크스페이스 설정 객체.

    전역 상태를 직접 수정하거나 importlib.reload()를 호출하는 대신,
    WorkspaceSettings.from_env(env=...)로 격리된 설정 인스턴스를 생성해 주입할 수 있다.
    - category_tree_file: 16개 대분야·55개 세부분야 고정 분류 트리 정의서 (config/category_tree.yaml)
    - content_category_map_file: Drive 파일 ID ↔ 세부분야 ID 매핑 배정표 (config/content_category_map.yaml)
    - project_layout_profiles_file: 프로젝트 유형별 폴더·파일 구조 규격 (config/project_layout_profiles.yaml)
    """

    base_dir: Path
    google_service_account_file: str
    google_drive_folder_id: str
    snapshots_dir: str
    category_tree_file: str
    content_category_map_file: str
    project_layout_profiles_file: str
    workspace_dir: Path
    virustotal_api_key: str
    vt_cache_file: str
    local_contents_cache_file: str = ""

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        base_dir: Path | None = None,
    ) -> WorkspaceSettings:
        source = os.environ if env is None else env
        root = base_dir or BASE_DIR
        snapshots_dir = source.get("DOCTREE_SNAPSHOTS_DIR", str(root / "snapshots"))
        category_tree_file = source.get(
            "DOCTREE_CATEGORY_TREE_FILE",
            str(root / "config" / "category_tree.yaml"),
        )
        content_category_map_file = source.get(
            "DOCTREE_CONTENT_CATEGORY_MAP_FILE",
            str(root / "config" / "content_category_map.yaml"),
        )
        project_layout_profiles_file = source.get(
            "DOCTREE_PROJECT_LAYOUT_PROFILES_FILE",
            str(root / "config" / "project_layout_profiles.yaml"),
        )
        return cls(
            base_dir=root,
            google_service_account_file=source.get(
                "GOOGLE_SERVICE_ACCOUNT_FILE", str(root / "credentials.json")
            ),
            google_drive_folder_id=source.get("GOOGLE_DRIVE_FOLDER_ID", ""),
            snapshots_dir=snapshots_dir,
            category_tree_file=category_tree_file,
            content_category_map_file=content_category_map_file,
            project_layout_profiles_file=project_layout_profiles_file,
            workspace_dir=Path(source.get("FREERIDE_WORKSPACE_DIR", str(root.parent))),
            virustotal_api_key=source.get("VIRUSTOTAL_API_KEY", ""),
            vt_cache_file=source.get(
                "DOCTREE_VT_CACHE_FILE", str(Path(snapshots_dir) / ".vt_cache.json")
            ),
            local_contents_cache_file=source.get(
                "DOCTREE_LOCAL_CONTENTS_CACHE_FILE",
                str(Path(snapshots_dir) / ".local_contents_cache.json"),
            ),
        )


_DEFAULT = WorkspaceSettings.from_env()

GOOGLE_SERVICE_ACCOUNT_FILE: str = _DEFAULT.google_service_account_file
GOOGLE_DRIVE_FOLDER_ID: str = _DEFAULT.google_drive_folder_id
SNAPSHOTS_DIR: str = _DEFAULT.snapshots_dir
CATEGORY_TREE_FILE: str = _DEFAULT.category_tree_file
CONTENT_CATEGORY_MAP_FILE: str = _DEFAULT.content_category_map_file
PROJECT_LAYOUT_PROFILES_FILE: str = _DEFAULT.project_layout_profiles_file
WORKSPACE_DIR: Path = _DEFAULT.workspace_dir
VIRUSTOTAL_API_KEY: str = _DEFAULT.virustotal_api_key
VT_CACHE_FILE: str = _DEFAULT.vt_cache_file
LOCAL_CONTENTS_CACHE_FILE: str = _DEFAULT.local_contents_cache_file
