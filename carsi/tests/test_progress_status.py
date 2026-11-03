"""Machine progress contract: isolated files, real CLI processes, no downloads.

The `progress` subcommand of paper-search-carsi and the standalone
progress_status.py script are both exercised as real processes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "paper_search_carsi"
DOI = "10.1000/progress-fixture"
SECRET = "synthetic-secret-not-for-output"


def load_isolated():
    # Use the real modules without importing package startup/config in this
    # process. Subprocess cases below exercise the actual Typer CLI as well.
    package = ModuleType("_progress_fixture")
    package.__path__ = [str(SOURCE)]
    modules = {package.__name__: package}
    with patch.dict(sys.modules, modules):
        loaded = []
        for name in ("progress_reporter", "progress_status"):
            spec = importlib.util.spec_from_file_location(f"{package.__name__}.{name}", SOURCE / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(package, name, module)
            loaded.append(module)
    return loaded


pr, status = load_isolated()


class ProgressStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.file = self.data / "progress" / "current.json"
        env = patch.dict(os.environ, {"CARSI_DATA_DIR": str(self.data), "CARSI_PROGRESS_BAR": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(lambda: setattr(pr, "_STATE", {}))
        pr._STATE = {}
        self.env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        # Suppress unrelated IDE proxy workarounds in package startup.
        self.env.pop("SSL_CERT_FILE", None)
        self.env.pop("REQUESTS_CA_BUNDLE", None)
        self.env.pop("CURL_CA_BUNDLE", None)
        self.record = dict(schema_version=1, run_id=str(uuid4()), revision=1,
                           status="running", stage="waiting_login", owner_pid=os.getpid(),
                           current=DOI, total=1, done=0, success=0, failed=0,
                           started_at=datetime.now().isoformat(), updated_at=datetime.now().isoformat())

    def write(self, **fields):
        self.record.update(fields)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.record), encoding="utf-8")
        tmp.replace(self.file)

    def command(self, *args, standalone=False):
        target = [str(SOURCE / "progress_status.py")] if standalone else ["-m", "paper_search_carsi.cli", "progress"]
        return [sys.executable, "-B", *target, *args]

    def run_cli(self, *args, standalone=False, code=0):
        result = subprocess.run(self.command(*args, standalone=standalone), env=self.env,
                                capture_output=True, text=True, timeout=8, cwd=ROOT)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        return result

    def watch(self, *args):
        process = subprocess.Popen(self.command("--json", "--watch", "--timeout", "3", "--interval", "0.1", *args),
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=3)
        self.addCleanup(cleanup)
        return process

    def read_line(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(timeout=5), "watch did not flush a status in time")
        line = process.stdout.readline()
        self.assertTrue(line, "watch exited without a status")
        return json.loads(line)

    def test_revision_covers_every_successful_writer_and_new_run(self):
        pr.start_task("fixture", 1, current=DOI)
        first = pr.read_state()
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["stage"], "starting")
        UUID(first["run_id"])
        actions = [lambda: pr.update(phase="任意GUI文本"),
                   lambda: pr.report_stage("waiting_login"),
                   lambda: pr.set_attention("login", "fixture"),
                   lambda: pr.clear_attention("login"),
                   lambda: pr.set_output_dir("/fixture/output"),
                   lambda: pr.advance(True), pr.finish]
        for revision, action in enumerate(actions, 2):
            action()
            self.assertEqual(pr.read_state()["revision"], revision)
        self.assertEqual(pr.read_state()["run_id"], first["run_id"])
        self.assertEqual(pr.read_state()["stage"], "waiting_login")
        pr.start_task("next", 1)
        self.assertEqual(pr.read_state()["revision"], 1)
        self.assertNotEqual(pr.read_state()["run_id"], first["run_id"])

    def test_failed_write_does_not_advance_committed_revision(self):
        pr.start_task("fixture", 1)
        before = self.file.read_bytes()
        with patch.object(pr, "_atomic_write", side_effect=OSError("fixture")):
            pr.report_stage("fetching_pdf")
        self.assertEqual(pr._STATE["revision"], 1)
        self.assertEqual(self.file.read_bytes(), before)
        pr.report_stage("pdf_captured")
        self.assertEqual(pr.read_state()["revision"], 2)

    def test_explicit_stages_only_and_stage_only_retains_identifier(self):
        pr.start_task("fixture", 1, current=DOI)
        for stage in pr.STAGES:
            pr.report_stage(stage)
            self.assertEqual(pr.read_state()["stage"], stage)
            self.assertEqual(status.snapshot(identifier=DOI)["identifier"], DOI)
        pr.report_stage("waiting_login", current="")
        self.assertEqual(pr.read_state()["current"], DOI)
        pr.update(phase="保存成功，身份已验证")
        self.assertEqual(pr.read_state()["stage"], "waiting_login")
        for invalid in ("verified", "等待登录", "", [], None):
            with self.subTest(stage=invalid), self.assertRaises(ValueError):
                pr.report_stage(invalid)
        pr.report_stage("opening_article", current="10.1000/other")
        self.assertEqual(pr.read_state()["current"], "10.1000/other")

    def test_identity_fields_cannot_be_overridden_by_extra_or_update(self):
        pr.start_task("fixture", 1, run_id=SECRET, revision=999, schema_version=99, owner_pid=0, stage="verified")
        state = pr.read_state()
        self.assertNotEqual(state["run_id"], SECRET)
        self.assertEqual((state["schema_version"], state["revision"], state["stage"]), (1, 1, "starting"))
        self.assertEqual(state["owner_pid"], os.getpid())
        for field in ("run_id", "revision", "schema_version", "owner_pid"):
            with self.assertRaises(ValueError):
                pr.update(**{field: SECRET})

    def test_no_task_report_does_not_create_directory(self):
        pr.report_stage("starting")
        pr.update(done=1)
        pr.finish()
        self.assertIsNone(pr.read_state())
        self.assertFalse(self.data.exists())

    def test_cli_idle_is_read_only_and_standalone_matches(self):
        for standalone in (False, True):
            result = self.run_cli("--json", standalone=standalone)
            self.assertEqual(json.loads(result.stdout)["status"], "idle")
            self.assertEqual(result.stderr, "")
            self.assertFalse(self.data.exists())

    def test_cli_filters_and_normalizes_identifier(self):
        self.write()
        output = json.loads(self.run_cli("--json", "--run-id", self.record["run_id"],
                                         "--identifier", "https://doi.org/" + DOI.upper()).stdout)
        self.assertEqual(output["stage"], "waiting_login")
        self.assertEqual(output["identifier"], DOI)
        self.assertEqual(output["scope"], "run")
        for args in (("--run-id", str(uuid4())), ("--identifier", "10.1000/other")):
            output = json.loads(self.run_cli("--json", *args, code=3).stdout)
            self.assertEqual(output["status"], "task_mismatch")
            self.assertNotIn("identifier", output)
            self.assertNotIn("success", output)

    def test_direct_snapshot_validates_filters(self):
        self.write()
        self.assertEqual(status.snapshot(identifier="DOI:" + DOI.upper())["identifier"], DOI)
        for filters in ({"identifier": SECRET}, {"run_id": SECRET}):
            with self.assertRaises(ValueError):
                status.snapshot(**filters)

    def test_cli_allowlist_strips_secrets_including_scalar_fields(self):
        self.write(phase=SECRET, task=SECRET, output_dir="/" + SECRET,
                   attention={"message": SECRET}, cookie=SECRET, config={"key": SECRET},
                   url="https://example.invalid/?token=" + SECRET,
                   total=SECRET, success={"token": SECRET}, failed=[SECRET],
                   current="https://doi.org/" + DOI + "?token=" + SECRET,
                   stage=SECRET, stale=SECRET)
        result = self.run_cli("--json")
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["stage"], "unknown")
        self.assertFalse(output["stale"])
        allowed = {"schema_version", "run_id", "revision", "status", "stage", "scope", "stale", "done", "started_at", "updated_at"}
        self.assertEqual(set(output), allowed)

    def test_schema_identity_revision_time_values_fail_closed(self):
        for field, value in (("schema_version", True), ("schema_version", 2), ("schema_version", SECRET),
                             ("run_id", SECRET), ("run_id", {}), ("revision", True), ("revision", 0),
                             ("revision", 1.5), ("revision", SECRET), ("revision", 2**60),
                             ("started_at", SECRET), ("updated_at", "2026-02-30T12:00:00"),
                             ("finished_at", SECRET), ("status", [SECRET]), ("status", {"token": SECRET})):
            with self.subTest(field=field, value=value):
                baseline = dict(self.record)
                self.write(**{field: value})
                output = status.snapshot()
                self.assertEqual(output["status"], "unavailable")
                self.assertNotIn(SECRET, json.dumps(output))
                self.record = baseline

    def test_cli_malformed_json_is_unavailable_not_success(self):
        self.file.parent.mkdir(parents=True)
        for raw in ('{"phase": "' + SECRET, "[]", "null", '{"status": {}}', b"\xff",
                    '{"revision":' + "9" * 5000 + '}'):
            with self.subTest(raw=raw):
                self.file.write_bytes(raw if isinstance(raw, bytes) else raw.encode())
                result = self.run_cli("--json", code=1)
                self.assertIn(json.loads(result.stdout)["status"], {"unavailable", "unknown"})
                self.assertNotIn(SECRET, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_unreadable_path_is_unavailable_without_exception_text(self):
        self.file.mkdir(parents=True)
        result = self.run_cli("--json", code=1)
        self.assertEqual(json.loads(result.stdout)["reason"], "unreadable")
        self.assertNotIn(str(self.file), result.stdout + result.stderr)

    def test_cli_dead_owner_overrides_wait_and_never_writes(self):
        owner = subprocess.Popen([sys.executable, "-B", "-c", "pass"])
        owner.wait(timeout=3)
        self.write(owner_pid=owner.pid, updated_at=(datetime.now() - timedelta(days=1)).isoformat())
        before = self.file.read_bytes()
        result = self.run_cli("--json", "--watch", "--run-id", self.record["run_id"], code=1)
        output = json.loads(result.stdout)
        self.assertEqual((output["status"], output["stage"]), ("interrupted", "interrupted"))
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(pr.read_state()["stage"], "interrupted")

    def test_legacy_gui_stale_semantics_and_no_saved_inference(self):
        self.record = dict(status="done", done=1, success=1, phase="保存成功")
        self.write()
        self.assertEqual(pr.read_state(), self.record)
        result = self.run_cli("--json", code=1)
        self.assertEqual(json.loads(result.stdout)["stage"], "unknown")
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")
        self.assertEqual(json.loads(self.run_cli("--json", "--run-id", str(uuid4()), code=3).stdout)["status"], "task_mismatch")
        self.write(status="running", updated_at=(datetime.now() - timedelta(days=1)).isoformat())
        self.assertIsNone(pr.read_state())
        self.assertEqual(status.snapshot()["reason"], "stale")
        self.write(owner_pid=os.getpid())
        self.assertTrue(pr.read_state()["stale"])

    def test_alive_stale_owner_stays_visible(self):
        self.write(updated_at=(datetime.now() - timedelta(days=1)).isoformat())
        output = json.loads(self.run_cli("--json").stdout)
        self.assertEqual(output["status"], "running")
        self.assertTrue(output["stale"])

    def test_saved_is_explicit_terminal_not_identity_verified(self):
        self.write(status="done", stage="saved_pending_verification", done=1, success=1)
        result = self.run_cli("--json", "--watch")
        self.assertEqual(json.loads(result.stdout)["stage"], "saved_pending_verification")
        self.assertNotIn("identity_verified", result.stdout)
        self.write(stage="unknown")
        self.assertEqual(json.loads(self.run_cli("--json").stdout)["stage"], "unknown")

    def test_cli_rejects_unbounded_or_non_json_watch(self):
        for args in (("--watch",), ("--json", "--timeout", "61"), ("--json", "--timeout", "0"),
                     ("--json", "--timeout", "nan"), ("--json", "--interval", "0.01"),
                     ("--json", "--interval", "inf"), ("--json", "--run-id", SECRET),
                     ("--json", "--identifier", SECRET)):
            with self.subTest(args=args):
                result = self.run_cli(*args, code=2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(SECRET, result.stderr)
        self.assertFalse(self.data.exists())

    def test_watch_changes_only_then_saved_terminal(self):
        self.write()
        process = self.watch("--run-id", self.record["run_id"], "--identifier", DOI)
        self.assertEqual(self.read_line(process)["stage"], "waiting_login")
        # Wait across polling ticks: no unchanged JSON lines should be emitted.
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertFalse(selector.select(timeout=0.25))
        self.write(stage="fetching_pdf", revision=2)
        self.assertEqual(self.read_line(process)["stage"], "fetching_pdf")
        self.write(stage="saved_pending_verification", revision=3, status="done")
        self.assertEqual(self.read_line(process)["stage"], "saved_pending_verification")
        stdout, stderr = process.communicate(timeout=4)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout, "")

    def test_watch_route_failure_allows_fallback_before_final_saved(self):
        self.write(stage="route_failed")
        process = self.watch("--run-id", self.record["run_id"], "--identifier", DOI)
        initial = self.read_line(process)
        self.assertEqual((initial["status"], initial["stage"]), ("running", "route_failed"))
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertFalse(selector.select(timeout=0.25))
        self.assertIsNone(process.poll())
        self.write(stage="fetching_pdf", revision=2)
        self.assertEqual(self.read_line(process)["stage"], "fetching_pdf")
        self.write(stage="saved_pending_verification", status="done", revision=3)
        self.assertEqual(self.read_line(process)["stage"], "saved_pending_verification")
        stdout, stderr = process.communicate(timeout=3)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout, "")

    def test_watch_binds_first_run_and_exits_on_same_doi_replacement(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                self.write(run_id=str(uuid4()))
                old = self.record["run_id"]
                process = self.watch(*(["--run-id", old] if explicit else []))
                self.assertEqual(self.read_line(process)["run_id"], old)
                self.write(run_id=str(uuid4()), revision=1)
                output = self.read_line(process)
                self.assertEqual(output["status"], "run_changed")
                self.assertEqual(output["expected_run_id"], old)
                self.assertNotIn("identifier", output)
                process.communicate(timeout=3)
                self.assertEqual(process.returncode, 4)

    def test_watch_idle_binds_arrival_then_stops_on_failure(self):
        process = self.watch()
        self.assertEqual(self.read_line(process)["status"], "idle")
        self.write()
        self.assertEqual(self.read_line(process)["stage"], "waiting_login")
        self.write(stage="failed", revision=2, status="done")
        self.assertEqual(self.read_line(process)["stage"], "failed")
        process.communicate(timeout=3)
        self.assertEqual(process.returncode, 1)

    def test_watch_timeout_is_bounded_and_distinct_from_task_failure(self):
        self.write()
        start = time.monotonic()
        result = self.run_cli("--json", "--watch", "--timeout", "0.25", "--interval", "0.1", code=124)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([line["status"] for line in lines], ["running", "timeout"])
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(pr.read_state()["status"], "running")


if __name__ == "__main__":
    unittest.main()
