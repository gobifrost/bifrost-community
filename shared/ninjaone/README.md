# Recreate NinjaOne PowerShell execution in Bifrost

Give this README to a coding agent with access to your Bifrost workspace and
NinjaOne environment. It is a build prompt: follow the steps through verification
and leave a working execution path, with evidence for anything still blocked.
The adjacent source is a portable reference for the core used in our live system.

## Task and completion criteria

Implement one shared Python helper that accepts a NinjaOne device ID, PowerShell
source, optional named parameters, and an optional wait budget. Store the work in
Bifrost, launch a reusable NinjaOne script, deliver the source to the device, and
persist its output or error back in Bifrost. Other workflows should import this
helper rather than each implementing their own NinjaOne execution path.

Complete means all source, table, configuration, endpoint registrations, access
rules, NinjaOne library installation, and tests below are accounted for. Report
local-only work, deployed resources, and verified device execution separately.
Use placeholders for installation-specific values throughout source and reports.

## 1. Discover the target and existing implementation

Load the current Bifrost build skill and repository instructions. Inspect the
installed CLI's `--help` and SDK source when a command or API differs from this
reference. Confirm the selected instance with `bifrost auth default` and identify
the provider organization, authorized operators, and a Windows test device the
operator has approved. Ask only for values unavailable from existing resources.

Search live workspace and Solution source for `execute_powershell`, `script_jobs`,
`get_script_job`, and `post_script_job_result`. Inspect their callers before
editing. Reuse compatible resources and preserve workflow IDs and access rules.
For a moved/renamed workflow, use the supported replacement command. A file write
alone does not register a workflow.

Use the Workspace model for this shared transport. This community repository is
a reference collection, not an installable Solution. Its root `.bifrost/*.yaml`
files are historical exports; discover current live entities through the CLI.
If the target deliberately owns this code in a Solution, follow that Solution's
source/deployment lifecycle instead of live-mutating its managed definitions.

Exit this step with the exact target, existing resource inventory, intended
callers, source ownership, and access model established.

## 2. Recreate the transport contract

```mermaid
sequenceDiagram
    participant W as Calling workflow
    participant B as Bifrost / script_jobs
    participant N as NinjaOne API
    participant D as Windows runner
    W->>B: Insert pending job (UUID, source, params, device)
    W->>N: Run library script with job ID + URLs + key
    N->>D: Launch Bifrost (Windows)
    D->>B: POST get_script_job {job_id}
    B-->>D: result.script_content + result.params; mark running
    D->>D: Write temp .ps1, splat parameters, execute, clean up
    D->>B: POST result {job_id, status, result, error}
    B->>B: Store completed/failed receipt
    W->>B: Optional bounded status reads
```

Keep these responsibilities and public paths (relative to the repository root):

| Path | Responsibility |
|------|----------------|
| `modules/ninjaone.py` | Existing generated NinjaOne SDK; resolves `NinjaOne` integration OAuth and `base_url`. Requires `requests`. |
| `modules/extensions/ninjaone.py` | `PowerShellResult`, script discovery/cache, job creation, NinjaOne launch, optional waiting. |
| `shared/ninjaone/workflows/get_script_job.py` | Synchronous authenticated fetch endpoint. |
| `shared/ninjaone/workflows/post_script_job_result.py` | Authenticated completion receiver. |
| `shared/ninjaone/scripts/bifrost-windows.ps1` | Script installed in the NinjaOne library. |
| `shared/ninjaone/workflows/example_execute_powershell.py` | Benign parameterized greeting for one explicitly chosen device. |

Expose this helper contract:

```python
async def execute_powershell(
    device_id: int,
    script_content: str,
    *,
    params: dict | None = None,
    wait_seconds: int | None = None,
    run_as: str | None = None,
) -> PowerShellResult: ...

# PowerShellResult fields:
# job_id: str; status: str; result: str | None;
# error: str | None; device_id: int | None
```

