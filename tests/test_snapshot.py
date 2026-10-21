"""스냅샷 저장과 변경 이력 검증 (KBI-4)."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from src.snapshot import (
    CHANGELOG_FILENAME,
    CHANGELOG_HEADER,
    Change,
    Changes,
    append_changelog,
    diff_snapshots,
    load_latest_snapshot,
    save_snapshot,
)


def _rec(id_, name, folder="IT/개발", md5="m", size=1):
    return {
        "id": id_,
        "name": name,
        "folder_path": folder,
        "size_bytes": size,
        "md5": md5,
        "modified_time": "2026-01-01T00:00:00Z",
        "web_view_link": f"https://drive/{id_}",
    }


class TestSaveSnapshot(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp())

    def test_kbi_4_1_saves_dated_json(self):
        """KBI-4#1 ledger/snapshots/YYYY-MM-DD.json에 레코드를 UTF-8 JSON으로 저장한다."""
        recs = [_rec("a", "클린코드.pdf")]
        path = save_snapshot(recs, self.ledger, datetime(2026, 10, 21, 9, 30))
        self.assertEqual(path, self.ledger / "snapshots" / "2026-10-21.json")
        raw = path.read_text(encoding="utf-8")
        self.assertIn("클린코드.pdf", raw)  # ensure_ascii=False
        data = json.loads(raw)
        self.assertEqual(data["records"], recs)
        self.assertEqual(data["taken_at"], "2026-10-21T09:30:00")
        self.assertEqual(data["count"], 1)

    def test_kbi_4_1_stable_output(self):
        """KBI-4#1 같은 입력은 레코드 순서·키 순서와 무관하게 같은 바이트로 저장된다."""
        a, b = _rec("a", "A.pdf"), _rec("b", "B.pdf")
        now = datetime(2026, 10, 21, 9, 30)
        p1 = save_snapshot([a, b], self.ledger, now).read_bytes()
        reordered = dict(reversed(list(b.items())))
        p2 = save_snapshot([reordered, a], self.ledger, now).read_bytes()
        self.assertEqual(p1, p2)

    def test_kbi_4_1_same_day_overwrites(self):
        """KBI-4#1 같은 날 재실행하면 같은 파일을 덮어쓴다."""
        save_snapshot([_rec("a", "A.pdf")], self.ledger, datetime(2026, 10, 21, 9, 0))
        save_snapshot([_rec("b", "B.pdf")], self.ledger, datetime(2026, 10, 21, 18, 0))
        files = list((self.ledger / "snapshots").iterdir())
        self.assertEqual([f.name for f in files], ["2026-10-21.json"])
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual([r["id"] for r in data["records"]], ["b"])


class TestLoadLatestSnapshot(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp())

    def test_kbi_4_1_none_when_missing(self):
        """KBI-4#1 스냅샷이 하나도 없으면 None."""
        self.assertIsNone(load_latest_snapshot(self.ledger))

    def test_kbi_4_b4_latest_by_date(self):
        """KBI-4#B4 비교 기준은 존재하는 스냅샷 중 날짜가 가장 최근인 것이다."""
        save_snapshot([_rec("old", "O.pdf")], self.ledger, datetime(2026, 9, 1))
        save_snapshot([_rec("new", "N.pdf")], self.ledger, datetime(2026, 10, 20))
        save_snapshot([_rec("mid", "M.pdf")], self.ledger, datetime(2026, 10, 2))
        day, recs = load_latest_snapshot(self.ledger)
        self.assertEqual(day, date(2026, 10, 20))
        self.assertEqual([r["id"] for r in recs], ["new"])

    def test_kbi_4_b4_includes_same_day_earlier_run(self):
        """KBI-4#B4 같은 날 앞선 실행이 남긴 오늘 스냅샷도 비교 기준이 된다."""
        save_snapshot([_rec("y", "Y.pdf")], self.ledger, datetime(2026, 10, 20))
        save_snapshot([_rec("t", "T.pdf")], self.ledger, datetime(2026, 10, 21, 9))
        day, recs = load_latest_snapshot(self.ledger)
        self.assertEqual(day, date(2026, 10, 21))
        self.assertEqual([r["id"] for r in recs], ["t"])

    def test_kbi_4_b4_ignores_non_snapshot_files(self):
        """KBI-4#B4 YYYY-MM-DD.json 형식이 아닌 파일은 무시한다."""
        save_snapshot([_rec("a", "A.pdf")], self.ledger, datetime(2026, 10, 1))
        (self.ledger / "snapshots" / "notes.json").write_text("{}", encoding="utf-8")
        (self.ledger / "snapshots" / "2026-13-99.json").write_text("{}", encoding="utf-8")
        day, _ = load_latest_snapshot(self.ledger)
        self.assertEqual(day, date(2026, 10, 1))


