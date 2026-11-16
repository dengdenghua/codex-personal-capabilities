param(
    [Parameter(Mandatory=$true)][string]$Config,
    [string]$Python='python',
    [switch]$Force,
    [string]$SessionInput,
    [string]$SessionId
)
$ErrorActionPreference='Stop'
$arguments=@('-B',(Join-Path $PSScriptRoot 'scripts/optics_autobackup.py'),'--config',$Config)
if ($Force) { $arguments+='--force' }
if ($SessionInput) { $arguments+=@('--session-input',$SessionInput) }
if ($SessionId) { $arguments+=@('--session-id',$SessionId) }
& $Python @arguments
exit $LASTEXITCODE
