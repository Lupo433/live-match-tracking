# Roadmap

Idee per le prossime evoluzioni. Fatto nella seconda sessione (e quindi tolto da qui): cache su disco, Dockerfile e
istruzioni di deploy, feed live simulato con jitter buffer e DVR, xT/xG dimostrativi, reti di passaggi, report
post-partita, excitement index ed engagement (sintetico).

## 1. Prodotto live
- **Provider reale**: client per un feed commerciale (autenticazione, formazioni e cambi, orologio ufficiale, eventi
  corretti/annullati) sull'adattatore `ProviderFeedSource` già testato con il fake provider.
- **Watch party con Redis**: più spettatori sincronizzati sulla stessa sessione via pub/sub invece di un replay per
  connessione; il server calcola le metriche una volta sola per partita.
- **Deploy reale** di una demo pubblica sul campione (Fly.io o Render, vedi `docs/deploy.md`) e build Docker verificata in CI.
- **Persistenza del flusso live** (disco o Kafka) per rivedere la partita dopo il fischio finale.

## 2. Dati
- **Loader per Metrica Sample Game 3 (formato EPTS/FIFA)**: tracking in `.txt` + metadata XML + eventi JSON, da
  ispezionare (frequenza, sistema di coordinate, id giocatori) come fatto per i CSV in `docs/data_format.md`.
- Altri dataset pubblici di tracking (es. SkillCorner open data broadcast tracking, con giocatori fuori inquadratura).

## 3. Tracking da video (computer vision, su GPU)
- Pipeline **YOLO (detection giocatori/palla) + ByteTrack (tracking multi-oggetto)** su video broadcast o tattico.
- **Omografia del campo** (keypoint delle linee) per passare da pixel a metri e assegnazione delle squadre per colore
  della maglia (k-means sui crop).
- Output nello stesso schema interno (`Frame`), così la pipeline video diventa solo un'altra `DataSource`.

## 4. Analytics avanzate
- xT e xG addestrati su **molte** partite (con feature di tracking: pressione, posizione del portiere, parte del corpo)
  e validati (calibrazione, Brier score) prima di usarli per valutare giocatori.
- **Pitch control completo** (Spearman 2017 con integrazione temporale) ed **EPV**.
- **Pressing**: PPDA, intensità e distanza del pressing dal tracking; riconoscimento automatico di transizioni.
- **Formazioni dinamiche**: clustering delle posizioni medie per fase (possesso / non possesso).

## 5. Marketing
- **Calibrare i pesi dell'excitement index su dati reali** di audience (regressione dell'engagement sulle componenti con
  ritardo), mantenendo i dati fuori dal repository.
- Uso in tempo reale dell'indice: trigger di notifiche push, clip/highlight automatici, posizionamento dei contenuti.
- Segmentazione dei tifosi per contenuti consumati e A/B test di nuove visualizzazioni nell'app.
- Modelli di propensione (churn/upsell) con l'esposizione ai momenti chiave come feature.
