# Roadmap

Idee per le prossime evoluzioni, in ordine indicativo di valore/fattibilità.

## 1. Prodotto live
- **Feed live reale**: completare `sources/live_stub.py` per un provider (es. feed ottico a 25 Hz via WebSocket), con jitter buffer e "live edge" nel client.
- **Sessioni condivise ("watch party")**: più spettatori sincronizzati sulla stessa sessione via un canale broadcast (Redis pub/sub) invece di un replay per connessione.
- **Persistenza**: salvare i checkpoint delle metriche su disco (parquet/npz) per eliminare il pre-calcolo all'avvio; cache dei CSV convertiti.
- **Docker + deploy** (Fly.io / Render) con una demo pubblica sul campione.

## 2. Tracking da video (computer vision, su GPU)
- Pipeline **YOLO (detection giocatori/palla) + ByteTrack (tracking multi-oggetto)** su video broadcast o tattico.
- **Omografia del campo** (keypoint delle linee) per passare da pixel a metri e assegnazione delle squadre per colore della maglia (k-means su crop).
- Output nello stesso schema interno (`Frame`), così la pipeline video diventa solo un'altra `DataSource`.

## 3. Analytics avanzate
- **Expected Threat (xT)**: griglia di valore delle zone, valore aggiunto di passaggi e conduzioni, classifica dei giocatori per xT generato.
- **Expected Goals (xG)**: modello logistico/gradient boosting su distanza, angolo, pressione dei difensori (dal tracking) e parte del corpo; xG cumulato sulla timeline.
- **Pitch control completo** (Spearman 2017 con integrazione temporale) e **EPV** (Expected Possession Value).
- **Pressing**: PPDA, intensità e distanza del pressing dal tracking; riconoscimento automatico di passaggi e transizioni.
- **Formazioni dinamiche**: clustering delle posizioni medie per fase (possesso / non possesso).
- Report post-partita automatico (PDF/HTML) con le metriche chiave.

## 4. Integrazione con dati di engagement per il marketing
- **Momenti chiave → engagement**: allineare la timeline della partita (gol, occasioni, picchi di intensità, cambi di possesso) con serie temporali di audience, social, app e second screen, per misurare quali momenti generano attenzione.
- **"Excitement index"** in tempo reale (xG, velocità del gioco, vicinanza alla porta, punteggio) come segnale per notifiche push, highlight automatici e posizionamento degli spazi pubblicitari.
- **Segmentazione dei tifosi** in base ai contenuti consumati (heatmap, statistiche giocatore) e A/B test di nuove visualizzazioni nell'app.
- **Modelli di propensione** (churn/upsell) che usano l'esposizione ai momenti chiave come feature.
- Dashboard per il marketing con KPI di partita e di engagement affiancati.
