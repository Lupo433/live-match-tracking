# CLAUDE.md

Progetto personale da portfolio di Filippo: replay "live" di partite di calcio da tracking data
(Metrica Sports) con FastAPI + WebSocket e frontend canvas vanilla.

## Comandi
```bash
pip install -e ".[dev]"            # install
python scripts/download_data.py     # scarica i dati Metrica in data/raw/ (opzionale)
python -m pytest                    # test
ruff check . && ruff format --check .   # lint
python -m livematch                 # avvia il server su http://127.0.0.1:8000
```

## Regole
- Testo della documentazione in italiano; codice, commenti e docstring in inglese.
- Il resto del sistema dipende SOLO da `livematch.sources.base.DataSource`.
- Coordinate interne in metri, campo 105x68, la squadra di casa attacca sempre verso x=105.
- Metriche incrementali: aggiornate frame dopo frame, mai ricalcolo completo.
- Mai committare `data/raw/`, chiavi, token o dati personali. Solo il campione in `data/sample/`.
- Ogni push su `main` con ruff e pytest verdi; conventional commits; niente force push.
- Frontend: una pagina statica (HTML + JS vanilla + canvas), nessun build step.
- Aggiornare PROGRESS.md a ogni tappa e DECISIONS.md a ogni scelta non ovvia.
