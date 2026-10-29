"""런타임 환경 설정(doctree.runtime_env.workspace_settings) 및 프로젝트 대칭 구조·스냅샷 격리 검증."""
import ast
import dataclasses
import importlib
import os
import subprocess
import unittest
from pathlib import Path
from types import MappingProxyType

import doctree.runtime_env.workspace_settings as settings
from doctree.content_taxonomy.practice_kata_builder import SUPPORTED_LANG_MAP
from doctree.runtime_env.workspace_settings import BASE_DIR, WorkspaceSettings

ROOT = Path(__file__).resolve().parents[2]


class TestSettings(unittest.TestCase):
    def test_base_dir_path(self):
        self.assertIsInstance(BASE_DIR, Path)
        self.assertTrue(BASE_DIR.exists())
        self.assertEqual(BASE_DIR, ROOT)

    def test_workspace_settings_is_frozen_slotted_dataclass(self):
        """WorkspaceSettings는 불변(frozen) + slots 기반 데이터클래스이며 from_env()로 격리 생성된다."""
        env_input = {
            "DOCTREE_SNAPSHOTS_DIR": "/tmp/custom-snaps",
            "GOOGLE_SERVICE_ACCOUNT_FILE": "/tmp/sa.json",
            "GOOGLE_DRIVE_FOLDER_ID": "folder-xyz",
            "DOCTREE_CATEGORY_TREE_FILE": "/tmp/cats.yaml",
            "DOCTREE_CONTENT_CATEGORY_MAP_FILE": "/tmp/assigns.yaml",
            "DOCTREE_PROJECT_LAYOUT_PROFILES_FILE": "/tmp/layout.yaml",
            "FREERIDE_WORKSPACE_DIR": "/tmp/ws",
            "VIRUSTOTAL_API_KEY": "vt-secret",
        }
        cfg = WorkspaceSettings.from_env(env=env_input, base_dir=ROOT)
        env_input["DOCTREE_SNAPSHOTS_DIR"] = "/tmp/mutated-after"
        self.assertEqual(cfg.snapshots_dir, "/tmp/custom-snaps")
        self.assertEqual(cfg.vt_cache_file, "/tmp/custom-snaps/.vt_cache.json")
        self.assertEqual(cfg.google_service_account_file, "/tmp/sa.json")
        self.assertEqual(cfg.google_drive_folder_id, "folder-xyz")
        self.assertEqual(cfg.category_tree_file, "/tmp/cats.yaml")
        self.assertEqual(cfg.content_category_map_file, "/tmp/assigns.yaml")
        self.assertEqual(cfg.project_layout_profiles_file, "/tmp/layout.yaml")
        self.assertEqual(cfg.workspace_dir, Path("/tmp/ws"))
        self.assertEqual(cfg.virustotal_api_key, "vt-secret")
        self.assertTrue(hasattr(WorkspaceSettings, "__slots__"))
        self.assertFalse(hasattr(cfg, "__dict__"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            cfg.snapshots_dir = "/tmp/mutated"  # type: ignore[misc]

    def test_dotenv_import_error_fallback(self):
        """python-dotenv가 없어도 workspace_settings가 정상 로드된다."""
        import sys

        saved = sys.modules.get("dotenv")
        try:
            sys.modules["dotenv"] = None  # type: ignore[assignment]
            importlib.reload(settings)
            self.assertEqual(settings.BASE_DIR, ROOT)
        finally:
            if saved is not None:
                sys.modules["dotenv"] = saved
            else:
                sys.modules.pop("dotenv", None)
            importlib.reload(settings)

    def test_snapshots_dir_default_and_env(self):
        """SNAPSHOTS_DIR 기본값은 <repo>/snapshots이고 DOCTREE_SNAPSHOTS_DIR로 바꿀 수 있다."""
        old = os.environ.pop("DOCTREE_SNAPSHOTS_DIR", None)
        try:
            importlib.reload(settings)
            self.assertEqual(Path(settings.SNAPSHOTS_DIR), settings.BASE_DIR / "snapshots")
            os.environ["DOCTREE_SNAPSHOTS_DIR"] = "/tmp/x-snapshots"
            importlib.reload(settings)
            self.assertEqual(Path(settings.SNAPSHOTS_DIR), Path("/tmp/x-snapshots"))
        finally:
            os.environ.pop("DOCTREE_SNAPSHOTS_DIR", None)
            if old is not None:
                os.environ["DOCTREE_SNAPSHOTS_DIR"] = old
            importlib.reload(settings)


class TestSelfDocumentingNamingAndSymmetry(unittest.TestCase):
    def test_config_dir_has_only_yaml_files_and_pypa_src_layout(self):
        """루트 config/에는 순수 YAML만 있고, src/ 아래에는 doctree 패키지 하나만 존재한다(PyPA 표준 src-layout)."""
        config_files = sorted(p.name for p in (ROOT / "config").iterdir() if not p.name.startswith("."))
        self.assertEqual(
            config_files,
            ["category_tree.yaml", "content_category_map.yaml", "project_layout_profiles.yaml"],
        )
        src_top = sorted(
            p.name for p in (ROOT / "src").iterdir()
            if not p.name.startswith(".") and not p.name.endswith(".egg-info") and p.name != "__pycache__"
        )
        self.assertEqual(src_top, ["doctree"])

    def test_src_doctree_and_tests_mirror_self_documenting_structure(self):
        """src/doctree/와 tests/는 동일한 하위 디렉터리 및 1:1 모듈 구조를 갖는다."""
        pkg_root = ROOT / "src" / "doctree"
        src_dirs = sorted(
            str(p.relative_to(pkg_root))
            for p in pkg_root.rglob("*")
            if p.is_dir() and p.name != "__pycache__"
        )
        test_dirs = sorted(
            str(p.relative_to(ROOT / "tests"))
            for p in (ROOT / "tests").rglob("*")
            if p.is_dir() and p.name != "__pycache__"
        )
        self.assertEqual(
            src_dirs,
            [
                "content_taxonomy",
                "doctree_cli",
                "drive_sync",
                "pdf_threat_audit",
                "runtime_env",
            ],
        )
        self.assertEqual(src_dirs, test_dirs)

        src_modules = sorted(
            str(p.relative_to(pkg_root))
            for p in pkg_root.rglob("*.py")
            if p.name != "__init__.py"
        )
        expected_tests = sorted(
            str(Path(rel).parent / f"test_{Path(rel).name}") for rel in src_modules
        )
        actual_tests = sorted(
            str(p.relative_to(ROOT / "tests"))
            for p in (ROOT / "tests").rglob("*.py")
            if p.name != "__init__.py"
        )
        self.assertEqual(actual_tests, expected_tests)

    def test_all_modules_and_facades_importable(self):
        """모든 도메인 모듈과 패키지 Facade(__all__)가 정상 import된다."""
        for name in (
            "doctree",
            "doctree.runtime_env",
            "doctree.runtime_env.workspace_settings",
            "doctree.runtime_env.layout_profile_store",
            "doctree.runtime_env.project_scaffolder",
            "doctree.drive_sync",
            "doctree.drive_sync.drive_pdf_fetcher",
            "doctree.drive_sync.snapshot_diff_tracker",
            "doctree.drive_sync.workspace_sync_engine",
            "doctree.content_taxonomy",
            "doctree.content_taxonomy.category_classifier",
            "doctree.content_taxonomy.duplicate_and_naming_linter",
            "doctree.content_taxonomy.practice_kata_builder",
            "doctree.pdf_threat_audit",
            "doctree.pdf_threat_audit.pdf_byte_inspector",
            "doctree.pdf_threat_audit.pdf_page_ingestor",
            "doctree.pdf_threat_audit.threat_intel_client",
            "doctree.doctree_cli",
            "doctree.doctree_cli.command_dispatcher",
            "doctree.doctree_cli.terminal_tree_renderer",
        ):
            mod = importlib.import_module(name)
            if name == "doctree" or name.count(".") == 2:
                self.assertTrue(hasattr(mod, "__all__"), f"{name} must define __all__")
            if hasattr(mod, "__all__"):
                for exported in mod.__all__:
                    self.assertTrue(hasattr(mod, exported), f"{name}.{exported}")
                    if exported != "__version__":
                        self.assertFalse(exported.startswith("_"), f"{name}.{exported} must be public")

    def test_module_encapsulation_and_layer_import_boundaries(self):
        """모든 모듈은 공개 심볼(__all__)만 외부에 노출·참조하며 계층 간 단방향 의존성 규칙을 지킨다."""
        self.assertIsInstance(SUPPORTED_LANG_MAP, MappingProxyType)
        with self.assertRaises(TypeError):
            SUPPORTED_LANG_MAP["rb"] = "Ruby"  # type: ignore[index]

        pkg_root = ROOT / "src" / "doctree"
        for py_file in sorted(pkg_root.rglob("*.py")):
            rel_parts = py_file.relative_to(pkg_root).parts
            layer = rel_parts[0] if len(rel_parts) > 1 else "root"
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("doctree"):
                    target_parts = node.module.split(".")
                    target_layer = target_parts[1] if len(target_parts) > 1 else "root"

                    # 1) 최하위 기반 계층(runtime_env)은 상위 도메인·CLI 계층을 절대 역참조하지 않는다
                    if layer == "runtime_env":
                        self.assertEqual(
                            target_layer,
                            "runtime_env",
                            f"runtime_env 모듈({py_file.name})이 상위 계층({node.module})을 참조함",
                        )
                    # 2) 도메인 계층은 최상위 진입점(doctree_cli)을 역참조하지 않는다
                    if layer in {"drive_sync", "content_taxonomy", "pdf_threat_audit"}:
                        self.assertNotEqual(
                            target_layer,
                            "doctree_cli",
                            f"도메인 모듈({py_file.name})이 CLI 계층({node.module})을 역참조함",
                        )

                    # 3) 다른 doctree 모듈에서 import하는 모든 심볼은 대상 모듈의 __all__에 등록된 공개 심볼이어야 한다
                    target_mod = importlib.import_module(node.module)
                    target_all = set(getattr(target_mod, "__all__", ()))
                    for alias in node.names:
                        if alias.name != "__version__":
                            self.assertFalse(
                                alias.name.startswith("_"),
                                f"{py_file.name}에서 비공개 심볼 {node.module}.{alias.name}를 import함",
                            )
                        self.assertIn(
                            alias.name,
                            target_all,
                            f"{py_file.name}에서 __all__ 밖의 심볼 {node.module}.{alias.name}를 import함",
                        )


class TestSnapshotsIgnoredAndNoLedger(unittest.TestCase):
    def test_no_ledger_directory(self):
        """ledger/ 디렉터리는 존재하지 않고 snapshots/만 사용한다."""
        self.assertFalse((ROOT / "ledger").exists())

    def test_gitignore_has_snapshots(self):
        """.gitignore에 snapshots/가 있다."""
        lines = [line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()]
        self.assertIn("snapshots/", lines)

    def test_snapshots_outputs_ignored_by_git(self):
        """스냅샷 산출물(snapshots/*)은 git이 무시해 커밋되지 않는다."""
        result = subprocess.run(
            ["git", "check-ignore", "-q", "snapshots/2026-10-27.json"],
            cwd=ROOT,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