Create a UUID job before calling NinjaOne. Resolve `ninja_script_id` from config
first; otherwise call `get_options(str(device_id))`, match `ninja_script_name`
exactly, and cache the discovered ID. Call `create_run(str(device_id), data=...)`
with the library script ID, `runAs`, and the runner's four named parameters:
`-job_id`, `-get_url`, `-post_url`, and `-api_key`. The source and its named
parameters stay in the job; they are fetched separately from the launch call.
The SDK maps discovery to `GET /v2/device/{id}/scripting/options` (read its
`scripts` array of `id`/`name` records) and dispatch to
`POST /v2/device/{id}/script/run`, with JSON
`{"id":<library-script-id>,"parameters":"<runner-arguments>","runAs":"system"}`.
Both use the NinjaOne OAuth bearer token; their response is not the script's
completion receipt.
Validate inputs before storage or dispatch: a positive non-boolean integer device
ID, string source, dictionary-or-null params, and positive integer-or-null wait.
If discovery or triggering raises, record `failed` and an error before raising
`UserError`. A transport error after sending the launch request can be ambiguous;
inspect the existing job/device before retrying an operation with side effects.

With `wait_seconds=None`, return a pending receipt immediately. With a wait
budget, read the row every three seconds and return terminal output when its
status is `completed` or `failed`. Return `timeout` when the budget elapses.
**Timeout is a caller result, not a table transition or a remote cancellation.**
The job can still finish later. The reference sleep interval can overrun the wait
budget by up to one interval. Keep waits short and below the workflow deadline.

Exit this step with one shared helper and all three workflow entry points
available locally, without adding per-caller copies of the transport.

## 3. Provision storage, integration, and configuration

Create/reuse `script_jobs`. Each document's ID is the UUID returned as `job_id`;
its data is:

| Field | Value |
|-------|-------|
| `script_content` | PowerShell source string |
| `params` | JSON object of named arguments, or null |
| `device_id` | Positive NinjaOne device ID |
| `status` | `pending` → `running` → `completed` or `failed` |
| `result` | Captured output string, initially null |
| `error` | Error string, initially null |
| `created_at` | UTC ISO 8601 timestamp |

Use the target SDK's supported table schema format; allow the JSON `params`
field even if an older table's display schema omits it. Assign table policies
for the actual human and unattended identities: create/read/update for trusted
PowerShell operators and the transport identities, with delete reserved for an
administrator or retention owner. Script source, parameters, and results are
sensitive operational data. Establish a retention period with the operator.

Reuse the `NinjaOne` integration. Its OAuth connection must permit reading device
scripting options and running scripts on the intended devices. Set `base_url`
for the correct NinjaOne region. This integration credential and the Bifrost
callback credential are separate. Keep both in the target platform's secret
storage; obtain external credentials through the environment's approved secret
workflow. Never copy populated configs or keys into Git.

Resolve these Bifrost config keys in the same execution scope as the helper:

| Key | Required value / default |
|-----|--------------------------|
| `ninja_get_script_endpoint` | Full HTTPS URL of the synchronous fetch endpoint. |
| `ninja_post_result_webhook_url` | Full HTTPS completion receiver URL; the historical name also permits an authenticated workflow endpoint. |
| `ninja_bifrost_api_key` | Secret sent in the `X-Bifrost-Key` header. |
| `ninja_script_id` | Optional numeric library ID, cached after discovery. Clear/update it when replacing the NinjaOne library script. |
| `ninja_script_name` | Optional; defaults to `Bifrost (Windows)`. |
| `ninja_run_as` | Optional; defaults to `system`. Explicit helper `run_as` overrides it. |

Keep the helper, endpoints, table resolution, integration mapping, and config
resolution in compatible scopes. A provider-controlled global table is possible,
but its name alone provides no tenant isolation. The supplied helper accepts an
arbitrary device ID and does not verify device ownership: expose it only through
trusted provider workflows, or add a caller wrapper that checks the device's
Ninja organization against the caller's integration mapping before dispatch.
Customer-facing tools need that check and matching table isolation policies.

Exit this step with the table and its policies, working NinjaOne OAuth, and all
required config values set or explicitly identified as external setup blockers.

## 4. Register and authenticate fetch and completion

