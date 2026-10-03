"""Route child progress into this sampler's total, only during its execution."""
from contextvars import ContextVar
from functools import wraps
import threading
from .progress_utils import make_progress

_active = ContextVar('lyonir_sampler_progress', default=None)


class TotalProgress:
    def __init__(self):
        self.bar = make_progress()
        self.current = 0
        self.start, self.end = 0, 0

    def stage(self, start, end):
        self.start, self.end = start, end

    def update_absolute(self, value, total=100, preview=None):
        self.current = max(self.current, min(100, int(value)))
        if self.bar is not None:
            self.bar.update_absolute(self.current, 100, preview)

    def child(self, value, total, preview=None):
        fraction = max(0.0, min(1.0, float(value) / max(1, float(total))))
        self.update_absolute(self.start + (self.end - self.start) * fraction, preview=preview)


def make_sampler_progress():
    return _active.get() or TotalProgress()


def total_progress(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        import comfy.utils
        progress = TotalProgress()
        previous = comfy.utils.PROGRESS_BAR_HOOK
        owner = threading.get_ident()
        token = _active.set(progress)

        def route(value, total, preview=None, *hook_args, **hook_kwargs):
            if threading.get_ident() == owner and _active.get() is progress:
                progress.child(value, total, preview)
            elif previous is not None:
                previous(value, total, preview, *hook_args, **hook_kwargs)

        comfy.utils.set_progress_bar_global_hook(route)
        try:
            return function(*args, **kwargs)
        finally:
            _active.reset(token)
            if comfy.utils.PROGRESS_BAR_HOOK is route:
                comfy.utils.set_progress_bar_global_hook(previous)
    return wrapped
