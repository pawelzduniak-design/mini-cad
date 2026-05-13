# Tutorial GIFs

Generate the public tutorial animations with:

```powershell
.\run.ps1 tutorials
```

The generator opens the CAD window, moves the real Windows cursor with WinAPI,
sends real mouse/keyboard input, captures the desktop window with the current
system cursor, and writes GIF files to `docs/tutorials/gifs/`.
On Windows, OCCT may print `wglMakeCurrent() has failed` while closing capture
windows; treat that as non-fatal when the command exits with code 0 and all GIFs
are written.

Current tutorials:

- `01_hat_from_sketch_extrude.gif`: sketch circles and extrude a simple top hat.
- `02_revolve_lid_from_side_profile.gif`: sketch a side profile and revolve it.
- `03_move_and_rotate_body.gif`: move and rotate a body.
- `04_multi_body_move.gif`: Ctrl-select two bodies and move them together.