Write only the required source paths. For a new file, use
`bifrost files write <path> --from-file <local-path> --create-only`. For an existing
file, capture `files stat --json`, preserve unrelated code, then write with
`--expected-version <version>` and read it back. Register the functions after
writing source, choosing the target provider organization and operator roles:

```bash
bifrost workflows register --path shared/ninjaone/workflows/get_script_job.py --function-name get_script_job --org "<provider-org>" --access-level role_based --role-ids "<operator-role>"
bifrost workflows register --path shared/ninjaone/workflows/post_script_job_result.py --function-name post_script_job_result --org "<provider-org>" --access-level role_based --role-ids "<operator-role>"
bifrost workflows register --path shared/ninjaone/workflows/example_execute_powershell.py --function-name example_execute_powershell --org "<provider-org>" --access-level role_based --role-ids "<operator-role>"
```

Enable POST endpoint access for fetch and result; configure fetch to execute
synchronously. Use the instance's workflow endpoint settings for execution mode,
allowed methods, and keys. Verify persisted records through `workflows get`.
Endpoint URLs follow `https://<bifrost-host>/api/endpoints/<workflow-id>` on the
reference platform. A successful synchronous fetch must have this envelope:

```json
{"result":{"job_id":"<job-uuid>","script_content":"param([string]$Message)\nWrite-Output $Message","params":{"Message":"Hello from Bifrost"}}}
```

The fetch function accepts pending/running jobs, marks them running, and rejects
missing or terminal jobs. Running jobs can be fetched again: this reference is
not an exactly-once execution mechanism. The result function accepts
`{"job_id":"<job-uuid>","status":"completed","result":"output","error":null}`,
validates the job and terminal status, and updates the row. It also accepts a
legacy `body` dictionary or JSON string. Ordinary duplicate receipts overwrite
the prior receipt; callers needing first-receipt semantics must implement them.

The supplied runner sends one key to both URLs. Select a credential that the
target instance actually accepts on both endpoints and verify that boundary.
Record the key's endpoint authorization and the unattended execution identity
with its organization and table/config grants as explicit setup artifacts. Human
workflow roles alone do not configure device-key authentication. Verify that a
POST JSON body `{job_id}` is mapped to the function's `job_id` argument and returns
the envelope above through the actual HTTP endpoint, not only a direct SDK call.
If the instance uses separate per-workflow keys, extend the helper and runner
together to carry separate fetch/result keys from secret config; retain the
single-key behavior for existing callers. Keep both receivers authenticated.
Do not make a receiver public to bypass an authentication failure.

The reference launcher passes the callback key through NinjaOne's script
arguments. Secret config storage does not conceal it from NinjaOne or the device.
Verify who can inspect script/run history and device process arguments, restrict
that access to trusted operators, and document the resulting credential trust
boundary. If that trust model is unsuitable, implement scoped, short-lived job
credentials before enabling execution. Keep real arguments out of test reports.
The reference concatenates launch arguments without quoting: use whitespace-free,
argument-safe endpoint URLs and generated keys. If an environment needs spaces
or shell-significant characters, implement argument serialization for its actual
NinjaOne PowerShell invocation and test that invocation's parameter binding.

An existing result webhook may remain the receiver if its adapter authentication
and payload mapping are verified. `X-Bifrost-Key` authenticates workflow endpoints;
the generic webhook adapter does not validate that header. A webhook configured
for HMAC needs matching request signing in the runner. Current event subscribers
read `context.event.data`; adapt that payload into the result handler rather
than assuming all event adapters provide legacy `body` keyword arguments.

Inspect the runtime identity for each trigger and grant only the table/config
permissions it needs. Avoid relying on old system/admin bypass behavior. Exercise
fetch/result HTTP calls with correct and incorrect keys; ensure bad credentials
cannot read source or change a job. Exit this step with authenticated HTTP
receivers and the exact response envelope verified on the selected instance.

## 5. Install and verify the Windows runner

Add `scripts/bifrost-windows.ps1` to the NinjaOne script library as
`Bifrost (Windows)` (or the configured name), enable it for the approved Windows
test device, and use a PowerShell runtime supported by that device. The script
has four mandatory string parameters matching the launch call above. It must:

