"""Catalogo dei 151 indicatori di pandas-ta, con classificazione per il grafico.

pandas-ta e' gia' una dipendenza (vedi indicators.py, che ne usa solo 6 dei
151 disponibili). Questo modulo espone gli altri: un registro che dice per
ciascuno come chiamarlo, se va disegnato sul prezzo o in un riquadro separato,
e quali parametri ha senso esporre in UI. Il frontend lo usa per popolare la
libreria a tendina; nessun indicatore viene calcolato finche' l'utente non lo
sceglie esplicitamente, cosi' /api/analyze non si appesantisce.
"""
from __future__ import annotations

import pandas as pd
import pandas_ta  # noqa: F401  (registra l'accessor .ta)

from app.models import IndicatorSeries

Param = dict  # {"name": str, "label": str, "default": float, "min": float, "max": float}


class IndicatorSpec:
    __slots__ = ("id", "label", "category", "kind", "params", "output_labels")

    def __init__(self, id_: str, label: str, category: str, kind: str,
                 params: list[Param] | None = None, output_labels: list[str] | None = None):
        self.id = id_
        self.label = label
        self.category = category
        self.kind = kind  # "overlay" (sul prezzo) o "oscillator" (riquadro proprio)
        self.params = params or []
        self.output_labels = output_labels  # nomi delle colonne quando l'output ha piu' linee


def _p(name: str, label: str, default: float, lo: float, hi: float) -> Param:
    return {"name": name, "label": label, "default": default, "min": lo, "max": hi}


LENGTH = lambda d=14: [_p("length", "Periodo", d, 2, 400)]  # noqa: E731

CATEGORY_LABELS = {
    "candle": "Pattern candele",
    "cycle": "Cicli",
    "momentum": "Momentum",
    "overlap": "Medie e overlay",
    "performance": "Performance",
    "statistics": "Statistiche",
    "trend": "Trend",
    "volatility": "Volatilita'",
    "volume": "Volume",
}

