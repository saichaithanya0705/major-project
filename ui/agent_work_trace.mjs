const ROUTER_REPLY_SOURCE = 'rapid_response';
const MAX_TRACE_ENTRIES = 24;
const MAX_TRACE_TEXT_CHARS = 1400;
const VALID_TRACE_STATUSES = new Set(['idle', 'running', 'completed', 'failed']);

const SOURCE_LABELS = new Map([
  ['jarvis', 'JARVIS'],
  ['jarvis_completion', 'JARVIS'],
  ['browser', 'Browser'],
  ['browser_use', 'Browser'],
  ['cua_cli', 'CLI'],
  ['cua_vision', 'Computer'],
  ['screen_context', 'Screen'],
  ['screen_judge', 'Screen'],
]);

function truncateText(value, maxChars = MAX_TRACE_TEXT_CHARS) {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 3)).trimEnd()}...`;
}

function cloneEntry(entry) {
  return { ...entry };
}

function cloneState(state) {
  return {
    isOpen: state.isOpen,
    status: state.status,
    summary: state.summary,
    entries: state.entries.map(cloneEntry),
  };
}

export function normalizeAgentTraceSource(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function isAgentTraceSource(value) {
  const source = normalizeAgentTraceSource(value);
  if (!source || source === ROUTER_REPLY_SOURCE) return false;
  return SOURCE_LABELS.has(source);
}

export function getAgentTraceSourceLabel(value) {
  const source = normalizeAgentTraceSource(value);
  if (SOURCE_LABELS.has(source)) {
    return SOURCE_LABELS.get(source);
  }

  return source
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(' ') || 'Agent';
}

export function normalizeAgentTraceStatus(value) {
  const status = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return VALID_TRACE_STATUSES.has(status) ? status : 'completed';
}

export function normalizeAgentTraceSnapshot(trace) {
  if (!trace || typeof trace !== 'object') return null;

  const entries = Array.isArray(trace.entries)
    ? trace.entries
      .map((entry) => {
        if (!entry || typeof entry !== 'object') return null;
        const text = truncateText(entry.text);
        if (!text) return null;
        const source = normalizeAgentTraceSource(entry.source);
        const label = truncateText(entry.label, 48)
          || (source ? getAgentTraceSourceLabel(source) : 'Agent');
        const status = normalizeAgentTraceStatus(entry.status);
        return source ? { source, label, status, text } : { label, status, text };
      })
      .filter(Boolean)
      .slice(-MAX_TRACE_ENTRIES)
    : [];

  if (entries.length === 0) return null;

  const status = normalizeAgentTraceStatus(trace.status || entries[entries.length - 1]?.status);
  const summary = truncateText(trace.summary) || entries[entries.length - 1].text;

  return {
    isOpen: Boolean(trace.isOpen) && status !== 'completed',
    status,
    summary,
    entries,
  };
}

export function inferAgentTraceStatus(payload = {}) {
  const command = typeof payload.command === 'string' ? payload.command : '';
  const statusText = truncateText(`${payload.doneText || ''} ${payload.responseText || ''} ${payload.text || ''}`, 400)
    .toLowerCase();

  if (command === 'complete_status_bubble') {
    if (/\b(failed|failure|error|stopped|stopping|canceled|cancelled|interrupted)\b/.test(statusText)) {
      return 'failed';
    }
    return 'completed';
  }

  if (/\b(failed|failure|error)\b/.test(statusText)) {
    return 'failed';
  }

  return 'running';
}

export function getAgentTraceEventText(payload = {}) {
  if (payload.command === 'complete_status_bubble') {
    return truncateText(payload.responseText || payload.text || payload.doneText || '');
  }
  return truncateText(payload.text || payload.responseText || payload.doneText || '');
}

export function createAgentWorkTraceState() {
  const state = {
    isOpen: false,
    status: 'idle',
    summary: '',
    entries: [],
  };
  let nextId = 1;

  function reset() {
    state.isOpen = false;
    state.status = 'idle';
    state.summary = '';
    state.entries = [];
    nextId = 1;
    return cloneState(state);
  }

  function snapshot() {
    return cloneState(state);
  }

  function applyEvent(payload = {}) {
    if (!isAgentTraceSource(payload.source)) {
      return snapshot();
    }

    const text = getAgentTraceEventText(payload);
    if (!text) {
      return snapshot();
    }

    const status = inferAgentTraceStatus(payload);
    const source = normalizeAgentTraceSource(payload.source);
    const entry = {
      id: nextId,
      source,
      label: getAgentTraceSourceLabel(source),
      status,
      text,
    };
    nextId += 1;

    state.entries.push(entry);
    if (state.entries.length > MAX_TRACE_ENTRIES) {
      state.entries.splice(0, state.entries.length - MAX_TRACE_ENTRIES);
    }

    state.status = status;
    state.summary = text;
    state.isOpen = status !== 'completed';

    return snapshot();
  }

  return {
    applyEvent,
    reset,
    snapshot,
  };
}
