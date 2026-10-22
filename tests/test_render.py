"""대장 렌더링 검증 (KBI-6#2, KBI-6#3, KBI-6#B1, KBI-6#B3)."""
import re
import textwrap
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.checks import run_checks
from src.classify import classify, load_categories
from src.render import display_title, render_ledger
from src.snapshot import Change, Changes, RunResult

KST = timezone(timedelta(hours=9), "KST")
NOW = datetime(2026, 10, 21, 22, 30, tzinfo=KST)
ACCOUNT = {"name": "tester", "email": "t@example.com", "limit_gb": 100.0, "usage_gb": 70.0,
           "drive_usage_gb": 68.0, "usage_percent": 70.0}

YAML = """\
categories:
  1. 컴퓨터 과학:
    알고리즘:
      - 종만북-1권
      - 종만북-2권
    운영체제:
      - TLPI-1
    빈 세부분야:
      - 아직없는책
  2. 빈 분야:
    없음:
      - 없는책
  3. 기타:
    파이프:
      - A|B 테스트
      - "`백틱` 책"
      - "[대괄호] 책"
notes:
  TLPI-1: "리눅스 시스템 프로그래밍"
"""


def _rec(id_, name, folder="knowledge-base/raw-data", size=1_000_000, md5=None):
    return {"id": id_, "name": name, "folder_path": folder, "size_bytes": size,
            "md5": md5 if md5 is not None else f"md5-{id_}", "modified_time": "2026-01-01T00:00:00Z",
            "web_view_link": f"https://drive.google.com/file/d/{id_}/view"}


RECORDS = [
    _rec("a", "종만북-1권.pdf", size=204_349_999),
    _rec("b", "종만북-2권.pdf", size=1_500_000_000, md5="same"),
    _rec("c", "TLPI-1", size=50_000),
    _rec("d", "A|B 테스트.pdf", folder="Saved from Chrome"),
    _rec("e", "`백틱` 책.pdf", folder="Saved from Chrome"),
    _rec("f", "[대괄호] 책.pdf", folder=""),
    _rec("g", "모르는책.pdf", md5="same"),
]


def _categories():
    path = Path(tempfile.mkdtemp()) / "categories.yaml"
    path.write_text(textwrap.dedent(YAML), encoding="utf-8")
    return load_categories(path)


def _run(first_run=False, changes=None, total=len(RECORDS)):
    return RunResult(changes or Changes(), total, first_run, None if first_run else date(2026, 10, 20),
                     Path("/x/ledger/snapshots/2026-10-21.json"), Path("/x/ledger/변경이력.md"))


def render(records=RECORDS, account=ACCOUNT, run=None):
    cats = _categories()
    return render_ledger(groups=classify(records, cats), warnings=run_checks(records), run=run or _run(),
                         account=account, now=NOW, categories=cats)


def section(text, title):
    """'## title' 아래부터 다음 '## ' 직전까지."""
    m = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert m, f"section {title!r} missing"
    return m.group(1)


def table_rows(text):
    """마크다운 표 행들을 (이스케이프되지 않은 '|' 기준) 셀 목록으로."""
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-:| ]+\|$", line):
            cells = re.split(r"(?<!\\)\|", line)[1:-1]
            rows.append([c.strip() for c in cells])
    return rows


