# Log interventi

**Questo file è di Claude.** Voi scrivete in [`TODO.md`](TODO.md); qui compare cosa è
stato fatto, quando e con quale commit. Tenerli separati significa che nessuno dei due
lati sovrascrive l'altro: non ci sono conflitti fra voi e me, solo eventualmente fra voi
due se salvate nello stesso istante.

Il campo "quando" non è scritto a mano — è la data del commit, che git registra da sé.

| id | stato | intervento | commit | data |
|----|-------|------------|--------|------|
| `#7` | risolto | Il backtest gira sul timeframe del grafico (`backtest_interval_for()` restituisce `ltf_interval`), non piu' forzato a `1d`. Bacheca: `seed-0007`. | vedi `seed-0007` in `resolutions.json` | 2026-09 |
| `#10` | risolto | `_find_confirmation()` parte da `swing_pos + swing_length`: niente piu' conferme prima che lo swing sia visibile. Bacheca: `seed-0010`. | vedi `seed-0010` in `resolutions.json` | 2026-09 |

---

## Note di analisi

Annotazioni su singole voci, prima che diventino codice.


### `#7` — perché ottimizzazione e manuale danno numeri di trade diversi

Non è un errore di calcolo: **i due usano feed di dati diversi**, e non lo dicono
da nessuna parte.

`/api/analyze` (il grafico) legge il timeframe che hai scelto tu, con
`ltf_candles = 3000`. `/api/optimize` e `/api/backtest/deep` chiamano invece
`backtest_interval_for()`, che **forza il minimo a `1d`**, con
`backtest_candles = 5000`. È deliberato — la docstring dichiara di voler la
storia più profonda possibile — ma non è visibile a chi guarda il risultato.

Misurato su KASUSDT con gli **stessi identici parametri** di Lorenzo:

| feed | candele | trade | rendimento |
|---|---|---|---|
| `1d` — usato dall'ottimizzatore | 1 438 | **27** | +120,0% |
| `4h` — visto sul grafico | 8 623 | **186** | +66,4% |

Rendimenti dello stesso ordine, trade **7 volte** diversi: il sintomo descritto,
riprodotto. La richiesta della voce — ogni variabile della logica automatica
dev'essere visibile e replicabile — è quindi corretta alla lettera: finché il
timeframe e il numero di candele realmente usati non tornano nella risposta
dell'API, quel backtest non è riproducibile a mano nemmeno in linea di principio.

### `#10` — il dubbio sui trade contati "a giochi fatti" era fondato

Confermato per `Accumulo / Distribuzione`, con due misure indipendenti.

Gli ingressi nascono da swing rilevati con `smc.swing_highs_lows(swing_length=8)`.
Quella funzione usa una finestra centrata: uno swing in posizione P diventa
riconoscibile solo quando esistono `swing_length` barre successive. Misurato su
16 swing di KASUSDT, cercando il primo istante in cui lo swing compare **e non
sparisce più**: ritardo minimo 8, mediano 8, massimo 8 barre — esattamente
`swing_length`.

Ma `_find_confirmation()` parte da `swing_pos + 1`. Su 87 segnali con conferma:

    conferme che scattano prima di P+8:  84 / 87  = 97%
    ritardo mediano della conferma:      2 barre  (ne servirebbero 8)

**Il 97% degli ingressi si appoggia a uno swing che in quel momento non era
ancora identificabile.** Nel backtest il trade viene aperto; con il bot in tempo
reale quel segnale non sarebbe esistito. I risultati di questa strategia sono
quindi sistematicamente ottimisti e non riproducibili dal vivo — cioè
precisamente il sospetto della voce.

Il fix è una riga (`range(swing_pos + 1, …)` → `range(swing_pos + swing_length, …)`),
ma **sposta verso il basso ogni risultato storico già guardato**. Non applicato
di iniziativa: è una decisione che tocca tutti i numeri visti finora.

*Nota di metodo:* il primo test di causalità sembrava mostrare gli swing visibili
subito, ed era un artefatto — troncando la serie a P, la barra P è l'ultima e
risulta banalmente l'estremo. La misura valida è quella di stabilità qui sopra.
