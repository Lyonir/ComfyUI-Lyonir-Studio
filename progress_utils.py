from __future__ import annotations

try:
    from comfy.utils import ProgressBar
except Exception:  # pragma: no cover - allows source inspection outside ComfyUI
    ProgressBar = None

PROGRESS_TOTAL = 100


def make_progress(total: int = PROGRESS_TOTAL):
    return ProgressBar(int(total)) if ProgressBar is not None else None


def update_progress(pbar, value: float, total: int = PROGRESS_TOTAL):
    """Best-effort ComfyUI progress update. Progress UI must never break a node."""
    if pbar is None:
        return
    try:
        value = max(0, min(int(total), int(round(float(value)))))
        pbar.update_absolute(value, int(total), None)
    except Exception:
        pass
