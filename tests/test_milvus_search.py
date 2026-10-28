import re
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import clients.milvus_client as milvus_module


class MilvusSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_doc_ids_are_batched_and_results_merged_to_global_top_ten(self):
        doc_ids = list(range(1, 54))
        result_batches = [
            [[
                {
                    "distance": batch_index * 0.1 + hit_index * 0.01,
                    "content_id": f"{doc_ids[min(batch_index * 20, len(doc_ids) - 1)]}-{hit_index}",
                }
                for hit_index in range(10)
            ]]
            for batch_index in range(3)
        ]
        fake_client = SimpleNamespace(search=AsyncMock(side_effect=result_batches))

        with (
            patch.object(milvus_module, "embedding_text", new=AsyncMock(return_value=[0.1] * 8)),
            patch.object(milvus_module, "milvus_client", fake_client),
        ):
            result = await milvus_module.search_milvus_data("深蹲怎么做", doc_ids)

        self.assertEqual(fake_client.search.await_count, 3)
        filters = [call.kwargs["filter"] for call in fake_client.search.await_args_list]
        self.assertEqual([len(re.findall(r"content_id like", expr)) for expr in filters], [20, 20, 13])
        self.assertTrue(all("filter" in call.kwargs for call in fake_client.search.await_args_list))
        self.assertTrue(all(call.kwargs["limit"] == 10 for call in fake_client.search.await_args_list))

        hits = result["data"]
        self.assertEqual(len(hits), 10)
        self.assertEqual(
            [hit["distance"] for hit in hits],
            sorted((hit["distance"] for batch in result_batches for hit in batch[0]), reverse=True)[:10],
        )

    async def test_empty_visible_doc_ids_return_without_embedding_or_search(self):
        fake_client = SimpleNamespace(search=AsyncMock())
        with (
            patch.object(milvus_module, "embedding_text", new=AsyncMock()) as embed,
            patch.object(milvus_module, "milvus_client", fake_client),
        ):
            result = await milvus_module.search_milvus_data("anything", [])

        self.assertEqual(result["data"], [])
        embed.assert_not_awaited()
        fake_client.search.assert_not_awaited()

    async def test_none_doc_ids_keeps_unfiltered_single_search(self):
        fake_client = SimpleNamespace(search=AsyncMock(return_value=[[{"distance": 0.8}]]))
        with (
            patch.object(milvus_module, "embedding_text", new=AsyncMock(return_value=[0.1] * 8)),
            patch.object(milvus_module, "milvus_client", fake_client),
        ):
            result = await milvus_module.search_milvus_data("anything", None)

        fake_client.search.assert_awaited_once()
        self.assertIsNone(fake_client.search.await_args.kwargs["filter"])
        self.assertEqual(result["data"], [{"distance": 0.8}])


if __name__ == "__main__":
    unittest.main()
