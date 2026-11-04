# Decisioni di progetto

Scelte prese in autonomia durante lo sviluppo notturno, con la motivazione.

1. **Branch di lavoro: `main`.** Il prompt chiede push diretti su `main` (repo personale, niente PR).
2. **Sistema di coordinate interno**: metri, x ∈ [0, 105] lungo il campo, y ∈ [0, 68] con origine in basso a sinistra (y verso l'alto). La squadra di casa attacca sempre verso x = 105 in entrambi i tempi: il verso viene ricavato dai dati (posizione media della squadra di casa a inizio periodo) e, se serve, il periodo viene ruotato di 180°.
3. **Frame = array allineati al roster.** Invece di una lista di oggetti per giocatore, ogni `Frame` contiene un array `(n_giocatori, 2)` allineato al roster (`Player.index`), con NaN per chi non è in campo. Il roster include anche le riserve (Metrica ne ha 14 per squadra). È molto più veloce per le metriche vettoriali e per la serializzazione.
4. **`DataSource` con accesso casuale (`frame(i)`)** oltre all'iterazione: serve al seek del replay. Una sorgente live vera può implementare `frame(i)` su un buffer circolare.
5. **Sorgente sintetica sempre disponibile** (anche quando i dati Metrica ci sono): è il fixture dei test ed è utile per demo senza dati.
6. **Test con `python -m pytest`**: nell'ambiente cloud `pytest` globale punta a un altro interprete; `pythonpath = ["src"]` in pyproject rende i test robusti.
7. **Campione = 60 s del 1° tempo + 60 s del 2° tempo** (Game 1), invece di 2 minuti consecutivi: così i test coprono anche il cambio di lato.
8. **Identificativi giocatore** `H<n>` / `A<n>` (es. `H11`): brevi nei messaggi WebSocket e indipendenti dal provider.
9. **Portiere = prima colonna di ogni squadra** nei CSV Metrica (verificato sulle posizioni medie). Serve per la linea difensiva.
10. **Verso di attacco ricavato dai dati** (x media della squadra di casa nei primi 10 s di ogni periodo) invece di assumerlo: Game 1 e Game 2 hanno orientamenti opposti.
11. **Un messaggio ogni 40 ms indipendentemente dalla velocità**: a 10× il server avanza di 10 frame per tick ma invia solo l'ultimo snapshot (le metriche invece consumano tutti i frame). Il client interpola tra gli ultimi due snapshot con `requestAnimationFrame`, quindi il movimento resta fluido anche a 60 fps.
12. **Statistiche a ~5 Hz** (ogni 5 tick) e posizioni a 25 Hz, per tenere i messaggi piccoli. Il messaggio dopo un comando include sempre le statistiche.
13. **Posizioni come lista piatta `[x0, y0, x1, y1, ...]`** allineata al roster, arrotondate al centimetro, `null` per i giocatori fuori campo.
14. **Una sessione di replay per connessione WebSocket**: ogni spettatore ha il proprio replay (come un "DVR"); la sorgente dati è condivisa e caricata una sola volta (cache nel catalogo).
15. **Velocità ammesse**: 0.5×, 1×, 2×, 5×, 10× (0.5× aggiunto per analizzare le azioni).
