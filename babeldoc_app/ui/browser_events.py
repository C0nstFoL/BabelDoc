"""Ui browser events."""

from pathlib import Path

from .components import Components

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets"
CUSTOM_CSS = (ASSET_DIR / "style.css").read_text(encoding="utf-8")


def bind_browser_events(demo, ui: Components):
    demo.load(
        fn=None,
        inputs=[],
        outputs=[],
        js=(ASSET_DIR / "history_selection.js").read_text(encoding="utf-8"),
    )
    demo.load(
        fn=None,
        inputs=[],
        outputs=[],
        js=(ASSET_DIR / "theme_init.js").read_text(encoding="utf-8"),
    )
    ui.theme_toggle_btn.click(
        fn=None,
        inputs=[],
        outputs=[],
        js=(ASSET_DIR / "theme_toggle.js").read_text(encoding="utf-8"),
    )
