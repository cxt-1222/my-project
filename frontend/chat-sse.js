(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else Object.assign(root, api);
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  async function consumeChatSse(response, {signal, isCurrent = () => true, onEvent = () => {}} = {}) {
    if (!response?.ok) throw new Error('AI 流式响应不可用');
    if (!response.body?.getReader) throw new Error('浏览器不支持读取 AI 流式响应');

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let completed = false;
    const abortReader = () => { void reader.cancel().catch(() => {}); };
    signal?.addEventListener('abort', abortReader, {once: true});

    const dispatchFrame = async frame => {
      if (!frame || !isCurrent()) return;
      let event = 'message';
      const dataLines = [];
      for (const line of frame.split(/\r?\n/)) {
        if (!line || line.startsWith(':')) continue;
        if (line.startsWith('event:')) event = line.slice(6).trim();
        else if (line.startsWith('data:')) {
          const value = line.slice(5);
          dataLines.push(value.startsWith(' ') ? value.slice(1) : value);
        }
      }
      if (!dataLines.length) return;

      let payload;
      try { payload = JSON.parse(dataLines.join('\n')); }
      catch { return; }

      await onEvent(event, payload);
      if (!isCurrent()) return;
      if (event === 'error') {
        try { await reader.cancel(payload.message || 'AI 生成失败'); } catch { /* response may already be closed */ }
        throw new Error(payload.message || 'AI 生成失败');
      }
      if (event === 'done') completed = true;
    };

    try {
      while (true) {
        if (signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
        const {value, done} = await reader.read();
        if (signal?.aborted) throw new DOMException('The operation was aborted', 'AbortError');
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        for (const frame of frames) await dispatchFrame(frame);
      }

      buffer += decoder.decode();
      if (buffer.trim()) await dispatchFrame(buffer);
      if (isCurrent() && !completed) throw new Error('AI 流式响应未正常结束');
      return completed;
    } finally {
      signal?.removeEventListener('abort', abortReader);
      try { reader.releaseLock(); } catch { /* reader may already be released */ }
    }
  }

  return {consumeChatSse};
});
