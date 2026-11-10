"""The lists behind the window's 成功, 失败 and 剩余: each paper of a batch as the
caller sends it (papers.json), grouped for the window, and its PDF shown in its
folder, only from inside the batch's folder (user, 2026-11-10)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from paper_search_carsi import progress_capsule as capsule
from paper_search_carsi import progress_reporter as pr
from paper_search_carsi import progress_view as pv
from paper_search_carsi import server


def paper(index, state, **fields):
    return {"index": index, "doi": f"10.1000/{index}", "title": f"Paper {index}", "journal": "Nature",
            "state": state, **fields}


class SyncPapersTests(unittest.TestCase):
    def setUp(self):
        pr.papers_path().unlink(missing_ok=True)

    def listed(self):
        return json.loads(pr.papers_path().read_text(encoding="utf-8"))

    def test_every_paper_once_then_the_changed_ones(self):
        self.assertTrue(pr.sync_papers("b1", "/papers", [paper(1, "open"), paper(2, "open"), paper(3, "open")]))
        self.assertTrue(pr.sync_papers("b1", "", [paper(2, "school")]))
        self.assertTrue(pr.sync_papers("b1", "", [paper(1, "ok", via="开放下载", detail="出版社 API",
                                                            path="/papers/1/Paper 1.pdf")]))
        listed = self.listed()
        self.assertEqual((listed["batch_id"], listed["folder"]), ("b1", "/papers"))
        self.assertEqual({k: p["state"] for k, p in listed["papers"].items()}, {"1": "ok", "2": "school", "3": "open"})
        self.assertEqual(listed["papers"]["1"]["path"], "/papers/1/Paper 1.pdf")

    def test_a_late_report_never_takes_a_paper_back(self):
        pr.sync_papers("b1", "/papers", [paper(1, "failed", cls="no_access", reason="本校没有订阅")])
        pr.sync_papers("b1", "/papers", [paper(1, "school"), paper(2, "school")])
        pr.sync_papers("b1", "/papers", [paper(2, "open")])
        listed = self.listed()["papers"]
        self.assertEqual((listed["1"]["state"], listed["1"]["reason"]), ("failed", "本校没有订阅"))
        self.assertEqual(listed["2"]["state"], "school")

    def test_another_batch_starts_a_new_list(self):
        pr.sync_papers("b1", "/one", [paper(1, "ok"), paper(2, "ok")])
        pr.sync_papers("b2", "/two", [paper(1, "open")])
        listed = self.listed()
        self.assertEqual((listed["batch_id"], listed["folder"], list(listed["papers"])), ("b2", "/two", ["1"]))

    def test_what_is_kept_is_checked_and_bounded(self):
        pr.sync_papers("b1", "relative/folder", [
            paper(1, "failed", cls="bogus", reason="<i>x</i> &amp; y", title="T" * 900),
            paper(2, "ok", path="relative.pdf"), paper(0, "ok"), paper(True, "ok"), paper(3, "done"), "junk",
            {**paper(4, "school"), "extra": "dropped", "path": "/not/kept.pdf"}])
        listed = self.listed()
        self.assertEqual(listed["folder"], "")
        self.assertEqual(sorted(listed["papers"]), ["1", "2", "4"])
        failed = listed["papers"]["1"]
        self.assertEqual((failed["cls"], failed["reason"], len(failed["title"])), ("unexplained", "x & y", 300))
        self.assertNotIn("path", listed["papers"]["2"])
        self.assertEqual(set(listed["papers"]["4"]), {"index", "state", "doi", "title", "journal"})
        for bad in (("", "/f", []), ("b" * 129, "/f", []), ("b1", "/f", "papers"), (None, "/f", [])):
            self.assertFalse(pr.sync_papers(*bad))

    def test_the_server_tool_merges_without_touching_the_progress(self):
        pr.progress_path().unlink(missing_ok=True)
        self.assertEqual(json.loads(server.carsi_batch_papers("b9", "/papers", [paper(1, "open")])), {"updated": True})
        self.assertEqual(pr.read_papers()["papers"]["1"]["state"], "open")
        self.assertFalse(pr.progress_path().exists())


class PaperListsTests(unittest.TestCase):
    state = {"batch_id": "b1", "status": "running", "current": "10.1000/5"}

    def lists(self, *papers, state=None):
        return pv.paper_lists({"batch_id": "b1", "folder": "/papers",
                               "papers": {str(p["index"]): p for p in papers}}, state or self.state)

    def test_saved_papers_by_the_way_they_came(self):
        lists = self.lists(paper(1, "ok", via="开放下载"), paper(2, "ok", via="开放下载", detail="出版社 API"),
                           paper(3, "ok", via="机构下载"), paper(4, "ok", via="开放下载", journal=""),
                           paper(6, "ok", via="开放下载", detail="出版社 API"))
        ok = lists["ok"]
        self.assertEqual(ok["count"], 5)
        self.assertEqual([(g["label"], g["count"], g["open"]) for g in ok["groups"]],
                         [("开放下载（出版社 API 2）", 4, True), ("机构下载", 1, False)])
        self.assertEqual([(p["index"], p["where"]) for p in ok["groups"][0]["papers"]],
                         [(1, "Nature · 开放获取"), (2, "Nature · 出版社 API"), (4, "开放获取"), (6, "Nature · 出版社 API")])
        self.assertEqual(ok["groups"][1]["papers"][0]["where"], "Nature")

    def test_failed_papers_by_reason_like_the_finished_card(self):
        lists = self.lists(paper(1, "failed", cls="no_access", reason="本校没有订阅"),
                           paper(2, "failed", cls="user_or_external", reason="等学校登录到时限"),
                           paper(3, "failed", cls="no_access", reason="本校没有订阅", doi="not a doi"))
        failed = lists["failed"]
        self.assertEqual(failed["count"], 3)
        self.assertEqual([(g["cls"], g["label"], g["count"], g["open"]) for g in failed["groups"]],
                         [("no_access", "本校没有订阅", 2, True), ("user_or_external", "等学校登录到时限", 1, False)])
        self.assertEqual([p["doi"] for p in failed["groups"][0]["papers"]], ["10.1000/1", ""])

    def test_the_rest_by_lane_with_the_paper_being_downloaded_first(self):
        lists = self.lists(paper(4, "open"), paper(5, "school", journal="Digestion"), paper(6, "school"), paper(7, "open"),
                           paper(8, "ok"))
        left = lists["left"]
        self.assertEqual(left["count"], 4)
        self.assertEqual([(g["label"], g["count"], g["open"]) for g in left["groups"]],
                         [("正在下载", 1, True), ("排队等机构下载", 1, False), ("开放下载还没查", 2, False)])
        self.assertEqual(left["groups"][0]["papers"][0]["where"], "Digestion · 机构下载")
        # The open lane's paper, when no institutional download runs.
        lists = self.lists(paper(4, "open"), state={**self.state, "current": "10.1000/4"})
        self.assertEqual(lists["left"]["groups"][0]["papers"][0]["where"], "Nature · 开放下载")
        # Once the batch is over nothing is being downloaded.
        lists = self.lists(paper(5, "school"), state={**self.state, "status": "done"})
        self.assertEqual([g["label"] for g in lists["left"]["groups"]], ["排队等机构下载"])

    def test_another_batchs_papers_are_not_shown(self):
        self.assertEqual(self.lists(paper(1, "ok"), state={**self.state, "batch_id": "b2"}), {})
        self.assertEqual(pv.paper_lists(None, self.state), {})
        self.assertEqual(pv.paper_lists({"batch_id": "b1", "papers": {}}, None), {})
        self.assertEqual(self.lists()["ok"], {"count": 0, "groups": []})

    def test_a_paper_without_title_or_doi_still_has_a_line(self):
        lists = self.lists({"index": 9, "state": "open", "doi": "", "title": "", "journal": ""})
        self.assertEqual(lists["left"]["groups"][0]["papers"][0]["title"], "第 9 篇")


class OpenPaperTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(os.path.realpath(tmp.name))
        self.folder = self.root / "batch"
        (self.folder / "papers" / "1").mkdir(parents=True)
        self.pdf = self.folder / "papers" / "1" / "Paper 1.pdf"
        self.pdf.write_bytes(b"%PDF-1.7")
        self.outside = self.root / "other.pdf"
        self.outside.write_bytes(b"%PDF-1.7")
        self.api = capsule.Api(MagicMock(), MagicMock(), MagicMock())
        state = patch.object(capsule, "read_state", return_value={"batch_id": "b1", "status": "running"})
        state.start()
        self.addCleanup(state.stop)

    def listed(self, *papers, batch="b1"):
        return patch.object(capsule, "read_papers", return_value={
            "batch_id": batch, "folder": str(self.folder), "papers": {str(p["index"]): p for p in papers}})

    def test_a_saved_pdf_of_the_batch_is_shown_in_its_folder(self):
        with self.listed(paper(1, "ok", path=str(self.pdf))), patch("subprocess.Popen") as shown:
            self.assertEqual(self.api.show_paper(1), "已打开所在文件夹")
        shown.assert_called_once()
        self.assertIn(str(self.pdf.parent), str(shown.call_args))

    def test_the_folder_comes_up_with_the_file_selected(self):
        cases = [("darwin", "posix", ["open", "-R", str(self.pdf)]),
                 ("win32", "nt", f'explorer /select,"{self.pdf}"'),
                 ("linux", "posix", ["xdg-open", str(self.pdf.parent)])]
        for platform, name, command in cases:
            with self.subTest(platform=platform), patch.object(pv.sys, "platform", platform), \
                    patch.object(pv.os, "name", name), patch("subprocess.Popen") as shown:
                self.assertTrue(pv.reveal_file(str(self.pdf)))
                self.assertEqual(shown.call_args.args[0], command)
        self.assertFalse(pv.reveal_file(str(self.folder / "gone.pdf")))

    def test_nothing_outside_the_batchs_folder_or_not_a_saved_pdf_opens(self):
        link = self.folder / "papers" / "link.pdf"
        link.symlink_to(self.outside)
        text = self.folder / "papers" / "1" / "notes.txt"
        text.write_text("x")
        cases = [
            (paper(1, "ok", path=str(self.outside)), 1, "打开失败：PDF 不在这批的下载文件夹里"),
            (paper(1, "ok", path=str(self.folder / ".." / "other.pdf")), 1, "打开失败：PDF 不在这批的下载文件夹里"),
            (paper(1, "ok", path=str(link)), 1, "打开失败：PDF 不在这批的下载文件夹里"),
            (paper(1, "ok", path=str(text)), 1, "打开失败：PDF 不在这批的下载文件夹里"),
            (paper(1, "ok", path=str(self.folder / "papers" / "1" / "gone.pdf")), 1, "打开失败：文件已被移走或删除"),
            (paper(1, "failed", path=str(self.pdf)), 1, "打开失败：没有这篇的 PDF"),
            (paper(1, "ok", path=str(self.pdf)), 2, "打开失败：没有这篇的 PDF"),
            (paper(1, "ok", path=str(self.pdf)), True, "打开失败：没有这篇的 PDF"),
            (paper(1, "ok", path=str(self.pdf)), "1", "打开失败：没有这篇的 PDF"),
        ]
        for item, index, expected in cases:
            with self.subTest(path=item.get("path"), index=index), self.listed(item), patch("subprocess.Popen") as shown:
                self.assertEqual(self.api.show_paper(index), expected)
                shown.assert_not_called()
        with self.listed(paper(1, "ok", path=str(self.pdf)), batch="b0"), patch("subprocess.Popen") as shown:
            self.assertEqual(self.api.show_paper(1), "打开失败：没有这篇的 PDF")
            shown.assert_not_called()

    def test_the_counts_open_lists_only_for_this_batchs_papers(self):
        pr.papers_path().unlink(missing_ok=True)
        with patch.object(capsule.progress_view, "view", side_effect=lambda *_: {"mode": "running"}):
            self.assertNotIn("lists", self.api.state())
            pr.sync_papers("b1", str(self.folder), [paper(1, "open")])
            self.assertTrue(self.api.state()["lists"])
            pr.sync_papers("b2", str(self.folder), [paper(1, "open")])
            os.utime(pr.papers_path(), ns=(1, 1))  # another write, whatever the clock says
            self.assertNotIn("lists", self.api.state())


if __name__ == "__main__":
    unittest.main()
