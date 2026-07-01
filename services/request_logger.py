"""Request logging for Telegram API calls."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RequestLogger:
    """
    Logs every Telegram API request to JSONL file.

    Features:
    - Automatic date-based file rotation
    - Structured JSON logging
    - Tracks request timing, success/failure, flood waits
    """

    def __init__(self, log_dir: str = "logs", prefix: str = "requests"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self._file = None
        self._current_date = None

    def _get_file(self):
        """Get or create log file for current date."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._current_date != today or self._file is None:
            if self._file:
                self._file.close()
            self._current_date = today
            filepath = self.log_dir / f"{self.prefix}_{today}.jsonl"
            self._file = open(filepath, "a", encoding="utf-8")
            logger.debug(f"Request log file: {filepath}")
        return self._file

    def log(
        self,
        account: str,
        method: str,
        channel: str,
        success: bool,
        duration_ms: int,
        request_num: int,
        error: Optional[str] = None,
        wait_seconds: Optional[int] = None,
        extra: Optional[dict] = None,
    ):
        """
        Log a single API request.

        Args:
            account: Account username or ID
            method: API method name (e.g., "get_entity", "GetFullChannel")
            channel: Target channel username
            success: Whether the request succeeded
            duration_ms: Request duration in milliseconds
            request_num: Sequential request number in session
            error: Error type if failed
            wait_seconds: FloodWait seconds if applicable
            extra: Additional data to log
        """
        entry = {
            "ts": datetime.now().isoformat(),
            "account": account,
            "method": method,
            "channel": channel,
            "success": success,
            "duration_ms": duration_ms,
            "request_num": request_num,
        }
        if error:
            entry["error"] = error
        if wait_seconds is not None:
            entry["wait_seconds"] = wait_seconds
        if extra:
            entry.update(extra)

        f = self._get_file()
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()

    def close(self):
        """Close log file."""
        if self._file:
            self._file.close()
            self._file = None
            self._current_date = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
