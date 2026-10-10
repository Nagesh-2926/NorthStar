# Default read-only fixture dry-run. No write-enabled arguments are accepted or passed.
if ($args.Count -ne 0) {
    Write-Output 'STOP -- arguments are not accepted; no operation was run.'
    exit 1
}
& (Join-Path $PSScriptRoot 'fixture_readonly.ps1') -Operation dry-run
exit $LASTEXITCODE
