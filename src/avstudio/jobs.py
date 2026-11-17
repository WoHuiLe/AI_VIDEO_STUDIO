"""Persistent single-worker queue with truthful status, cancellation and restart recovery."""

import queue
import threading
from uuid import uuid4

from .storage import StudioError, read_json, write_json


class Jobs:
    def __init__(self, desk, executor):
        self.desk, self.executor = desk, executor
        self.queue = queue.Queue()
        self.cancelled = {}
        self.thread = None
        self.stopping = threading.Event()
        self.recovered = False

    def recover(self):
        if self.recovered:
            return
        self.recovered = True
        for root in self.desk.projects.iterdir():
            if root.name.startswith(".") or root.is_symlink():
                continue
            for path in (root / "work/jobs").glob("*.json"):
                try:
                    job = read_json(path)
                    if job["status"] in {"queued", "running", "cancelling"}:
                        job.update(status="interrupted", message="服务已重启，任务中断；可以重新开始")
                        write_json(path, job)
                        meta = read_json(root / "planning/submission.json")
                        if meta.get("active_job") == job["id"]:
                            meta.update(status="error", active_job=None, error=job["message"], last_job_status="interrupted")
                            write_json(root / "planning/submission.json", meta)
                except (OSError, ValueError, KeyError):
                    continue

    def record(self, project_id, job_id):
        return self.desk.project(project_id) / f"work/jobs/{job_id}.json"

    def start(self, project_id, action):
        with self.desk.lock:
            root = self.desk.project(project_id)
            meta = read_json(root / "planning/submission.json")
            active = meta.get("active_job")
            if active and self.record(project_id, active).is_file():
                current = read_json(self.record(project_id, active))
                if current["status"] in {"queued", "running", "cancelling"}:
                    if current["action"] == action:
                        return current
                    raise StudioError("这个项目已有任务，请等待完成或先取消")
            self.desk.production.check_action(root, action)
            job = {"id": uuid4().hex, "action": action, "status": "queued",
                   "created_at": self.desk.now(), "message": "任务已入队，等待本机执行",
                   "stage": "queued", "events": [{"at": self.desk.now(), "message": "任务已入队", "stage": "queued"}]}
            write_json(self.record(project_id, job["id"]), job)
            meta.update(status="working", active_job=job["id"], last_job_status="queued", error=None, updated_at=self.desk.now())
            write_json(root / "planning/submission.json", meta)
            self.cancelled[job["id"]] = threading.Event()
            self.queue.put((project_id, job["id"]))
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.run, daemon=True, name="avstudio-worker")
                self.thread.start()
            return job

    def progress(self, project_id, job_id, message):
        with self.desk.lock:
            path = self.record(project_id, job_id)
            job = read_json(path)
            update = message if isinstance(message, dict) else {"message": message}
            if update.get("stage") != job.get("stage") and "stage" in update:
                for key in ["completed", "total", "unit"]:
                    job.pop(key, None)
            job.update({k: v for k, v in update.items() if k in {"message", "stage", "completed", "total", "unit"}})
            job["updated_at"] = self.desk.now()
            job["events"] = (job.get("events", []) + [{"at": self.desk.now(), **update}])[-60:]
            if job["status"] == "cancelling":
                job["message"] = "正在停止，已保存的素材会保留"
            write_json(path, job)

    def cancel(self, project_id):
        with self.desk.lock:
            meta = read_json(self.desk.project(project_id) / "planning/submission.json")
            job_id = meta.get("active_job")
            if not job_id or job_id not in self.cancelled:
                raise StudioError("没有正在执行的任务")
            self.cancelled[job_id].set()
            job = read_json(self.record(project_id, job_id))
            job.update(status="cancelling", message="正在停止，已保存的素材会保留")
            write_json(self.record(project_id, job_id), job)
            return job

    def run(self):
        while not self.stopping.is_set():
            try:
                project_id, job_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                with self.desk.lock:
                    path = self.record(project_id, job_id)
                    job = read_json(path)
                    job.update(status="running", started_at=self.desk.now())
                    write_json(path, job)
                event = self.cancelled[job_id]
                if event.is_set():
                    raise StudioError("任务已取消")
                self.executor(project_id, job["action"], event,
                              lambda message: self.progress(project_id, job_id, message))
                if event.is_set():
                    raise StudioError("任务已取消")
                with self.desk.lock:
                    job = read_json(path)
                    job.update(status="succeeded", message="任务完成", finished_at=self.desk.now())
                    job["stage"] = "done"
                    job["events"] = (job.get("events", []) + [{"at": self.desk.now(), "message": "任务完成", "stage": "done"}])[-60:]
                    write_json(path, job)
                    meta_path = self.desk.project(project_id) / "planning/submission.json"
                    meta = read_json(meta_path)
                    meta.update(active_job=None, last_job_status="succeeded", updated_at=self.desk.now())
                    write_json(meta_path, meta)
            except Exception as exc:
                with self.desk.lock:
                    path = self.record(project_id, job_id)
                    if not isinstance(exc, StudioError):
                        import traceback
                        from .storage import atomic_text
                        try:
                            atomic_text(path.with_suffix(".error.log"), traceback.format_exc())
                        except OSError:
                            pass  # Diagnostics must not prevent recording the terminal task state.
                    job = read_json(path)
                    is_cancelled = self.cancelled[job_id].is_set()
                    message = str(exc) if isinstance(exc, StudioError) else "执行失败，请重试或检查本机任务日志"
                    job.update(status="cancelled" if is_cancelled else "failed", message=message,
                               finished_at=self.desk.now())
                    job["events"] = (job.get("events", []) + [{"at": self.desk.now(), "message": message, "stage": job["status"]}])[-60:]
                    write_json(path, job)
                    meta_path = self.desk.project(project_id) / "planning/submission.json"
                    meta = read_json(meta_path)
                    meta.update(status="error", active_job=None, error=message,
                                last_job_status=job["status"], updated_at=self.desk.now())
                    write_json(meta_path, meta)
            finally:
                self.cancelled.pop(job_id, None)
                self.queue.task_done()

    def close(self):
        self.stopping.set()
        for event in list(self.cancelled.values()):
            event.set()
        if self.thread:
            self.thread.join(timeout=5)
