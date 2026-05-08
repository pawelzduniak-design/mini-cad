# Magic Lantern 5D3: pseudo-tests graniczne dla `12-bit hi-res lossless`

## Cel

Przed zmianami w kodzie chcemy wykryc, ktore elementy pipeline'u moga sie rozsypac po probie uruchomienia prawdziwego `12-bit` w hi-res cropach, szczegolnie dla `3.5K 1:1 centered x5`.

To nie jest plan benchmarku predkosci. To jest plan lapania regresji i punktow awarii:

- bledny format wejscia do kompresora,
- zly stride / offset / Bayer alignment,
- niedzialajacy preview,
- bledne metadata MLV,
- niestabilnosc start/stop,
- dropy w scenach o wysokiej entropii,
- rozjazd miedzy `mlv_lite`, `crop_rec` i `raw.c`.

## Aktualny model ryzyka

W obecnym kodzie istnieja trzy rozne mechanizmy "bitdepth":

1. `raw_lv_request_bpp()` w `raw.c`
2. `raw_lv_request_digital_gain()` w `raw.c`
3. `crop_rec` bitdepth przez ADTG podczas nagrywania

To nie jest jedna spojna sciezka.

Dodatkowo:

- `mlv_lite` dla lossless trzyma kontener `14-bit`
- wrapper kompresora lossless liczy wejsciowy layout jak `14-bit`
- preview dziala tylko dla `raw_info.bits_per_pixel == 14`
- `white_level` jest latany recznie w kilku miejscach

## Glowne hipotezy awarii

### H1. Prawdziwe `12-bit packed` rozwali wejscie kompresora

Powod:

- `lossless.c` liczy `src_adjusted`, `xb` i `off1b` uzywajac `14/8`.

Objaw:

- uszkodzone klatki,
- zly Bayer pattern,
- bledna kompresja,
- niestabilny rozmiar wyjscia,
- losowe artefakty lub crash.

### H2. Prawdziwe `12-bit packed` rozwali preview

Powod:

- `raw_preview_fast_ex2()` wychodzi od razu, jesli `raw_info.bits_per_pixel != 14`.

Objaw:

- brak framing preview,
- czarny albo nieodswiezajacy sie podglad,
- dziwne zachowanie tylko po wlaczeniu REC.

### H3. `crop_rec` i `mlv_lite` beda nadpisywac sobie interpretacje bitdepth

Powod:

- `crop_rec` ma wlasny `crop.bitdepth`,
- `mlv_lite` ma osobne `BPP` i `BPP_D`,
- `raw.c` utrzymuje `raw_info.bits_per_pixel` i `white_level`.

Objaw:

- metadata nie odpowiadaja realnym danym,
- MLV otwiera sie, ale ma zly histogram / ekspozycje / white level,
- problemy pojawiaja sie tylko w czesci presetow.

### H4. Naprawa `12-bit` poprawi przepustowosc, ale pogorszy stabilnosc przejsc stanu

Powod:

- po zmianie bitdepth beda inaczej zachowywac sie start REC, stop REC, half-shutter, powrot do 14-bit.

Objaw:

- po wyjsciu z REC zostaje zly preview,
- nastepne nagranie jest uszkodzone,
- tylko pierwsze nagranie dziala dobrze.

## Minimalna instrumentacja przed zmianami

Przed ruszaniem logiki warto dodac krotkie logi lub `bmp_printf/printf` w tych punktach:

1. `setup_bit_depth()` w `mlv_lite.c`
2. `setup_bit_depth_digital_gain()` w `mlv_lite.c`
3. `raw_lv_request_bpp()` w `raw.c`
4. `raw_lv_request_digital_gain()` w `raw.c`
5. wejscie do `lossless_compress_raw_rectangle()` w `lossless.c`
6. `raw_lv_settings_still_valid()` w `raw.c`
7. `raw_preview_fast_ex2()` w `raw.c`
8. zapis RAWI metadata w `mlv_lite.c`

Kazdy log powinien wypisywac minimum:

- preset crop,
- `raw_info.width`,
- `raw_info.height`,
- `raw_info.bits_per_pixel`,
- `BPP`,
- `BPP_D`,
- `bitdepth` z `crop_rec`,
- `white_level`,
- `pitch`,
- `frame_size`.

