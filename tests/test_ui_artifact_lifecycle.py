import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent


def _run_artifact_lifecycle_eval(artifact_dir: Path, body: str):
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to validate ui/artifact_lifecycle.js")

    script = (
        "const fs = require('fs');\n"
        "const path = require('path');\n"
        "const { cleanupVisionArtifactImages } = require(path.join(process.cwd(), 'ui', 'artifact_lifecycle.js'));\n"
        "const artifactDir = process.env.ARTIFACT_DIR;\n"
        f"{body}\n"
    )
    env = os.environ.copy()
    env["ARTIFACT_DIR"] = str(artifact_dir)
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT_DIR),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.strip() or "null")


def test_cleanup_vision_artifact_images_deletes_only_old_png_files(tmp_path: Path) -> None:
    result = _run_artifact_lifecycle_eval(
        tmp_path,
        (
            "fs.mkdirSync(artifactDir, { recursive: true });\n"
            "const now = Date.UTC(2026, 4, 6, 0, 0, 0);\n"
            "function writeFile(name, ageMs) {\n"
            "  const filePath = path.join(artifactDir, name);\n"
            "  fs.writeFileSync(filePath, 'generated');\n"
            "  const date = new Date(now - ageMs);\n"
            "  fs.utimesSync(filePath, date, date);\n"
            "}\n"
            "writeFile('vision-artifact-old.png', 25 * 60 * 60 * 1000);\n"
            "writeFile('vision-artifact-recent.png', 60 * 60 * 1000);\n"
            "writeFile('vision-artifact-old.txt', 25 * 60 * 60 * 1000);\n"
            "const report = cleanupVisionArtifactImages(artifactDir, { now });\n"
            "process.stdout.write(JSON.stringify({\n"
            "  deleted: report.deleted.map((item) => path.basename(item)),\n"
            "  oldPngExists: fs.existsSync(path.join(artifactDir, 'vision-artifact-old.png')),\n"
            "  recentPngExists: fs.existsSync(path.join(artifactDir, 'vision-artifact-recent.png')),\n"
            "  oldTextExists: fs.existsSync(path.join(artifactDir, 'vision-artifact-old.txt')),\n"
            "}));"
        ),
    )

    assert result["oldPngExists"] is False
    assert result["recentPngExists"] is True
    assert result["oldTextExists"] is True
    assert result["deleted"] == ["vision-artifact-old.png"]


def test_cleanup_vision_artifact_images_tolerates_missing_directory(tmp_path: Path) -> None:
    result = _run_artifact_lifecycle_eval(
        tmp_path / "missing",
        (
            "const report = cleanupVisionArtifactImages(artifactDir);\n"
            "process.stdout.write(JSON.stringify(report));"
        ),
    )

    assert result == {"deleted": [], "skipped": [], "errors": []}
