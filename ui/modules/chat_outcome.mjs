import { EXECUTION_PHASES } from './status_lifecycle.js';

const FAILURE_PATTERN = /\b(failed|failure|error|needs attention|unable|unavailable|quota|resource_exhausted|exhausted|rate limit|429)\b/;
const STOPPED_PATTERN = /\b(stopped|stopping|stop requested|interrupted|cancelled|canceled)\b/;

function normalizeText(value) {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
}

function truncateText(value, maxChars = 180) {
  const text = normalizeText(value);
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(0, maxChars - 3)).trimEnd()}...`;
}

function normalizeStatus(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function getAssistantLifecycleOutcome({ text = '', agentTrace = null } = {}) {
  const message = normalizeText(text);
  const lowered = message.toLowerCase();
  const traceStatus = normalizeStatus(agentTrace?.status);
  const traceSummary = truncateText(agentTrace?.summary || '');

  if (traceStatus === 'failed' || FAILURE_PATTERN.test(lowered)) {
    return {
      phase: EXECUTION_PHASES.STOPPED,
      text: 'Needs attention',
      detail: traceSummary
        ? `Agent work failed: ${traceSummary}`
        : 'An agent step failed before the task completed.',
    };
  }

  if (STOPPED_PATTERN.test(lowered)) {
    return {
      phase: EXECUTION_PHASES.STOPPED,
      text: 'Stopped',
      detail: 'Running work was interrupted before completion.',
    };
  }

  return {
    phase: EXECUTION_PHASES.COMPLETED,
    text: 'Completed',
    detail: message ? 'Latest response is ready.' : 'The latest action finished successfully.',
  };
}
