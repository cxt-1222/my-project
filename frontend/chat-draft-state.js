(function (root, factory) {
  const createChatDraftRegistry = factory();
  if (typeof module === 'object' && module.exports) module.exports = {createChatDraftRegistry};
  else root.createChatDraftRegistry = createChatDraftRegistry;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  return function createChatDraftRegistry() {
    const drafts = new Map();
    const keyOf = sessionId => sessionId == null ? '__unassigned__' : String(sessionId);

    return {
      get: sessionId => drafts.get(keyOf(sessionId)) || '',
      set: (sessionId, value) => drafts.set(keyOf(sessionId), String(value ?? '')),
      delete: sessionId => drafts.delete(keyOf(sessionId)),
      clear: () => drafts.clear(),
      move(fromSessionId, toSessionId) {
        const draft = drafts.get(keyOf(fromSessionId)) || '';
        drafts.delete(keyOf(fromSessionId));
        drafts.set(keyOf(toSessionId), draft);
        return draft;
      },
    };
  };
});