class TestLedgerSections(unittest.TestCase):
    def setUp(self):
        self.text = render()

    def test_kbi_6_2_has_all_sections(self):
        """KBI-6#2 대장에 기준 시각·스토리지·요약·폴더·분야별·트리·상세·경고·최근 변경 절이 있다."""
        self.assertIn("기준 시각: 2026-10-21 22:30 KST (UTC+09:00)", self.text)
        for title in ("스토리지 현황", "요약", "폴더 구성", "분야별 권수·용량", "분류 트리",
                      "분야별 상세", "경고", "최근 변경"):
            section(self.text, title)

    def test_kbi_6_2_storage(self):
        """KBI-6#2 스토리지 현황에 계정·사용량이 나온다."""
        s = section(self.text, "스토리지 현황")
        self.assertIn("t@example.com", s)
        self.assertIn("70.0 GB / 100.0 GB (70.0%)", s)
        self.assertIn("68.0 GB", s)

    def test_kbi_6_2_storage_lookup_failed_still_renders(self):
        """KBI-6#2 계정 정보가 None이면 '조회 실패'를 적고 나머지는 그대로 렌더한다."""
        text = render(account=None)
        self.assertIn("조회 실패", section(text, "스토리지 현황"))
        section(text, "분야별 상세")

    def test_kbi_6_2_summary(self):
        """KBI-6#2 요약에 파일 수·총 용량·분류/미분류·경고 수가 나온다."""
        s = section(self.text, "요약")
        self.assertIn("파일 7개", s)
        self.assertIn("1.7 GB", s)  # 1,708,399,999 B
        self.assertIn("미분류 1권", s)

    def test_kbi_6_2_folder_table(self):
        """KBI-6#2 폴더 구성 표: 폴더별 파일 수와 용량, 루트는 (루트)."""
        rows = {r[0]: r[1:] for r in table_rows(section(self.text, "폴더 구성"))[1:]}
        self.assertEqual(rows["`knowledge-base/raw-data`"][0], "4")
        self.assertEqual(rows["`Saved from Chrome`"][0], "2")
        self.assertEqual(rows["(루트)"][0], "1")

    def test_kbi_6_2_category_table_omits_empty(self):
        """KBI-6#2 분야별 표: 빈 분야는 빼고, 미분류는 있을 때만 나온다."""
        rows = {r[0]: r[1:] for r in table_rows(section(self.text, "분야별 권수·용량"))[1:]}
        self.assertEqual(rows["1. 컴퓨터 과학"][0], "3")
        self.assertEqual(rows["3. 기타"][0], "3")
        self.assertEqual(rows["미분류"][0], "1")
        self.assertNotIn("2. 빈 분야", rows)
        no_unclassified = render(records=RECORDS[:-1])
        for title in ("분야별 권수·용량", "분류 트리", "분야별 상세"):
            self.assertNotIn("미분류", section(no_unclassified, title), title)

    def test_kbi_6_2_tree(self):
        """KBI-6#2 분류 트리: text 코드 블록, ├──/└── 가지, 세부분야 권수, 제목. 빈 세부분야 생략."""
        tree = section(self.text, "분류 트리")
        self.assertIn("```text", tree)
        self.assertIn("├── 1. 컴퓨터 과학", tree)
        self.assertIn("│   ├── 알고리즘 (2)", tree)
        self.assertIn("│   │   ├── 종만북 1권", tree)
        self.assertIn("│   │   └── 종만북 2권", tree)
        self.assertIn("│   └── 운영체제 (1)", tree)
        self.assertIn("└── 미분류", tree)
        self.assertNotIn("빈 세부분야", tree)
        self.assertNotIn("빈 분야", tree)

    def test_kbi_6_2_detail_tables(self):
        """KBI-6#2 분야별 상세: 세부분야 표(제목·용량·경로·비고), 비고에 분류 비고와 파일별 경고."""
        detail = section(self.text, "분야별 상세")
        self.assertIn("### 1. 컴퓨터 과학", detail)
        self.assertIn("#### 알고리즘", detail)
        self.assertNotIn("빈 세부분야", detail)
        self.assertIn("| 제목 | 용량 | 경로 | 비고 |", detail)
        tlpi = next(l for l in detail.splitlines() if "TLPI 1" in l)
        self.assertIn("리눅스 시스템 프로그래밍", tlpi)
        self.assertIn(".pdf 확장자", tlpi)
        dup = next(l for l in detail.splitlines() if "종만북 2권" in l)
        self.assertIn("완전 중복", dup)

    def test_kbi_6_2_warnings_grouped_by_kind(self):
        """KBI-6#2 경고 절은 종류별 한국어 제목으로 묶인다."""
        w = section(self.text, "경고")
        self.assertIn("### 완전 중복 (1)", w)
        self.assertIn("### .pdf 확장자 누락 (1)", w)
        self.assertIn("TLPI-1", w)
        self.assertNotIn("missing_pdf_extension", w)

    def test_kbi_6_2_no_warnings(self):
        """KBI-6#2 경고가 없으면 '경고 없음'."""
        text = render(records=[RECORDS[0]], run=_run(total=1))
        self.assertIn("경고 없음", section(text, "경고"))

    def test_kbi_6_2_recent_changes(self):
        """KBI-6#2 최근 변경: 최초 등록 / 변경 없음 / 종류별 건수, 변경이력.md 링크."""
        first = section(render(run=_run(first_run=True)), "최근 변경")
        self.assertIn("최초 등록 7권", first)
        self.assertIn("[변경이력.md](변경이력.md)", first)
        self.assertIn("변경 없음", section(self.text, "최근 변경"))
        ch = Changes(added=[RECORDS[0]], renamed=[Change("b", "n", "o", "n")],
                     content_changed=[Change("c", "x", "1", "2")])
        changed = section(render(run=_run(changes=ch)), "최근 변경")
        self.assertIn("추가 1", changed)
        self.assertIn("이름 변경 1", changed)
        self.assertIn("내용 변경 1", changed)
        self.assertIn("2026-10-20", changed)


