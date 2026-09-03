# Cose da sistemare

**Questo file è vostro.** Aggiungete righe, spuntate `[x]` quando è verificato da voi.
Claude non scrive mai qui: le sue risposte vanno in [`TODO_LOG.md`](TODO_LOG.md).

Ogni voce ha un `#id` stabile: serve a Claude per collegare la soluzione alla riga
giusta anche quando l'elenco viene riordinato. Aggiungendo una voce nuova, usate il
numero successivo più alto e non riusate mai quelli cancellati.

---

- [ ] `#1` Bug grafico sui trade del backtest
- [ ] `#2` **FONDAMENTALE** — una volta attivato l'alert di una strategia bisogna poter accedere al backtesting e salvarlo in database, così da poterlo consultare in ogni momento e avere un archivio delle strategie generate dalla funzione di ottimizzazione
- [ ] `#3` Creare strategia Gabriele 2 con anche il movimento short, da testare e applicare sui futures
- [ ] `#4` Graficare l'imbalance FVG in stile TradingView, con le zone d'interesse a barre orizzontali
- [ ] `#5` Mostrare il valore RSI sul "pallino" blu e non sulla freccia del cursore
- [ ] `#6` Pulsante per attivare/disattivare modalità black
- [ ] `#7` **FONDAMENTALE** — discrepanza tra profittabilità e numero di trade fra modalità ottimizzazione e normale: con gli stessi valori impostati a mano si ottengono risultati simili ma quantità di trade molto diverse. Qualsiasi variabile aggiuntiva usata dalla logica automatica deve essere parametrizzata e VISIBILE dopo l'ottimizzazione, così da renderla replicabile a mano e verificabile
- [ ] `#8` Attivato un alert, su Telegram sono arrivate una ventina di notifiche con prezzi di ingresso e uscita disparati
- [ ] `#9` Parametri di ottimizzazione per selezionare solo strategie con un minimo/massimo di trade in perdita (compreso 0) oppure di drawdown % (compreso 0%)
- [ ] `#10` Dubbi sui dati non usati in ottimizzazione nel backtest: verificare che non escluda trade "a giochi fatti" per gonfiare la performance, e che quei trade sarebbero davvero stati aperti o chiusi dal bot in tempo reale
