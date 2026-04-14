import sys
from pathlib import Path


def ensure_repo_paths() -> Path:
    root = Path(__file__).resolve().parents[4]
    worker_src = root / "apps" / "worker"
    if str(worker_src) not in sys.path:
        sys.path.insert(0, str(worker_src))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root

