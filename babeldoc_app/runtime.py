"""Dependency checks shared by native startup and Docker image validation."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys


REQUIREMENTS_FILE = Path(__file__).resolve().parent.parent / "requirements.txt"


def require_runtime():
    """Reject stale environments before importing or constructing the Web UI."""
    problems = []
    for line in REQUIREMENTS_FILE.read_text(encoding="utf-8").splitlines():
        requirement = line.split("#", 1)[0].strip()
        if not requirement or requirement.startswith("-"):
            continue
        name, expected = requirement.split("==", 1)
        try:
            actual = version(name)
        except PackageNotFoundError:
            actual = "not installed"
        if actual != expected:
            problems.append(f"{name}: installed {actual}, required {expected}")
    if problems:
        raise SystemExit(
            "Incompatible Python dependencies:\n  "
            + "\n  ".join(problems)
            + "\nGradio 4.44 is not supported by this UI."
            + '\nRepair this interpreter: "'
            + sys.executable
            + '" -m pip install --upgrade -r "'
            + str(REQUIREMENTS_FILE)
            + '"\nOn Windows, run start.bat restart to repair the project environment.'
        )


def main():
    """Exercise dependency APIs and the real layout, beyond import-only checks."""
    require_runtime()
    from bitstring import BitStream
    from babeldoc.format.pdf.high_level import async_translate
    import ocrmypdf

    from .ui.app import build_ui

    assert BitStream("0xff").read("uint:8") == 255
    assert callable(async_translate)
    assert callable(ocrmypdf.ocr)
    demo = build_ui()
    demo.close()
    print("Runtime check passed: pinned dependencies, translation/OCR APIs and Web UI.")


if __name__ == "__main__":
    main()
