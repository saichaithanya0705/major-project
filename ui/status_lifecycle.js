export const EXECUTION_PHASES = Object.freeze({
  IDLE: 'idle',
  PREPARING: 'preparing',
  ROUTING: 'routing',
  RUNNING: 'running',
  COMPLETED: 'completed',
  STOPPED: 'stopped',
  RECONNECTING: 'reconnecting',
});

const PHASE_META = {
  [EXECUTION_PHASES.IDLE]: {
    label: 'Idle',
    text: 'Ready for command',
    detail: 'Type the next task below or reopen a prior session from History.',
    theme: {
      phase: EXECUTION_PHASES.IDLE,
      icon: 'check',
      statusBg: 'rgba(17, 20, 24, 0.98)',
      statusBorder: 'rgba(124, 136, 150, 0.26)',
      statusText: 'rgba(240, 244, 248, 0.96)',
      statusShimmer: 'rgba(160, 169, 180, 0.46)',
      statusCheck: 'rgba(160, 169, 180, 0.86)',
    },
  },
  [EXECUTION_PHASES.PREPARING]: {
    label: 'Preparing',
    text: 'Capturing screen…',
    detail: 'Collecting the current workspace before the next action.',
    theme: {
      phase: EXECUTION_PHASES.PREPARING,
      icon: 'check',
      statusBg: 'rgba(24, 20, 14, 0.98)',
      statusBorder: 'rgba(184, 142, 78, 0.3)',
      statusText: 'rgba(248, 240, 227, 0.97)',
      statusShimmer: 'rgba(212, 171, 100, 0.56)',
      statusCheck: 'rgba(212, 171, 100, 0.92)',
    },
  },
  [EXECUTION_PHASES.ROUTING]: {
    label: 'Routing',
    text: 'Routing request…',
    detail: 'Choosing the next tool path and waiting on the model.',
    theme: {
      phase: EXECUTION_PHASES.ROUTING,
      icon: 'check',
      statusBg: 'rgba(20, 23, 29, 0.98)',
      statusBorder: 'rgba(116, 136, 160, 0.28)',
      statusText: 'rgba(238, 242, 247, 0.97)',
      statusShimmer: 'rgba(146, 166, 190, 0.54)',
      statusCheck: 'rgba(146, 166, 190, 0.88)',
    },
  },
  [EXECUTION_PHASES.RUNNING]: {
    label: 'Running',
    text: 'Running desktop action…',
    detail: 'JARVIS is executing the requested steps.',
    theme: {
      phase: EXECUTION_PHASES.RUNNING,
      icon: 'check',
      statusBg: 'rgba(18, 22, 20, 0.98)',
      statusBorder: 'rgba(106, 146, 124, 0.3)',
      statusText: 'rgba(239, 244, 241, 0.97)',
      statusShimmer: 'rgba(128, 171, 148, 0.56)',
      statusCheck: 'rgba(128, 171, 148, 0.9)',
    },
  },
  [EXECUTION_PHASES.COMPLETED]: {
    label: 'Completed',
    text: 'Completed',
    detail: 'The latest action finished successfully.',
    theme: {
      phase: EXECUTION_PHASES.COMPLETED,
      icon: 'check',
      statusBg: 'rgba(18, 24, 20, 0.98)',
      statusBorder: 'rgba(92, 146, 112, 0.3)',
      statusText: 'rgba(241, 247, 243, 0.97)',
      statusShimmer: 'rgba(122, 177, 143, 0.5)',
      statusCheck: 'rgba(122, 177, 143, 0.9)',
    },
  },
  [EXECUTION_PHASES.STOPPED]: {
    label: 'Stopped',
    text: 'Stopped',
    detail: 'All running actions were interrupted.',
    theme: {
      phase: EXECUTION_PHASES.STOPPED,
      icon: 'stop',
      statusBg: 'rgba(42, 18, 18, 0.98)',
      statusBorder: 'rgba(201, 100, 100, 0.32)',
      statusText: 'rgba(255, 238, 238, 0.98)',
      statusShimmer: 'rgba(227, 125, 125, 0.56)',
      statusCheck: 'rgba(227, 125, 125, 0.9)',
    },
  },
  [EXECUTION_PHASES.RECONNECTING]: {
    label: 'Reconnecting',
    text: 'Reconnect in progress…',
    detail: 'Trying to restore the live session.',
    theme: {
      phase: EXECUTION_PHASES.RECONNECTING,
      icon: 'check',
      statusBg: 'rgba(26, 21, 14, 0.98)',
      statusBorder: 'rgba(192, 148, 78, 0.3)',
      statusText: 'rgba(250, 241, 226, 0.97)',
      statusShimmer: 'rgba(214, 169, 94, 0.54)',
      statusCheck: 'rgba(214, 169, 94, 0.9)',
    },
  },
};

