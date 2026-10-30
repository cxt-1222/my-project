import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import milvus as milvus_api


class MilvusApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_table_preserves_existing_collection(self):
        client = SimpleNamespace()
        with (
            patch.object(milvus_api, "has_milvus_collection", AsyncMock(return_value=True)),
            patch.object(milvus_api, "milvus_client", client),
        ):
            result = await milvus_api.create_milvus_database()

        self.assertIn("已存在", result["msg"])
        self.assertIn("未执行重建", result["msg"])
        self.assertFalse(hasattr(client, "drop_collection"))
