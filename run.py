"""Launcher for source checkouts and portable installs. No system packages required."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

if __name__ == "__main__":
    from app.server import main
    main()
