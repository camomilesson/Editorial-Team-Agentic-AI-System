"""Separate, atomic JSON persistence for Monitor reports."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from editorial_agent.contracts import MonitorReport
from editorial_agent.monitoring.errors import MonitorPersistenceError


def persist_monitor_report(
    report: MonitorReport,
    *,
    output_path: Path,
    input_bundle_path: Path | None = None,
    force: bool = False,
) -> None:
    """Atomically write only the report, preserving any supplied bundle."""

    output = output_path.resolve(strict=False)
    if input_bundle_path is not None and output == input_bundle_path.resolve(strict=False):
        raise MonitorPersistenceError(
            "Monitor report output must differ from the input bundle."
        )
    if output.exists() and not force:
        raise MonitorPersistenceError("Monitor report output already exists.")

    temporary: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            report.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, output)
        else:
            try:
                os.link(temporary, output)
            except FileExistsError as exc:
                raise MonitorPersistenceError(
                    "Monitor report output already exists."
                ) from exc
            temporary.unlink()
        temporary = None
    except MonitorPersistenceError:
        raise
    except OSError as exc:
        raise MonitorPersistenceError("Monitor report could not be persisted.") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
