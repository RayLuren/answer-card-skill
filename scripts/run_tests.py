from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import os
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    basetemp = Path(tempfile.gettempdir()) / f"answer-card-skill-pytest-{uuid4().hex}"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--basetemp",
        str(basetemp),
        "-p",
        "no:cacheprovider",
    ]

    returncode = 1
    cleanup_error: OSError | None = None
    try:
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src") + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )
        environment["PYTHONUTF8"] = "1"
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False, env=environment)
        returncode = result.returncode
    finally:
        try:
            shutil.rmtree(basetemp)
        except FileNotFoundError:
            pass
        except OSError as exc:
            cleanup_error = exc

    if cleanup_error is not None:
        print(
            f"error: pytest temporary directory could not be removed: {basetemp}: "
            f"{cleanup_error}",
            file=sys.stderr,
        )
        return 1
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