# Indicatori con parametri o output non banali: classificazione a mano.
# Tutto il resto (la stragrande maggioranza) prende un default ragionevole
# per categoria (vedi _default_kind_for_category) e un solo parametro
# "length" quando la funzione lo accetta.
OVERRIDES: dict[str, IndicatorSpec] = {
    "supertrend": IndicatorSpec("supertrend", "SuperTrend", "overlap", "overlay",
        [_p("length", "Periodo", 10, 2, 100), _p("multiplier", "Moltiplicatore ATR", 3.0, 0.5, 10)],
        ["SUPERT", "SUPERTd"]),
    "ichimoku": IndicatorSpec("ichimoku", "Ichimoku Kinko Hyo", "overlap", "overlay",
        [_p("tenkan", "Tenkan", 9, 2, 60), _p("kijun", "Kijun", 26, 2, 120), _p("senkou", "Senkou", 52, 2, 200)]),
    "vwma": IndicatorSpec("vwma", "VWMA", "overlap", "overlay", LENGTH(20)),
    "hilo": IndicatorSpec("hilo", "Gann HiLo", "overlap", "overlay",
        [_p("high_length", "Periodo massimi", 13, 2, 100), _p("low_length", "Periodo minimi", 21, 2, 100)]),
    "hl2": IndicatorSpec("hl2", "HL2", "overlap", "overlay", []),
    "hlc3": IndicatorSpec("hlc3", "HLC3", "overlap", "overlay", []),
    "ohlc4": IndicatorSpec("ohlc4", "OHLC4", "overlap", "overlay", []),
    "donchian": IndicatorSpec("donchian", "Canale di Donchian", "volatility", "overlay",
        [_p("lower_length", "Periodo minimo", 20, 2, 200), _p("upper_length", "Periodo massimo", 20, 2, 200)],
        ["DCL", "DCM", "DCU"]),
    "kc": IndicatorSpec("kc", "Canale di Keltner", "volatility", "overlay", LENGTH(20),
        ["KCL", "KCB", "KCU"]),
    "bbands": IndicatorSpec("bbands", "Bande di Bollinger", "volatility", "overlay", LENGTH(20),
        ["BBL", "BBM", "BBU"]),
    "accbands": IndicatorSpec("accbands", "Acceleration Bands", "volatility", "overlay", LENGTH(20),
        ["ACCBL", "ACCBM", "ACCBU"]),
    "chandelier_exit": IndicatorSpec("chandelier_exit", "Chandelier Exit", "volatility", "overlay",
        [_p("length", "Periodo", 22, 2, 100), _p("multiplier", "Moltiplicatore ATR", 3.0, 0.5, 10)]),
    "psar": IndicatorSpec("psar", "Parabolic SAR", "trend", "overlay",
        [_p("af0", "Accelerazione iniziale", 0.02, 0.001, 0.5), _p("max_af", "Accelerazione massima", 0.2, 0.01, 1)]),
    "vwap": IndicatorSpec("vwap", "VWAP", "overlap", "overlay", []),
    "alligator": IndicatorSpec("alligator", "Alligator (Williams)", "overlap", "overlay", []),
    "adx": IndicatorSpec("adx", "ADX / Directional Movement", "trend", "oscillator", LENGTH(14),
        ["ADX", "DMP", "DMN"]),
    "aroon": IndicatorSpec("aroon", "Aroon", "trend", "oscillator", LENGTH(14), ["AROOND", "AROONU"]),
    "macd": IndicatorSpec("macd", "MACD", "momentum", "oscillator",
        [_p("fast", "Veloce", 12, 2, 100), _p("slow", "Lenta", 26, 2, 200), _p("signal", "Segnale", 9, 2, 100)],
        ["MACD", "MACDh", "MACDs"]),
    "stoch": IndicatorSpec("stoch", "Stocastico", "momentum", "oscillator",
        [_p("k", "%K", 14, 2, 100), _p("d", "%D", 3, 2, 50)], ["STOCHk", "STOCHd"]),
    "rsi": IndicatorSpec("rsi", "RSI", "momentum", "oscillator", LENGTH(14)),
    "cci": IndicatorSpec("cci", "CCI", "momentum", "oscillator", LENGTH(20)),
    "willr": IndicatorSpec("willr", "Williams %R", "momentum", "oscillator", LENGTH(14)),
    "mfi": IndicatorSpec("mfi", "Money Flow Index", "volume", "oscillator", LENGTH(14)),
    "obv": IndicatorSpec("obv", "On Balance Volume", "volume", "oscillator", []),
    "cmf": IndicatorSpec("cmf", "Chaikin Money Flow", "volume", "oscillator", LENGTH(20)),
    "atr": IndicatorSpec("atr", "ATR", "volatility", "oscillator", LENGTH(14)),
    "chop": IndicatorSpec("chop", "Choppiness Index", "trend", "oscillator", LENGTH(14)),
    "vortex": IndicatorSpec("vortex", "Vortex Indicator", "trend", "oscillator", LENGTH(14), ["VTXP", "VTXM"]),
    "cdl_pattern": IndicatorSpec("cdl_pattern", "Pattern candlestick (tutti)", "candle", "overlay", []),
}

_OSCILLATOR_CATEGORIES = {"momentum", "trend", "volatility", "volume", "cycle", "performance", "statistics"}

