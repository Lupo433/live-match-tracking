# Deploy (istruzioni, nessun deploy eseguito)

L'immagine Docker contiene solo il **campione di 2 minuti** (`data/sample/`) e la partita sintetica: le partite complete
Metrica non vengono incluse (≈230 MB e licenza da verificare per la redistribuzione).

> **Stato della verifica.** Nell'ambiente di sviluppo il daemon Docker si avvia, ma il pull dell'immagine base
> `python:3.11-slim` da Docker Hub è fallito con `429 Too Many Requests` e non è stato possibile usare un mirror:
> **la build non è stata testata**. È stato invece verificato lo stesso scenario dell'immagine senza Docker:
> installazione non-editable del pacchetto (`pip install .`) in un virtualenv pulito, con `LIVEMATCH_DATA_DIR`
> che punta a una cartella con il solo campione, `HOST=0.0.0.0` e `PORT` personalizzata: `/api/health` risponde `ok`,
> le partite disponibili sono `sample_game_1` e `synthetic`, i file statici vengono serviti.

## Build ed esecuzione locale

```bash
docker build -t live-match-tracking .
```

```bash
docker run --rm -p 8000:8000 live-match-tracking
```

Poi http://localhost:8000. L'immagine:

- parte da `python:3.11-slim`, installa il pacchetto con `pip install .` (niente dipendenze di sviluppo);
- gira come utente non root (`app`, uid 10001);
- ha un `HEALTHCHECK` su `/api/health` (con `urllib`, senza installare curl);
- legge `HOST` e `PORT` dall'ambiente (default `0.0.0.0:8000`), come richiesto da Fly.io e Render;
- usa `/tmp/livematch-cache` come cache (effimera: con il solo campione il pre-calcolo dura meno di un secondo).

Per usare le partite complete in un container, montare i dati scaricati:

```bash
docker run --rm -p 8000:8000 -v "$PWD/data:/app/data:ro" live-match-tracking
```

## Fly.io

1. Installare `flyctl` e fare login (`fly auth login`).
2. Dalla radice del repo: `fly launch --no-deploy` (rileva il `Dockerfile`; scegliere nome e regione, es. `fra`).
3. Nel `fly.toml` generato verificare `internal_port = 8000` e aggiungere il check:

   ```toml
   [[http_service.checks]]
     interval = "30s"
     timeout = "5s"
     grace_period = "20s"
     method = "GET"
     path = "/api/health"
   ```

4. `fly deploy`. Una macchina `shared-cpu-1x` con 256–512 MB è sufficiente per il campione.
   Il WebSocket funziona senza configurazioni aggiuntive.

## Render

1. New → **Web Service** → collegare il repository GitHub.
2. Runtime: **Docker** (Render usa il `Dockerfile` nella radice).
3. Health check path: `/api/health`. Render imposta `PORT`, che l'app legge automaticamente.
4. Piano free/starter: il servizio si addormenta dopo inattività; il primo accesso richiede qualche secondo.

## Note

- Ogni client WebSocket ha un proprio replay: il costo cresce con il numero di spettatori (≈1 KB × 25 messaggi/s ciascuno).
- Non servono segreti né variabili d'ambiente obbligatorie.
