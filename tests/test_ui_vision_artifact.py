from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_chat_window_handles_vision_artifact_payload() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert "payload.command === 'chat_vision_artifact'" in input_window_js
    assert "appendVisionArtifactMessage" in input_window_js
    assert "chat-vision-artifact__image" in input_window_js
    assert "object-fit: contain" in input_window_css
    assert ".chat-msg--with-artifacts" in input_window_css


def test_chat_window_can_restore_after_hidden_vision_capture() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    preload_js = (ROOT_DIR / "ui" / "preload.js").read_text(encoding="utf-8")
    main_js = (ROOT_DIR / "ui" / "main.js").read_text(encoding="utf-8")
    server_py = (ROOT_DIR / "ui" / "server.py").read_text(encoding="utf-8")

    assert "payload.command === 'vision_capture_started'" in input_window_js
    assert "payload.command === 'vision_chat_restore'" in input_window_js
    assert "restoreVisionChatWindow" in input_window_js
    assert "showInputWindow" in preload_js
    assert "input-window-show-request" in main_js
    assert "vision_capture_started" in server_py
    assert "vision_chat_restore" in server_py


def test_vision_artifact_opens_full_image_viewer() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    input_window_css = (ROOT_DIR / "ui" / "input_window.css").read_text(encoding="utf-8")

    assert "openVisionArtifactViewer" in input_window_js
    assert "chat-vision-artifact__open" in input_window_js
    assert "chat-vision-viewer" in input_window_js
    assert ".chat-vision-viewer" in input_window_css
    assert ".chat-vision-viewer__image" in input_window_css
    assert "max-height: calc(100vh - 104px)" in input_window_css


def test_vision_artifact_prefers_native_image_viewer() -> None:
    input_window_js = (ROOT_DIR / "ui" / "input_window.js").read_text(encoding="utf-8")
    preload_js = (ROOT_DIR / "ui" / "preload.js").read_text(encoding="utf-8")
    main_js = (ROOT_DIR / "ui" / "main.js").read_text(encoding="utf-8")
    artifact_lifecycle_js = (ROOT_DIR / "ui" / "artifact_lifecycle.js").read_text(encoding="utf-8")

    assert "openVisionArtifactImage" in input_window_js
    assert "window.api?.openVisionArtifactImage" in input_window_js
    assert "open-vision-artifact-image" in preload_js
    assert "open-vision-artifact-image" in main_js
    assert "shell.openPath" in main_js
    assert "getVisionArtifactImageDir" in main_js
    assert "vision-artifact-images" in artifact_lifecycle_js


def test_jarvis_output_layer_hidden_for_now() -> None:
    renderer_js = (ROOT_DIR / "ui" / "renderer.js").read_text(encoding="utf-8")

    source_block = renderer_js.split("const OVERLAY_VISIBLE_SOURCES", 1)[1].split(";", 1)[0]
    assert "'jarvis'" not in source_block


def test_annotation_overlay_has_click_to_clear_affordance() -> None:
    renderer_js = (ROOT_DIR / "ui" / "renderer.js").read_text(encoding="utf-8")
    overlay_box_css = (ROOT_DIR / "ui" / "animations" / "overlay_box.css").read_text(encoding="utf-8")
    server_py = (ROOT_DIR / "ui" / "server.py").read_text(encoding="utf-8")
    app_py = (ROOT_DIR / "app.py").read_text(encoding="utf-8")
    main_js = (ROOT_DIR / "ui" / "main.js").read_text(encoding="utf-8")

    assert "ensureAnnotationDismissButton" in renderer_js
    assert "clear_annotations" in renderer_js
    assert ".annotation-dismiss" in overlay_box_css
    assert "on_clear_annotations" in server_py
    assert "on_clear_annotations=clear_annotation_actions" in app_py
    assert "setOverlayWindowInteractive" in main_js
    assert "setIgnoreMouseEvents(!interactive" in main_js
