"""Request-scoped loading progress, readable without the garage/import locks."""
from contextlib import contextmanager
from concurrent.futures import CancelledError
import threading
import time


class LoadingProgress:
    def __init__(self):
        self.lock = threading.Lock()
        self.local = threading.local()
        self.jobs = {}

    @contextmanager
    def track(self, request_id, label):
        previous = getattr(self.local, "request_id", None)
        self.local.request_id = request_id
        if request_id:
            with self.lock:
                self.jobs[request_id] = {"label": label, "stage": label, "detail": "", "completed": None,
                                         "total": None, "state": "running", "started": time.monotonic()}
                # Keep recent results briefly so the final poll can see completion.
                for key, job in list(self.jobs.items()):
                    if job["state"] != "running" and time.monotonic() - job["started"] > 60:
                        del self.jobs[key]
        try:
            yield
        except BaseException as error:
            if request_id:
                with self.lock:
                    self.jobs[request_id].update(state="cancelled" if isinstance(error, CancelledError) else "error", detail=str(error))
            raise
        else:
            if request_id:
                with self.lock:
                    self.jobs[request_id]["state"] = "done"
        finally:
            self.local.request_id = previous

    def update(self, stage, detail="", completed=None, total=None):
        request_id = getattr(self.local, "request_id", None)
        if request_id:
            with self.lock:
                self.jobs[request_id].update(stage=stage, detail=detail, completed=completed, total=total)

    def snapshot(self, request_ids):
        now = time.monotonic()
        with self.lock:
            return {key: {**{name: value for name, value in self.jobs[key].items() if name != "started"},
                          "elapsedSeconds": round(now - self.jobs[key]["started"], 1)}
                    for key in request_ids if key in self.jobs}
