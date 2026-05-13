# Direct Modeling CAD

Desktop direct-modeling CAD prototype written in Python with PySide6 and OCP.

The app focuses on explicit selection, direct modeling commands, sketch-driven
features, parametric rebuild contracts, and visual workflow checks.

## Requirements

- Python 3.10+
- Windows is the primary tested platform for GUI and tutorial capture workflows.
- Runtime dependencies are declared in `pyproject.toml`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Run

```powershell
.\run.ps1 app
```

Useful tasks:

```powershell
.\run.ps1 check
.\run.ps1 all
.\run.ps1 visual
.\run.ps1 tutorials
```

`CAD_APP_PYTHON` can point `run.ps1` at a specific Python executable.

## Documentation

- `docs/START_HERE.md`
- `docs/PRODUCT_CONTRACT.md`
- `docs/ARCHITECTURE.md`
- `docs/CLICKING_CONTRACT.md`
- `docs/TESTING.md`
- `docs/VISUAL_TESTING.md`

## License

No public license has been selected yet. Add a `LICENSE` file before publishing
as open source.
