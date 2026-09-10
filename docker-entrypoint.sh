#!/bin/sh
# Il container parte come root apposta: il volume dati (/srv/backend/data)
# e' montato DOPO il build, quindi il chown scritto nel Dockerfile non lo
# tocca mai — vale solo per il layer dell'immagine, non per quello che
# Docker ci sovrappone a runtime. Se il volume esisteva gia' da prima che
# il container smettesse di girare come root (seed-0031), resta di
# proprieta' di quell'utente vecchio per sempre: appuser non puo' scriverci,
# e ogni salvataggio (utenti, preferiti, credenziali) finisce in
# PermissionError. Farlo qui, a ogni avvio, lo ripara da solo invece di
# richiedere un comando a mano sul server ogni volta che il volume cambia
# proprietario per un motivo o per l'altro.
set -e
chown -R appuser:appuser /srv/backend/data
exec su -s /bin/sh appuser -c "cd /srv/backend && exec $*"
