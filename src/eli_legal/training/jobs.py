"""Running the trainer: one job at a time, in the training environment, watched from ELI Legal.

A job is a folder in the trained model's own place (``training/models/<model id>``): the job
file, a copy of the trainer, the examples it trains on (deleted when the job ends: the trained
model keeps only their ids and a digest), the log of everything the trainer printed, and what it
made. The trainer writes its output to the log itself and, however it ends, ``outcome.json``, so
it needs nothing of ELI Legal once started: it runs in its own session, and a run that autonomous
mode started from the daily checks finishes after they have. ELI Legal reads the log as it grows,
keeps the latest state in ``state.json`` so any window (or a restart) can show where the job is,
and cancels by leaving a file the trainer looks for between steps.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from eli_legal.training import environment

_RUNNING: dict[str, subprocess.Popen[bytes]] = {}
_LOCK = threading.Lock()


def models_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir) / "training" / "models"
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def job_dir(data_dir: str | Path, model_id: str) -> Path:
    return models_dir(data_dir) / model_id


def worker_source() -> str:
    return files("eli_legal.training").joinpath("worker.py").read_text(encoding="utf-8")


# A run nothing has heard from for this long, and no process here is watching, has stopped.
SILENT_HOURS = 2.0


def state(folder: Path) -> dict[str, Any]:
    """Where a job is. The trainer's own outcome file decides how it ended."""
    try:
        found: dict[str, Any] = json.loads((folder / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        found = {"status": "unknown"}
    try:
        outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        outcome = None
    if isinstance(outcome, dict) and outcome.get("status") in ("done", "failed", "cancelled"):
        found.update(
            status=outcome["status"], message=outcome.get("message") or found.get("message", "")
        )
        if outcome.get("result") is not None:
            found["result"] = outcome["result"]
        if outcome.get("trace"):
            found["trace"] = outcome["trace"]
        return found
    if found.get("status") == "running" and folder.name not in running():
        log = folder / "trainer.log"
        try:
            quiet = time.time() - log.stat().st_mtime
        except OSError:
            quiet = (
                time.time() - (folder / "job.json").stat().st_mtime
                if (folder / "job.json").exists()
                else 0
            )
        if quiet > SILENT_HOURS * 3600:
            found.update(
                status="failed",
                message=f"the trainer has said nothing for {quiet / 3600:.1f} hours and left no "
                "outcome: it stopped (the machine restarted, or it was ended)",
            )
    return found


def _save_state(folder: Path, data: dict[str, Any]) -> None:
    tmp = folder / "state.json.tmp"
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, folder / "state.json")


def running() -> list[str]:
    with _LOCK:
        return [k for k, p in _RUNNING.items() if p.poll() is None]


def start(
    data_dir: str | Path,
    model_id: str,
    *,
    base: str,
    train_rows: list[dict[str, Any]],
    recipe: dict[str, Any],
    gguf_type: str = "q8_0",
    dry_run: bool = False,
    python: str | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Write the job and start the trainer in the background. Returns the job's folder."""
    if running():
        raise RuntimeError("a training run is already going on this machine; one at a time")
    folder = job_dir(data_dir, model_id)
    folder.mkdir(parents=True, exist_ok=False)
    os.chmod(folder, 0o700)
    env = environment.folder(data_dir)
    train = folder / "train.jsonl"
    with train.open("w", encoding="utf-8") as fh:
        for row in train_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.chmod(train, 0o600)
    worker = folder / "worker.py"
    worker.write_text(worker_source(), encoding="utf-8")
    job = {
        "base": base,
        "train": str(train),
        "out": str(folder),
        "recipe": recipe,
        "gguf_type": gguf_type,
        "dry_run": dry_run,
        "converter": str(environment.converter_dir(env) / "convert_hf_to_gguf.py"),
    }
    (folder / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    py = python or str(environment.python_of(env))
    log = (folder / "trainer.log").open("ab")
    detach: dict[str, Any] = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    try:
        proc = subprocess.Popen(
            [py, str(worker), str(folder / "job.json")],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=str(folder),
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", "1"),
            },
            **detach,
        )
    finally:
        log.close()
    with _LOCK:
        _RUNNING[model_id] = proc
    _save_state(
        folder,
        {"status": "running", "step": 0, "max_steps": 0, "message": "starting", "pid": proc.pid},
    )
    threading.Thread(
        target=_watch,
        args=(folder, model_id, proc, on_event),
        daemon=True,
        name=f"training-{model_id}",
    ).start()
    return folder


def _watch(
    folder: Path,
    model_id: str,
    proc: subprocess.Popen[bytes],
    on_event: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Read the trainer's log as it grows, keeping state.json and any window up to date."""
    current: dict[str, Any] = state(folder)
    log = folder / "trainer.log"

    def take(line: str) -> None:
        try:
            event = json.loads(line)
        except ValueError:
            event = {"type": "log", "message": line.rstrip()}
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "step":
            current.update(
                step=event.get("step"),
                max_steps=event.get("max_steps"),
                loss=event.get("loss"),
                seconds=event.get("seconds"),
            )
        elif kind in ("stage", "log"):
            current["message"] = event.get("message", "")
        elif kind in ("done", "failed", "cancelled"):
            current["status"] = kind
            current["message"] = event.get("message", current.get("message", ""))
            if kind == "done":
                current["result"] = event.get("result")
            if kind == "failed":
                current["trace"] = event.get("trace", "")
        _save_state(folder, current)
        if on_event is not None:
            try:
                on_event({**event, "model_id": model_id})
            except Exception:  # a window that has gone must not stop the run
                pass

    with log.open("r", encoding="utf-8", errors="replace") as fh:
        pending = ""
        while True:
            chunk = fh.read()
            if chunk:
                pending += chunk
                *lines, pending = pending.split("\n")
                for line in lines:
                    if line.strip():
                        take(line)
                continue
            if proc.poll() is not None:
                rest = fh.read()
                for line in (pending + rest).split("\n"):
                    if line.strip():
                        take(line)
                break
            time.sleep(0.25)
    code = proc.wait()
    ended = state(folder)  # the trainer's outcome file decides
    if ended.get("status") == "running":
        ended.update(
            status="failed",
            message=f"the trainer stopped (exit {code}) without saying why; see trainer.log",
        )
    _save_state(folder, ended)
    # The examples are case material: they do not outlive the run (the trainer deletes them
    # too; this is for a trainer that could not).
    try:
        (folder / "train.jsonl").unlink()
    except OSError:
        pass
    with _LOCK:
        _RUNNING.pop(model_id, None)
    if on_event is not None:
        try:
            on_event({"type": "finished", "model_id": model_id, "status": ended["status"]})
        except Exception:
            pass


def cancel(data_dir: str | Path, model_id: str) -> bool:
    folder = job_dir(data_dir, model_id)
    if not folder.is_dir():
        return False
    (folder / "cancel").write_text("cancelled", encoding="utf-8")
    return True


def wait(model_id: str, timeout: float | None = None) -> None:
    with _LOCK:
        proc = _RUNNING.get(model_id)
    if proc is not None:
        proc.wait(timeout=timeout)
    for thread in threading.enumerate():
        if thread.name == f"training-{model_id}":
            thread.join(timeout=timeout)


def remove(data_dir: str | Path, model_id: str) -> None:
    shutil.rmtree(job_dir(data_dir, model_id), ignore_errors=True)
