"""Compatibility entry point for the modular BabelDOC application."""

import sys


def main():
    if sys.argv[1:] == ["--translation-worker"]:
        # The child imports only the execution layer, avoiding Web UI construction.
        from babeldoc_app.engine import _translation_child_main

        _translation_child_main()
    else:
        from babeldoc_app.server import main as serve

        serve()


if __name__ == "__main__":
    main()
