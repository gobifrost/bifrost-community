# Bifrost (Windows) — NinjaRMM Pre-Deployed Script
# Add this script to your NinjaOne library as "Bifrost (Windows)".
#
# This script is triggered by Bifrost's execute_powershell() function.
# It fetches a PowerShell payload from the Bifrost API, executes it,
# and posts the result back.
#
# v2: Supports params — saves script to temp file and uses splatting
#     instead of [ScriptBlock]::Create().Invoke()

param(
    [Parameter(Mandatory = $true)]
    [string]$job_id,

    [Parameter(Mandatory = $true)]
    [string]$get_url,

    [Parameter(Mandatory = $true)]
    [string]$post_url,

    [Parameter(Mandatory = $true)]
    [string]$api_key
)

$ErrorActionPreference = 'Stop'

$headers = @{
    'Content-Type'   = 'application/json'
    'X-Bifrost-Key'  = $api_key
}

# Fetch script content and params from Bifrost
try {
    $getBody = @{ job_id = $job_id } | ConvertTo-Json -Compress
    $response = Invoke-RestMethod -Uri $get_url -Method POST -Body $getBody -Headers $headers
    $scriptContent = $response.result.script_content
    $inputParams = $response.result.params
}
catch {
    $errorBody = @{
        job_id = $job_id
        status = 'failed'
        error  = "Failed to fetch script: $($_.Exception.Message)"
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $post_url -Method POST -Body $errorBody -Headers $headers
    exit 1
}

# Save script to temp file (enables param() blocks)
$tmpFile = "$env:TEMP\bifrost_$job_id.ps1"

# Protect preparation and execution so either failure produces a receipt.
$output = $null
$scriptError = $null
try {
    $scriptContent | Out-File -FilePath $tmpFile -Encoding UTF8
    $splatParams = @{}
    if ($inputParams) {
        $inputParams.PSObject.Properties | ForEach-Object {
            $splatParams[$_.Name] = $_.Value
        }
    }
    $output = . $tmpFile @splatParams | Out-String
}
catch {
    $scriptError = $_.Exception.Message
}
finally {
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
}

# Post result back to Bifrost
$resultBody = @{
    job_id = $job_id
    status = if ($scriptError) { 'failed' } else { 'completed' }
    result = $output
    error  = $scriptError
} | ConvertTo-Json -Compress

try {
    Invoke-RestMethod -Uri $post_url -Method POST -Body $resultBody -Headers $headers
}
catch {
    Write-Error "Failed to post result: $($_.Exception.Message)"
    exit 1
}
