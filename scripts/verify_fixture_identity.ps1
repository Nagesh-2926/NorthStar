# Run from your own local terminal only after approval of the read-only identity connection.
if ($args.Count -ne 0) {
    Write-Output 'STOP -- arguments are not accepted; enter credentials only at the masked local prompt.'
    exit 1
}
& (Join-Path $PSScriptRoot 'fixture_readonly.ps1') -Operation identity
exit $LASTEXITCODE