# Una riga per ciascuno dei 151: cosa misura e a cosa serve, in italiano
# semplice. Lorenzo: "non conosco i nomi cosi non so cosa cercare" — senza
# questo la libreria sarebbe solo un elenco di sigle.
DESCRIPTIONS: dict[str, str] = {
    # candle
    "cdl_pattern": "Riconosce in automatico i pattern di candele classici (doji, martello, engulfing...) sul grafico.",
    "cdl_z": "Normalizza corpo e ombre delle candele in unita' statistiche, per confrontare candele di dimensioni diverse.",
    "ha": "Heikin-Ashi: ridisegna le candele mediando i prezzi, per vedere il trend senza il rumore delle singole barre.",
    # cycle
    "ebsw": "Even Better Sinewave — stima la fase di un ciclo di mercato con un filtro adattivo, utile nei mercati laterali.",
    "reflex": "Filtro di Ehlers che isola il ciclo dominante del prezzo eliminando il rumore ad alta frequenza.",
    # momentum
    "ao": "Awesome Oscillator — differenza fra media veloce e lenta del punto medio, misura lo slancio del movimento.",
    "apo": "Differenza assoluta fra due medie mobili, come il MACD ma senza linea di segnale.",
    "bias": "Scostamento percentuale del prezzo dalla sua media mobile: quanto e' 'tirato' rispetto al proprio equilibrio.",
    "bop": "Balance of Power — confronta la forza dei compratori e dei venditori dentro ogni singola candela.",
    "brar": "Coppia di indicatori che misurano la pressione di acquisto/vendita sull'apertura rispetto al giorno prima.",
    "cci": "Commodity Channel Index — quanto il prezzo si discosta dalla sua media tipica; estremi = ipercomprato/ipervenduto.",
    "cfo": "Chande Forecast Oscillator — scarto percentuale fra il prezzo e una proiezione lineare del suo trend.",
    "cg": "Center of Gravity — oscillatore a bassissimo ritardo pensato per anticipare i punti di svolta.",
    "cmo": "Chande Momentum Oscillator — simile all'RSI ma usa la somma netta dei movimenti invece della media.",
    "coppock": "Coppock Curve — pensato per segnalare l'inizio di un nuovo trend rialzista di lungo periodo.",
    "crsi": "Connors RSI — combina RSI, durata dello streak e rank del rendimento per un ipercomprato/ipervenduto piu' reattivo.",
    "cti": "Correlation Trend Indicator — correla il prezzo con una linea retta per dire quanto il trend e' pulito.",
    "er": "Efficiency Ratio (Kaufman) — quanto della distanza percorsa dal prezzo e' vero movimento e quanto rumore.",
    "eri": "Elder Ray Index — separa la forza dei rialzisti (bull power) da quella dei ribassisti (bear power).",
    "exhc": "Exhaustion Count — conta le chiusure consecutive piu' alte/basse della media, segnala un movimento esausto.",
    "fisher": "Fisher Transform — trasforma il prezzo per renderne i massimi e minimi piu' netti e riconoscibili.",
    "inertia": "Versione lisciata del Relative Vigor Index, riduce i falsi segnali del trend a breve termine.",
    "kdj": "KDJ — variante dello Stocastico con una terza linea (J) piu' sensibile ai cambi di direzione.",
    "kst": "Know Sure Thing — somma pesata di piu' oscillatori ROC, un quadro di momentum su piu' orizzonti insieme.",
    "macd": "MACD — differenza fra due medie mobili con una linea di segnale: il classico per trend e incroci.",
    "mom": "Momentum — differenza grezza fra il prezzo attuale e quello di N barre fa.",
    "pgo": "Pretty Good Oscillator — distanza del prezzo dalla sua media, misurata in unita' di ATR.",
    "ppo": "Come il MACD ma in percentuale, cosi' e' confrontabile fra strumenti a prezzo molto diverso.",
    "psl": "Psychological Line — percentuale di barre rialziste sulle ultime N, misura il sentiment recente.",
    "qqe": "RSI lisciato con bande dinamiche, pensato per restare dentro il trend piu' a lungo prima di uscire.",
    "roc": "Rate of Change — variazione percentuale del prezzo su N barre: la velocita' pura del movimento.",
    "rsi": "RSI — il piu' diffuso: misura la velocita' dei guadagni contro le perdite recenti, su scala 0-100.",
    "rsx": "RSI ulteriormente lisciato per ridurre il rumore senza aggiungere ritardo significativo.",
    "rvgi": "Relative Vigor Index — confronta dove chiude la candela rispetto a dove apre, misura la convinzione del trend.",
    "slope": "Pendenza della retta di regressione del prezzo sulle ultime N barre.",
    "smc": "Oscillatore derivato dai concetti di Smart Money Concepts.",
    "smi": "Stochastic Momentum Index — versione piu' fluida dello Stocastico, meno sobbalzi vicino agli estremi.",
    "squeeze": "TTM Squeeze — segnala quando Bollinger si stringe dentro Keltner: compressione prima di una rottura.",
    "squeeze_pro": "Come Squeeze ma con tre livelli di compressione invece di uno solo.",
    "stc": "Schaff Trend Cycle — MACD passato attraverso uno Stocastico, per anticipare i cambi di trend piu' in fretta.",
    "stoch": "Stocastico — posizione della chiusura nel range recente; il classico per ipercomprato/ipervenduto.",
    "stochf": "Stocastico veloce — la versione non lisciata dello Stocastico classico, piu' reattiva e piu' rumorosa.",
    "stochrsi": "Stocastico applicato all'RSI invece che al prezzo: doppio filtro, ancora piu' sensibile agli estremi.",
    "tmo": "True Momentum Oscillator — momentum calcolato sul segno delle variazioni giornaliere, lisciato due volte.",
    "trix": "Tasso di variazione di una tripla media esponenziale: filtra il rumore a breve quasi del tutto.",
    "tsi": "True Strength Index — momentum a doppia lisciatura, utile per confermare un trend gia' in corso.",
    "uo": "Ultimate Oscillator — combina tre orizzonti temporali insieme per ridurre i falsi segnali di un solo periodo.",
    "willr": "Williams %R — come lo Stocastico ma capovolto: misura la distanza dal massimo recente.",
    # overlap
    "alligator": "Alligator (Williams) — tre medie sfalsate: intrecciate = mercato fermo, aperte = trend in corso.",
    "alma": "Media mobile gaussiana pensata per ridurre il ritardo senza perdere fluidita'.",
    "dema": "Double EMA — doppia esponenziale per dimezzare il ritardo tipico di una media mobile singola.",
    "ema": "Media Mobile Esponenziale — pesa di piu' le candele recenti; la base di molte altre strategie.",
    "fwma": "Media mobile pesata con i numeri di Fibonacci invece che linearmente.",
    "hilo": "Gann HiLo — linea che segue massimi o minimi recenti, cambia lato quando il trend si inverte.",
    "hl2": "Punto medio (massimo+minimo)/2 — prezzo di riferimento piu' stabile della sola chiusura.",
    "hlc3": "Prezzo tipico (massimo+minimo+chiusura)/3 — media dei tre prezzi principali della candela.",
    "hma": "Hull MA — media mobile pensata per essere fluida e reattiva insieme, un obiettivo raro fra le medie.",
    "hwma": "Media mobile con smorzamento adattivo, si aggiusta da sola alla volatilita' recente.",
    "ichimoku": "Ichimoku Kinko Hyo — sistema completo giapponese: trend, supporto/resistenza e momentum insieme.",
    "jma": "Jurik MA — media mobile proprietaria nota per basso ritardo e resistenza al rumore.",
    "kama": "Kaufman Adaptive MA — rallenta nei mercati laterali e accelera nei trend, si adatta da sola.",
    "linreg": "Regressione lineare — la retta che meglio approssima il prezzo delle ultime N barre.",
    "mama": "Media mobile che cambia velocita' in base al ciclo dominante del prezzo (MESA Adaptive).",
    "mcgd": "McGinley Dynamic — media mobile che si auto-corregge per seguire il prezzo senza sovra-reagire.",
    "midpoint": "Punto medio fra massimo e minimo del prezzo di chiusura sulle ultime N barre.",
    "midprice": "Punto medio fra il massimo e il minimo assoluti (non di chiusura) sulle ultime N barre.",
    "ohlc4": "Media dei quattro prezzi della candela: apertura, massimo, minimo, chiusura.",
    "pivots": "Punti pivot — livelli di supporto/resistenza dalla sessione precedente, molto usati intraday.",
    "pwma": "Media mobile pesata secondo il triangolo di Pascal, piu' morbida ai bordi.",
    "rma": "La lisciatura usata dentro RSI e ATR (media di Wilder), piu' lenta di una EMA classica.",
    "sinwma": "Media mobile pesata con una curva sinusoidale, molto fluida.",
    "sma": "Media Mobile Semplice — la media aritmetica del prezzo sulle ultime N barre, la piu' elementare.",
    "smma": "Media mobile lisciata, reagisce piu' lentamente della SMA agli ultimi prezzi.",
    "ssf": "Ehlers Super Smoother — filtro passa-basso che leviga il prezzo con pochissimo ritardo.",
    "ssf3": "Ehlers Super Smoother a 3 poli — versione ancora piu' liscia della precedente.",
    "supertrend": "SuperTrend — linea che segue il prezzo a distanza di ATR, cambia lato ad ogni inversione di trend.",
    "swma": "Media mobile pesata simmetricamente attorno al centro della finestra.",
    "t3": "Media mobile a piu' stadi molto fluida, spesso usata al posto della EMA nei sistemi di trend.",
    "tema": "Triple EMA — tripla esponenziale, ancora meno ritardo della doppia (DEMA).",
    "trima": "Triangular MA — media mobile che pesa di piu' il centro della finestra, molto liscia.",
    "vidya": "Media mobile che accelera con la volatilita' recente (Variable Index Dynamic Average).",
    "wcp": "Prezzo di chiusura pesato il doppio rispetto a massimo e minimo (Weighted Close Price).",
    "wma": "Media Mobile Ponderata — pesa linearmente le candele piu' recenti piu' di quelle vecchie.",
    "zlma": "Zero-Lag MA — media mobile costruita apposta per eliminare il ritardo strutturale di una media.",
    "vwap": "VWAP — il prezzo medio pesato per il volume da inizio sessione: il riferimento istituzionale del giorno.",
    "vwma": "Volume Weighted MA — media mobile che pesa di piu' le candele con volume maggiore.",
    # performance
    "log_return": "Rendimento logaritmico barra su barra — la misura preferita in statistica per le sue proprieta' additive.",
    "percent_return": "Rendimento percentuale barra su barra — quanto e' salito o sceso il prezzo dalla candela precedente.",
    # statistics
    "entropy": "Entropia — quanto e' imprevedibile la distribuzione dei rendimenti recenti; piu' alta, piu' caotico il mercato.",
    "kurtosis": "Curtosi — quanto i rendimenti recenti hanno code pesanti, cioe' movimenti estremi piu' frequenti del normale.",
    "mad": "Deviazione assoluta media — dispersione dei prezzi dalla loro media, alternativa robusta alla deviazione standard.",
    "median": "Mediana mobile — il valore centrale del prezzo sulle ultime N barre, meno sensibile agli estremi della media.",
    "quantile": "Quantile mobile — la soglia sotto cui cade una certa percentuale dei prezzi recenti.",
    "skew": "Asimmetria — se i rendimenti recenti pendono piu' verso rialzi estremi o ribassi estremi.",
    "stdev": "Deviazione standard — la misura classica di volatilita': quanto il prezzo si allontana dalla sua media.",
    "tos_stdevall": "Bande di deviazione standard (stile thinkorswim) attorno a una regressione lineare del prezzo.",
    "variance": "Varianza — il quadrato della deviazione standard, la stessa volatilita' in un'altra unita' di misura.",
    "zscore": "Z-score — quante deviazioni standard il prezzo attuale e' distante dalla sua media recente.",
    # trend
    "adx": "ADX — quanto e' forte un trend, senza dirne la direzione (viene dalle linee +DI/-DI incluse).",
    "alphatrend": "Combina ATR e volume per tracciare una linea di trend con minor rumore.",
    "amat": "Segnala quando due medie mobili confermano insieme un trend rialzista o ribassista.",
    "aroon": "Da quante barre sono passati l'ultimo massimo e l'ultimo minimo: dice se il trend e' ancora fresco.",
    "chop": "Choppiness Index — se il mercato sta facendo trend o solo laterale caotico, a prescindere dalla direzione.",
    "cksp": "Chande Kroll Stop — stop dinamico basato sulla volatilita' recente, pensato per restare nel trend.",
    "decay": "Decadimento esponenziale del prezzo — pesa il passato con un'attenuazione via via minore.",
    "decreasing": "Segnala da quante barre consecutive il prezzo (o un altro indicatore) sta scendendo.",
    "dpo": "Detrended Price Oscillator — rimuove il trend di fondo per far emergere i cicli piu' brevi.",
    "ht_trendline": "Stima una linea di trend usando l'analisi di fase del segnale (trasformata di Hilbert).",
    "increasing": "Segnala da quante barre consecutive il prezzo (o un altro indicatore) sta salendo.",
    "long_run": "Segnala una fase di trend rialzista sostenuto, combinando velocita' e accelerazione della media.",
    "psar": "Parabolic SAR — punti che seguono il prezzo e si capovolgono ad ogni cambio di trend, utili per gli stop.",
    "qstick": "Media mobile della differenza fra chiusura e apertura: il sentiment delle ultime candele.",
    "rwi": "Random Walk Index — se il movimento recente e' piu' ampio di quanto ci si aspetterebbe dal puro caso.",
    "short_run": "Segnala una fase di trend ribassista sostenuto, combinando velocita' e accelerazione della media.",
    "trendflex": "Ehlers TrendFlex — oscillatore che segue il trend con un ritardo molto basso.",
    "vhf": "Vertical Horizontal Filter — se il mercato si muove in verticale (trend) o in orizzontale (range).",
    "vortex": "Due linee che si incrociano per segnalare l'inizio di un nuovo trend.",
    "zigzag": "Collega solo i massimi e minimi significativi, ignorando le oscillazioni minori: la struttura pulita del prezzo.",
    # volatility
    "aberration": "Bande attorno a una media, segnalano quando il prezzo si allontana in modo anomalo.",
    "accbands": "Acceleration Bands — bande attorno al prezzo che si allargano con la volatilita'.",
    "atr": "Average True Range — l'ampiezza media del movimento di una candela: la misura standard di volatilita'.",
    "atrts": "Uno stop che segue il prezzo a distanza di ATR, si stringe quando la volatilita' cala.",
    "bbands": "Bande di Bollinger — canale che si allarga e restringe con la volatilita' attorno a una media mobile.",
    "chandelier_exit": "Stop calcolato dal massimo/minimo recente meno un multiplo di ATR.",
    "donchian": "Canale di Donchian — il massimo e il minimo delle ultime N barre: la base delle strategie a breakout.",
    "hwc": "Canale di volatilita' costruito attorno alla media Holt-Winters.",
    "kc": "Canale di Keltner — come Bollinger ma usa l'ATR invece della deviazione standard per l'ampiezza.",
    "massi": "Mass Index — individua un'inversione imminente quando il range delle candele si allarga rapidamente.",
    "natr": "L'ATR espresso in percentuale del prezzo, cosi' e' confrontabile fra strumenti diversi.",
    "pdist": "Quanto ampio e' stato il range di una singola candela rispetto alla precedente.",
    "rvi": "Relative Volatility Index — come l'RSI ma applicato alla deviazione standard invece che al prezzo.",
    "thermo": "Elder Thermometer — quanto e' 'calda' la candela attuale rispetto al range recente.",
    "true_range": "L'ampiezza reale di una singola candela, tenendo conto anche dei gap: la base dell'ATR.",
    "ui": "Ulcer Index — misura il dolore di un drawdown: quanto profondo e per quanto il prezzo resta sotto i massimi.",
    # volume
    "ad": "Accumulation/Distribution — flusso cumulato di volume pesato da dove chiude la candela nel suo range.",
    "adosc": "Differenza fra due medie dell'Accumulation/Distribution: ne misura lo slancio.",
    "aobv": "OBV con bande e segnali di ipercomprato/ipervenduto incorporati.",
    "cmf": "Chaikin Money Flow — se il volume recente sta entrando o uscendo dallo strumento.",
    "efi": "Elder's Force Index — combina variazione di prezzo e volume in un'unica misura di forza del movimento.",
    "eom": "Ease of Movement — quanto facilmente il prezzo si muove per unita' di volume scambiato.",
    "kvo": "Klinger Volume Oscillator — pensato per anticipare le inversioni di lungo periodo tramite il volume.",
    "mfi": "Money Flow Index — un RSI che usa anche il volume, spesso chiamato 'RSI pesato per volume'.",
    "nvi": "Segue il prezzo solo nei giorni a volume in calo, isola il comportamento 'smart money' (Negative Volume Index).",
    "obv": "On Balance Volume — somma o sottrae il volume intero di ogni giorno secondo la direzione del prezzo.",
    "pvi": "Come NVI ma sui giorni a volume in aumento (Positive Volume Index).",
    "pvo": "Il MACD applicato al volume invece che al prezzo.",
    "pvol": "Prezzo per volume — il controvalore scambiato in ogni candela.",
    "pvr": "Classifica ogni candela in base alla combinazione di direzione di prezzo e volume.",
    "pvt": "Come OBV ma pesato per l'ampiezza della variazione di prezzo, non solo il segno (Price Volume Trend).",
    "tsv": "Divide il volume in intervalli temporali per capire se sta entrando o uscendo denaro dal mercato.",
    "vhm": "Variazione del volume rispetto alla sua media recente.",
}


