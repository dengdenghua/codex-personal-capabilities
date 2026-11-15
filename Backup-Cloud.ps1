param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$KeyDirectory,
    [string]$LocalRepository,
    [string]$Remote,
    [string]$RcloneConfig,
    [ValidateSet('Rclone','Quark')][string]$Provider='Rclone',
    [string]$QuarkSkill,
    [string]$ReadbackCache,
    [string]$SessionInput,
    [string]$SessionId
)
$ErrorActionPreference='Stop'
$python=Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Install Python 3.11+ and make python available on PATH first.' }
& $python.Source -B (Join-Path $PSScriptRoot 'scripts/validate.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$baseArgs=@('-B',(Join-Path $PSScriptRoot 'scripts/optics_cloud.py'))
if ($RcloneConfig) { $baseArgs+=@('--rclone-config',$RcloneConfig) }
if ($QuarkSkill) { $baseArgs+=@('--quark-skill',$QuarkSkill) }
if ($SessionInput) { $baseArgs+=@('--session-input',$SessionInput) }
if ($SessionId) { $baseArgs+=@('--session-id',$SessionId) }
if ($Provider -eq 'Quark' -and $Remote) { throw 'Quark uses its own account scope; do not pass an rclone Remote.' }
$recovery=Join-Path $KeyDirectory 'recovery.json'
if (-not (Test-Path -LiteralPath $recovery)) {
    if (-not $LocalRepository) { throw 'The first backup requires a separate local encrypted repository directory.' }
    & $python.Source @baseArgs init --key-dir $KeyDirectory --local-repository $LocalRepository
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
$record=Get-Content -LiteralPath $recovery -Raw | ConvertFrom-Json
if ($Provider -eq 'Quark') {
    if (-not $ReadbackCache) {
        $ReadbackCache=Join-Path (Split-Path -Parent $Archive) 'quark-readback'
    }
    & $python.Source @baseArgs backup-quark --recovery $recovery --archive $Archive --cache-dir $ReadbackCache
    exit $LASTEXITCODE
}
if ($Remote -and $record.storage -ne 'local-encrypted' -and $record.repository -ne ('rclone:'+$Remote)) {
    throw 'This recovery key is configured for a different cloud destination; nothing backed up.'
}
& $python.Source @baseArgs backup --recovery $recovery --archive $Archive
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($Remote) {
    $record=Get-Content -LiteralPath $recovery -Raw | ConvertFrom-Json
    if ($record.storage -eq 'local-encrypted') {
        & $python.Source @baseArgs publish --recovery $recovery --remote $Remote
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } elseif ($record.repository -ne ('rclone:'+$Remote)) { throw 'This recovery key is configured for a different cloud destination.' }
}
exit 0
