"""Benign transport check; register only for trusted provider operators."""

from dataclasses import asdict

from bifrost import UserError, workflow
from modules.extensions.ninjaone import execute_powershell


@workflow(name="example_execute_powershell", category="NinjaOne", tags=["ninjaone", "powershell"])
async def example_execute_powershell(device_id: int, wait_seconds: int = 90) -> dict:
    """Run a parameterized greeting on an explicitly selected test device."""
    if isinstance(device_id, bool) or not isinstance(device_id, int) or device_id < 1:
        raise UserError("device_id must be a positive NinjaOne device ID")
    if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int) or not 1 <= wait_seconds <= 120:
        raise UserError("wait_seconds must be between 1 and 120")
    receipt = await execute_powershell(
        device_id=device_id,
        script_content='param([string]$Message)\nWrite-Output $Message',
        params={"Message": "Hello from Bifrost"},
        wait_seconds=wait_seconds,
    )
    return asdict(receipt)
