# Decisioni di progetto

Scelte prese in autonomia durante lo sviluppo notturno, con la motivazione.

1. **Branch di lavoro: `main`.** Il prompt chiede push diretti su `main` (repo personale, niente PR).
2. **Sistema di coordinate interno**: metri, x ∈ [0, 105] lungo il campo, y ∈ [0, 68] con origine in basso a sinistra (y verso l'alto). La squadra di casa attacca sempre verso x = 105 in entrambi i tempi: il verso viene ricavato dai dati (posizione media della squadra di casa a inizio periodo) e, se serve, il periodo viene ruotato di 180°.
3. **Frame = array allineati al roster.** Invece di una lista di oggetti per giocatore, ogni `Frame` contiene un array `(n_giocatori, 2)` allineato al roster (`Player.index`), con NaN per chi non è in campo. Il roster include anche le riserve (Metrica ne ha 14 per squadra). È molto più veloce per le metriche vettoriali e per la serializzazione.
4. **`DataSource` con accesso casuale (`frame(i)`)** oltre all'iterazione: serve al seek del replay. Una sorgente live vera può implementare `frame(i)` su un buffer circolare.
5. **Sorgente sintetica sempre disponibile** (anche quando i dati Metrica ci sono): è il fixture dei test ed è utile per demo senza dati.
6. **Test con `python -m pytest`**: nell'ambiente cloud `pytest` globale punta a un altro interprete; `pythonpath = ["src"]` in pyproject rende i test robusti.
