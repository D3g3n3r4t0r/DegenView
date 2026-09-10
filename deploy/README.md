# Ospitare il sistema su un server proprio

Perché esiste questa cartella: su Fly il sistema girava con **512 MB e una
vCPU condivisa strozzata**. Una ricerca di ottimizzazione ha già saturato
quella memoria una volta, e una macchina senza memoria non è lenta — è
morta, il che dall'esterno significa alert che non arrivano. Qui il
sistema gira su una macchina con margine, e la ricerca non può più
portarsi dietro gli avvisi.

Misurato sullo stesso endpoint (`/api/analyze` BTCUSDT 1d, a caldo):
Fly **1,69 s**, portatile **0,41 s**. Un CX22 sta nel mezzo, intorno ai
0,6–0,7 s.

## Cosa serve

- Un server Ubuntu 24.04 (Hetzner CX22: 2 vCPU, 4 GB, ~4–5 €/mese)
- Il dominio `liquidityengine.app` (registrato, DNS su Cloudflare) puntato all'IP del server
- I cinque segreti che erano su Fly

## Primo avvio

**1. Prepara il server** — una volta sola, come root:

```bash
ssh root@<IP>
bash <(curl -fsSL https://raw.githubusercontent.com/lorenzocorazzi-wq/liquidity-analysis-engine/main/deploy/setup-server.sh)
```

Installa Docker, chiude il firewall (aperti solo SSH/HTTP/HTTPS), disattiva
il login SSH con password, attiva aggiornamenti automatici e `fail2ban`,
aggiunge 2 GB di swap e clona il repo in `/opt/liquidity`.

**2. DNS** — un record `A` verso l'IP del server. Il certificato HTTPS si
ottiene **solo** se il nome risolve già lì: fallo prima di avviare.

```
A    @      <IP del server>
A    www    <IP del server>
```

Con Cloudflare, tieni la nuvoletta **grigia** (proxy spento) al primo
avvio, altrimenti Let's Encrypt non riesce a verificare il dominio.

**3. I segreti:**

```bash
cd /opt/liquidity/deploy
cp .env.example .env
nano .env
```

I valori sono quelli che stavano su Fly. Fly non li mostra (tiene solo il
digest), quindi vanno ripresi dalla fonte: il token del bot da BotFather,
la chiave TwelveData dal loro pannello, il PAT da GitHub.
`SESSION_SECRET` può essere nuovo — cambiarlo invalida solo le sessioni
aperte, e basta rifare login.

**4. Avvia:**

```bash
docker compose up -d --build
docker compose logs -f
```

## Portare i dati da Fly

Segnalazioni, utenti, diario ordini e alert sul prezzo vivono nel volume,
non nel repo. Da questo PC:

```bash
# 1. scarica dal volume di Fly
flyctl ssh console -a liquidity-analysis-engine -C "tar czf - -C /srv/backend/data ." > dati-fly.tar.gz

# 2. mandali sul server nuovo
scp -i ~/.ssh/hetzner dati-fly.tar.gz root@<IP>:/tmp/

# 3. scompattali dentro il volume del container
ssh -i ~/.ssh/hetzner root@<IP>
docker run --rm -v deploy_app-data:/data -v /tmp:/backup alpine \
  sh -c "tar xzf /backup/dati-fly.tar.gz -C /data"
docker compose -f /opt/liquidity/deploy/docker-compose.yml restart app
```

Le **risoluzioni** delle segnalazioni no: quelle stanno nel repo
(`backend/app/data/resolutions.json`) e arrivano da sole con il codice.

## Deploy automatico

Dopo il primo avvio, ogni push su `main` fa il deploy da solo. Servono tre
segreti nel repo GitHub (*Settings → Secrets and variables → Actions*):

| segreto | valore |
|---|---|
| `HETZNER_HOST` | l'IP del server |
| `HETZNER_USER` | `root` |
| `HETZNER_SSH_KEY` | il contenuto di `~/.ssh/hetzner` (la chiave **privata**) |

A differenza di Fly, la pipeline esegue anche i **test** prima di
deployare, non solo il lint.

## Quando qualcosa non va

```bash
cd /opt/liquidity/deploy
docker compose ps                  # chi è su e chi no
docker compose logs --tail 100 app # cosa dice l'app
docker compose logs caddy          # problemi di certificato
docker stats --no-stream           # quanta memoria sta usando davvero
docker compose restart app
```

**Il certificato non arriva**: il DNS non punta ancora qui, oppure il
proxy Cloudflare è acceso. Verifica con `dig +short <dominio>`.

**L'app riparte in continuazione**: `docker compose logs app` lo dice. Se
è memoria, si vede da `docker stats` — il tetto è a 3 GB in
`docker-compose.yml`.

## Tenere Fly come riserva

Fly può restare acceso in parallelo qualche giorno: costa poco e ti lascia
tornare indietro puntando di nuovo il DNS. Quando sei sicuro:

```bash
flyctl scale count 0 -a liquidity-analysis-engine
```
