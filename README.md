# Direct Modeling CAD

Desktop direct-modeling CAD prototype written in Python with PySide6 and OCP.

The app focuses on explicit selection, direct modeling commands, sketch-driven
features, parametric rebuild contracts, and visual workflow checks.

## Requirements

- Python 3.10+; Python 3.11 is recommended for OCP/cadquery-ocp wheels.
- Windows is the primary tested platform for GUI and tutorial capture workflows.
- Runtime dependencies are declared in `pyproject.toml` and mirrored in
  `requirements.txt`.
- Development/test dependencies are in `requirements-dev.txt`.

## Setup

Create a local virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

Install the app for development:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Or install from requirements files:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Run

```powershell
.\run.ps1 app
```

`run.ps1` uses `.venv\Scripts\python.exe` automatically when it exists. To use a
different interpreter:

```powershell
$env:CAD_APP_PYTHON = "C:\path\to\python.exe"
.\run.ps1 app
```

Useful tasks:

```powershell
.\run.ps1 check
.\run.ps1 all
.\run.ps1 visual
.\run.ps1 tutorials
```

## Documentation

- `docs/START_HERE.md`
- `docs/PRODUCT_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/CLICKING_CONTRACT.md`
- `docs/TESTING.md`
- `docs/VISUAL_TESTING.md`

## License

MIT — see [LICENSE](LICENSE).
