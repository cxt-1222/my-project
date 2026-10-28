(function (root, factory) {
  const patchChatStreamMessage = factory();
  if (typeof module === 'object' && module.exports) module.exports = {patchChatStreamMessage};
  else root.patchChatStreamMessage = patchChatStreamMessage;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  return function patchChatStreamMessage(container, sessionId, answerText, statusText) {
    const node = Array.from(container.querySelectorAll('[data-stream-session]'))
      .find(item => String(item.dataset.streamSession) === String(sessionId));
    if (!node) return false;

    const shouldStickToBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 48;
    const bubble = node.querySelector('.message-bubble');
    const meta = node.querySelector('.message-meta');
    if (bubble && answerText) {
      bubble.classList.add('is-streaming');
      const textNode = Array.from(bubble.childNodes).find(child => child.nodeType === 3);
      if (textNode) {
        if (textNode.nodeValue !== answerText) textNode.nodeValue = answerText;
      } else bubble.textContent = answerText;
    }
    if (meta && meta.textContent !== statusText) meta.textContent = statusText;

    if (shouldStickToBottom) {
      const previousBehavior = container.style.scrollBehavior;
      container.style.scrollBehavior = 'auto';
      container.scrollTop = container.scrollHeight;
      container.style.scrollBehavior = previousBehavior;
    }
    return true;
  };
});
