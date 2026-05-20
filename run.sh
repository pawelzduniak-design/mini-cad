#!/usr/bin/env bash
set -euo pipefail

task="${1:-app}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

if [[ "$(uname -s)" == "Linux" && -n "${DISPLAY:-}" && -z "${QT_QPA_PLATFORM:-}" ]]; then
  export QT_QPA_PLATFORM=xcb
fi

resolve_python() {
  if [[ -n "${CAD_APP_PYTHON:-}" ]]; then
    printf '%s\n' "$CAD_APP_PYTHON"
    return
  fi
  if [[ -x "$root/.venv/bin/python" ]]; then
    printf '%s\n' "$root/.venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi
  printf 'Python not found. Set CAD_APP_PYTHON or create .venv.\n' >&2
  exit 127
}

run_step() {
  local name="$1"
  shift
  printf '\n=== %s ===\n' "$name"
  "$@"
}

python_bin="$(resolve_python)"
printf 'Python: %s\n' "$python_bin"
printf 'Task: %s\n' "$task"

case "$task" in
  app)
    "$python_bin" -c "from cad_app.app import run; run()"
    ;;
  test)
    "$python_bin" -m pytest
    ;;
  safety)
    "$python_bin" -m dev.run_cad_safety_tests
    ;;
  gui)
    CAD_APP_GUI_TESTS=1 "$python_bin" -m pytest tests/gui -q
    ;;
  lint)
    "$python_bin" -m ruff check cad_app tests dev
    ;;
  format)
    "$python_bin" -m black cad_app tests dev
    ;;
  format-check)
    "$python_bin" -m black --check cad_app tests dev
    ;;
  visual)
    CAD_APP_VISUAL_TESTS=1 "$python_bin" -m pytest tests/perception -q
    CAD_APP_VISUAL_TESTS=1 "$python_bin" -m dev.visual_window_probe --scenario all --fail-on-problems
    ;;
  tutorials)
    "$python_bin" -m dev.generate_tutorial_gifs
    ;;
  check)
    run_step pytest "$python_bin" -m pytest
    run_step ruff "$python_bin" -m ruff check cad_app tests dev
    run_step "black --check" "$python_bin" -m black --check cad_app tests dev
    ;;
  smoke)
    run_step "CAD safety" "$python_bin" -m dev.run_cad_safety_tests
    run_step "Sketch workflow" "$python_bin" -m dev.smoke_sketch_workflow
    run_step "UX walkthrough" "$python_bin" -m dev.ux_user_walkthrough_check
    run_step "First-open visual check" "$python_bin" -m dev.mama_opens_cad_check
    run_step "Window visual probe" "$python_bin" -m dev.visual_window_probe --scenario all --fail-on-problems
    ;;
  all)
    run_step pytest "$python_bin" -m pytest
    run_step ruff "$python_bin" -m ruff check cad_app tests dev
    run_step "black --check" "$python_bin" -m black --check cad_app tests dev
    run_step "CAD safety" "$python_bin" -m dev.run_cad_safety_tests
    run_step "GUI integration" env CAD_APP_GUI_TESTS=1 "$python_bin" -m pytest tests/gui -q
    run_step "Sketch workflow" "$python_bin" -m dev.smoke_sketch_workflow
    run_step "UX walkthrough" "$python_bin" -m dev.ux_user_walkthrough_check
    run_step "First-open visual check" "$python_bin" -m dev.mama_opens_cad_check
    run_step "Window visual probe pytest" env CAD_APP_VISUAL_TESTS=1 "$python_bin" -m pytest tests/perception -q
    run_step "Window visual probe" env CAD_APP_VISUAL_TESTS=1 "$python_bin" -m dev.visual_window_probe --scenario all --fail-on-problems
    ;;
  *)
    printf 'Unknown task: %s\n' "$task" >&2
    printf 'Usage: ./run.sh {app|test|safety|gui|lint|format|format-check|visual|tutorials|check|smoke|all}\n' >&2
    exit 2
    ;;
esac
