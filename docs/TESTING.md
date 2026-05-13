# Testing

The test suite is organized by contract level and by whether it needs a real
Qt/OCP window.

## Layout

- `tests/core/`: pure model, geometry, sketch, and STEP contracts.
- `tests/safety/`: command routing and mutation guardrails.
- `tests/ui/`: Qt-free or light Qt UI state/action contracts.
- `tests/gui/`: real Qt/OCP window interaction tests, gated by
  `CAD_APP_GUI_TESTS=1`.
- `tests/perception/`: screenshot and visual metric checks, gated by
  `CAD_APP_VISUAL_TESTS=1`.
- `tests/helpers/`: local test helpers.

## Commands

```powershell
.\run.ps1 test
.\run.ps1 safety
.\run.ps1 gui
.\run.ps1 visual
.\run.ps1 check
.\run.ps1 all
```

- `test`: normal pytest suite. GUI/perception tests skip unless enabled.
- `safety`: safety contracts only.
- `gui`: enables and runs `tests/gui`.
- `visual`: enables and runs `tests/perception`, then runs the visual probe.
- `check`: pytest, ruff, and black check.
- `all`: check, safety, gui, and visual.

## Contract Rules

- Do not weaken tests to pass a patch.
- If the product behavior changes intentionally, update docs and tests together.
- Visual tests should check obvious user-visible failures, not pixel-perfect
  golden images.
- A passing unit test does not excuse a black or blank viewport.
