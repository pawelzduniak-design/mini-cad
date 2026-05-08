# Human Visual Smoke Test

## Pierwsze wrazenie po uruchomieniu

- co widac: viewport 3D jest widoczny, nie jest czarny, siatka i osie sa czytelne, a kamera patrzy na srodek sceny.
- co jest niejasne: bez podpowiedzi startowej uzytkownik widzi pusta scene i musi zgadnac, czy zaczac od Sketch, Create, czy importu.
- co moze zaniepokoic uzytkownika: pusta scena moze wygladac jak brak modelu albo brak renderingu, jesli nie ma jasnego komunikatu "Start".

## Krytyczne problemy UX

- Zdublowane tryby `Object/Face/Edge/Vertex` na lewym pasku wygladaly jak dwa rozne zestawy narzedzi robiace to samo.
- Marker plaszczyzny Sketch wygladal jak zamkniety prostokat/profil, mimo ze byl tylko wizualna ramka plaszczyzny.
- Brak stalej podpowiedzi startowej na pustej scenie wymagal domyslania sie pierwszego kroku.

## Problemy z widocznoscia

- Tlo i siatka maja wystarczajacy kontrast.
- Osie sa widoczne i daja punkt odniesienia.
- Neutralne bryly kontrastuja z tlem.
- Sketch profile i preview wymagaja mocnego koloru, szczegolnie kiedy szkic jest rysowany na jasnej scianie.
- Hint w lewym gornym rogu jest uzyteczny, ale musi byc krotki, bo lezy nad viewportem.

## Problemy ze sciezka uzytkownika

- Start: uzytkownik wie, ze program dziala, ale bez hintu nie wie, co zrobic jako pierwsze.
- Sketch: po kliknieciu Sketch narzedzia sa dostepne w tym samym lewym obszarze, ale marker plaszczyzny nie moze wygladac jak gotowy profil.
- Selection: hover i selection sa widoczne, ale na zlozonej topologii trzeba ukrywac operacje, ktore nie zadzialaja.
- Edge move: na brylach z krzywymi powierzchniami operacja nie powinna byc pokazywana, bo obecny algorytm obsluguje tylko bryly plasko-scienne.

## Minimalne poprawki wymagane przed dalszym kodowaniem

- Pokazac krotka podpowiedz startowa na pustej scenie.
- Usunac duplikaty trybow selekcji z adaptive command toolbar.
- Zmienic marker plaszczyzny Sketch tak, zeby nie wygladal jak zamkniety profil.
- Utrzymac wysoki kontrast szkicu na jasnych scianach.
- Blokowac lokalne Move Edge/Vertex/Face, gdy topologia nie jest obslugiwana.

## Propozycje konkretnych zmian w kodzie

- Startup: pokazac `Start: Sketch on the grid or Create a body`.
- Adaptive menu: w trybie `Select` nie dublowac `Object/Face/Edge/Vertex`, bo jest osobny selection-mode toolbar.
- Sketch plane: rysowac tylko narozne ticki i krotki krzyz osi, nie pelna zamknieta ramke.
- Workplane marker: renderowac jako wireframe marker.
- Visual regression: dodac `python -m dev.mama_opens_cad_check`, ktory zapisuje screenshot startowy i sprawdza, czy viewport nie jest czarny/pusty.
