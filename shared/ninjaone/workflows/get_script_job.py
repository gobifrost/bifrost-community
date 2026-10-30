"""API-key endpoint used by the NinjaOne runner to fetch a script job."""

from bifrost import UserError, tables, workflow

SCRIPT_JOBS_TABLE = "script_jobs"


@workflow(name="get_script_job", category="NinjaOne", tags=["ninjaone", "powershell"])
async def get_script_job(job_id: str) -> dict:
    """Fetch a pending/running job and mark it running before returning content."""
    if not job_id:
        raise UserError("job_id is required")
    document = await tables.get(SCRIPT_JOBS_TABLE, job_id)
    if not document:
        raise UserError(f"Job {job_id} not found")
    status = document.data.get("status", "")
    if status not in ("pending", "running"):
        raise UserError(f"Job {job_id} is not available (status={status})")
    # Application-specific metadata needs its owning authorization/transport
    # implementation. This portable core serves ordinary script jobs only.
    if document.data.get("metadata"):
        raise UserError("This job requires an application-specific delivery handler")
    await tables.update(SCRIPT_JOBS_TABLE, job_id, {"status": "running"})
    return {
        "job_id": job_id,
        "script_content": document.data.get("script_content", ""),
        "params": document.data.get("params"),
    }
