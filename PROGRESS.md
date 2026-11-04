# Stato di avanzamento

## Sessione 2 (notte 4→5 novembre 2026)

### Tappa 1 — Solidità e demo ✅
- Cache su disco (`.cache/`): CSV convertiti e checkpoint delle metriche, con invalidazione per hash/mtime e recupero da file corrotti.
  Game 1: primo avvio 10.4 s + 38.7 s di pre-calcolo → secondo avvio **1.2 s + 0.04 s**.
- Gol temporizzati al passaggio della linea di porta (8/8 rilevati), con fallback al frame del tiro.
- Campione esteso a 95 s + 25 s per includere il primo gol.
- `docs/demo.gif` (13 s, 4.2 MB) e 3 screenshot generati con `scripts/make_demo.js` (Playwright + ffmpeg).
- `Dockerfile`, `.dockerignore`, `docs/deploy.md` (Fly.io, Render). **Build Docker non testata** (Docker Hub ha risposto 429);
  verificato lo scenario equivalente con `pip install .` non-editable.
- Prestazioni a 10× sul Game 2 (rimisurate): con pre-calcolo in corso 25 msg/s (40.1 ms medi, p99 99.7 ms), 2 500 frame su
  2 509 attesi; con checkpoint già in cache 40.0 ms medi, **p99 45.2 ms**, 2 508/2 509; metriche sempre sincronizzate.

### Tappa 2 — Feed live simulato end-to-end ✅
- `livematch/live/provider.py` + `scripts/fake_provider.py`: provider WebSocket a 25 Hz con formato diverso (id opachi,
  coordinate 0–1 "da stadio", ms), ritardo, perdita, riordino e disconnessioni.
- `ProviderFeedSource` (in `sources/live_stub.py`): roster dal line-up, conversione in metri, verso d'attacco per tempo
  (portieri), `JitterBuffer` con buchi → frame NaN, riconnessione, gol trattenuti fino alla linea.
- `LiveClock` (live edge + DVR), comando `go_live`, campi `live/at_edge/lag/ev/n` nel messaggio `frame`;
  badge LIVE/DVR e pulsante "Torna al live" nel frontend.
- `python -m livematch --live-demo`. 9 test nuovi, incluso un end-to-end su WebSocket vero con disconnessioni ogni secondo.
- Prestazioni a 10× sul Game 2 dopo le modifiche alla sessione: 40.0 ms medi, p99 46.8 ms, 2 509/2 509 frame, sync 1.0.

### Tappa 3 — Analytics ✅
- xT (griglia 16×12, iterazione del valore, conduzioni ricavate dagli eventi), xG logistico regolarizzato su distanza e
  angolo (N = 48 tiri, IC 95% bootstrap riportati: modello dimostrativo), modelli in `analytics/models.json`
  (`scripts/fit_models.py`).
- xT/xG accumulati live nel motore (`metrics/threat.py`), nel pannello, nella tabella giocatori e come curve a gradini
  sopra la timeline.
- Rete dei passaggi (overlay + endpoint), report post-partita HTML autonomo (endpoint, CLI, pulsante "Report ↗").
- Prestazioni a 10× sul Game 2: 40.0 ms medi, p99 48.1 ms, 2 498/2 500 frame, sync 1.0.
- 10 test nuovi (xT con risultato noto su griglia 2×1, conduzioni, xG monotono, rete passaggi, tracker incrementale = batch,
  report via API e CLI).

### Tappa 4 — Angolo marketing ✅
- Excitement index per secondo (5 componenti documentate in `docs/excitement_index.md`), incrementale nel motore,
  traccia sulla timeline e valore live (`st.exc`).