## Macierz pseudo-testow

### Grupa A. Testy spojnosci stanu

#### A1. Idle -> REC -> Idle bez hi-res crop

Cel:

- upewnic sie, ze logowanie niczego nie myli i mamy punkt odniesienia.

Wejscie:

- standardowy tryb RAW bez `crop_rec`,
- `14-bit lossless`,
- start i stop nagrania trzy razy.

Pass:

- `raw_info.bits_per_pixel`, `white_level`, `pitch` wracaja do stanu bazowego po kazdym klipie,
- preview nie degraduje sie po stopie,
- brak niespojnosci w logach.

#### A2. Idle -> REC -> Idle z `3.5K centered x5`, bez zmiany bitdepth

Cel:

- potwierdzic stan bazowy hi-res.

Wejscie:

- `crop_rec: 3.5K 1:1 centered x5`,
- `14-bit lossless`,
- trzy start/stop.

Pass:

- brak driftu rejestrow i metadata miedzy kolejnymi klipami,
- `white_level` i `pitch` pozostaja spojne,
- preview wraca do poprawnego stanu po stopie.

#### A3. Ten sam preset, ale z `crop_rec bitdepth = 12`

Cel:

- zobaczyc, co juz dzis zmienia sam `crop_rec`.

Pass:

- log pokaze, czy zmienil sie realny `raw_info.bits_per_pixel`, czy tylko `white_level`,
- wiemy dokladnie, ktora warstwa juz dotyka bitdepth.

### Grupa B. Testy kompresora

#### B1. Kompresor z wejsciem `14-bit` jako kontrola

Cel:

- zlapac bazowy `compressed_size`, czas kompresji i stabilnosc.

Wejscie:

- `3.5K centered x5`,
- `14-bit lossless`,
- 10-15 sekund sceny o niskiej entropii i wysokiej entropii.

Pass:

- znamy baseline dla:
  - czasu kompresji,
  - wielkosci klatki po kompresji,
  - liczby dropow.

#### B2. Symulacja "czy wrapper kompresora zaklada 14-bit"

Cel:

- sprawdzic, czy wszystkie obliczenia wejscia do kompresora sa zalezne od `14/8`.

Metoda:

- statyczny audit kodu i logi runtime dla:
  - `src_adjusted`,
  - `RD1_info.xb`,
  - `RD1_info.off1b`,
  - `TTL_Args.SamplePrecision`.

Pass:

- pelna lista miejsc, ktore musza zostac przelaczone z `14/8` na `bits_per_pixel/8` albo rownowazny wzor.

#### B3. Granica szerokosci i wysokosci

Cel:

- upewnic sie, ze nowy stride nie rozjedzie sie na granicznych rozdzielczosciach.

Wejscie:

- kilka wysokosci wokol praktycznej granicy, np. nizej niz 1320, okolo 1320 i minimalnie ponizej limitu stabilnosci.

Pass:

- brak roznic zachowania zaleznych od konkretnej wysokosci,
- brak objawow uszkodzenia tylko przy najwyzszym Y-res.

### Grupa C. Testy preview

#### C1. Preview kontrolne w 14-bit

Cel:

- miec wzorzec zachowania framing preview.

Pass:

- preview dziala przed REC, w REC i po REC.

#### C2. Wymuszenie `raw_info.bits_per_pixel != 14`

Cel:

- potwierdzic, ze obecny preview path odpada natychmiast.

Pass:

- log z `raw_preview_fast_ex2()` potwierdza, ze funkcja wychodzi wczesnie,
- wiemy, ze preview trzeba traktowac jako osobny temat, nie efekt uboczny.

#### C3. Half-shutter / zoom / przejscia LV

Cel:

- wykryc przejscia, ktore przy zmianie bitdepth najlatwiej zostawiaja system w zlym stanie.

Wejscie:

- half-shutter,
- wejscie/wyjscie z x5,
- start REC tuz po zmianie zoom,
- stop REC i natychmiast kolejny start.

Pass:

- preview i `raw_info` wracaja do spojnego stanu po kazdej sekwencji.

### Grupa D. Testy metadata i dekodowalnosci

