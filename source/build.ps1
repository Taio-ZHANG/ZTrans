$ErrorActionPreference = 'Stop'
$sourceRoot = $PSScriptRoot
$venvPython = Join-Path $sourceRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.12 -m venv (Join-Path $sourceRoot '.venv')
}
& $venvPython -m pip install -r (Join-Path $sourceRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
# Restrict DLL discovery to this Python and Windows; do not change the system PATH.
$pythonBase = & $venvPython -c 'import sys; print(sys.base_prefix)'
$savedBuildPath = $env:PATH
try {
    $env:PATH = "$pythonBase;$sourceRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & $venvPython -m pytest (Join-Path $sourceRoot 'test_core.py') -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    & $venvPython (Join-Path $sourceRoot 'collect_licenses.py') (Join-Path $sourceRoot '..\THIRD_PARTY_LICENSES')
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    & $venvPython -m PyInstaller (Join-Path $sourceRoot 'ZTrans.spec') --noconfirm --clean --distpath (Join-Path $sourceRoot 'dist') --workpath (Join-Path $sourceRoot 'build')
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
} finally {
    $env:PATH = $savedBuildPath
}
