from __future__ import annotations

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    os.chdir(root)

    port = int(os.getenv("IPOCAL_PORT", "8000"))
    url = f"http://127.0.0.1:{port}/"

    # Use the venv python if present; otherwise fallback to current python.
    venv_py = root / ".venv" / "Scripts" / "python.exe"
    py = str(venv_py) if venv_py.exists() else sys.executable

    # Start uvicorn as a child process.
    cmd = [
        py,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    # Avoid --reload in packaged EXE (it spawns extra processes).
    if os.getenv("IPOCAL_RELOAD", "0") == "1":
        cmd.append("--reload")

    proc = subprocess.Popen(cmd, cwd=str(root))

    # Give the server a moment, then open browser.
    time.sleep(0.8)
    webbrowser.open(url)

    # Wait until server exits.
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())