#### D1. RAWI metadata kontra realny stan runtime

Cel:

- sprawdzic, czy MLV opisuje faktyczne dane.

Porownac:

- `rawi_hdr.raw_info.bits_per_pixel`,
- `rawi_hdr.raw_info.pitch`,
- `rawi_hdr.raw_info.white_level`,
- runtime `raw_info.*`,
- `bitdepth` z `crop_rec`.

Pass:

- nie ma sytuacji, gdzie plik mowi `12-bit`, a bufor / kompresor faktycznie dziala jak `14-bit`.

#### D2. Dekodowanie pliku poza aparatem

Cel:

- zlapac "dziala na aparacie, ale plik jest logicznie uszkodzony".

Metoda:

- po kazdym krytycznym tescie otworzyc MLV w zewnetrznym parserze i sprawdzic:
  - czy klatki sa czytelne,
  - czy histogram i ekspozycja sa sensowne,
  - czy nie ma skakania Bayer pattern.

Pass:

- material jest dekodowalny i wyglada spojnie.

### Grupa E. Testy dropogenne

#### E1. Scena niska entropia

Wejscie:

- duzo swiatla,
- malo detalu,
- niski ISO.

Cel:

- baseline minimalnego obciazenia.

#### E2. Scena wysoka entropia

Wejscie:

- ciemno,
- wysoki ISO,
- duzo drobnego detalu,
- lekki ruch w calym kadrze.

Cel:

- najgorszy realny przypadek dla lossless.

#### E3. Skok miedzy E1 i E2

Cel:

- wykryc problemy heurystyk i buforowania.

Wejscie:

- rozpoczac nagranie na latwej scenie,
- szybko przejsc na trudna scene bez zatrzymywania REC.

Pass dla E1-E3:

- log pokazuje:
  - `compressed_size`,
  - czas kompresji,
  - `queued_frames`,
  - write throughput,
  - dropy.

Najwazniejsze:

- patrzymy nie tylko na srednia, ale na najgorsze kilka klatek z rzedu.

### Grupa F. Testy przejsc konfiguracji

#### F1. 14-bit -> pseudo-12-bit -> 14-bit

Cel:

- upewnic sie, ze przejscia stanu nie zostawiaja zlych ustawien.

#### F2. `crop_rec OFF` -> `3.5K centered x5` -> `crop_rec OFF`

Cel:

- wykryc wycieki konfiguracji miedzy presetami.

#### F3. `mlv_lite` lossless OFF/ON podczas jednej sesji LV

Cel:

- wykryc niespojnosci przy wielokrotnym uzbrajaniu pipeline'u.

Pass:

- kazdy kolejny klip zachowuje sie identycznie do pierwszego.

## Kolejnosc wykonywania

1. Zalogowac i ustabilizowac testy bazowe `A1`, `A2`, `B1`, `C1`.
2. Zmierzyc dzisiejszy wplyw samego `crop_rec bitdepth` przez `A3`, `D1`.
3. Potwierdzic twarde zaleznosci od `14-bit` przez `B2`, `C2`.
4. Sprawdzic przejscia stanu przez `C3`, `F1`, `F2`, `F3`.
5. Dopiero potem odpalac sceny dropogenne `E1-E3`.

## Kryteria stop

Przerywamy wdrazanie prawdziwego `12-bit hi-res lossless`, jesli ktorykolwiek z tych punktow jest niespelniony:

- kompresor nadal ma choc jedno aktywne zalozenie `14/8`,
- preview nie ma osobnej sciezki dla `!= 14-bit`,
- metadata MLV nie sa jednoznacznie zgodne z realnym buforem,
- po stop/start pojawia sie drift stanu,
- `crop_rec` i `mlv_lite` nadal rownolegle steruja bitdepth bez jednego zrodla prawdy.

## Co z tego wynika praktycznie

Jesli te pseudo-testy potwierdza obecne przypuszczenia, to bezpieczna kolejnosc zmian bedzie taka:

1. Najpierw instrumentacja i jedno zrodlo prawdy dla bitdepth.
2. Potem poprawka wejscia kompresora lossless.
3. Potem preview dla `!= 14-bit`.
4. Dopiero na koncu heurystyki i tuning wydajnosci.
