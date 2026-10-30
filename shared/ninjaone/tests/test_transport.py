"""Contract tests with in-memory Bifrost storage and a fake NinjaOne API."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]


class FakeTables:
    def __init__(self):
        self.rows = {}

    async def insert(self, table, data, *, id):
        assert table == "script_jobs"
        self.rows[id] = dict(data)

    async def get(self, table, id):
        assert table == "script_jobs"
        return SimpleNamespace(data=self.rows[id]) if id in self.rows else None

    async def update(self, table, id, data):
        assert table == "script_jobs"
        self.rows[id].update(data)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tables = FakeTables()
        self.values = {
            "ninja_get_script_endpoint": "https://example.invalid/get",
            "ninja_post_result_webhook_url": "https://example.invalid/result",
            "ninja_bifrost_api_key": "synthetic-test-key",
            "ninja_script_id": 999,
        }

        async def get_config(key, default=None):
            return self.values.get(key, default)

        async def set_config(key, value):
            self.values[key] = value

        sdk = ModuleType("bifrost")
        sdk.tables = self.tables
        sdk.config = SimpleNamespace(get=get_config, set=set_config)
        sdk.UserError = ValueError
        sdk.workflow = lambda **kwargs: lambda function: function
        self.ninja = ModuleType("modules.ninjaone")
        self.ninja.create_run = AsyncMock()
        self.ninja.get_options = AsyncMock(return_value={"scripts": []})
        modules = ModuleType("modules")
        modules.ninjaone = self.ninja
        self.module_patch = patch.dict(sys.modules, {
            "bifrost": sdk, "modules": modules, "modules.ninjaone": self.ninja,
        })
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.helper = load_module("ninja_test_helper", "modules/extensions/ninjaone.py")
        self.fetch = load_module("ninja_test_fetch", "shared/ninjaone/workflows/get_script_job.py")
        self.post = load_module("ninja_test_post", "shared/ninjaone/workflows/post_script_job_result.py")

    async def create_job(self, **kwargs):
        return await self.helper.execute_powershell(
            42, "param([string]$Message)\nWrite-Output $Message",
            params={"Message": 'hello "world" — café'}, **kwargs,
        )

    async def test_dispatch_fetch_callback_and_wait_contract(self):
        receipt = await self.create_job()
        self.assertEqual(receipt.status, "pending")
        device, = self.ninja.create_run.call_args.args
        launch = self.ninja.create_run.call_args.kwargs["data"]
        self.assertEqual((device, launch["id"], launch["runAs"]), ("42", 999, "system"))
        self.assertIn(f"-job_id {receipt.job_id}", launch["parameters"])
        self.assertNotIn("Write-Output", launch["parameters"])
        payload = await self.fetch.get_script_job(receipt.job_id)
        self.assertEqual(payload["params"]["Message"], 'hello "world" — café')
        self.assertEqual(self.tables.rows[receipt.job_id]["status"], "running")
        await self.post.post_script_job_result(receipt.job_id, result="hello\n")
        with patch.object(self.helper.asyncio, "sleep", new=AsyncMock()):
            final = await self.helper._poll_job(receipt.job_id, 42, 3)
        self.assertEqual((final.status, final.result), ("completed", "hello\n"))
        with self.assertRaises(ValueError):
            await self.fetch.get_script_job(receipt.job_id)

    async def test_timeout_does_not_cancel_and_late_receipt_is_accepted(self):
        with patch.object(self.helper.asyncio, "sleep", new=AsyncMock()):
            receipt = await self.create_job(wait_seconds=1)
        self.assertEqual(receipt.status, "timeout")
        self.assertEqual(self.tables.rows[receipt.job_id]["status"], "pending")
        await self.post.post_script_job_result(receipt.job_id, status="failed", error="payload threw")
        self.assertEqual(self.tables.rows[receipt.job_id]["error"], "payload threw")

    async def test_discovery_caches_script_and_run_as_override(self):
        self.values.pop("ninja_script_id")
        self.ninja.get_options.return_value = {"scripts": [{"id": 321, "name": "Bifrost (Windows)"}]}
        await self.create_job(run_as="loggedonuser")
        await self.create_job()
        self.assertEqual(self.values["ninja_script_id"], 321)
        self.ninja.get_options.assert_awaited_once_with("42")
        self.assertEqual(self.ninja.create_run.call_args_list[0].kwargs["data"]["runAs"], "loggedonuser")

    async def test_discovery_and_launch_failures_persist_failed_job(self):
        self.values.pop("ninja_script_id")
        with self.assertRaisesRegex(ValueError, "not found"):
            await self.create_job()
        self.assertEqual(next(iter(self.tables.rows.values()))["status"], "failed")
        self.values["ninja_script_id"] = 999
        self.ninja.create_run.side_effect = RuntimeError("synthetic network failure")
        with self.assertRaisesRegex(ValueError, "synthetic network failure"):
            await self.create_job()
        self.assertTrue(all(row["status"] == "failed" for row in self.tables.rows.values()))

    async def test_missing_config_does_not_create_or_launch_job(self):
        self.values.pop("ninja_bifrost_api_key")
        with self.assertRaisesRegex(ValueError, "ninja_bifrost_api_key"):
            await self.create_job()
        self.assertEqual(self.tables.rows, {})
        self.ninja.create_run.assert_not_awaited()

    async def test_invalid_helper_inputs_fail_before_storage_or_dispatch(self):
        for arguments in (
            {"device_id": True, "script_content": "test"},
            {"device_id": 0, "script_content": "test"},
            {"device_id": 42, "script_content": None},
            {"device_id": 42, "script_content": "test", "params": []},
            {"device_id": 42, "script_content": "test", "wait_seconds": 0},
            {"device_id": 42, "script_content": "test", "wait_seconds": True},
        ):
            with self.assertRaises(ValueError):
                await self.helper.execute_powershell(**arguments)
        self.assertEqual(self.tables.rows, {})
        self.ninja.create_run.assert_not_awaited()

    async def test_result_envelope_variants_and_invalid_input(self):
        receipt = await self.create_job()
        for body in ({"job_id": receipt.job_id, "status": "failed", "error": "oops"},
                     json.dumps({"job_id": receipt.job_id, "result": "done"})):
            await self.post.post_script_job_result(body=body)
        self.assertEqual(self.tables.rows[receipt.job_id]["result"], "done")
        for arguments in ({"body": "invalid JSON"}, {"job_id": "missing"},
                          {"job_id": receipt.job_id, "status": "running"},
                          {"body": {"job_id": receipt.job_id, "status": "invalid"}}):
            with self.assertRaises(ValueError):
                await self.post.post_script_job_result(**arguments)
        with self.assertRaises(ValueError):
            await self.fetch.get_script_job("missing")

    async def test_application_jobs_require_application_handlers(self):
        receipt = await self.create_job()
        self.tables.rows[receipt.job_id]["metadata"] = {"kind": "deployment_run"}
        for handler in (self.fetch.get_script_job, self.post.post_script_job_result):
            with self.assertRaisesRegex(ValueError, "application-specific"):
                await handler(receipt.job_id)
        self.assertEqual(self.tables.rows[receipt.job_id]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