class TestLedgerDirSetting(unittest.TestCase):
    def test_kbi_4_1_ledger_dir_default_and_env(self):
        """KBI-4#1 LEDGER_DIR 기본값은 <repo>/ledger이고 DOCTREE_LEDGER_DIR로 바꿀 수 있다."""
        import importlib

        import config.settings as settings

        old = os.environ.pop("DOCTREE_LEDGER_DIR", None)
        try:
            importlib.reload(settings)
            self.assertEqual(Path(settings.LEDGER_DIR), settings.BASE_DIR / "ledger")
            os.environ["DOCTREE_LEDGER_DIR"] = "/tmp/x-ledger"
            importlib.reload(settings)
            self.assertEqual(Path(settings.LEDGER_DIR), Path("/tmp/x-ledger"))
        finally:
            os.environ.pop("DOCTREE_LEDGER_DIR", None)
            if old is not None:
                os.environ["DOCTREE_LEDGER_DIR"] = old
            importlib.reload(settings)


class TestDiffSnapshots(unittest.TestCase):
    def test_kbi_4_2_no_changes(self):
        """KBI-4#2 같은 목록이면 변경이 없다."""
        recs = [_rec("a", "A.pdf"), _rec("b", "B.pdf")]
        ch = diff_snapshots(recs, [dict(r) for r in recs])
        self.assertTrue(ch.is_empty)
        self.assertEqual(ch, Changes())

    def test_kbi_4_2_added_and_removed(self):
        """KBI-4#2 새 id는 추가, 사라진 id는 삭제로 구분한다."""
        ch = diff_snapshots([_rec("a", "A.pdf")], [_rec("b", "B.pdf")])
        self.assertEqual([r["id"] for r in ch.added], ["b"])
        self.assertEqual([r["id"] for r in ch.removed], ["a"])
        self.assertEqual((ch.renamed, ch.moved, ch.content_changed), ([], [], []))
        self.assertFalse(ch.is_empty)

    def test_kbi_4_2_renamed(self):
        """KBI-4#2 이름이 바뀌면 이름 변경(old→new)으로 기록한다."""
        ch = diff_snapshots([_rec("a", "A.pdf")], [_rec("a", "A2.pdf")])
        self.assertEqual(ch.renamed, [Change("a", "A2.pdf", "A.pdf", "A2.pdf")])
        self.assertEqual((ch.added, ch.removed, ch.moved), ([], [], []))

    def test_kbi_4_2_moved(self):
        """KBI-4#2 folder_path가 바뀌면 폴더 이동(old→new)으로 기록한다."""
        ch = diff_snapshots([_rec("a", "A.pdf", folder="IT")], [_rec("a", "A.pdf", folder="IT/개발")])
        self.assertEqual(ch.moved, [Change("a", "A.pdf", "IT", "IT/개발")])
        self.assertEqual(ch.renamed, [])

    def test_kbi_4_2_content_changed_by_md5(self):
        """KBI-4#2 MD5가 바뀌면 내용 변경으로 기록한다."""
        ch = diff_snapshots([_rec("a", "A.pdf", md5="x")], [_rec("a", "A.pdf", md5="y")])
        self.assertEqual(ch.content_changed, [Change("a", "A.pdf", "x", "y")])

    def test_kbi_4_2_content_same_md5_different_size_ignored(self):
        """KBI-4#2 MD5가 둘 다 있고 같으면 크기·수정시각이 달라도 내용 변경이 아니다."""
        old = _rec("a", "A.pdf", md5="x", size=1)
        new = dict(_rec("a", "A.pdf", md5="x", size=2), modified_time="2026-02-02T00:00:00Z")
        self.assertTrue(diff_snapshots([old], [new]).is_empty)

    def test_kbi_4_2_content_changed_by_size_when_md5_missing(self):
        """KBI-4#2 MD5가 비어 있으면 크기로 내용 변경을 판단한다."""
        ch = diff_snapshots([_rec("a", "A.pdf", md5="", size=1)], [_rec("a", "A.pdf", md5="", size=2)])
        self.assertEqual(ch.content_changed, [Change("a", "A.pdf", "1", "2")])
        same = diff_snapshots([_rec("a", "A.pdf", md5="", size=1)], [_rec("a", "A.pdf", md5="", size=1)])
        self.assertTrue(same.is_empty)

    def test_kbi_4_b1_identity_is_id_only(self):
        """KBI-4#B1 같은 id면 이름·경로가 모두 바뀌어도 추가+삭제가 아니라 같은 책이다."""
        ch = diff_snapshots([_rec("a", "A.pdf", folder="X")], [_rec("a", "Z.pdf", folder="Y")])
        self.assertEqual((ch.added, ch.removed), ([], []))

    def test_kbi_4_b1_same_name_different_id_is_add_remove(self):
        """KBI-4#B1 이름·경로가 같아도 id가 다르면 다른 책(삭제+추가)이다."""
        ch = diff_snapshots([_rec("a", "A.pdf")], [_rec("b", "A.pdf")])
        self.assertEqual([r["id"] for r in ch.added], ["b"])
        self.assertEqual([r["id"] for r in ch.removed], ["a"])

    def test_kbi_4_b2_rename_and_move_both_recorded(self):
        """KBI-4#B2 이름 변경과 폴더 이동이 동시에 일어나면 둘 다 기록한다."""
        ch = diff_snapshots([_rec("a", "A.pdf", folder="X")], [_rec("a", "Z.pdf", folder="Y")])
        self.assertEqual(ch.renamed, [Change("a", "Z.pdf", "A.pdf", "Z.pdf")])
        self.assertEqual(ch.moved, [Change("a", "Z.pdf", "X", "Y")])

    def test_kbi_4_2_sorted_output(self):
        """KBI-4#2 각 목록은 입력 순서와 무관하게 정렬된다."""
        new = [_rec("b", "나.pdf"), _rec("a", "가.pdf")]
        ch1 = diff_snapshots([], new)
        ch2 = diff_snapshots([], list(reversed(new)))
        self.assertEqual(ch1, ch2)
        self.assertEqual([r["name"] for r in ch1.added], ["가.pdf", "나.pdf"])


