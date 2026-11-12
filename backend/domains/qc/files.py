"""QC files kept in S3 as well as on disk (a hosted server's disk does not survive a restart): the uploaded export
an analyst checks, and the QC report produced from it. Without S3 every call is a no-op and the disk path stands."""
from __future__ import annotations

from pathlib import Path

from ...core import object_store

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload_key(path: Path) -> str:
    return f"qc/uploads/{path.name}"         # upload names are qc_<8 hex><ext>: unique


def _export_key(run_id: int, path: Path) -> str:
    return f"qc/exports/run-{run_id}/{path.name}"     # export names repeat across runs (<file>_QC_Report.xlsx)


def keep_upload(path: Path) -> None:
    if path.is_file():
        object_store.put_file(_upload_key(path), path)


def upload_path(report: dict) -> str:
    """The report's uploaded file on this server's disk, restored from S3 first when it is missing."""
    path = Path(report["file_path"])
    if not path.is_file():
        object_store.download(_upload_key(path), path)
    return str(path)


def keep_export(run_id: int, path: Path) -> None:
    if path.is_file():
        object_store.put_file(_export_key(run_id, path), path, XLSX)


def export_link(run_id: int, path: Path, name: str) -> str | None:
    return object_store.presigned_url(_export_key(run_id, path), download_name=name)
