"""Persist a NinjaOne runner's completion receipt in script_jobs."""

import json
from typing import Any

from bifrost import UserError, tables, workflow

SCRIPT_JOBS_TABLE = "script_jobs"


@workflow(name="post_script_job_result", category="NinjaOne", tags=["ninjaone", "powershell"])
async def post_script_job_result(
    job_id: str | None = None,
    status: str = "completed",
    result: str | None = None,
    error: str | None = None,
    body: Any | None = None,
) -> dict:
    """Accept flat endpoint arguments or a legacy webhook body dict/JSON string."""
    if not job_id and body is not None:
        parsed = body
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except (ValueError, TypeError):
                parsed = None
        if isinstance(parsed, dict):
            job_id = parsed.get("job_id")
            status = parsed.get("status", status)
            if result is None:
                result = parsed.get("result")
            if error is None:
                error = parsed.get("error")
    if not job_id:
        raise UserError("job_id is required")
    if status not in ("completed", "failed"):
        raise UserError("status must be 'completed' or 'failed'")
    document = await tables.get(SCRIPT_JOBS_TABLE, job_id)
    if not document:
        raise UserError(f"Job {job_id} not found")
    if document.data.get("metadata"):
        raise UserError("This job requires an application-specific completion handler")
    await tables.update(
        SCRIPT_JOBS_TABLE, job_id, {"status": status, "result": result, "error": error},
    )
    return {"job_id": job_id, "status": status}
