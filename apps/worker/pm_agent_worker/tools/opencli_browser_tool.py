import os
import shlex
import shutil
import subprocess
from typing import Dict, List, Optional

from pm_agent_worker.tools.env_loader import load_local_env


load_local_env()


class OpenCliBrowserTool:
    def __init__(self) -> None:
        self.command_parts = self._resolve_command()
        self.command = " ".join(self.command_parts) if self.command_parts else None

    def _resolve_explicit_command(self, command: str) -> Optional[List[str]]:
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
        if not parts:
            return None

        binary = parts[0]
        if os.path.isabs(binary):
            if os.path.isfile(binary) and os.access(binary, os.X_OK):
                return [binary] + parts[1:]
            return None

        resolved = shutil.which(binary)
        if not resolved:
            return None
        return [resolved] + parts[1:]

    def _resolve_command(self) -> Optional[List[str]]:
        configured_command = os.getenv("OPENCLI_COMMAND", "").strip()
        if configured_command:
            resolved = self._resolve_explicit_command(configured_command)
            if resolved:
                return resolved

        candidate_binaries = [
            shutil.which("opencli"),
            "/opt/homebrew/bin/opencli",
            "/usr/local/bin/opencli",
            os.path.expanduser("~/.local/bin/opencli"),
            os.path.expanduser("~/bin/opencli"),
            shutil.which("open"),
            shutil.which("xdg-open"),
        ]
        for candidate in candidate_binaries:
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return [candidate]
        return None

    def is_available(self) -> bool:
        return self.command_parts is not None

    def mode(self) -> str:
        if not self.command_parts:
            return "unavailable"
        binary_name = os.path.basename(self.command_parts[0])
        if binary_name == "opencli":
            return "opencli"
        if binary_name == "open":
            return "mac-open"
        return "xdg-open"

    def open(self, url: str) -> Dict[str, str]:
        if not self.command_parts:
            return {
                "status": "degraded",
                "reason": "opencli is unavailable; static fetch should be used instead.",
                "url": url,
                "mode": self.mode(),
                "command": "",
            }
        try:
            subprocess.Popen([*self.command_parts, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            return {
                "status": "error",
                "reason": str(error),
                "url": url,
                "command": self.command or "",
                "mode": self.mode(),
            }
        return {"status": "ready", "url": url, "command": self.command, "mode": self.mode()}
