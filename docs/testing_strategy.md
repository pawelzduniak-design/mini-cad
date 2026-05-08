# CAD testing strategy

## Dlaczego ad hoc testy nie wystarcza

Direct Modeling CAD ma latwe do przeoczenia bledy zakresu operacji. Klikniecie w
sciane nadal ma wlasciciela body, ale komenda nie moze uzyc wlasciciela jako
fallbacku, jesli kontrakt wymaga lokalnej topologii. Dlatego testy musza
sprawdzac caly lancuch: selection type, routing komendy, mutacje modelu,
undo/redo, walidacje BRep i stan UI.

## Global invariants

- Click, hover i zmiana selection nie moga mutowac modelu.
- Selection type musi pasowac do aktywnego selection mode.
- Owner body jest tylko kontekstem dla face/edge/vertex, nie celem fallback.
- Blocked albo failed-safe command zostawia model bez zmian.
- Kazda udana mutacja ma undo snapshot.
- Undo przywraca stan sprzed operacji, redo odtwarza wynik.
- Wszystkie ksztalty po operacji przechodza BRepCheck_Analyzer.
- UI nie moze pokazywac idle, gdy dziala szkic, extrude albo transform.

## Command contract matrix

Kontrakty sa w `tests/cad_safety/contracts.py`. Macierz laczy kazda komende z
typami selection:

- `DELETE_OBJECT`: tylko `OBJECT`.
- `DELETE_FACE`: tylko `FACE`; dopoki nie ma implementacji, ma fail-safe.
- `MOVE_OBJECT`: tylko `OBJECT`.
- `MOVE_FACE`: tylko `FACE`.
- `MOVE_EDGE`: tylko `EDGE`.
- `EXTRUDE_PROFILE`: tylko `SKETCH_PROFILE`.
- `EXTRUDE_FACE`: tylko `FACE`.
- `BOOLEAN_*`: tylko `OBJECT` i tylko dla body-body.

Test `tests/test_command_contract_matrix.py` odpala kazda pare. Dla forbidden
selection wymaga statusu `blocked` i identycznego fingerprintu modelu. Dla
allowed selection akceptuje `success` albo `failed_safe`, ale failed-safe tez
musi zostawic model bez zmian.

## Snapshots and fingerprints

Snapshoty sa w `tests/cad_safety/snapshots.py`. Zawieraja:

- liczbe bodies i sketches,
- selection i active item,
- depth undo/redo,
- face/edge/vertex/solid count per shape,
- bbox, volume, center of mass,
- wynik BRepCheck,
- hash fingerprint.

Fingerprint sluzy do twardego wykrywania przypadkow typu "blocked command
zmienila model" albo "undo nie przywrocilo stanu".

## Fixture models

Modele sa w `tests/fixtures/model_factory.py`:

- `SingleBox`: 60 x 40 x 20.
- `BoxWithTopLevel`: baza 80 x 50 x 15 plus pietro 40 x 30 x 20.
- `BoxWithCylinder`: baza plus boss cylindryczny.
- `BoxWithCutout`: baza z wycieciem cylindrycznym.
- `SketchProfiles`: rectangle, circle, closed polyline, arc+chord, sketch entity.

## Workflow tests

`tests/test_user_workflows.py` pokrywa uzytkowe scenariusze:

- sketch rectangle -> extrude profile -> extrude face -> undo/redo -> STEP export,
- face operation na `BoxWithTopLevel` nie usuwa body,
- Object delete usuwa body, Face selection nie usuwa body,
- unimplemented Offset Face fail-safe zostawia model bez zmian.

## Random sequence tests

`tests/test_random_command_sequences.py` uzywa stalego seed `20260507` i miesza:
selection, komendy, undo, redo i clear selection. Po kazdym kroku sprawdzane sa
globalne invariants. Ten test nie zastapi macierzy kontraktow, ale dobrze lapie
nieoczywiste interakcje miedzy undo, selection i kolejnymi komendami.

## UI state contracts

`cad_app.main_window.ViewerWidget.get_ui_state()` zwraca stabilny stan bez
pelnego renderowania GUI:

- work mode,
- selection mode i selection type,
- active tool,
- active operation,
- context actions,
- status/hint text,
- overlay/manipulator visibility,
- right panel context.

`tests/test_ui_state_contracts.py` sprawdza miedzy innymi, ze face selection
pokazuje `Sketch on Face`, nie pokazuje `Delete Object`, a aktywny Extrude nie
jest raportowany jako idle.

## Jak uruchomic

Pelny standardowy zestaw:

```powershell
python -m pytest
python -m ruff check cad_app tests dev
python -m black --check cad_app tests dev
```

Tylko safety harness:

```powershell
python -m dev.run_cad_safety_tests
```

Jesli w katalogu projektu jest `.venv`, uzyj jego interpretera zamiast `python`.

## Jak interpretowac logi

Runner pokazuje grupy:

```text
=== CAD Safety & Workflow Test Suite ===
[INFO] Running contract matrix
[PASS] contract matrix
...
=== RESULT: PASS ===
```

`blocked` oznacza, ze kontrakt zabrania komendy dla danego selection. `failed_safe`
oznacza, ze komenda jest dozwolona, ale operacja nie zostala wykonana i model
pozostal bez zmian. To jest akceptowalne dla komend jeszcze niezaimplementowanych
albo topologii, ktorej engine nie wspiera.

## Rules for adding new CAD commands

1. Dodaj `CommandType` i `CommandContract`.
2. Zdefiniuj allowed selection types i forbidden fallback behavior.
3. Dodaj egzekucje w `SafetyHarness._execute_allowed`.
4. Dodaj fixture, jesli komenda wymaga specjalnej topologii.
5. Dodaj workflow test dla typowego uzytkownika.
6. Jesli komenda ma UI, rozszerz `get_ui_state()` albo test context actions.
7. Blocked i failed-safe sciezki musza zostawiac identyczny fingerprint modelu.
