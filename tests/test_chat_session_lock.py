import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from services.chat_session_lock import ChatSessionLockManager


class ChatSessionLockManagerTests(unittest.TestCase):
    def test_same_user_and_session_is_rejected_but_other_keys_are_independent(self):
        locks = ChatSessionLockManager()
        first = locks.try_acquire(7, 101)

        self.assertIsNotNone(first)
        self.assertIsNone(locks.try_acquire(7, 101))
        self.assertIsNotNone(locks.try_acquire(7, 102))
        self.assertIsNotNone(locks.try_acquire(8, 101))
        self.assertTrue(locks.release(7, 101, first))
        self.assertFalse(locks.release(7, 101, first))
        self.assertIsNotNone(locks.try_acquire(7, 101))

    def test_stale_release_cannot_release_a_new_lease(self):
        locks = ChatSessionLockManager()
        old_token = locks.try_acquire(7, 101)
        self.assertTrue(locks.release(7, 101, old_token))
        new_token = locks.try_acquire(7, 101)

        self.assertFalse(locks.release(7, 101, old_token))
        self.assertTrue(locks.is_locked(7, 101))
        self.assertTrue(locks.release(7, 101, new_token))


class StreamLockIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api import ai

        self.ai = ai
        ai.chat_session_locks._active.clear()
        self.user = SimpleNamespace(id=73)

    async def asyncTearDown(self):
        self.ai.chat_session_locks._active.clear()

    def _common_patches(self, stack, *, history_side_effect=None, prepare_side_effect=None, model=None):
        stack.enter_context(patch.object(self.ai, '_get_history', new_callable=AsyncMock,
                                          side_effect=history_side_effect, return_value=[]))
        stack.enter_context(patch.object(self.ai, '_recall_chat_memories', new_callable=AsyncMock, return_value=[]))
        stack.enter_context(patch.object(self.ai, '_load_account_fitness_profile', new_callable=AsyncMock, return_value=None))
        self.save_message_mock = stack.enter_context(patch.object(self.ai, '_save_message', new_callable=AsyncMock))
        stack.enter_context(patch.object(self.ai, '_prepare_materials', new_callable=AsyncMock,
                                          side_effect=prepare_side_effect, return_value=('test context', [{'index': 1, 'documentTitle': 'test'}])))
        stack.enter_context(patch.object(self.ai, '_extract_and_store_chat_memories', new_callable=AsyncMock))

        class FakeDbContext:
            async def __aenter__(self):
                return object()

            async def __aexit__(self, *_args):
                return False

        stack.enter_context(patch.object(self.ai, 'SessionLocal', FakeDbContext))
        if model is not None:
            stack.enter_context(patch.object(self.ai, 'model', model))

    async def _start(self, session_id):
        return await self.ai._do_invoke_stream(
            query=f'question-{session_id}',
            top_n=5,
            enable_web=False,
            session_id=session_id,
            db=object(),
            current_user=self.user,
        )

    async def test_same_session_request_gets_409_before_history_is_read(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_history(*_args):
            entered.set()
            await release.wait()
            return []

        with ExitStack() as stack:
            self._common_patches(stack, history_side_effect=blocked_history)
            first_task = asyncio.create_task(self._start(501))
            await asyncio.wait_for(entered.wait(), timeout=1)

            with self.assertRaises(HTTPException) as caught:
                await self._start(501)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn('正在回答', caught.exception.detail)

            release.set()
            response = await first_task
            self.assertEqual(response.media_type, 'text/event-stream')
            await response.background()

    async def test_different_sessions_enter_async_preparation_concurrently(self):
        entered = []
        both_entered = asyncio.Event()
        release = asyncio.Event()

        async def history_for_session(session_id, _db, _user):
            entered.append(session_id)
            if len(entered) == 2:
                both_entered.set()
            await release.wait()
            return []

        with ExitStack() as stack:
            self._common_patches(stack, history_side_effect=history_for_session)
            task_a = asyncio.create_task(self._start(601))
            task_b = asyncio.create_task(self._start(602))
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            self.assertCountEqual(entered, [601, 602])
            release.set()
            response_a, response_b = await asyncio.gather(task_a, task_b)
            self.assertEqual(response_a.media_type, 'text/event-stream')
            self.assertEqual(response_b.media_type, 'text/event-stream')
            await response_a.background()
            await response_b.background()

    async def test_lock_releases_after_sse_success_and_preserves_event_contract(self):
        class FakeModel:
            async def astream(self, _messages):
                yield SimpleNamespace(content='answer')

        with ExitStack() as stack:
            self._common_patches(stack, model=FakeModel())
            response = await self._start(701)
            frames = []
            async for frame in response.body_iterator:
                frames.append(frame)

            output = ''.join(frames)
            self.assertIn('event: sources', output)
            self.assertIn('"sources": [{"index": 1, "documentTitle": "test"}]', output)
            self.assertIn('event: delta', output)
            self.assertIn('event: done', output)
            self.assertIn('answer', output)
            self.assertEqual([call.args[3] for call in self.save_message_mock.await_args_list], ['user', 'assistant'])
            self.assertEqual(self.save_message_mock.await_args_list[-1].args[5], [{'index': 1, 'documentTitle': 'test'}])
            self.assertFalse(self.ai.chat_session_locks.is_locked(self.user.id, 701))
            # A completed session accepts a later request.
            second_response = await self._start(701)
            self.assertEqual(second_response.media_type, 'text/event-stream')
            await second_response.background()

    async def test_lock_releases_after_model_error_and_emits_error_event(self):
        class FailingModel:
            async def astream(self, _messages):
                raise RuntimeError('provider failed')
                yield  # Make this an async generator.

        with ExitStack() as stack:
            self._common_patches(stack, model=FailingModel())
            response = await self._start(801)
            output = ''.join([frame async for frame in response.body_iterator])

            self.assertIn('event: sources', output)
            self.assertIn('event: error', output)
            self.assertNotIn('event: done', output)
            self.assertFalse(self.ai.chat_session_locks.is_locked(self.user.id, 801))

    async def test_lock_releases_when_client_disconnects_or_preparation_fails(self):
        entered_model = asyncio.Event()
        release_model = asyncio.Event()

        class WaitingModel:
            async def astream(self, _messages):
                entered_model.set()
                await release_model.wait()
                yield SimpleNamespace(content='late')

        with ExitStack() as stack:
            self._common_patches(stack, model=WaitingModel())
            response = await self._start(901)
            iterator = response.body_iterator
            await iterator.__anext__()  # sources frame starts the response body
            next_chunk = asyncio.create_task(iterator.__anext__())
            await asyncio.wait_for(entered_model.wait(), timeout=1)
            next_chunk.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await next_chunk
            self.assertFalse(self.ai.chat_session_locks.is_locked(self.user.id, 901))

        async def failed_prepare(*_args):
            raise RuntimeError('retrieval failed')

        with ExitStack() as stack:
            self._common_patches(stack, prepare_side_effect=failed_prepare)
            with self.assertRaises(HTTPException) as caught:
                await self._start(902)
            self.assertEqual(caught.exception.status_code, 502)
            self.assertFalse(self.ai.chat_session_locks.is_locked(self.user.id, 902))

    async def test_delete_session_uses_the_same_lock_and_does_not_race_streaming(self):
        from api import chat

        token = chat.chat_session_locks.try_acquire(self.user.id, 1001)
        self.assertIsNotNone(token)
        with self.assertRaises(HTTPException) as caught:
            await chat.delete_session_api(1001, db=object(), current_user=self.user)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(chat.chat_session_locks.is_locked(self.user.id, 1001))
        chat.chat_session_locks.release(self.user.id, 1001, token)

        db = SimpleNamespace(execute=AsyncMock(), delete=AsyncMock(), commit=AsyncMock())
        session = SimpleNamespace(id=1001, user_id=self.user.id)
        with ExitStack() as stack:
            stack.enter_context(patch.object(chat, '_get_owned_session', new_callable=AsyncMock, return_value=session))
            stack.enter_context(patch.object(chat, 'delete_recent_messages', new_callable=AsyncMock))
            stack.enter_context(patch.object(chat, 'delete_chat_memories_for_session', new_callable=AsyncMock))
            result = await chat.delete_session_api(1001, db=db, current_user=self.user)

        self.assertEqual(result, {'msg': '删除成功'})
        self.assertFalse(chat.chat_session_locks.is_locked(self.user.id, 1001))


if __name__ == '__main__':
    unittest.main()
