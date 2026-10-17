"""Identify the source checkout used by a running service."""

import logging
import subprocess
from pathlib import Path


def log_startup(service: str) -> None:
    root = Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root}",
                "-C",
                str(root),
                "rev-parse",
                "--short=12",
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        )
        commit = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.info("startup service=%s commit=%s source=%s", service, commit, root / "src")
