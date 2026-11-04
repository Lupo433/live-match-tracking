# Decisioni di progetto

Scelte prese in autonomia durante lo sviluppo notturno, con la motivazione.

1. **Branch di lavoro: `main`.** Il prompt chiede push diretti su `main` (repo personale, niente PR).
2. **Sistema di coordinate interno**: metri, x ∈ [0, 105] lungo il campo, y ∈ [0, 68] con origine in basso a sinistra (y verso l'alto). La squadra di casa attacca sempre verso x = 105 in entrambi i tempi: il verso viene ricavato dai dati (posizione media della squadra di casa a inizio periodo) e, se serve, il periodo viene ruotato di 180°.
3. **Frame = array allineati al roster.** Invece di una lista di oggetti per giocatore, ogni `Frame` contiene un array `(n_giocatori, 2)` allineato al roster (`Player.index`), con NaN per chi non è in campo. Il roster include anche le riserve (Metrica ne ha 14 per squadra). È molto più veloce per le metriche vettoriali e per la serializzazione.
4. **`DataSource` con accesso casuale (`frame(i)`)** oltre all'iterazione: serve al seek del replay. Una sorgente live vera può implementare `frame(i)` su un buffer circolare.
5. **Sorgente sintetica sempre disponibile** (anche quando i dati Metrica ci sono): è il fixture dei test ed è utile per demo senza dati.
6. **Test con `python -m pytest`**: nell'ambiente cloud `pytest` globale punta a un altro interprete; `pythonpath = ["src"]` in pyproject rende i test robusti.
7. **Campione = 95 s del 1° tempo + 25 s del 2° tempo** (Game 1), invece di 2 minuti consecutivi: così i test coprono il cambio di lato e il primo gol (01:31). Inizialmente era 60 s + 60 s; esteso nella seconda sessione per includere un gol.
8. **Identificativi giocatore** `H<n>` / `A<n>` (es. `H11`): brevi nei messaggi WebSocket e indipendenti dal provider.
9. **Portiere = prima colonna di ogni squadra** nei CSV Metrica (verificato sulle posizioni medie). Serve per la linea difensiva.
10. **Verso di attacco ricavato dai dati** (x media della squadra di casa nei primi 10 s di ogni periodo) invece di assumerlo: Game 1 e Game 2 hanno orientamenti opposti.
11. **Un messaggio ogni 40 ms indipendentemente dalla velocità**: a 10× il server avanza di 10 frame per tick ma invia solo l'ultimo snapshot (le metriche invece consumano tutti i frame). Il client interpola tra gli ultimi due snapshot con `requestAnimationFrame`, quindi il movimento resta fluido anche a 60 fps.
12. **Statistiche a ~5 Hz** (ogni 5 tick) e posizioni a 25 Hz, per tenere i messaggi piccoli. Il messaggio dopo un comando include sempre le statistiche.
13. **Posizioni come lista piatta `[x0, y0, x1, y1, ...]`** allineata al roster, arrotondate al centimetro, `null` per i giocatori fuori campo.
14. **Una sessione di replay per connessione WebSocket**: ogni spettatore ha il proprio replay (come un "DVR"); la sorgente dati è condivisa e caricata una sola volta (cache nel catalogo).
15. **Velocità ammesse**: 0.5×, 1×, 2×, 5×, 10× (0.5× aggiunto per analizzare le azioni).
16. **Distanza dai passi grezzi, velocità dal filtro Savitzky-Golay** (finestra 11 frame = 0.44 s, polinomio di grado 2, derivata al centro della finestra). La distanza grezza è esatta per moto rettilineo (test: 5 m/s × 10 s = 50 m); i dati Metrica sono già puliti. Passi > 15 m/s (salti di tracking, rientri in campo, cambio di periodo) non vengono contati e fanno ripartire la finestra di smoothing.
17. **Sprint e alta intensità come "sforzi"**: si conta uno sforzo quando la velocità resta sopra soglia (7 / 5.5 m/s) per almeno 1 s; la distanza dello sforzo include anche il tratto prima del secondo di qualificazione. La velocità filtrata ha un ritardo di mezza finestra (5 frame): per allinearla ai metri percorsi si usa il passo del frame centrale della finestra.
18. **Velocità > 12.5 m/s scartate** come glitch (non contano per velocità massima e sprint). Palla: finestra 5, grado 1, max 45 m/s.
19. **Possesso**: squadra del giocatore più vicino alla palla entro 3 m; se nessuno è vicino (passaggio in volo) il possesso resta all'ultima squadra; i frame con palla non tracciata (palla non in gioco) sono esclusi.
20. **Linea difensiva** = distanza media dalla propria porta dei 4 giocatori di movimento più arretrati (portiere escluso). Forma di squadra campionata a 5 Hz solo a palla in gioco; il valore "attuale" è una media mobile esponenziale.
21. **Pitch control semplificato** (tempo di intercetto alla Spearman 2017): tempo di arrivo = 0.7 s di reazione + distanza dalla posizione proiettata / 5 m/s, probabilità logistica (σ = 0.45 s) sulla differenza tra il giocatore più veloce di ciascuna squadra. Griglia 32×21. La percentuale cumulata è campionata una volta al secondo di gioco; la griglia per l'overlay è calcolata su richiesta solo quando serve allo snapshot.
22. **Checkpoint condivisi in background** invece di ricalcolare tutto a ogni seek: ~250 µs/frame per l'intero motore ⇒ ~35 s per una partita intera, fatti una volta sola in un thread; ogni seek riparte dal checkpoint più vicino (≤ 1 minuto di frame da riprocessare).
23. **Linea difensiva e baricentro dell'overlay calcolati nel browser** dalle posizioni mostrate (stessa regola del server), così il disegno è sempre allineato al frame visualizzato anche quando le statistiche arrivano a 5 Hz.
24. **Frontend senza framework**: una pagina statica servita da FastAPI (`/` e `/static`), canvas 2D con layer del campo pre-renderizzato su un canvas offscreen (le linee non vengono ridisegnate a ogni frame). Tema scuro, colori casa rosso corallo / ospiti azzurro, portieri in giallo e viola come nelle divise reali.
25. **Orologio "da TV"** (il secondo tempo parte da 45:00) nello scoreboard e nel feed eventi; la timeline mostra invece il tempo effettivo trascorso / durata totale.
26. **Banner del gol solo per gol "vissuti"** (entro 10 s di gioco dal frame mostrato), non quando un seek supera un gol.
27. **Feed eventi filtrato** su eventi rilevanti (tiri, gol, cartellini, falli, calci piazzati): i ~800 passaggi a partita renderebbero il feed illeggibile; i passaggi sono comunque contati nelle statistiche.
28. **Partita di default**: Game 1 completo se scaricato, altrimenti il campione, altrimenti la sintetica.
