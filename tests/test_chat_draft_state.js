const assert = require('node:assert/strict');
const test = require('node:test');

const {createChatDraftRegistry} = require('../frontend/chat-draft-state.js');

test('drafts stay with their session when switching and creating another session', () => {
  const drafts = createChatDraftRegistry();
  drafts.set(101, '问题只属于会话 A');

  assert.equal(drafts.get(101), '问题只属于会话 A');
  assert.equal(drafts.get(202), '');

  drafts.set(202, '问题只属于会话 B');
  assert.equal(drafts.get(101), '问题只属于会话 A');
  assert.equal(drafts.get(202), '问题只属于会话 B');
});

test('an unassigned first draft moves into the first created session only', () => {
  const drafts = createChatDraftRegistry();
  drafts.set(null, '首次提问草稿');

  assert.equal(drafts.move(null, 101), '首次提问草稿');
  assert.equal(drafts.get(101), '首次提问草稿');
  assert.equal(drafts.get(null), '');

  drafts.set(202, '');
  assert.equal(drafts.get(202), '');
  assert.equal(drafts.get(101), '首次提问草稿');
});
