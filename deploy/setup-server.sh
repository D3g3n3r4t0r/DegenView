#!/usr/bin/env bash
# Prepara un server Ubuntu 24.04 appena creato a ospitare il sistema.
#
# Da eseguire UNA VOLTA SOLA, come root, sul server nuovo:
#
#     ssh root@<IP>
#     bash <(curl -fsSL https://raw.githubusercontent.com/lorenzocorazzi-wq/liquidity-analysis-engine/main/deploy/setup-server.sh)
#
# Cosa fa, e perche':
#
# - Docker, per far girare l'app come gia' gira su Fly.
# - Firewall chiuso a tutto tranne SSH e HTTPS. Su una macchina che tiene
#   chiavi con permessi di trading, "esposto solo cio' che serve" non e'
#   pignoleria.
# - Aggiornamenti di sicurezza automatici. Un server auto-ospitato che
#   nessuno aggiorna e' peggio di un servizio gestito, non meglio.
# - Login SSH con sola chiave: niente password da indovinare.
# - fail2ban, che blocca chi ci prova comunque.
# - Swap da 2 GB: non serve a far girare le cose piu' in fretta, serve a
#   dare al kernel un margine invece di uccidere il processo. E' esattamente
#   il caso che vi ha gia' tolto il sito una volta su Fly.

set -euo pipefail

log() { printf "\n\033[1;32m==>\033[0m %s\n" "$*"; }

if [ "$(id -u)" -ne 0 ]; then
	echo "Va eseguito come root." >&2
	exit 1
fi

log "Aggiornamento del sistema"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq

log "Strumenti di base"
apt-get install -y -qq ca-certificates curl git ufw fail2ban unattended-upgrades

log "Docker"
if ! command -v docker >/dev/null 2>&1; then
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	chmod a+r /etc/apt/keyrings/docker.asc
	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
		> /etc/apt/sources.list.d/docker.list
	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

log "Firewall: aperti solo SSH, HTTP e HTTPS"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null    # serve a Let's Encrypt per verificare il dominio
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null

log "SSH: solo chiave, niente password"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
# Su Ubuntu 24.04 la configurazione vera puo' stare in un frammento che
# rimette la password a "yes": senza questo, la riga sopra non ha effetto.
mkdir -p /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nPermitRootLogin prohibit-password\n' > /etc/ssh/sshd_config.d/99-hardening.conf
systemctl reload ssh || systemctl reload sshd

log "fail2ban"
systemctl enable --now fail2ban

log "Aggiornamenti di sicurezza automatici"
dpkg-reconfigure -f noninteractive unattended-upgrades

log "Swap da 2 GB"
if [ ! -f /swapfile ]; then
	fallocate -l 2G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile >/dev/null
	swapon /swapfile
	echo '/swapfile none swap sw 0 0' >> /etc/fstab
	# Usa lo swap solo quando serve davvero, non per abitudine.
	sysctl -w vm.swappiness=10 >/dev/null
	echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
fi

log "Cartella del progetto"
mkdir -p /opt/liquidity
if [ ! -d /opt/liquidity/.git ]; then
	git clone --depth 1 https://github.com/lorenzocorazzi-wq/liquidity-analysis-engine.git /opt/liquidity
fi

cat <<'FINE'

================================================================
Server pronto.

Restano tre cose, in quest'ordine:

  1. Il file dei segreti — senza, l'app parte ma non manda notifiche
     ne' riconosce le sessioni:

       cd /opt/liquidity/deploy
       cp .env.example .env
       nano .env          # incolla i cinque valori

  2. Il dominio: nel DNS crea un record A verso l'IP di questo server,
     poi scrivilo in .env come SITE_DOMAIN. Il certificato si ottiene
     solo se il nome risolve gia' qui.

  3. Avvio:

       cd /opt/liquidity/deploy
       docker compose up -d --build

Poi guarda che sia salito davvero:

       docker compose logs -f

================================================================
FINE
