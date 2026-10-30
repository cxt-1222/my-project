import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import main
import clients.milvus_client as milvus_module


class MilvusStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_knowledge_collection_becomes_ready_only_after_load_finishes(self):
        load_started = asyncio.Event()
        finish_load = asyncio.Event()

        class FakeMilvus:
            async def has_collection(self, *, collection_name):
                return collection_name == "knowledge"

            async def load_collection(self, *, collection_name, timeout):
                load_started.set()
                await finish_load.wait()

        with (
            patch.object(milvus_module, "milvus_client", FakeMilvus()),
            patch.object(milvus_module, "has_milvus_collection", AsyncMock(return_value=True)),
            patch.object(
                milvus_module,
                "get_milvus_load_state",
                AsyncMock(side_effect=[{"state": "NotLoad"}, {"state": "Loaded"}]),
            ),
            patch.object(milvus_module.settings, "COLLECTION_NAME", "knowledge"),
            patch.object(milvus_module, "_knowledge_collection_loaded", False),
        ):
            load_task = asyncio.create_task(milvus_module.ensure_knowledge_collection())
            await asyncio.wait_for(load_started.wait(), timeout=0.5)
            self.assertFalse(milvus_module._knowledge_collection_loaded)
            finish_load.set()
            await load_task
            self.assertTrue(milvus_module._knowledge_collection_loaded)

    async def test_already_loaded_knowledge_collection_is_not_loaded_again(self):
        fake_milvus = type("FakeMilvus", (), {"load_collection": AsyncMock()})()
        with (
            patch.object(milvus_module, "milvus_client", fake_milvus),
            patch.object(milvus_module, "has_milvus_collection", AsyncMock(return_value=True)),
            patch.object(
                milvus_module,
                "get_milvus_load_state",
                AsyncMock(return_value={"state": "Loaded"}),
            ),
            patch.object(milvus_module.settings, "COLLECTION_NAME", "knowledge"),
            patch.object(milvus_module, "_knowledge_collection_loaded", False),
        ):
            await milvus_module.ensure_knowledge_collection()
            self.assertTrue(milvus_module._knowledge_collection_loaded)

        fake_milvus.load_collection.assert_not_awaited()

    async def test_startup_timeout_does_not_cancel_collection_load(self):
        finished = asyncio.Event()
        cancelled = False

        async def slow_load():
            nonlocal cancelled
            try:
                await asyncio.sleep(0.05)
                finished.set()
            except asyncio.CancelledError:
                cancelled = True
                raise

        with (
            patch.object(main, "MILVUS_STARTUP_WAIT_SECONDS", 0.001),
            patch("builtins.print"),
        ):
            await main._load_milvus_collection("Knowledge", slow_load)
            self.assertEqual(len(main._background_milvus_load_tasks), 1)
            await asyncio.wait_for(finished.wait(), timeout=0.5)
            await asyncio.sleep(0)

        self.assertFalse(cancelled)
        self.assertFalse(main._background_milvus_load_tasks)


if __name__ == "__main__":
    unittest.main()
