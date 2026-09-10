FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Mirror the local layout so main.py's Path(__file__).parent^3 / "frontend" resolves correctly.
# Local:  _trading/backend/app/main.py  →  _trading/frontend/
# Docker: /srv/backend/app/main.py      →  /srv/frontend/
WORKDIR /srv

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./backend/app
COPY backend/app_entry.py ./backend/app_entry.py
COPY frontend ./frontend

# Run uvicorn from the backend sub-dir so `app.main` import resolves
# Il processo non gira da root: se un giorno qualcosa dentro l'app venisse
# sfruttato, chi entra si trova un utente senza privilegi invece del padrone
# del container. La cartella dei dati resta scrivibile perche' e' li' che
# vivono segnalazioni, utenti e diario ordini.
RUN useradd --system --uid 10001 --create-home appuser     && mkdir -p /srv/backend/data     && chown -R appuser:appuser /srv
USER appuser

WORKDIR /srv/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