1. POST `{job_id}` to the fetch URL with JSON content type and `X-Bifrost-Key`.
2. Read `response.result.script_content` and `response.result.params`.
3. Write UTF-8 source to `$env:TEMP\bifrost_<job_id>.ps1` so `param()` blocks work.
4. Protect temporary-file writing, parameter setup, and execution in the same
   try/catch/finally so a preparation failure also produces a failed receipt.
   Convert the params object's properties to a hashtable and dot-source the file
   with splatting. Capture pipeline output through `Out-String` and catch
   terminating PowerShell errors under `$ErrorActionPreference = 'Stop'`.
5. Delete the temporary file in `finally`, then POST `job_id`, terminal `status`,
   `result`, and `error`. Fetch failure posts a failed receipt and exits 1;
   delivery failure exits 1 and leaves the server without a completion receipt.

Keep named values in `params` rather than interpolating them into source. Default
execution is LocalSystem, not the interactive desktop user's session. Capture is
PowerShell pipeline output, not a structured result object or every diagnostic
stream. An unsuccessful native executable may require explicitly checking
`$LASTEXITCODE` and throwing: behavior varies by PowerShell version. Payloads
should finish normally or throw, rather than use `exit`, which can bypass the
runner's completion code. The core runner has no independent script timeout,
durable callback retry, or cancellation protocol. Endpoint network access must
work under the selected NinjaOne execution identity.

Exit this step with the installed library ID and parameter/runtime setup
recorded, without hardcoding an environment's script ID in source.

## 6. Run acceptance checks and deliver evidence

Run the included local checks from the community repository root:

```bash
python3 -m unittest discover -s shared/ninjaone/tests -p 'test_*.py' -v
pwsh -NoProfile -File shared/ninjaone/tests/test_runner.ps1
```

They use fake storage/API responses and mocked HTTP; no endpoint credentials or
customer machines are needed. Add target-specific tests for any adaptations.
Then run the registered greeting workflow on the approved device:

```bash
bifrost workflows execute example_execute_powershell --params '{"device_id":<approved-device-id>,"wait_seconds":90}' --json
```

This command is a template: replace `<approved-device-id>` with a positive JSON
integer. Confirm a completed row with `Hello from Bifrost` in its output and a
removed temporary file. Also verify:

| Check | Required evidence |
|-------|-------------------|
| Named parameter values with quotes, spaces, and Unicode | Literal values survive JSON, fetch, splatting, and output. |
| Payload throws | Job becomes `failed`; error survives callback. |
| TEMP write/setup fails | Failed receipt is delivered and partial temporary files are cleaned up. |
| No wait / short wait | Pending receipt / caller timeout; original job can complete later. |
| Missing config or unknown library script | Actionable error; no silent successful dispatch. |
| Invalid fetch ID, completed-job fetch, invalid result status | Rejected without changing an unrelated job. |
| Callback delivery/network failure | Distinguishable from script success; no automatic rerun of uncertain work. |
| Operator and unattended identities | Intended access passes; unauthorized and cross-tenant access fails. |

Deliver paths, workflow IDs, selected instance/scope, config key names without
values, installed NinjaOne script ID, test results, live job ID/status, retention
choice, and remaining external blockers. A local mock test does not establish
live authentication, permissions, NinjaOne installation, or device execution.

## Extending this core to match application-specific orchestration

The live system has additional consumers for bulk scripts, diagnostics, patching,
Active Directory, vulnerability remediation, and deployments. Its extended helper
also accepts stable `job_id` and `metadata`, enabling correlated dispatch receipts.
Its completion handler can emit `vulnerability.powershell.completed` or scoped
`bifrost.ninja.powershell.completed.v1` events. Prefer those callbacks for long
orchestrations, with bounded reconciliation when callbacks are missing.

Deployment delivery additionally rechecks authorization/cancellation, binds the
script hash/device/run/step, bootstraps encrypted secret-parameter transport, and
redacts secret/artifact output. Those behaviors require their owning application
and are not included in this portable core. The supplied receivers reject jobs
with metadata rather than delivering application jobs without their controls.
Preserve the application's existing handlers when installing into a workspace
that already has these extensions; merge the core behavior into its shared owner.
