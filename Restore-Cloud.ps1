param(
    [Parameter(Mandatory=$true)][string]$Recovery,
    [Parameter(Mandatory=$true)][string]$RestoreTo,
    [string]$RcloneConfig,
    [string]$CacheDir,
    [string]$CiphertextCache,
    [switch]$NtfsCompressed,
    [string]$QuarkSkill,
    [ValidateRange(1,64)][int]$QuarkWorkers=3,
    [string]$SessionInput,
    [string]$SessionId,
    [switch]$AllowIncompleteBackup,
    [switch]$SkipInstall
)
$ErrorActionPreference='Stop'
$python=Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Install Python 3.11+ and make python available on PATH first.' }
& $python.Source -B (Join-Path $PSScriptRoot 'scripts/validate.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$arguments=@('-B',(Join-Path $PSScriptRoot 'scripts/optics_cloud.py'))
$arguments+=@('--quark-workers',"$QuarkWorkers")
if ($RcloneConfig) { $arguments+=@('--rclone-config',$RcloneConfig) }
if ($QuarkSkill) { $arguments+=@('--quark-skill',$QuarkSkill) }
if ($SessionInput) { $arguments+=@('--session-input',$SessionInput) }
if ($SessionId) { $arguments+=@('--session-id',$SessionId) }
$arguments+=@('restore','--recovery',$Recovery,'--destination',$RestoreTo)
if ($CacheDir) { $arguments+=@('--cache-dir',$CacheDir) }
if ($CiphertextCache) { $arguments+=@('--ciphertext-cache',$CiphertextCache) }
if ($NtfsCompressed) { $arguments+='--ntfs-compressed' }
if ($AllowIncompleteBackup) { $arguments+='--allow-incomplete' }
if ($SkipInstall) { $arguments+='--skip-install' }
& $python.Source @arguments
exit $LASTEXITCODE
