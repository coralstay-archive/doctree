"""프로젝트 구성 검증 (KBI-1)."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestPipelineRemoved(unittest.TestCase):
    def test_kbi_1_1_pipeline_modules_deleted(self):
        """KBI-1#1 파이프라인 모듈(converter·validator·summarizer·auth_login·main)이 삭제돼 있다."""
        for rel in ("src/converter.py", "src/validator.py", "src/summarizer.py", "auth_login.py", "main.py"):
            self.assertFalse((ROOT / rel).exists(), rel)

    def test_kbi_1_1_pipeline_tests_deleted(self):
        """KBI-1#1 삭제된 모듈만 검증하던 테스트도 삭제돼 있다."""
        for rel in ("tests/test_converter.py", "tests/test_validator.py", "tests/test_summarizer.py", "tests/test_main.py"):
            self.assertFalse((ROOT / rel).exists(), rel)


REMOVED_DEPS = ("pdfplumber", "langdetect", "openai", "httpx", "aiofiles", "pytest-asyncio")
_NAME_RE = re.compile(r"^\s*\"?([A-Za-z0-9_.\-]+)")


def _dep_names(lines) -> set:
    names = set()
    for line in lines:
        m = _NAME_RE.match(line)
        if m and not line.lstrip().startswith("#"):
            names.add(m.group(1).lower())
    return names


def _pyproject_dep_names() -> set:
    """pyproject.toml의 dependencies / optional-dependencies 배열 안의 패키지명 (tomllib 없이 3.9 호환)."""
    text = (ROOT / "pyproject.toml").read_text()
    blocks = re.findall(r"^(?:dependencies|dev)\s*=\s*\[(.*?)\]", text, re.S | re.M)
    return _dep_names(l for b in blocks for l in b.splitlines() if l.strip())


class TestDependenciesRemoved(unittest.TestCase):
    def test_kbi_1_2_pyproject_has_no_pipeline_deps(self):
        """KBI-1#2 pyproject.toml에 파이프라인 전용 의존성이 없다."""
        names = _pyproject_dep_names()
        for dep in REMOVED_DEPS:
            self.assertNotIn(dep, names)

    def test_kbi_1_2_requirements_has_no_pipeline_deps(self):
        """KBI-1#2 requirements.txt에 파이프라인 전용 의존성이 없다."""
        names = _dep_names((ROOT / "requirements.txt").read_text().splitlines())
        for dep in REMOVED_DEPS:
            self.assertNotIn(dep, names)

    def test_kbi_1_2_drive_deps_kept(self):
        """KBI-1#2 Drive 조회에 필요한 의존성은 유지된다."""
        names = _pyproject_dep_names()
        for dep in ("google-api-python-client", "google-auth-oauthlib", "python-dotenv", "rich", "pytest"):
            self.assertIn(dep, names)


if __name__ == "__main__":
    unittest.main()