def _default_kind_for(category: str) -> str:
    return "overlay" if category == "overlap" else "oscillator"


def _humanize(fn_name: str) -> str:
    return fn_name.replace("_", " ").upper()


def build_catalog() -> list[IndicatorSpec]:
    """Introspeziona pandas_ta.Category e produce una voce per ogni funzione,
    usando OVERRIDES dove serve una definizione precisa e un default
    ragionevole ovunque altro."""
    out: list[IndicatorSpec] = []
    seen: set[str] = set()
    for category, names in pandas_ta.Category.items():
        for name in names:
            if name in seen or name.startswith("_"):
                continue
            seen.add(name)
            if name in OVERRIDES:
                out.append(OVERRIDES[name])
                continue
            fn = getattr(pandas_ta, name, None)
            has_length = False
            if fn is not None:
                try:
                    has_length = "length" in fn.__code__.co_varnames
                except AttributeError:
                    has_length = False
            out.append(IndicatorSpec(
                id_=name,
                label=_humanize(name),
                category=category,
                kind=_default_kind_for(category),
                params=LENGTH() if has_length else [],
            ))
    out.sort(key=lambda s: (s.category, s.label))
    return out


CATALOG: list[IndicatorSpec] = build_catalog()
CATALOG_BY_ID: dict[str, IndicatorSpec] = {s.id: s for s in CATALOG}


