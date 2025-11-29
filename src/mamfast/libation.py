"""Libation Docker wrapper for running audiobook scans."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from mamfast.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """Result of a Libation scan."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def success(self) -> bool:
        return self.returncode == 0


def run_scan(interactive: bool = False) -> ScanResult:
    """
    Run libationcli scan inside the Libation Docker container.

    Args:
        interactive: If True, use -it flags for interactive output.

    Returns:
        ScanResult with return code and output.
    """
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "exec",
    ]

    if interactive:
        cmd.extend(["-it"])

    cmd.extend([
        settings.libation_container,
        "/libation/LibationCli",  # Full path, proper case
        "scan",
    ])

    logger.info(f"Running Libation scan in container: {settings.libation_container}")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        if interactive:
            # Interactive mode - don't capture output
            result = subprocess.run(cmd, check=False, text=True)
            return ScanResult(
                returncode=result.returncode,
            )
        else:
            # Non-interactive - capture output
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            return ScanResult(
                returncode=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )

    except FileNotFoundError:
        logger.error(f"Docker binary not found: {settings.docker_bin}")
        return ScanResult(returncode=-1, stderr="Docker binary not found")

    except Exception as e:
        logger.exception(f"Error running Libation scan: {e}")
        return ScanResult(returncode=-1, stderr=str(e))


def run_liberate(asin: str | None = None) -> ScanResult:
    """
    Run liberate command to download and decrypt books.

    Args:
        asin: Optional specific ASIN to liberate. If None, liberates all.

    Returns:
        ScanResult with return code and output.
    """
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "exec",
        settings.libation_container,
        "/libation/LibationCli",
        "liberate",
    ]

    if asin:
        cmd.append(asin)

    logger.info("Running Libation liberate...")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return ScanResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    except Exception as e:
        logger.exception(f"Error running Libation liberate: {e}")
        return ScanResult(returncode=-1, stderr=str(e))


def check_container_running() -> bool:
    """Check if the Libation container is running."""
    settings = get_settings()

    cmd = [
        settings.docker_bin,
        "container",
        "inspect",
        "-f",
        "{{.State.Running}}",
        settings.libation_container,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    except Exception:
        return False
