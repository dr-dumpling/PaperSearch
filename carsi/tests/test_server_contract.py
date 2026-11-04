"""MCP contract that PaperSearch depends on, checked in a subprocess with an isolated data dir."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = r"""
import asyncio, json, sys
from paper_search_carsi.server import mcp_app, carsi_cache_clear, SERVER_NAME
from paper_search_carsi.orchestrator import download_institutional

async def tools():
    return [(t.name, t.input_schema if hasattr(t, "input_schema") else t.inputSchema) for t in await mcp_app.list_tools()]

out = {"server": SERVER_NAME, "tools": {n: s for n, s in asyncio.run(tools())}}
out["cache_clear"] = json.loads(carsi_cache_clear("10.1000/none"))
out["unconfigured"] = download_institutional("10.1000/not-configured", None, strategy="institutional_only")
out["bad_strategy"] = download_institutional("10.1000/x", None, strategy="fastest")
out["arxiv"] = download_institutional("2101.00001", None)
print(json.dumps(out))
"""


class ServerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="carsi-contract-")
        env = {**os.environ, "CARSI_DATA_DIR": cls.tmp, "PYTHONPATH": str(ROOT), "CARSI_PROGRESS_BAR": "0"}
        proc = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, timeout=120)
        assert proc.returncode == 0, proc.stderr[-2000:]
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_server_name_and_tools(self):
        self.assertEqual(self.out["server"], "paper-search-carsi")
        self.assertEqual(
            set(self.out["tools"]),
            {"carsi_download", "carsi_cache_clear", "carsi_list_publishers",
             "carsi_batch_progress"},
        )

    def test_download_schema_matches_paper_search_contract(self):
        props = self.out["tools"]["carsi_download"]["properties"]
        for field in ("identifier", "output_dir", "scihub_enabled", "use_tor", "use_vpnsci", "bibtex", "strategy"):
            self.assertIn(field, props)
        self.assertNotIn("ctx", props)
        text = json.dumps(props["strategy"])
        self.assertIn("legal_only", text)
        self.assertIn("institutional_only", text)
        self.assertEqual(self.out["tools"]["carsi_download"].get("required"), ["identifier"])
        self.assertIn("identifier", self.out["tools"]["carsi_cache_clear"]["properties"])

    def test_batch_fields_are_optional_and_typed(self):
        props = self.out["tools"]["carsi_download"]["properties"]
        for name in ("batch_id", "batch_index", "batch_total", "batch_done", "batch_succeeded", "batch_failed"):
            self.assertIn(name, props)
        progress = self.out["tools"]["carsi_batch_progress"]
        self.assertEqual(set(progress["required"]), {"batch_id", "total", "done", "succeeded", "failed"})

    def test_diagnostic_directory_is_an_optional_extension(self):
        schema = self.out["tools"]["carsi_download"]
        self.assertIn("diagnostics_dir", schema["properties"])
        self.assertNotIn("diagnostics_dir", schema.get("required", []))
        self.assertIn("string", json.dumps(schema["properties"]["diagnostics_dir"]))

    def test_cache_clear_is_noop_safe(self):
        self.assertEqual(self.out["cache_clear"], {"cleared": 0})

    def test_unconfigured_institution_is_paywall_login_required(self):
        result = self.out["unconfigured"]
        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "paywall")
        self.assertEqual(result["action"], "login_required")
        self.assertEqual(result["doi"], "10.1000/not-configured")

    def test_rejected_inputs(self):
        self.assertFalse(self.out["bad_strategy"]["success"])
        self.assertEqual(self.out["bad_strategy"]["error_type"], "source_exception")
        self.assertFalse(self.out["arxiv"]["success"])
        self.assertEqual(self.out["arxiv"]["error_type"], "not_found")

    def test_isolated_data_dir_was_used(self):
        self.assertTrue(Path(self.tmp).exists())
        self.assertFalse((Path.home() / ".local" / "share" / "paper-search-cli" / "carsi" / "carsi-contract-marker").exists())


if __name__ == "__main__":
    unittest.main()
