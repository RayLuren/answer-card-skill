"""Persistent stage timing for the answer-card pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Callable, TypeVar


REPORT_SCHEMA_VERSION = 1
T = TypeVar("T")


class PipelineTimer:
    """Append script and agent wall-clock stages to one persistent report."""

    def __init__(self, report_path: str | Path) -> None:
        self.path = Path(report_path)
        self.data = self._load_or_initialize()

    def begin(self, *, label: str | None = None, reset: bool = True) -> None:
        if reset or not self.data:
            self.data = _new_report(label=label)
        else:
            self.data["status"] = "running"
            self.data.pop("finished_at", None)
            self.data.pop("total_duration_seconds", None)
            if label is not None:
                self.data["label"] = label
        self._write()

    def ensure_running(self, *, reset_if_finished: bool = False) -> None:
        status = self.data.get("status")
        if status == "running":
            return
        if reset_if_finished:
            self.begin(label=self.data.get("label"), reset=True)
        else:
            self.data["status"] = "running"
            self.data.pop("finished_at", None)
            self.data.pop("total_duration_seconds", None)
            self._write()

    def start_stage(self, name: str, *, source: str = "script") -> str:
        if not name.strip():
            raise ValueError("stage name must not be empty")
        self.ensure_running()
        stage_id = f"{len(self.data['stages']) + 1:03d}"
        self.data["stages"].append(
            {
                "id": stage_id,
                "name": name,
                "source": source,
                "status": "running",
                "started_at": _utc_now(),
                "_started_epoch_seconds": time.time(),
            }
        )
        self._write()
        return stage_id

    def stop_stage(
        self,
        name_or_id: str,
        *,
        status: str = "passed",
        error: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if status not in {"passed", "failed"}:
            raise ValueError("stage status must be passed or failed")
        stage = self._find_running_stage(name_or_id)
        started_epoch = float(stage.pop("_started_epoch_seconds", time.time()))
        stage["status"] = status
        stage["finished_at"] = _utc_now()
        stage["duration_seconds"] = round(max(0.0, time.time() - started_epoch), 3)
        if error:
            stage["error"] = error
        if details:
            stage.update(details)
        if status == "failed":
            self.data["status"] = "failed"
            self.data["finished_at"] = _utc_now()
            pipeline_started = float(self.data.get("_started_epoch_seconds", time.time()))
            self.data["total_duration_seconds"] = round(max(0.0, time.time() - pipeline_started), 3)
        self._write()
        return stage

    def run(
        self,
        name: str,
        func: Callable[..., T],
        *args: object,
        source: str = "script",
        **kwargs: object,
    ) -> T:
        stage_id = self.start_stage(name, source=source)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            self.stop_stage(
                stage_id,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self.stop_stage(stage_id, status="passed")
        return result

    def update_result(self, values: dict[str, Any]) -> None:
        result = self.data.setdefault("result", {})
        if not isinstance(result, dict):
            result = {}
            self.data["result"] = result
        result.update(values)
        self._write()

    def update_configuration(self, values: dict[str, Any]) -> None:
        configuration = self.data.setdefault("configuration", {})
        if not isinstance(configuration, dict):
            configuration = {}
            self.data["configuration"] = configuration
        configuration.update(values)
        self._write()

    def finish(self, *, status: str = "passed") -> None:
        if status not in {"passed", "failed"}:
            raise ValueError("pipeline status must be passed or failed")
        running = [stage["name"] for stage in self.data["stages"] if stage.get("status") == "running"]
        if running:
            raise ValueError("cannot finish pipeline with running stages: " + ", ".join(running))
        self.data["status"] = status
        self.data["finished_at"] = _utc_now()
        started_epoch = float(self.data.pop("_started_epoch_seconds", time.time()))
        self.data["total_duration_seconds"] = round(max(0.0, time.time() - started_epoch), 3)
        self._write()

    def summary_text(self) -> str:
        lines = [
            f"status: {self.data.get('status')}",
            f"total: {_format_duration(self.data.get('total_duration_seconds'))}",
        ]
        for stage in self.data.get("stages", []):
            lines.append(
                f"- {stage.get('name')}: {_format_duration(stage.get('duration_seconds'))} "
                f"[{stage.get('status')}]"
            )
        return "\n".join(lines)

    def _find_running_stage(self, name_or_id: str) -> dict[str, Any]:
        for stage in reversed(self.data["stages"]):
            if stage.get("status") != "running":
                continue
            if stage.get("id") == name_or_id or stage.get("name") == name_or_id:
                return stage
        raise ValueError(f"no running stage found: {name_or_id}")

    def _load_or_initialize(self) -> dict[str, Any]:
        if not self.path.exists():
            data = _new_report()
            self.data = data
            self._write()
            return data
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "schema_version" not in data and isinstance(data.get("stages"), list):
            data = _migrate_legacy_report(data)
            self.data = data
            self._write()
        if not isinstance(data, dict) or data.get("schema_version") != REPORT_SCHEMA_VERSION:
            raise ValueError("pipeline report has an unsupported schema")
        stages = data.get("stages")
        if not isinstance(stages, list):
            raise ValueError("pipeline report stages must be a list")
        return data

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _new_report(*, label: str | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "running",
        "started_at": _utc_now(),
        "_started_epoch_seconds": time.time(),
        "stages": [],
    }
    if label is not None:
        report["label"] = label
    return report


def _migrate_legacy_report(data: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(data)
    migrated["schema_version"] = REPORT_SCHEMA_VERSION
    migrated["_started_epoch_seconds"] = _iso_to_epoch(migrated.get("started_at"))
    migrated_stages: list[dict[str, Any]] = []
    for index, stage in enumerate(migrated.get("stages", []), start=1):
        if not isinstance(stage, dict):
            continue
        migrated_stage = dict(stage)
        migrated_stage.setdefault("id", f"{index:03d}")
        migrated_stage.setdefault("source", "script")
        migrated_stages.append(migrated_stage)
    migrated["stages"] = migrated_stages
    return migrated


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_to_epoch(value: object) -> float:
    if not isinstance(value, str):
        return time.time()
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return time.time()


def _format_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "running"
    seconds = float(value)
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remaining = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {remaining:.1f}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(remaining_minutes)}m {remaining:.1f}s"
