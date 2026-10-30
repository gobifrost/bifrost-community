# Execute the actual runner with mocked HTTP. Requires PowerShell, not Pester.
$ErrorActionPreference = 'Stop'
$runner = Join-Path $PSScriptRoot '../scripts/bifrost-windows.ps1'
$originalTemp = $env:TEMP
$testDirectory = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $testDirectory | Out-Null
$env:TEMP = $testDirectory

function Assert-True($condition, [string]$message) {
    if (-not $condition) { throw $message }
}

function Out-File {
    param([Parameter(ValueFromPipeline = $true)]$InputObject, $FilePath, $Encoding)
    process {
        if ($global:NinjaRunnerTest.case -eq 'prepare-failed') { throw 'synthetic temp write failure' }
        $InputObject | Microsoft.PowerShell.Utility\Out-File -FilePath $FilePath -Encoding $Encoding
    }
}

function Invoke-RestMethod {
    param($Uri, $Method, $Body, $Headers)
    Assert-True ($Method -eq 'POST') 'Expected POST'
    Assert-True ($Headers['X-Bifrost-Key'] -eq 'synthetic-test-key') 'Missing callback key'
    $parsed = $Body | ConvertFrom-Json
    if ($Uri -eq 'https://example.invalid/get') {
        if ($global:NinjaRunnerTest.case -eq 'fetch-failed') { throw 'synthetic fetch failure' }
        $script = if ($global:NinjaRunnerTest.case -eq 'script-failed') {
            "throw 'synthetic script failure'"
        } else {
            'param([string]$Message) Write-Output $Message'
        }
        return [pscustomobject]@{
            result = [pscustomobject]@{
                script_content = $script
                params = [pscustomobject]@{ Message = 'hello "world" — café' }
            }
        }
    }
    Assert-True ($Uri -eq 'https://example.invalid/result') 'Wrong result URL'
    $global:NinjaRunnerTest.receipt = $parsed
    if ($global:NinjaRunnerTest.case -eq 'post-failed') { throw 'synthetic post failure' }
}

try {
    foreach ($case in @('completed', 'script-failed', 'prepare-failed', 'fetch-failed', 'post-failed')) {
        $global:NinjaRunnerTest = @{ case = $case; receipt = $null }
        $jobId = [guid]::NewGuid().ToString()
        $caught = $false
        try {
            & $runner -job_id $jobId -get_url 'https://example.invalid/get' `
                -post_url 'https://example.invalid/result' -api_key 'synthetic-test-key'
        } catch {
            $caught = $true
            Assert-True ($case -eq 'post-failed') "Unexpected failure: $_"
        }
        $receipt = $global:NinjaRunnerTest.receipt
        Assert-True ($null -ne $receipt) "Missing receipt in $case"
        Assert-True ($receipt.job_id -eq $jobId) 'Wrong correlation ID'
        Assert-True (-not (Test-Path (Join-Path $testDirectory "bifrost_$jobId.ps1"))) 'Temporary file remains'
        if ($case -in @('completed', 'post-failed')) {
            Assert-True ($receipt.status -eq 'completed') 'Expected completed script'
            Assert-True ($receipt.result.Trim() -eq 'hello "world" — café') 'Named parameter was corrupted'
        } else {
            Assert-True ($receipt.status -eq 'failed') 'Expected failed receipt'
            Assert-True ($receipt.error -match 'synthetic') 'Missing error details'
        }
        if ($case -eq 'post-failed') { Assert-True $caught 'Callback delivery error was hidden' }
        if ($case -eq 'fetch-failed') { Assert-True ($LASTEXITCODE -eq 1) 'Fetch failure should exit 1' }
        Write-Output "PASS $case"
    }
} finally {
    $env:TEMP = $originalTemp
    Remove-Item -Recurse -Force $testDirectory
    Remove-Variable NinjaRunnerTest -Scope Global -ErrorAction SilentlyContinue
}
