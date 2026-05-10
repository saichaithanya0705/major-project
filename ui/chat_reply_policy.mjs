const CHAT_REPLY_SOURCES = new Set(['rapid_response']);

export function normalizeAgentSource(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function shouldDisplayReplyInChat(payload) {
  const source = normalizeAgentSource(payload?.source);
  if (!source) return true;
  return CHAT_REPLY_SOURCES.has(source);
}
