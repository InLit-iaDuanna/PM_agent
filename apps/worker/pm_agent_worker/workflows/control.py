from __future__ import annotations

from typing import Any, Dict, List, Optional


class JobCancelledError(RuntimeError):
    def __init__(
        self,
        message: str = "研究任务已取消。",
        *,
        partial_evidence: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.partial_evidence = list(partial_evidence or [])