class TestSizes(unittest.TestCase):
    def test_kbi_6_b1_file_size_mb_one_decimal(self):
        """KBI-6#B1 KBI-6#2 개별 용량은 MB(10^6) 소수 1자리."""
        text = render()
        line = next(l for l in section(text, "분야별 상세").splitlines() if "종만북 1권" in l)
        self.assertIn("204.3 MB", line)
        line = next(l for l in section(text, "분야별 상세").splitlines() if "TLPI 1" in l)
        self.assertIn("0.1 MB", line)

    def test_kbi_6_b1_totals_gb_one_decimal(self):
        """KBI-6#B1 KBI-6#2 합계는 GB(10^9) 소수 1자리."""
        rows = {r[0]: r[1:] for r in table_rows(section(render(), "분야별 권수·용량"))[1:]}
        self.assertEqual(rows["1. 컴퓨터 과학"][1], "1.7 GB")  # 1,704,399,999 B
        self.assertEqual(rows["미분류"][1], "0.0 GB")


class TestEscaping(unittest.TestCase):
    def setUp(self):
        self.text = render()
        self.detail = section(self.text, "분야별 상세")

    def test_kbi_6_b3_pipe_escaped_in_cells(self):
        """KBI-6#B3 KBI-6#2 표 셀 안의 '|'는 이스케이프돼 열 수가 깨지지 않는다."""
        for row in table_rows(self.detail):
            self.assertEqual(len(row), 4, row)
        line = next(l for l in self.detail.splitlines() if "테스트" in l)
        self.assertIn("A\\|B 테스트", line)

    def test_kbi_6_b3_backticks_and_newlines(self):
        """KBI-6#B3 백틱·줄바꿈이 든 이름도 표 한 줄·올바른 코드 스팬으로 남는다."""
        line = next(l for l in self.detail.splitlines() if "백틱" in l)
        self.assertIn("`` Saved from Chrome/`백틱` 책.pdf ``", line)
        weird = [_rec("n", "줄\n바꿈|책.pdf")]
        text = render(records=weird, run=_run(total=1))
        rows = [l for l in section(text, "분야별 상세").splitlines() if "바꿈" in l]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(table_rows(rows[0])[0]), 4)

    def test_kbi_6_b3_tree_fence_not_broken_by_backticks(self):
        """KBI-6#B3 제목에 ```가 있어도 분류 트리 코드 블록이 닫히지 않는다."""
        text = render(records=[_rec("t", "a```b.pdf")], run=_run(total=1))
        tree = section(text, "분류 트리")
        self.assertIn("````text", tree)


class TestTitleLinks(unittest.TestCase):
    def setUp(self):
        self.detail = section(render(), "분야별 상세")

    def _row(self, needle):
        return next(l for l in self.detail.splitlines() if needle in l and l.startswith("|"))

    def test_kbi_6_3_display_title(self):
        """KBI-6#3 표시 제목: 끝의 .pdf 제거, 하이픈 → 공백."""
        self.assertEqual(display_title("종만북-1권.pdf"), "종만북 1권")
        self.assertEqual(display_title("TLPI-1.PDF"), "TLPI 1")
        self.assertEqual(display_title("a.pdf.bak"), "a.pdf.bak")

    def test_kbi_6_3_title_links_to_web_view_link(self):
        """KBI-6#3 상세 표의 제목은 web_view_link로 연결된 마크다운 링크다."""
        row = self._row("종만북 1권")
        self.assertTrue(row.startswith("| [종만북 1권](https://drive.google.com/file/d/a/view) |"), row)

    def test_kbi_6_3_brackets_escaped(self):
        """KBI-6#3 제목의 '['·']'는 이스케이프돼 링크 문법이 깨지지 않는다."""
        row = self._row("대괄호")
        self.assertIn("[\\[대괄호\\] 책](https://drive.google.com/file/d/f/view)", row)

    def test_kbi_6_3_pipe_in_linked_title(self):
        """KBI-6#3 KBI-6#B3 링크 제목 안의 '|'도 이스케이프된다."""
        self.assertIn("[A\\|B 테스트](https://drive.google.com/file/d/d/view)", self._row("테스트"))

    def test_kbi_6_3_no_link_falls_back_to_plain_title(self):
        """KBI-6#3 web_view_link가 비어 있으면 제목만 쓴다."""
        rec = dict(_rec("z", "링크없음.pdf"), web_view_link="")
        detail = section(render(records=[rec], run=_run(total=1)), "분야별 상세")
        row = next(l for l in detail.splitlines() if "링크없음" in l)
        self.assertTrue(row.startswith("| 링크없음 |"), row)


if __name__ == "__main__":
    unittest.main()
