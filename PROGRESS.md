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
