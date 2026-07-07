function isBrokenPipeError(error) {
  return Boolean(
    error
      && typeof error === 'object'
      && (
        error.code === 'EPIPE'
        || error.errno === 'EPIPE'
        || String(error.message || '').includes('EPIPE')
        || String(error.message || '').includes('broken pipe')
      )
  );
}

function createSafeLogger(target = console) {
  let outputBroken = false;

  function write(method, args) {
    if (outputBroken) {
      return false;
    }

    const writer = target && typeof target[method] === 'function'
      ? target[method]
      : target?.log;
    if (typeof writer !== 'function') {
      return false;
    }

    try {
      writer.apply(target, args);
      return true;
    } catch (error) {
      if (isBrokenPipeError(error)) {
        outputBroken = true;
        return false;
      }
      throw error;
    }
  }

  return {
    log: (...args) => write('log', args),
    warn: (...args) => write('warn', args),
    error: (...args) => write('error', args),
    isOutputBroken: () => outputBroken,
  };
}

module.exports = {
  createSafeLogger,
  isBrokenPipeError,
};
