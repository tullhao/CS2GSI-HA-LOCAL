"""Startet CS2 Local Claude aus dem Quellcode. Für die EXE verpackt PyInstaller genau diese Datei."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from cs2local.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
