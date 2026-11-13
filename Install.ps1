param([switch]$SkillsOnly, [string]$RuntimeRoot, [string]$Config)
$ErrorActionPreference = 'Stop'
$pythonExe = $null
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    $candidate = & $launcher.Source -3.11 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0) { $pythonExe = $candidate.Trim() }
}
if (-not $pythonExe) {
    $launcher = Get-Command python -ErrorAction SilentlyContinue
    if ($launcher -and $launcher.Source -notlike '*WindowsApps*') {
        & $launcher.Source -c 'import sys; assert sys.version_info >= (3,11)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExe = $launcher.Source }
    }
}
if (-not $pythonExe) {
    throw 'Python 3.11+ is required. Install Python, then run Install.ps1 again. Windows: winget install --exact --id Python.Python.3.11'
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    $codexApp = Get-AppxPackage OpenAI.Codex -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($codexApp) {
        $cliFolder = Join-Path $codexApp.InstallLocation 'app\resources'
        if (Test-Path -LiteralPath (Join-Path $cliFolder 'codex.exe')) { $env:PATH = "$cliFolder;$env:PATH" }
    }
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw 'Install Codex CLI or the Codex desktop app first.' }
$installArgs = @((Join-Path $PSScriptRoot 'scripts\install.py'))
if ($SkillsOnly) { $installArgs += '--skills-only' }
if ($RuntimeRoot) { $installArgs += @('--runtime-root', $RuntimeRoot) }
if ($Config) { $installArgs += @('--config', $Config) }
& $pythonExe @installArgs
if ($LASTEXITCODE -ne 0) { throw 'Installation/check failed. Read the local runtime install.log and doctor.json before retrying.' }
