# Visual Redesign

## Problem

Poprzedni interfejs działał funkcjonalnie, ale wyglądał jak prototyp Qt/OCP:

- jasne systemowe toolbary konkurowały z viewportem,
- akcje kontekstowe były wizualnie podobne do trybów pracy,
- prawy panel wyglądał bardziej jak debug lista niż panel CAD,
- status bar był czytelny technicznie, ale nie miał hierarchii,
- kolory viewportu i markerów były rozrzucone po kodzie.

## Kierunek

Nowy kierunek to lekki, nowoczesny direct-modeling CAD:

- ciemny top bar i sidebar,
- spokojny grafitowy viewport jako centrum pracy,
- jasny panel Model/Properties,
- jeden główny akcent: niebieski,
- szare neutralne bryły,
- niebieskie hover/selection/preview dla operacji,
- pigułkowy context toolbar nad viewportem.

## Design System

Centralne tokeny są w `cad_app/theme.py`.

Kolory obejmują:

- `APP_BG_DARK`, `TOP_BAR_BG`, `SIDEBAR_BG`, `VIEWPORT_BG`,
- `PANEL_BG`, `PANEL_BORDER`,
- `TEXT_PRIMARY`, `TEXT_SECONDARY`, `DISABLED_TEXT`,
- `ACCENT_BLUE`, `ACCENT_BLUE_HOVER`, `ACCENT_BLUE_ACTIVE`,
- `GRID_MAJOR`, `GRID_MINOR`,
- `BODY_DEFAULT`, `BODY_EDGE`,
- `FACE_HOVER`, `FACE_SELECTED`, `PREVIEW_BLUE`,
- `SKETCH_PROFILE`, `SKETCH_ENTITY`, `TOOLTIP_BG`.

Spacing i rozmiary:

- `SIDEBAR_WIDTH`,
- `RIGHT_PANEL_WIDTH`,
- `STATUS_BAR_HEIGHT`,
- `BORDER_RADIUS`,
- `SIDEBAR_ICON_SIZE`,
- `CONTEXT_ICON_SIZE`,
- `TOP_ICON_SIZE`.

## Top Bar

Top bar jest ciemny i globalny. Zawiera nazwę aplikacji oraz kompaktowe akcje:

- Undo,
- Redo,
- Save,
- Export STEP.

Menu `File`, `Edit`, `View` nadal istnieją, ale wizualnie są częścią ciemnej belki.

## Left Sidebar

Lewy sidebar ma ciemne tło i sekcje:

- `WORKSPACE`,
- `SELECTION`.

Aktywny tryb ma niebieskie tło, hover jest subtelny, a disabled state jest przygaszony.
Zachowane zostały istniejące tryby pracy, żeby nie usuwać funkcji.

## Context Toolbar

Context toolbar został przeniesiony nad viewport. Jest ukrywany, gdy nie ma sensownych akcji.

Przy zaznaczonym elemencie pokazuje tylko kontekstowe operacje, np.:

- `Extrude Face`,
- `Move Face`,
- `Offset Face`,
- `Fillet Edge`,
- `Chamfer Edge`,
- `Extrude Sketch`,
- `New Body`.

Przyciski są pigułkowe, ciemne, z niebieskim hover/active akcentem.

## Viewport

Viewport ma ciemny grafitowy background. Grid jest subtelny, osie są czytelne, ale nie dominują.

Geometria:

- body: neutralny szary półmat,
- edges: ciemny techniczny obrys,
- face hover: delikatny niebieski,
- selected face: mocniejszy niebieski,
- preview/extrude ghost: półprzezroczysty niebieski,
- sketch profile/entity: niebieski akcent zgodny z resztą UI.

Manipulator extrude używa koloru `PREVIEW_BLUE`, a overlay wymiaru pokazuje wartość blisko akcji.

## Right Panel

Prawy panel jest jasny i spokojny. Zakładki mają niebieskie podkreślenie aktywnego taba.

Panel `Model` pokazuje teraz bardziej produktowe pojęcia:

- `Model Tree`,
- `Part 1`,
- aktywny obiekt.

Panel `Properties` pokazuje kontekst:

- tryb,
- selection mode,
- selection,
- active body/sketch,
- parametry aktywnej operacji extrude/move, jeśli trwa operacja.

## Status Bar

Status bar jest niski i ciemny. Pokazuje:

- bieżący komunikat,
- Mode,
- Selection,
- Select mode,
- Tool,
- Sketch.

Jest pomocniczy, nie dominuje nad viewportem.

## Remaining Polish

Do kolejnych iteracji warto jeszcze dopracować:

- prawdziwy formularz Properties zamiast listy tekstowej,
- aktywny stan przycisku aktualnie wykonywanej operacji w context toolbar,
- bardziej zaawansowany gradient viewportu, jeśli OCP backend pozwoli bez artefaktów,
- custom overlay z rich text, żeby wartość wymiaru była niebieska, a etykieta biała,
- lepsze ikony dla `Measure`, `Create`, `Transform` jako dedykowane assety.
