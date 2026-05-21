# mini-cad

A small direct-modeling CAD I built (vibe-coded, with heavy AI help) because I
needed to **prototype simple 3D models fast** — sketch something, extrude it,
cut, move, fillet, export STEP, move on.

It is **not** trying to be FreeCAD or Fusion. On purpose. The goal is a compact,
no-friction desktop CAD for quick model prototyping: open it, get a shape out,
export, done — without fighting a heavyweight tool.

<p align="center">
  <img src="docs/images/hero.png" alt="mini-cad — direct-modeling CAD" width="820">
  <br>
  <!-- A short feature-tour GIF can replace this still later:
       <img src="feature_tour.gif" alt="mini-cad feature tour" width="820"> -->
  <sub><em>Selection-first: pick a face, edge, or vertex and the matching tools light up.</em></sub>
</p>

## ✓ What it does

- **Sketch:** line, arc, circle, center & 3-point rectangle, trim, editable
  dimensions, and sketches hosted on a selected face.
- **Solids:** box bodies, push/pull extrude, sketch extrude/cut, new body from
  sketch, revolve, face removal, body transforms.
- **Booleans:** union, subtract, intersect between bodies.
- **Direct editing:** move bodies, faces, edges, vertices, and sketch geometry.
- **Finishing:** fillet, chamfer, threads, mirror, rib.
- **Snapping:** while sketching, the cursor snaps to a face's edges/vertices,
  the grid, and other bodies; hold **Ctrl** to also snap to the grid while
  dragging.
- **Measure:** edge length, radius/diameter, axis distance for round features.
- **Files:** native `.cadproj` save/load + STEP import/export.

## ✗ What it deliberately doesn't (yet)

- No assemblies, mates, or a full parametric constraint solver — dimensions are
  editable, but this is direct modeling, not history-driven parametrics.
- No mesh/STL export — STEP only.
- Linux is work-in-progress; Windows is the supported runtime today.
- It's a prototype. Expect rough edges and the occasional "that face can't be
  extruded" when geometry gets unusual.

## Keyboard

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `Arrows` | orbit camera around object | `1`/`2`/`3`/`4` | select object/face/edge/vertex |
| `F` | fit all | `S` | start sketch on selection |
| `H` | home view | `E` / `Shift+E` | push-pull / extrude inward |
| `G` or `M` | move | `R` | fillet/chamfer (or rectangle in a sketch) |
| `X`/`Y`/`Z` | constrain move axis | `Ctrl` (drag) | snap to grid/geometry |
| `Esc` | cancel | `Enter` | commit / finish sketch |
| `Ctrl+Z` | undo | `Del` | delete selection |

## Download (Windows)

The easy path — no Python needed:

1. Grab `mini-cad-windows.zip` from the [latest release](../../releases/latest).
2. Unzip it anywhere.
3. Run `mini-cad.exe`.

It's a self-contained build (bundles the OCCT geometry kernel), so the download
is ~165 MB and the first launch takes a few seconds while Windows scans it.

## Run from source

For development, or to run on Python directly:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\run.ps1 app
```

Needs Python 3.10+ (3.11 recommended for the OCP wheels); `pip install` pulls in
`PySide6`, `cadquery-ocp`, `build123d`, and `shapely`. After install the
`cad-app` entry point works too.

## Build the exe yourself

```powershell
.\build_exe.ps1
```

This bundles everything with PyInstaller into `dist\mini-cad\` and packs
`dist\mini-cad-windows.zip`. Pushing a `v*` tag runs the same build on CI and
publishes a GitHub Release automatically.

## Layout

- `cad_app/` — application code: modeling commands, viewer, UI, project IO.
- `dev/` — local workflow & smoke scripts.
- `docs/` — architecture notes and behavior contracts.
- `tests/` — contract tests (core geometry + UI), run with `./run.sh check`.

## How it's built

Selection-first direct modeling: whatever you have selected — body, face, edge,
vertex, or sketch profile — decides which commands light up. The code favors
many small, explicit modeling operations over one big framework, so each
feature is easy to find and change. Yes, it was built with heavy AI assistance;
the contracts in `docs/` exist so behavior stays honest as it grows.

## Credits — it's a wrapper, and that's the point

To be upfront: **mini-cad is a thin UI on top of an existing geometry engine.**
All the hard geometry — booleans, fillets, lofts, STEP import/export — is
[OpenCASCADE (OCCT)](https://dev.opencascade.org/), reached through
[`cadquery-ocp`](https://github.com/CadQuery/ocp-build-system) and
[`build123d`](https://github.com/gumyr/build123d). None of the kernel math is
mine. What's mine is the layer *around* it: the PySide6/Qt interface, the
selection-first interaction model, snapping, the viewport wiring, and project
save/load. So this isn't a new CAD engine — it's a no-friction front-end that
lets OCCT do all the heavy lifting.

## Author

Pawel Zduniak — MIT licensed, see [LICENSE](LICENSE).
