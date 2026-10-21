"""스냅샷 저장과 변경 이력 검증 (KBI-4)."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from src.snapshot import load_latest_snapshot, save_snapshot


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


if __name__ == "__main__":
    unittest.main()
