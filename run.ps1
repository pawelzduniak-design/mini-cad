param(
    [ValidateSet(
        "app",
        "test",
        "safety",
        "gui",
        "lint",
        "format",
        "format-check",
        "check",
        "smoke",
        "all"
    )]
    [string]$Task = "app"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Resolve-Python {
    $candidates = @()
    if ($env:CAD_APP_PYTHON) {
        $candidates += $env:CAD_APP_PYTHON
    }
    $candidates += Join-Path $Root ".venv\Scripts\python.exe"
    $candidates += "C:\Users\kwipzdadmin\Desktop\kodpasstmp\.venv\Scripts\python.exe"
    $candidates += "python"

    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            $command = Get-Command python -ErrorAction SilentlyContinue
            if ($command) {
                return $command.Source
            }
            continue
        }
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    throw "Nie znaleziono Pythona. Ustaw `$env:CAD_APP_PYTHON albo utworz .venv."
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ==="
    & $Command
}

$Python = Resolve-Python
Write-Host "Python: $Python"
Write-Host "Task: $Task"

switch ($Task) {
    "app" {
        & $Python -c "from cad_app.app import run; run()"
    }
    "test" {
        & $Python -m pytest
    }
    "safety" {
        & $Python -m dev.run_cad_safety_tests
    }
    "gui" {
        $env:CAD_APP_GUI_TESTS = "1"
        & $Python -m pytest tests\test_viewer_click_integration.py -q
    }
    "lint" {
        & $Python -m ruff check cad_app tests dev
    }
    "format" {
        & $Python -m black cad_app tests dev
    }
    "format-check" {
        & $Python -m black --check cad_app tests dev
    }
    "check" {
        Invoke-Step "pytest" { & $Python -m pytest }
        Invoke-Step "ruff" { & $Python -m ruff check cad_app tests dev }
        Invoke-Step "black --check" { & $Python -m black --check cad_app tests dev }
    }
    "smoke" {
        Invoke-Step "CAD safety" { & $Python -m dev.run_cad_safety_tests }
        Invoke-Step "Sketch workflow" { & $Python -m dev.smoke_sketch_workflow }
        Invoke-Step "UX walkthrough" { & $Python -m dev.ux_user_walkthrough_check }
        Invoke-Step "First-open visual check" { & $Python -m dev.mama_opens_cad_check }
    }
    "all" {
        Invoke-Step "pytest" { & $Python -m pytest }
        Invoke-Step "ruff" { & $Python -m ruff check cad_app tests dev }
        Invoke-Step "black --check" { & $Python -m black --check cad_app tests dev }
        Invoke-Step "CAD safety" { & $Python -m dev.run_cad_safety_tests }
        Invoke-Step "GUI integration" {
            $env:CAD_APP_GUI_TESTS = "1"
            & $Python -m pytest tests\test_viewer_click_integration.py -q
        }
        Invoke-Step "Sketch workflow" { & $Python -m dev.smoke_sketch_workflow }
        Invoke-Step "UX walkthrough" { & $Python -m dev.ux_user_walkthrough_check }
        Invoke-Step "First-open visual check" { & $Python -m dev.mama_opens_cad_check }
    }
}
