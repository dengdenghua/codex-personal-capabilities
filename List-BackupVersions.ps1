param([Parameter(Mandatory=$true)][string]$Config,[string]$Python='python')
$ErrorActionPreference='Stop'
& $Python -B (Join-Path $PSScriptRoot 'scripts/optics_autobackup.py') --config $Config --list-versions
exit $LASTEXITCODE
