# Stato di avanzamento

## Tappa 1 — Scaffold ✅
- pyproject, schema dati, interfaccia `DataSource`, sorgente sintetica, CI (ruff + pytest), CLAUDE.md.

## Tappa 2 — Dati Metrica ✅
- `scripts/download_data.py` (git clone shallow), loader `sources/metrica.py`, catalogo partite, campione in `data/sample/`.
- Documentazione del formato in `docs/data_format.md`.

## Tappa 3 — Replay live + WebSocket + canvas ✅ (primo traguardo)
- `replay.py` (ReplayClock: play/pausa/seek/velocità 0.5–10×, orologio iniettabile per i test).
- `session.py` (sessione per client), `api.py` (REST + WebSocket a ~25 messaggi/s), `python -m livematch`.
- Pagina canvas: campo regolamentare, pallini con numero di maglia, scia della palla, controlli e timeline cliccabile.
- Verificato con test WebSocket (i frame avanzano e le posizioni cambiano) e con screenshot headless (Playwright).

## Tappa 4 — Motore di metriche incrementale ✅
- `metrics/`: cinematica (distanza, velocità Savitzky-Golay, velocità max), sprint e alta intensità, heatmap, possesso,
  forma di squadra, pitch control, velocità palla, contatori eventi. Tutto aggiornato frame per frame.
- Collegato al WebSocket (statistiche a ~5 Hz) e al pannello statistiche.
- Seek istantaneo: checkpoint dello stato delle metriche ogni minuto, calcolati una volta per partita in un thread
  in background (`CheckpointStore`) e condivisi tra le sessioni; il recupero dei frame mancanti avviene con un budget
  di tempo per tick, quindi il WebSocket non si blocca mai.
- Misurato sul Game 2 completo a 10×: 25 messaggi/s (intervallo medio 40.1 ms), 2 496 frame avanzati in 10 s su 2 503 attesi,
  metriche sempre sincronizzate (nessun frame perso), messaggi ~1 KB (fino a ~4 KB con griglia pitch control e tabella).

## Tappa 5 — Heatmap, timeline, pitch control, grafica ✅ (prima versione)
- Heatmap del giocatore selezionato (click sul campo o sulla tabella), timeline con tiri/gol/cartellini cliccabile,
  overlay pitch control e forma di squadra (inviluppo convesso, baricentro, linea difensiva), feed eventi in italiano.