function hasKeyword(text, keywords) {
  return keywords.some((keyword) => text.includes(keyword));
}

function normalizeText(value) {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

export function mergeLifecycleTheme(baseTheme = {}, overrideTheme = {}) {
  return { ...baseTheme, ...overrideTheme };
}

export function getShortcutLabels(platform = 'win32') {
  const isMac = platform === 'darwin';
  return {
    open: isMac ? 'Cmd + Shift + Space' : 'Ctrl + Shift + Space',
    stop: isMac ? 'Cmd + Shift + C' : 'Ctrl + Shift + C',
    hide: 'Esc',
  };
}

export function getCompactShortcutSummary(platform = 'win32') {
  const shortcuts = getShortcutLabels(platform);
  return `Open ${shortcuts.open} · Stop ${shortcuts.stop} · Hide ${shortcuts.hide}`;
}

export function buildLifecycleSnapshot(phase, overrides = {}) {
  const meta = PHASE_META[phase] || PHASE_META[EXECUTION_PHASES.IDLE];
  return {
    phase,
    label: overrides.label || meta.label,
    text: overrides.text || meta.text,
    detail: overrides.detail ?? meta.detail,
    theme: mergeLifecycleTheme(meta.theme, overrides.theme || {}),
  };
}

function inferRunningText(text, source) {
  if (hasKeyword(text, ['browser', 'navigate', 'page', 'tab', 'url', 'dom'])) {
    return 'Running browser action…';
  }
  if (hasKeyword(text, ['terminal', 'shell', 'command', 'cli', 'stdout', 'stderr'])) {
    return 'Running terminal action…';
  }
  if (hasKeyword(text, ['desktop', 'window', 'screen', 'mouse', 'keyboard', 'cursor', 'click', 'drag', 'type'])) {
    return 'Running desktop action…';
  }

  if (source === 'browser') {
    return 'Running browser action…';
  }
  if (source === 'cua_cli') {
    return 'Running terminal action…';
  }
  return 'Running desktop action…';
}

export function inferLifecycleSnapshot(rawText, options = {}) {
  const normalizedText = normalizeText(rawText);
  const source = normalizeText(options.source);
  const fallbackPhase = options.phaseHint || EXECUTION_PHASES.IDLE;

  if (!normalizedText) {
    return buildLifecycleSnapshot(fallbackPhase, options.overrides || {});
  }

  if (normalizedText === 'ready' || normalizedText === 'connected') {
    return buildLifecycleSnapshot(EXECUTION_PHASES.IDLE, {
      text: 'Ready for command',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['reconnect', 'connecting', 'connection lost', 'socket closed'])) {
    return buildLifecycleSnapshot(EXECUTION_PHASES.RECONNECTING, {
      text: 'Reconnect in progress…',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['stopped', 'stop requested', 'interrupted', 'cancelled', 'canceled'])) {
    return buildLifecycleSnapshot(EXECUTION_PHASES.STOPPED, {
      text: 'Stopped',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['completed', 'finished', 'task done', 'chat archived'])) {
    return buildLifecycleSnapshot(EXECUTION_PHASES.COMPLETED, {
      text: 'Completed',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['capturing', 'screenshot', 'loading chat', 'restoring session', 'creating new chat', 'archiving chat'])) {
    return buildLifecycleSnapshot(EXECUTION_PHASES.PREPARING, {
      text: hasKeyword(normalizedText, ['loading chat', 'restoring session'])
        ? 'Restoring session…'
        : hasKeyword(normalizedText, ['creating new chat'])
          ? 'Creating new chat…'
          : hasKeyword(normalizedText, ['archiving chat'])
            ? 'Archiving chat…'
            : 'Capturing screen…',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['routing', 'planning', 'thinking', 'waiting for model', 'model response', 'analyzing'])) {
    return buildLifecycleSnapshot(EXECUTION_PHASES.ROUTING, {
      text: hasKeyword(normalizedText, ['thinking', 'waiting for model'])
        ? 'Waiting for model response…'
        : 'Routing request…',
      detail: options.detail,
      theme: options.theme,
    });
  }

  if (hasKeyword(normalizedText, ['running', 'opening', 'navigating', 'processing output', 'command completed', 'command failed', 'cli session', 'terminal session'])) {
    return buildLifecycleSnapshot(
      hasKeyword(normalizedText, ['command failed']) ? EXECUTION_PHASES.STOPPED : EXECUTION_PHASES.RUNNING,
      {
        text: hasKeyword(normalizedText, ['command failed'])
          ? 'Terminal command failed'
          : inferRunningText(normalizedText, source),
        detail: options.detail,
        theme: options.theme,
      },
    );
  }

  return buildLifecycleSnapshot(fallbackPhase, {
    text: rawText,
    detail: options.detail,
    theme: options.theme,
  });
}
