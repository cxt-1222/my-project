const assert = require('node:assert/strict');
const test = require('node:test');

const {createChatStreamRegistry} = require('../frontend/chat-stream-state.js');
const {consumeChatSse} = require('../frontend/chat-sse.js');

function makeControlledResponse() {
  let controller;
  const body = new ReadableStream({start(value) { controller = value; }});
  return {
    response: {ok: true, body},
    send(event, payload) {
      controller.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
    },
    close() { controller.close(); },
  };
}

function startConsumer(registry, record, accountGeneration, response) {
  return consumeChatSse(response, {
    isCurrent: () => registry.isCurrent(record, accountGeneration),
    onEvent(event, payload) {
      if (event === 'sources') registry.setSources(record, accountGeneration, payload.sources);
      if (event === 'delta') registry.appendDelta(record, accountGeneration, payload.text);
    },
  }).then(() => registry.finish(record, accountGeneration)).catch(error => {
    registry.fail(record, accountGeneration, error.message);
    throw error;
  });
}

test('two session streams progress concurrently and finish in reverse order without mixing sources or text', async () => {
  const registry = createChatStreamRegistry();
  const generation = 4;
  const controllerA = new AbortController();
  const controllerB = new AbortController();
  const streamA = registry.reserve(101, {controller: controllerA, accountGeneration: generation, ownerKey: 'u1'});
  const streamB = registry.reserve(202, {controller: controllerB, accountGeneration: generation, ownerKey: 'u1'});
  const responseA = makeControlledResponse();
  const responseB = makeControlledResponse();
  const readingA = startConsumer(registry, streamA, generation, responseA.response);
  const readingB = startConsumer(registry, streamB, generation, responseB.response);

  responseA.send('sources', {sources: [{documentTitle: '来源 A'}]});
  responseB.send('sources', {sources: [{documentTitle: '来源 B'}]});
  responseA.send('delta', {text: '回答 A-1'});
  responseB.send('delta', {text: '回答 B-1'});
  await new Promise(resolve => setImmediate(resolve));

  assert.equal(streamA.answer, '回答 A-1');
  assert.equal(streamB.answer, '回答 B-1');
  assert.equal(streamA.sources[0].documentTitle, '来源 A');
  assert.equal(streamB.sources[0].documentTitle, '来源 B');
  assert.equal(registry.isStreaming(101), true);
  assert.equal(registry.isStreaming(202), true);

  const visibleSession = sessionId => ({
    answer: registry.get(sessionId).answer,
    sources: registry.get(sessionId).sources,
    status: registry.get(sessionId).status,
  });
  let activeSessionId = 101;
  assert.equal(visibleSession(activeSessionId).answer, '回答 A-1');
  activeSessionId = 202;
  assert.equal(visibleSession(activeSessionId).answer, '回答 B-1');
  activeSessionId = 101;
  assert.equal(visibleSession(activeSessionId).sources[0].documentTitle, '来源 A');

  responseB.send('delta', {text: ' 完成'});
  responseB.send('done', {});
  responseB.close();
  await readingB;
  assert.equal(streamB.status, 'succeeded');
  assert.equal(registry.isStreaming(101), true);

  responseA.send('delta', {text: ' 完成'});
  responseA.send('done', {});
  responseA.close();
  await readingA;
  assert.equal(streamA.status, 'succeeded');
  assert.equal(streamA.answer, '回答 A-1 完成');
  assert.equal(streamB.answer, '回答 B-1 完成');
});

test('same-session duplicate is rejected while a different session can reserve immediately', () => {
  const registry = createChatStreamRegistry();
  const options = {controller: new AbortController(), accountGeneration: 1, ownerKey: 'u1'};
  const first = registry.reserve(101, options);

  assert.ok(first);
  assert.equal(registry.reserve(101, options), null);
  assert.ok(registry.reserve(202, options));
  assert.equal(registry.isStreaming(101), true);
  assert.equal(registry.isStreaming(202), true);
});

test('an SSE error fails only its session and leaves another session streaming', async () => {
  const registry = createChatStreamRegistry();
  const generation = 2;
  const streamA = registry.reserve(11, {controller: new AbortController(), accountGeneration: generation});
  const streamB = registry.reserve(22, {controller: new AbortController(), accountGeneration: generation});
  const responseA = makeControlledResponse();
  const responseB = makeControlledResponse();
  const readingA = startConsumer(registry, streamA, generation, responseA.response);
  const readingB = startConsumer(registry, streamB, generation, responseB.response);

  responseA.send('delta', {text: 'partial'});
  responseA.send('error', {message: 'provider failed'});
  responseA.close();
  await assert.rejects(readingA, /provider failed/);
  assert.equal(streamA.status, 'failed');
  assert.equal(streamA.error, 'provider failed');
  assert.equal(registry.isStreaming(22), true);

  responseB.send('delta', {text: 'still running'});
  responseB.send('done', {});
  responseB.close();
  await readingB;
  assert.equal(streamB.status, 'succeeded');
  assert.equal(streamB.answer, 'still running');
});

test('logout invalidation rejects late events and active sessions cannot be deleted', () => {
  const registry = createChatStreamRegistry();
  const controller = new AbortController();
  const stream = registry.reserve(31, {controller, accountGeneration: 9});

  assert.equal(registry.delete(31), false);
  registry.cancelAll();
  assert.equal(controller.signal.aborted, true);
  assert.equal(registry.isCurrent(stream, 9), false);
  assert.equal(registry.appendDelta(stream, 9, 'late text'), false);
  assert.equal(stream.answer, '');
  assert.equal(registry.get(31), null);
});

test('an aborted stream exits promptly and can be marked failed without changing another session', async () => {
  const registry = createChatStreamRegistry();
  const generation = 3;
  const timedOutController = new AbortController();
  const timedOut = registry.reserve(51, {controller: timedOutController, accountGeneration: generation});
  const other = registry.reserve(52, {controller: new AbortController(), accountGeneration: generation});
  const controlled = makeControlledResponse();
  const reading = consumeChatSse(controlled.response, {
    signal: timedOutController.signal,
    isCurrent: () => registry.isCurrent(timedOut, generation),
  });

  timedOutController.abort();
  await assert.rejects(reading, {name: 'AbortError'});
  registry.fail(timedOut, generation, 'timed out');
  assert.equal(timedOut.status, 'failed');
  assert.equal(registry.isStreaming(52), true);
  assert.equal(other.status, 'streaming');
});

test('refresh starts with no in-memory stream and normal server history remains authoritative', () => {
  const beforeRefresh = createChatStreamRegistry();
  beforeRefresh.reserve(41, {controller: new AbortController(), accountGeneration: 1});

  const afterRefresh = createChatStreamRegistry();
  assert.equal(afterRefresh.get(41), null);
  assert.equal(afterRefresh.isStreaming(41), false);
});

test('refresh marks an unsaved trailing user message as interrupted instead of silently discarding it', () => {
  const registry = createChatStreamRegistry();
  const messages = [{type: 'user', text: '未完成的问题'}];
  const stream = registry.recoverInterrupted(61, messages, {accountGeneration: 1, ownerKey: 'u1'});

  assert.equal(stream.status, 'failed');
  assert.equal(stream.interrupted, true);
  assert.match(stream.error, /没有已保存的回答/);
  assert.equal(registry.isStreaming(61), false);

  const persisted = registry.recoverInterrupted(61, [
    ...messages,
    {type: 'assistant', text: '已保存的回答'},
  ], {accountGeneration: 1, ownerKey: 'u1'});
  assert.equal(persisted, null);
  assert.equal(registry.get(61), null);
});