- `livematch/engagement/`: schema lungo, allineamento con offset, event study (lift), profilo medio, correlazione con ritardo;
  generatore SINTETICO con seed fisso + `scripts/make_synthetic_engagement.py` (CSV d'esempio del campione).
- Scheda "Marketing" con etichetta DATI SINTETICI DIMOSTRATIVI, endpoint `/api/matches/{id}/marketing`.
- Prestazioni a 10× sul Game 2: durante il pre-calcolo 40.0 ms medi, p99 80.2 ms, 2 495/2 500 frame; a cache calda 40.0 ms, p99 44.4 ms, 2 508/2 509; sync sempre 1.0. Motore ~305 µs/frame.
- 10 test nuovi (situazioni sintetiche gol vs palleggio, decadimento, allineamento, lift noto, ritardo noto, determinismo).

---

## Sessione 1

Ultimo aggiornamento: 4 novembre 2026, notte (sessione autonoma).

## Cosa funziona (verificato)
- **Tappa 1 — Scaffold** ✅ pyproject, schema dati, interfaccia `DataSource`, sorgente sintetica, CI (ruff + pytest), CLAUDE.md.
- **Tappa 2 — Dati Metrica** ✅ download (`scripts/download_data.py`), loader con conversione in metri e verso d'attacco
  normalizzato, catalogo partite, campione committato (`data/sample/`, 60 s per tempo del Game 1), `docs/data_format.md`.
- **Tappa 3 — Replay live + WebSocket + canvas** ✅ (primo traguardo) replay 0.5–10× con pausa/seek, WebSocket a 25 msg/s,
  pagina canvas con pallini, numeri di maglia, scia della palla.
- **Tappa 4 — Metriche incrementali** ✅ distanza, velocità (Savitzky-Golay), velocità max, sprint e HI, heatmap, possesso,
  forma di squadra, pitch control, velocità palla, contatori eventi; checkpoint condivisi in background per seek istantanei.
- **Tappa 5 — Rifinitura** ✅ heatmap del giocatore selezionato, timeline eventi cliccabile, overlay pitch control e forma di
  squadra, feed eventi in italiano con orologio "da TV", banner al gol, layout responsive (verificato a 390 px di larghezza).
- **Tappa 6 — Documentazione** ✅ README, DECISIONS, ROADMAP, questo file; screenshot in `docs/screenshot.png`.

Numeri misurati:
- 57 test verdi; ruff pulito; CI GitHub Actions verde.
- Motore di metriche: ~250 µs per frame (28 giocatori) ⇒ una partita intera in ~35 s.
- Game 2 completo a 10× via WebSocket: 25 messaggi/s (intervallo medio 40.1 ms, p99 74 ms con il pre-calcolo in
  background attivo), 2 496 frame avanzati in 10 s su 2 503 attesi, metriche sempre sincronizzate, messaggi ~1 KB (max ~4 KB).

## Verifica finale da ambiente pulito (4 nov 2026, ~21:25)
Clone fresco da GitHub in una cartella vuota + virtualenv nuovo, seguendo il README passo per passo:
- `pip install -e ".[dev]"` ✅
- `python -m pytest` ✅ 57 passed (1 warning di deprecazione di Starlette su `httpx`, innocuo)
- `ruff check . && ruff format --check .` ✅
- `python scripts/download_data.py` ✅ (~6 s, 3 partite scaricate)
- `python -m livematch` ✅ `/api/health` ok, pagina servita, screenshot headless con i giocatori in movimento e statistiche live, nessun errore JS né nel log del server.

## Cosa manca / limiti
- Lo stub del feed live è documentato e testato come buffer, ma non c'è un client per un provider reale (non c'era un feed a disposizione).
- Il pre-calcolo dei checkpoint di una partita completa dura ~35 s alla prima apertura: in quel lasso un seek lontano
  mostra "Sincronizzo statistiche…" per qualche secondo.
- Vedi "Limiti noti" nel README.

## Cosa fare per primo domattina
1. `git pull`, poi seguire "Avvio rapido" nel README (5 comandi) e aprire http://127.0.0.1:8000.
2. Provare: velocità 10×, click sulla timeline vicino a un gol (⚽), click su un giocatore per la heatmap, overlay "Pitch control".
3. Controllare che i testi del README rappresentino bene il progetto per il portfolio (nome, descrizione, screenshot).

## Prossimi passi consigliati
1. Persistere checkpoint e dati convertiti su disco per avvio istantaneo.
2. Dockerfile + deploy di una demo pubblica sul campione.
3. xT / xG (vedi ROADMAP.md) e un report post-partita.
