const assert = require('node:assert/strict');
const test = require('node:test');

const {patchChatStreamMessage} = require('../frontend/chat-stream-render.js');

function makeStreamDom(sessionId, {scrollTop = 0, scrollHeight = 500, clientHeight = 300} = {}) {
  const textNode = {nodeType: 3, nodeValue: 'old answer'};
  const classes = new Set();
  const bubble = {
    childNodes: [textNode],
    classList: {add: name => classes.add(name), contains: name => classes.has(name)},
    get textContent() { return this.childNodes.map(child => child.nodeValue || '').join(''); },
    set textContent(value) { this.childNodes = [{nodeType: 3, nodeValue: value}]; },
  };
  const meta = {textContent: 'AI 教练 · 正在回答'};
  const row = {
    dataset: {streamSession: String(sessionId)},
    querySelector(selector) {
      if (selector === '.message-bubble') return bubble;
      if (selector === '.message-meta') return meta;
      return null;
    },
  };
  let fullContainerHtml = 'history';
  const container = {
    querySelectorAll: selector => selector === '[data-stream-session]' ? [row] : [],
    scrollTop,
    scrollHeight,
    clientHeight,
    style: {scrollBehavior: 'smooth'},
    get innerHTML() { return fullContainerHtml; },
    set innerHTML(value) { fullContainerHtml = value; },
  };
  return {container, bubble, meta, textNode};
}

test('stream delta changes a stable text node without rebuilding the answer bubble or chat history', () => {
  const {container, bubble, meta, textNode} = makeStreamDom(101);
  const originalRow = container.querySelectorAll('[data-stream-session]')[0];

  assert.equal(patchChatStreamMessage(container, 101, '逐段', 'AI 教练 · 正在回答'), true);
  assert.equal(patchChatStreamMessage(container, 101, '逐段回答', 'AI 教练 · 正在回答'), true);

  assert.equal(bubble.childNodes[0], textNode);
  assert.equal(textNode.nodeValue, '逐段回答');
  assert.equal(bubble.classList.contains('is-streaming'), true);
  assert.equal(meta.textContent, 'AI 教练 · 正在回答');
  assert.equal(container.innerHTML, 'history');
  assert.equal(container.querySelectorAll('[data-stream-session]')[0], originalRow);
});

test('stream update does not steal scroll when the user has scrolled up', () => {
  const {container} = makeStreamDom(202, {scrollTop: 40});

  patchChatStreamMessage(container, 202, '继续', 'AI 教练 · 正在回答');

  assert.equal(container.scrollTop, 40);
});

test('stream update follows the answer when the user is already near the bottom', () => {
  const {container} = makeStreamDom(303, {scrollTop: 199, scrollHeight: 500, clientHeight: 300});

  patchChatStreamMessage(container, 303, '继续', 'AI 教练 · 正在回答');

  assert.equal(container.scrollTop, 500);
  assert.equal(container.style.scrollBehavior, 'smooth');
});

test('a missing stream row reports false so the caller can perform a full initial render', () => {
  const container = {
    querySelectorAll: () => [],
    scrollTop: 0,
    scrollHeight: 100,
    clientHeight: 100,
  };

  assert.equal(patchChatStreamMessage(container, 404, '回答', 'AI 教练 · 正在回答'), false);
});
