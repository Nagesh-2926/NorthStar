# Shared local-console entry point. This file never uses application credentials.
param(
    [string]$Operation
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$createdVariable = $false
$resultCode = 1
$expectedSeederHash = '8CC0215ADCFF86380A629634E7DF990C50E7C82146877BD6F5DDEF1EA81B4F26'

try {
    if ($args.Count -ne 0 -or $Operation -notin @('identity','dry-run')) {
        throw 'A reviewed operation is required; extra arguments are not accepted.'
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw 'The project Python environment is unavailable.'
    }
    $hash = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'seed_synthetic_upload_fixture.py') -Algorithm SHA256).Hash
    if ($hash -ne $expectedSeederHash) {
        throw 'The seeder differs from the reviewed source; stopped before any connection.'
    }
    Write-Output 'reviewed seeder hash: PASS'
    foreach ($name in @('DATABASE_URL','PGHOST','PGHOSTADDR','PGPORT','PGDATABASE','PGSERVICE',
                       'PGSERVICEFILE','PGSYSCONFDIR','PGOPTIONS','PGTARGETSESSIONATTRS')) {
        if (-not [string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($name, 'Process'))) {
            Write-Output "environment override present: $name (value withheld; unchanged)"
            throw 'A prohibited environment override is set. Review its origin locally; no variables were cleared.'
        }
    }
    Write-Output 'DATABASE_URL and nine libpq override checks: PASS'
    if (Test-Path -LiteralPath 'Env:\NORTHSTAR_TEST_DATABASE_URL') {
        if ([string]::IsNullOrEmpty($env:NORTHSTAR_TEST_DATABASE_URL)) {
            throw 'A pre-existing empty fixture variable was left unchanged; enter credentials in a clean local terminal.'
        }
        Write-Output 'Using the pre-existing process fixture variable; it will be left unchanged.'
    } else {
        $secure = Read-Host 'Enter the complete fixture URL for 127.0.0.1:5433/student_support_fixture (input hidden)' -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try {
            $env:NORTHSTAR_TEST_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
            $createdVariable = $true
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
            $secure.Dispose()
        }
    }
    Push-Location -LiteralPath $root
    try {
        & $python -B -I (Join-Path $PSScriptRoot 'check_fixture_target.py')
        if ($LASTEXITCODE -ne 0) {
            throw 'Target preflight refused; stopped before any database connection.'
        }
        if ($Operation -eq 'identity') {
            & $python -B -I (Join-Path $PSScriptRoot 'verify_fixture_identity.py')
        } else {
            # No arguments: the default seeder path is read-only.
            & $python -B -I (Join-Path $PSScriptRoot 'seed_synthetic_upload_fixture.py')
        }
        $resultCode = $LASTEXITCODE
        Write-Output "operation exit code: $resultCode"
    } finally {
        Pop-Location
    }
} catch {
    # PowerShell exception records can contain input; do not display them.
    Write-Output 'STOP -- operation not completed; preflight or local execution failed. No retry was made.'
    $resultCode = 1
} finally {
    if ($createdVariable) {
        Remove-Item -LiteralPath 'Env:\NORTHSTAR_TEST_DATABASE_URL' -ErrorAction SilentlyContinue
        $removed = -not (Test-Path -LiteralPath 'Env:\NORTHSTAR_TEST_DATABASE_URL')
        Write-Output "temporary fixture variable removed from this process: $removed"
        if (-not $removed) { $resultCode = 1 }
    }
}
exit $resultCode
