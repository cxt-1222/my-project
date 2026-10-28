(function (root, factory) {
  const createChatStreamRegistry = factory();
  if (typeof module === 'object' && module.exports) module.exports = {createChatStreamRegistry};
  else root.createChatStreamRegistry = createChatStreamRegistry;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  return function createChatStreamRegistry() {
    const records = new Map();
    const generations = new Map();

    function keyOf(sessionId) {
      return String(sessionId);
    }

    function isCurrent(record, accountGeneration) {
      return Boolean(record)
        && records.get(keyOf(record.sessionId)) === record
        && generations.get(keyOf(record.sessionId)) === record.requestGeneration
        && record.accountGeneration === accountGeneration;
    }

    function reserve(sessionId, {controller, accountGeneration, ownerKey, userMessage, startedAtMs} = {}) {
      const key = keyOf(sessionId);
      const previous = records.get(key);
      if (previous?.status === 'streaming') return null;

      const requestGeneration = (generations.get(key) || 0) + 1;
      generations.set(key, requestGeneration);
      const record = {
        sessionId,
        requestGeneration,
        accountGeneration,
        ownerKey,
        controller,
        userMessage,
        startedAtMs: startedAtMs ?? Date.now(),
        status: 'streaming',
        answer: '',
        sources: [],
        error: null,
      };
      records.set(key, record);
      return record;
    }

    function update(record, accountGeneration, updater) {
      if (!isCurrent(record, accountGeneration) || record.status !== 'streaming') return false;
      updater(record);
      return true;
    }

    function recoverInterrupted(sessionId, messages, {accountGeneration, ownerKey} = {}) {
      let existing = records.get(keyOf(sessionId)) || null;
      if (existing?.interrupted) {
        let userIndex = -1;
        for (let index = messages.length - 1; index >= 0; index -= 1) {
          if (messages[index]?.type === 'user' && messages[index].text === existing.userMessage?.text) {
            userIndex = index;
            break;
          }
        }
        const answerWasPersisted = userIndex >= 0
          && messages.slice(userIndex + 1).some(message => message.type === 'assistant');
        if (answerWasPersisted) {
          records.delete(keyOf(sessionId));
          generations.delete(keyOf(sessionId));
          existing = null;
        }
      }
      if (existing) return existing;

      const lastMessage = messages[messages.length - 1];
      if (lastMessage?.type !== 'user') return null;
      const record = reserve(sessionId, {
        controller: new AbortController(),
        accountGeneration,
        ownerKey,
        userMessage: lastMessage,
      });
      if (!record) return null;
      update(record, accountGeneration, current => {
        current.status = 'failed';
        current.interrupted = true;
        current.error = '上条问题目前没有已保存的回答；可能仍在其他窗口生成，或上次连接中断。确认没有其他窗口后可继续提问。';
      });
      return record;
    }

    return {
      reserve,
      recoverInterrupted,
      get: sessionId => records.get(keyOf(sessionId)) || null,
      isCurrent,
      isStreaming: sessionId => records.get(keyOf(sessionId))?.status === 'streaming',
      appendDelta: (record, accountGeneration, text) => update(record, accountGeneration, current => { current.answer += text; }),
      setSources: (record, accountGeneration, sources) => update(record, accountGeneration, current => { current.sources = Array.isArray(sources) ? sources : []; }),
      finish: (record, accountGeneration) => update(record, accountGeneration, current => { current.status = 'succeeded'; }),
      setAssistant: (record, accountGeneration, message) => update(record, accountGeneration, current => { current.assistantMessage = message; }),
      fail: (record, accountGeneration, error) => update(record, accountGeneration, current => {
        current.status = 'failed';
        current.error = error || 'AI 回答失败';
      }),
      cancel: sessionId => {
        const key = keyOf(sessionId);
        const record = records.get(key);
        if (!record) return false;
        if (record.status === 'streaming') {
          record.status = 'cancelled';
          record.controller?.abort();
        }
        records.delete(key);
        generations.delete(key);
        return true;
      },
      cancelAll: () => {
        for (const record of records.values()) {
          if (record.status === 'streaming') {
            record.status = 'cancelled';
            record.controller?.abort();
          }
        }
        records.clear();
        generations.clear();
      },
      delete: sessionId => {
        const key = keyOf(sessionId);
        const record = records.get(key);
        if (record?.status === 'streaming') return false;
        if (record) {
          records.delete(key);
          generations.delete(key);
        }
        return true;
      },
    };
  };
});
