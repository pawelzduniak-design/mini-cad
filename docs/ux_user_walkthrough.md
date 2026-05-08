# UX User Walkthrough

## Cel

Sprawdzic, czy uzytkownik bez znajomosci kodu potrafi wykonac:
Sketch -> closed profile selection -> Extrude -> Face edit -> Export STEP.

## Zasady testu

- Testujemy ekran, nie wewnetrzny stan.
- Jesli uzytkownik musi zgadywac nastepny krok, to FAIL.
- Jesli HUD, status bar i aktywne przyciski pokazuja sprzeczne stany, to FAIL.
- Jesli brak widocznego nastepnego kroku albo sposobu anulowania, to FAIL.

## Scenariusz 1: Rectangle to Extrude

1. Start app.

   Uzytkownik widzi pusty viewport, siatke, aktywny tryb `Select`, selection mode `Object`, `Tool: idle`.
   Hint powinien prowadzic do wyboru trybu albo narzedzia.
   PASS: nie ma jednoczesnie aktywnych trybow Sketch/Modify/Transform.
   FAIL: status sugeruje inny tryb niz podswietlony przycisk.

2. Kliknij `Sketch`.

   Na pustej scenie klik `Sketch` startuje szkic na XY tak samo jak klawisz `S`.
   Uzytkownik widzi narzedzia szkicu w adaptive menu.
   Hint: `Center Rectangle: click center, drag size, release`.
   PASS: `Sketch` i `S` sa tozsame dla pustej sceny.
   FAIL: klik `Sketch` tylko pokazuje `Start Sketch`, a `S` robi cos innego.

3. Wybierz `Center Rectangle`.

   Aktywny przycisk Center Rectangle jest checked.
   HUD pokazuje `Mode: Sketch`, `Select: face`, `Tool: Sketch center_rectangle`.
   PASS: uzytkownik widzi aktywne narzedzie.
   FAIL: status mowi `Tool: idle`.

4. Narysuj prostokat.

   Podczas dragowania widac preview profilu i overlay wymiarow, np. `W: 60.00 mm, H: 30.00 mm`.
   PASS: overlay jest blisko kursora.
   FAIL: wymiar jest tylko w status barze.

5. Po zatwierdzeniu prostokata najedz na jego wnetrze.

   Profil jest polprzezroczysty, nie wyglada jak biala bryla.
   Hover profilu ma delikatne wypelnienie i hint `Sketch Profile - click inside to select`.
   PASS: mozna kliknac wnetrze profilu.
   FAIL: trzeba trafic dokladnie w krawedz.

6. Zaznacz profil.

   HUD pokazuje `Selection: Sketch Profile`, adaptive menu pokazuje `Extrude Sketch`.
   Hint: `Sketch Profile selected - Extrude is available`.
   PASS: uzytkownik rozumie, ze nastepnym krokiem jest Extrude.
   FAIL: status mowi `Selection: face 1` bez informacji, ze to profil szkicu.

7. Kliknij `Extrude Sketch` albo nacisnij `E`.

   Widac overlay wymiaru `Extrude: 0.00 mm`, strzalke/uchwyt kierunku i hint:
   `Drag arrow to extrude, Enter accept, Esc cancel`.
   PASS: widac co przeciagac i jak zatwierdzic/anulowac.
   FAIL: widac tylko samotny tooltip z wartoscia.

8. Przeciagnij i zatwierdz Enter albo puszczeniem myszy.

   Powstaje neutralna szara bryla z czytelnymi krawedziami.
   PASS: profil szkicu nie zostaje jako niewyjasniona biala plama.
   FAIL: wynik wyglada jak plaski profil bez informacji, czy operacja sie udala.

## Scenariusz 2: Circle to Cylinder

1. Wejdz w `Sketch`.
2. Wybierz `Circle`.
3. Kliknij srodek.
4. Rusz mysz, zeby ustawic promien.
5. Kliknij, zeby zatwierdzic.
6. Najedz na wnetrze okregu i wybierz profil.
7. Uruchom `Extrude Sketch`.

PASS: overlay pokazuje `R: ... mm`, profil okregu jest wypelniony i wybieralny od srodka.
FAIL: trzeba klikac obwod okregu albo UI nie pokazuje, ze okrag jest gotowym profilem.

## Scenariusz 3: Face edit

1. Przelacz `Face` mode.
2. Kliknij sciane bryly.
3. Sprawdz adaptive menu.
4. Uruchom `Extrude Face` albo `Move Normal`.

PASS: sciana ma wyrazny highlight, adaptive menu pokazuje akcje face, a operacja pokazuje hint i wymiar.
FAIL: caly model wyglada jak zaznaczony albo status nie odroznia body/face/profile.

## Scenariusz 4: Export

1. Po utworzeniu bryly wybierz `Export`.
2. Zapisz STEP.

PASS: plik istnieje i ma rozmiar wiekszy niz 0.
FAIL: export jest aktywny bez aktywnej bryly albo nie ma jasnego komunikatu bledu.

## Known UX Blockers Fixed

- Klik `Sketch` na pustej scenie startuje szkic tak samo jak `S`.
- W trakcie szkicu HUD pokazuje `Mode: Sketch`, a nie mylace `Modify`.
- Sketch profile sa renderowane jako polprzezroczyste profile, nie jak biale bryly.
- Zaznaczony sketch profile pokazuje `Selection: Sketch Profile`.
- Extrude pokazuje hint z instrukcja Enter/Esc oraz viewportowy affordance w postaci strzalki.
- Overlay wymiaru Extrude jest widoczny juz po starcie narzedzia.

## Remaining UX Blockers

- Strzalka Extrude jest prostym overlayem 2D, a nie pelnym manipulatorem 3D z hit-testem uchwytu.
- Wpisywanie wartosci liczbowej podczas aktywnego Extrude nadal wymaga osobnej implementacji.
- Face/body hover i selection sa oparte na markerach AIS; warto dodac bardziej konsekwentny outline dla body.
- UX test nadal wymaga manualnego przejscia ekranu, bo automatyczny smoke log nie widzi wszystkich subtelnosci renderingu OCP.
