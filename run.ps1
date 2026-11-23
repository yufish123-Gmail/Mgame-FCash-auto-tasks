param(
    [switch]$Execute,
    [ValidateSet('all', 'page', 'browse12', 'promo', 'browse14', 'goods', 'capture')][string]$Task = 'all',
    [ValidateRange(0, 30)][int]$Limit = 0,
    [string]$Serial,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$candidates = if ($Python) { @($Python) } else {
    @(
        (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
        (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    )
}
foreach ($candidate in $candidates) {
    if (!$candidate -or !(Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    & $candidate -c 'import cv2, numpy' 2>$null
    if ($LASTEXITCODE -ne 0) { continue }
    $arguments = @((Join-Path $PSScriptRoot 'fcash.py'), '--task', $Task, '--limit', $Limit)
    if ($Serial) { $arguments += @('--serial', $Serial) }
    if ($Execute) { $arguments += '--execute' }
    & $candidate @arguments
    exit $LASTEXITCODE
}
throw 'Python with OpenCV and NumPy was not found. Use -Python to specify it.'
