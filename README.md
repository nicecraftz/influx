# Influx

Crawler asincrono che, per ogni organizzazione, esplora il sito web indicato,
salva le pagine e i documenti trovati (PDF, DOCX, TXT, DOC, ODT) e li spezza in
chunk di testo pronti per l'ingestione.

## Requisiti

- [uv](https://docs.astral.sh/uv/) (gestisce Python 3.13 e le dipendenze)
- [Docker](https://docs.docker.com/get-docker/) con Docker Compose (per il database PostgreSQL)

## Configurazione

Copia il file di esempio e, se necessario, modifica i valori:

```sh
cp .env.example .env
```

| Variabile     | Default     | Descrizione                    |
| ------------- | ----------- | ------------------------------ |
| `DB_USER`     | `influx`    | Utente del database            |
| `DB_PASSWORD` | `influx`    | Password del database          |
| `DB_HOST`     | `localhost` | Host a cui si connette l'app   |
| `DB_PORT`     | `5432`      | Porta esposta sulla macchina   |
| `DB_NAME`     | `influx`    | Nome del database              |

Lo stesso `.env` è letto sia dall'applicazione (che costruisce la stringa di
connessione `postgresql+asyncpg://…`) sia da `docker-compose.yml`, quindi
l'istanza PostgreSQL avviata con Docker corrisponde sempre a ciò che l'app
si aspetta.

Le altre impostazioni (numero di worker, concorrenza, limiti di dimensione,
batching dello storage, logging) sono costanti in
[`src/influx/core/config.py`](src/influx/core/config.py).

## Avvio

### 1. Database

```sh
docker compose up -d --wait
```

Il comando attende che PostgreSQL sia pronto ad accettare connessioni. I dati
sono persistiti nel volume `postgres_data`; per ripartire da zero:

```sh
docker compose down -v
```

### 2. Dipendenze e tabelle

```sh
uv sync
uv run influx init-db
```

`init-db` crea tutte le tabelle (idempotente: può essere rilanciato senza
problemi).

### 3. Utente e organizzazione

Ogni crawl è legato a un'organizzazione, che a sua volta ha un utente
amministratore. Al momento non esiste un comando CLI per crearli, quindi si
inseriscono direttamente in SQL:

```sh
docker compose exec postgres psql -U influx -d influx <<'SQL'
INSERT INTO "user" (name, last_name, email, hashed_password)
VALUES ('Mario', 'Rossi', 'mario.rossi@example.com', 'placeholder');

INSERT INTO organization (name, administrator_id)
VALUES ('Esempio', currval('user_id_seq'));

SELECT id, name FROM organization;
SQL
```

Se hai cambiato `DB_USER` o `DB_NAME` nel `.env`, adegua le opzioni `-U` e
`-d`. Annota l'`id` restituito: serve al passo successivo.

### 4. Crawl

```sh
uv run influx crawl --organization-id 1 https://esempio.it
```

Si possono passare più URL: ognuno diventa un crawl separato, eseguito dal
pool di worker in-process. Il comando termina quando tutti i crawl in coda
sono conclusi.

Il crawl resta all'interno del dominio dell'organizzazione (sottodomini
compresi), rispetta `robots.txt` e scarica solo i documenti sullo stesso host
della pagina che li linka.

## Comandi disponibili

```
uv run influx init-db                                   # crea le tabelle
uv run influx crawl --organization-id <ID> <URL> [URL…] # avvia uno o più crawl
```

## Log

La console mostra una riga per evento; lo stacktrace completo degli errori
finisce in `logs/influx.log` (rotazione automatica a 10 MB, 5 file
conservati).

## Struttura del progetto

```
src/influx/
├── __init__.py            # entrypoint CLI
├── core/                  # config, connessione al DB, logging
├── crawler/               # crawl, scheduler, storage batch, modelli Page/Document/Link
├── ingestion/             # estrazione testo e chunking
├── organization/          # Organization, Participation
└── user/                  # User
```