class TestAppendChangelog(unittest.TestCase):
    def setUp(self):
        self.ledger = Path(tempfile.mkdtemp())
        self.path = self.ledger / CHANGELOG_FILENAME

    def _read(self):
        return self.path.read_text(encoding="utf-8")

    def test_kbi_4_3_filename(self):
        """KBI-4#3 변경 이력 파일은 ledger/변경이력.md다."""
        self.assertEqual(CHANGELOG_FILENAME, "변경이력.md")
        out = append_changelog(self.ledger, datetime(2026, 10, 21, 9, 30), Changes(), 3)
        self.assertEqual(out, self.path)
        self.assertTrue(self.path.is_file())

    def test_kbi_4_3_no_changes_block(self):
        """KBI-4#3 변경이 없으면 실행 시각·총 권수와 '변경 없음'을 기록한다."""
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 30), Changes(), 3)
        text = self._read()
        self.assertTrue(text.startswith(CHANGELOG_HEADER))
        self.assertIn("## 2026-10-21 09:30", text)
        self.assertIn("총 3권", text)
        self.assertIn("변경 없음", text)

    def test_kbi_4_3_change_lines_grouped(self):
        """KBI-4#3 변경은 종류별로 묶어 이름과 old→new를 보여 준다."""
        ch = Changes(
            added=[_rec("n", "새책.pdf", folder="IT/AI")],
            removed=[_rec("r", "옛책.pdf", folder="경제")],
            renamed=[Change("a", "B.pdf", "A.pdf", "B.pdf")],
            moved=[Change("a", "B.pdf", "IT", "IT/개발")],
            content_changed=[Change("c", "C.pdf", "x", "y")],
        )
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 30), ch, 10)
        text = self._read()
        self.assertNotIn("변경 없음", text)
        order = ["### 추가 (1)", "IT/AI/새책.pdf", "### 삭제 (1)", "경제/옛책.pdf",
                 "### 이름 변경 (1)", "A.pdf → B.pdf", "### 폴더 이동 (1)", "IT → IT/개발",
                 "### 내용 변경 (1)", "C.pdf"]
        positions = [text.index(t) for t in order]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("### ", text.split("### 추가")[0])  # 빈 종류는 제목도 없음

    def test_kbi_4_3_empty_groups_omitted(self):
        """KBI-4#3 해당 변경이 없는 종류는 출력하지 않는다."""
        ch = Changes(renamed=[Change("a", "B.pdf", "A.pdf", "B.pdf")])
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 30), ch, 1)
        text = self._read()
        self.assertIn("### 이름 변경 (1)", text)
        for t in ("### 추가", "### 삭제", "### 폴더 이동", "### 내용 변경"):
            self.assertNotIn(t, text)

    def test_kbi_4_3_newest_on_top(self):
        """KBI-4#3 새 실행 블록은 제목 바로 아래, 기존 블록보다 위에 들어간다."""
        append_changelog(self.ledger, datetime(2026, 10, 20, 9, 0), Changes(), 1)
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 0), Changes(), 2)
        text = self._read()
        self.assertTrue(text.startswith(CHANGELOG_HEADER + "## 2026-10-21 09:00"))
        self.assertLess(text.index("2026-10-21"), text.index("2026-10-20"))
        self.assertEqual(text.count(CHANGELOG_HEADER.strip()), 1)

    def test_kbi_4_b3_existing_blocks_preserved_byte_for_byte(self):
        """KBI-4#B3 이력은 누적되고 기존 블록은 바이트 그대로 새 블록 아래에 남는다."""
        append_changelog(self.ledger, datetime(2026, 10, 19, 9, 0), Changes(), 1)
        append_changelog(self.ledger, datetime(2026, 10, 20, 9, 0),
                         Changes(added=[_rec("n", "새책.pdf")]), 2)
        before = self.path.read_bytes()
        body_before = before[len(CHANGELOG_HEADER.encode("utf-8")):]
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 0),
                         Changes(removed=[_rec("n", "새책.pdf")]), 1)
        after = self.path.read_bytes()
        self.assertTrue(after.endswith(body_before))
        self.assertTrue(after.startswith(CHANGELOG_HEADER.encode("utf-8")))
        self.assertGreater(len(after), len(before))

    def test_kbi_4_b3_hand_edited_content_preserved(self):
        """KBI-4#B3 제목이 없거나 손으로 고친 기존 내용도 지우지 않고 아래에 보존한다."""
        legacy = "옛 메모\r\n- 손으로 쓴 줄\n"
        self.path.write_bytes(legacy.encode("utf-8"))
        append_changelog(self.ledger, datetime(2026, 10, 21, 9, 0), Changes(), 1)
        after = self.path.read_bytes()
        self.assertTrue(after.endswith(legacy.encode("utf-8")))
        self.assertTrue(after.startswith(CHANGELOG_HEADER.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