_FALLBACK_DESCRIPTION = {
    "candle": "Legge la forma delle candele per riconoscere pattern.",
    "cycle": "Stima il ciclo dominante del prezzo con un filtro adattivo.",
    "momentum": "Misura la velocita' e la forza del movimento di prezzo.",
    "overlap": "Una media o un prezzo di riferimento da disegnare sopra il grafico.",
    "performance": "Misura il rendimento del prezzo barra su barra.",
    "statistics": "Una misura statistica calcolata sui prezzi recenti.",
    "trend": "Dice se e quanto il mercato sta facendo trend.",
    "volatility": "Misura quanto si muove il prezzo, a prescindere dalla direzione.",
    "volume": "Combina prezzo e volume scambiato.",
}


def catalog_payload() -> list[dict]:
    return [
        {
            "id": s.id,
            "label": s.label,
            "category": s.category,
            "category_label": CATEGORY_LABELS.get(s.category, s.category),
            "kind": s.kind,
            "params": s.params,
            "description": DESCRIPTIONS.get(s.id, _FALLBACK_DESCRIPTION.get(s.category, "")),
        }
        for s in CATALOG
    ]


def compute_indicator(df: pd.DataFrame, indicator_id: str, params: dict) -> list[IndicatorSeries]:
    """Calcola un indicatore del catalogo e lo riporta nella stessa forma di
    compute_indicators(): una IndicatorSeries per ciascuna linea d'uscita,
    allineata per indice alle candele di df."""
    spec = CATALOG_BY_ID.get(indicator_id)
    if spec is None:
        raise ValueError(f"Indicatore sconosciuto: {indicator_id}")
    fn = getattr(df.ta, indicator_id, None)
    if fn is None:
        raise ValueError(f"pandas-ta non espone '{indicator_id}'")
    # Parte dai default dichiarati nello spec (senza, un indicatore invocato
    # senza parametri prenderebbe quelli di default di pandas-ta, che spesso
    # non coincidono con i nostri — es. supertrend length=7 contro il nostro 10).
    clean_params = {p["name"]: p["default"] for p in spec.params}
    allowed = {p["name"] for p in spec.params}
    for k, v in (params or {}).items():
        if k in allowed:
            clean_params[k] = v
    result = fn(**clean_params)
    n = len(df)
    # Alcuni indicatori (ichimoku) restituiscono una tupla di dataframe — il
    # secondo e' la proiezione futura fuori dall'asse delle candele attuali,
    # non allineabile 1:1: si prende solo il primo, l'unico della stessa
    # lunghezza della serie richiesta.
    if isinstance(result, tuple):
        result = next((r for r in result if hasattr(r, "__len__") and len(r) == n), result[0])
    out: list[IndicatorSeries] = []
    if isinstance(result, pd.Series) and len(result) == n:
        out.append(IndicatorSeries(
            name=spec.label,
            values=[None if pd.isna(v) else float(v) for v in result],
        ))
    elif isinstance(result, pd.DataFrame) and len(result) == n:
        wanted = spec.output_labels
        cols = result.columns
        if wanted:
            for w in wanted:
                col = next((c for c in cols if c.upper().startswith(w.upper())), None)
                if col is not None:
                    s = result[col]
                    out.append(IndicatorSeries(name=f"{spec.label} ({col})",
                                                values=[None if pd.isna(v) else float(v) for v in s]))
        else:
            for col in cols:
                s = result[col]
                if pd.api.types.is_numeric_dtype(s):
                    out.append(IndicatorSeries(name=f"{spec.label} ({col})",
                                                values=[None if pd.isna(v) else float(v) for v in s]))
    return out
