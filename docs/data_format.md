# Formato dei dati Metrica Sports

Fonte: repository pubblico [`metrica-sports/sample-data`](https://github.com/metrica-sports/sample-data)
(scaricato con `python scripts/download_data.py` in `data/raw/metrica/`, ~230 MB, non committato).
Usiamo `Sample_Game_1` e `Sample_Game_2` (formato CSV). `Sample_Game_3` (formato FIFA/EPTS, JSON+XML) non è usato.

Tutto quello che segue è stato verificato ispezionando i file reali (non dato per scontato).

## File per partita

| File | Righe (Game 1) | Contenuto |
|---|---|---|
| `Sample_Game_N_RawTrackingData_Home_Team.csv` | 145 006 frame | posizioni dei giocatori di casa + palla |
| `Sample_Game_N_RawTrackingData_Away_Team.csv` | 145 006 frame | posizioni dei giocatori ospiti + palla |
| `Sample_Game_N_RawEventsData.csv` | 1 745 eventi | eventi manuali (passaggi, tiri, falli, ...) |

## Tracking: header su 3 righe

```
,,,Home,,Home,,Home,...            <- riga 1: squadra (solo sulle colonne x)
,,,11,,1,,2,...                    <- riga 2: numero di maglia (solo sulle colonne x)
Period,Frame,Time [s],Player11,,Player1,,...,Ball,   <- riga 3: nome colonna (x); la y ha nome vuoto
1,1,0.04,0.00082,0.48238,0.32648,0.65322,...
```

- Ogni giocatore occupa **due colonne consecutive** (x, y); la colonna y non ha nome.
- L'ultima coppia è la **palla** (identica nei due file Home/Away).
- **14 giocatori per squadra**: gli 11 titolari + 3 riserve. Le riserve hanno `NaN` finché non entrano;
  il giocatore sostituito ha `NaN` dopo l'uscita. Nel Game 1 ci sono frame con 23 giocatori validi (sovrapposizione al cambio).
- La **prima colonna di ogni squadra è il portiere** (Player11 Home, Player25 Away): verificato dalla posizione media.
- Gli id `PlayerN` sono unici tra le due squadre; il numero di maglia coincide con N.

## Campionamento e tempo

- **25 Hz** (Δt = 0.04 s), frame contigui da 1 a 145 006 (Game 1) / 141 156 (Game 2).
- `Time [s]` è continuo: il secondo tempo **non riparte da 0** (Game 1: il periodo 2 inizia al frame 71 269, t = 2850.76 s).
  L'intervallo non è presente nei dati (nessun buco nei frame).
- `Period` ∈ {1, 2}.

## Coordinate

- Normalizzate in [0, 1] con **origine in alto a sinistra** (x verso destra, y verso il basso).
- Valori leggermente fuori da [0, 1] sono presenti (palla fino a −0.045 / 1.06, giocatori fino a ±0.05): palla fuori campo
  o giocatori oltre la linea. Non vengono tagliati.
- Conversione nel sistema interno (metri, campo 105 × 68, origine in basso a sinistra, y verso l'alto):
  `x_m = x · 105`, `y_m = (1 − y) · 68`.
- **Palla NaN nel ~39% dei frame** (Game 1; 41% Game 2): palla non tracciata (fuori dal gioco, pause, intervallo).
  I NaN vengono mantenuti; le metriche ignorano i frame senza palla.

## Cambio di lato

Le coordinate sono "di campo", quindi le squadre si scambiano lato tra i tempi, e non nello stesso modo nelle due partite:

| | Home nel 1° tempo | Home nel 2° tempo |
|---|---|---|
| Game 1 | difende a sinistra (portiere x≈0.12) | difende a destra (x≈0.91) |
| Game 2 | difende a destra (x≈0.87) | difende a sinistra (x≈0.12) |

Il loader decide **per ogni periodo** se ruotare di 180° (`x → 105 − x`, `y → 68 − y`) guardando la x media della squadra di casa
nei primi 10 s del periodo: se è nella metà destra, il periodo viene ruotato. Risultato: **la squadra di casa attacca sempre verso x = 105**.
La stessa rotazione è applicata alle coordinate degli eventi. Verifica: dopo la normalizzazione tutti i gol Home sono a x ≈ 97–103 e quelli Away a x ≈ 8–13.

Nota: la rotazione introduce un "salto" tra l'ultimo frame del 1° tempo e il primo del 2°; le metriche azzerano lo stato di velocità a ogni cambio di periodo.

## Eventi

```
Team,Type,Subtype,Period,Start Frame,Start Time [s],End Frame,End Time [s],From,To,Start X,Start Y,End X,End Y
Away,SET PIECE,KICK OFF,1,1,0.04,0,0,Player19,,NaN,NaN,NaN,NaN
Away,PASS,,1,1,0.04,3,0.12,Player19,Player21,0.45,0.39,0.55,0.43
```

- Coordinate con la stessa convenzione del tracking (normalizzate, origine in alto a sinistra), con 2 decimali.
- `Start Frame` riferito alla numerazione del tracking (1-based) → convertito in indice 0-based.
- `End Frame = 0` significa "evento istantaneo".
- Tipi (Game 1): PASS 799, RECOVERY 278, BALL LOST 257, CHALLENGE 233, SET PIECE 77, BALL OUT 51, SHOT 24, FAULT RECEIVED 22, CARD 4.
- **Gol**: `Type = SHOT` e `Subtype` contiene `GOAL` (es. `ON TARGET-GOAL`, `HEAD-ON TARGET-GOAL`). Game 1: 3–0 per Home (nei dati);
  Game 2: 3–2 per Home.
- Il sottotipo combina più etichette con `-` (es. `CHALLENGE / TACKLE-FAULT-LOST`).

## Campione committato (`data/sample/`)

`scripts/make_sample.py` crea `data/sample/Sample_Game_1/` con **i primi 95 s del 1° tempo e i primi 25 s del 2°** del Game 1 (3 000 frame totali, incluso il primo gol al minuto 01:31,
~1.3 MB) nello stesso formato CSV, più gli eventi che cadono in quelle finestre. Include entrambi i tempi per testare il cambio di lato.
In questo caso i frame **non sono contigui** (salto dal frame 2 375 al 71 269): il loader usa l'indice di riga come `frame_id` interno e
mappa gli eventi tramite il numero di frame originale.
