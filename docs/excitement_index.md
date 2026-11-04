# Excitement index

Un numero da **0 a 100 per ogni secondo di partita** che riassume "quanto sta succedendo" in campo, calcolato solo dai
dati di tracking e dagli eventi, in modo **incrementale** (componente `ExcitementTracker` del motore di metriche,
`src/livematch/metrics/excitement.py`). Serve come segnale "lato campo" da confrontare con serie di engagement
(social, app, second screen) e come base per notifiche, highlight automatici o posizionamento di contenuti.

## Componenti (ciascuna in [0, 1], calcolata sul secondo k)

| Componente | Peso | Definizione | Intuizione |
|---|---|---|---|
| `proximity` | 0.25 | media su tutti i frame del secondo con palla tracciata di `max(0, 1 − d / 35 m)`, d = distanza della palla dal centro della porta più vicina | la palla vicino a una porta è pericolo |
| `tempo` | 0.15 | ½ · min(1, velocità media palla / 15 m/s) + ½ · min(1, velocità media dei giocatori di movimento / 4 m/s) | gioco veloce, transizioni |
| `threat` | 0.35 | Σ sui tiri passati di 1.5 · xG · e^(−Δt / 8 s) + per i gol 1.0 · e^(−Δt / 25 s), troncato a 1 | occasioni e gol, con una "coda" emotiva che decade |
| `turnovers` | 0.10 | cambi di possesso negli ultimi 10 s / 3, troncato a 1 | partita spezzata, duelli |
| `territory` | 0.15 | dal pitch control campionato ogni secondo: per ogni squadra la quota controllata del terzo offensivo; si prende il massimo e lo si riscala `(v − 0.25) / 0.5` (troncato in [0, 1]) | una squadra che "schiaccia" l'altra |

## Aggregazione e normalizzazione

```
raw(k)      = 0.25·proximity + 0.15·tempo + 0.35·threat + 0.10·turnovers + 0.15·territory
smooth(k)   = smooth(k−1) + 0.35 · (raw(k) − smooth(k−1))        # media mobile esponenziale (~3 s)
index(k)    = round(100 · min(1, smooth(k) / 0.75))
```

- **Scala fissa, non percentile**: lo stesso valore significa la stessa cosa in partite diverse (confrontabilità);
  0.75 è la soglia di saturazione scelta perché solo combinazioni "gol + palla in area + gioco veloce" la superino.
- **Palla non in gioco**: proximity e la parte palla del tempo valgono 0, quindi l'indice scende durante le pause,
  ma `threat` mantiene alto il valore subito dopo un gol (esultanza, replay).
- Il valore del secondo k è disponibile alla fine del secondo stesso: nessun dato futuro, utilizzabile live.

## Calibrazione osservata (Metrica Game 1, 5 800 s)

Percentili dell'indice: P10 = 5, mediana = 22, P90 = 41, P99 = 62, massimo 92. Ai tre gol l'indice sale a 79–92 e
torna sotto 40 in circa 30–40 s. Una fase di possesso lento a centrocampo resta sotto 30 (test
`tests/test_excitement.py`).

## Limiti

- Pesi scelti a mano per leggibilità, non stimati su dati di audience: con dati reali andrebbero calibrati (es. regressione
  dell'engagement sulle componenti, con ritardo).
- Il possesso per prossimità genera molti "cambi" nei duelli: la componente `turnovers` è rumorosa.
- L'xG usato in `threat` è il modello dimostrativo del progetto.
