const DEFAULT_GENERATING_PHRASES = [
  'Thinking',
  'Understanding the request',
  'Choosing the right agent',
  'Preparing the response',
  'Writing the answer',
];

const GENERIC_STATUS_LABELS = new Set([
  'capturing screen',
  'waiting for model response',
  'generating response',
  'thinking',
  'working',
]);

const GENERATING_PLACEHOLDERS = new Set([
  ...DEFAULT_GENERATING_PHRASES.map((phrase) => phrase.toLowerCase()),
  'waiting for model response',
  'capturing screen',
  'generating response',
]);

export const GENERATING_DOT_COUNT = 3;
export const GENERATING_PHRASE_INTERVAL_MS = 1500;

function normalizeStatusText(value) {
  return typeof value === 'string'
    ? value.replace(/[.。…]+$/u, '').replace(/\s+/g, ' ').trim()
    : '';
}

function phraseForStatus(statusText) {
  const text = normalizeStatusText(statusText);
  const lowered = text.toLowerCase();
  if (!text) return '';
  if (lowered.includes('routing')) return 'Choosing the right agent';
  if (lowered.includes('checking') || lowered.includes('verifying')) return 'Checking result';
  if (lowered.includes('terminal') || lowered.includes('cli')) return 'Working in terminal';
  if (lowered.includes('browser')) return 'Working in browser';
  if (lowered.includes('desktop') || lowered.includes('screen')) return 'Reading the screen';
  if (GENERIC_STATUS_LABELS.has(lowered)) return '';
  return text;
}

export function buildGeneratingIndicatorView(options = {}) {
  const elapsedMs = Math.max(0, Number(options.elapsedMs) || 0);
  const statusPhrase = phraseForStatus(options.statusText);
  const phraseIndex = Math.floor(elapsedMs / GENERATING_PHRASE_INTERVAL_MS) % DEFAULT_GENERATING_PHRASES.length;
  const label = statusPhrase || DEFAULT_GENERATING_PHRASES[phraseIndex];

  return {
    label,
    dotCount: GENERATING_DOT_COUNT,
    ariaLabel: `${label}...`,
  };
}

export function isGeneratingPlaceholderText(value) {
  const normalized = normalizeStatusText(value).toLowerCase();
  return Boolean(normalized && GENERATING_PLACEHOLDERS.has(normalized));
}
