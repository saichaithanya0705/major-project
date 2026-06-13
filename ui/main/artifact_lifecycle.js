const fs = require('fs');
const path = require('path');

const VISION_ARTIFACT_IMAGE_DIR = 'vision-artifact-images';
const VISION_ARTIFACT_IMAGE_TTL_MS = 24 * 60 * 60 * 1000;

function cleanupVisionArtifactImages(directory, options = {}) {
  const now = Number.isFinite(options.now) ? options.now : Date.now();
  const maxAgeMs = Number.isFinite(options.maxAgeMs) ? options.maxAgeMs : VISION_ARTIFACT_IMAGE_TTL_MS;
  const report = { deleted: [], skipped: [], errors: [] };

  let entries = [];
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch (error) {
    if (error && error.code !== 'ENOENT') {
      report.errors.push(`${directory}: ${error.message || error}`);
    }
    return report;
  }

  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith('.png')) {
      continue;
    }

    const filePath = path.join(directory, entry.name);
    try {
      const stats = fs.statSync(filePath);
      if (now - stats.mtimeMs > maxAgeMs) {
        fs.unlinkSync(filePath);
        report.deleted.push(filePath);
      }
    } catch (error) {
      report.errors.push(`${filePath}: ${error.message || error}`);
    }
  }

  return report;
}

function getVisionArtifactImageDir(app) {
  return path.join(app.getPath('temp'), 'jarvis', VISION_ARTIFACT_IMAGE_DIR);
}

module.exports = {
  VISION_ARTIFACT_IMAGE_DIR,
  VISION_ARTIFACT_IMAGE_TTL_MS,
  cleanupVisionArtifactImages,
  getVisionArtifactImageDir,
};
