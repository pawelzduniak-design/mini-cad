param(
    [ValidateSet(
        "app",
        "test",
        "safety",
        "gui",
        "lint",
        "format",
        "format-check",
        "visual",
        "tutorials",
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
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Native {
    param(
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

$Python = Resolve-Python
Write-Host "Python: $Python"
Write-Host "Task: $Task"

switch ($Task) {
    "app" {
        Invoke-Native { & $Python -c "from cad_app.app import run; run()" }
    }
    "test" {
        Invoke-Native { & $Python -m pytest }
    }
    "safety" {
        Invoke-Native { & $Python -m dev.run_cad_safety_tests }
    }
    "gui" {
        $env:CAD_APP_GUI_TESTS = "1"
        Invoke-Native { & $Python -m pytest tests\gui -q }
    }
    "lint" {
        Invoke-Native { & $Python -m ruff check cad_app tests dev }
    }
    "format" {
        Invoke-Native { & $Python -m black cad_app tests dev }
    }
    "format-check" {
        Invoke-Native { & $Python -m black --check cad_app tests dev }
    }
    "visual" {
        $env:CAD_APP_VISUAL_TESTS = "1"
        Invoke-Step "perception pytest" { & $Python -m pytest tests\perception -q }
        Invoke-Step "visual probe" {
            & $Python -m dev.visual_window_probe --scenario all --fail-on-problems
        }
    }
    "tutorials" {
        Invoke-Native { & $Python -m dev.generate_tutorial_gifs }
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
        Invoke-Step "Window visual probe" {
            & $Python -m dev.visual_window_probe --scenario all --fail-on-problems
        }
    }
    "all" {
        Invoke-Step "pytest" { & $Python -m pytest }
        Invoke-Step "ruff" { & $Python -m ruff check cad_app tests dev }
        Invoke-Step "black --check" { & $Python -m black --check cad_app tests dev }
        Invoke-Step "CAD safety" { & $Python -m dev.run_cad_safety_tests }
        Invoke-Step "GUI integration" {
            $env:CAD_APP_GUI_TESTS = "1"
            & $Python -m pytest tests\gui -q
        }
        Invoke-Step "Sketch workflow" { & $Python -m dev.smoke_sketch_workflow }
        Invoke-Step "UX walkthrough" { & $Python -m dev.ux_user_walkthrough_check }
        Invoke-Step "First-open visual check" { & $Python -m dev.mama_opens_cad_check }
        Invoke-Step "Window visual probe" {
            $env:CAD_APP_VISUAL_TESTS = "1"
            & $Python -m pytest tests\perception -q
            & $Python -m dev.visual_window_probe --scenario all --fail-on-problems
        }
    }
}
