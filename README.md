# Influx

Crawler asincrono che, per ogni organizzazione, esplora il sito web indicato,
salva le pagine e i documenti trovati (PDF, DOCX, TXT, DOC, ODT), spezza il
testo in chunk e ne calcola gli embedding con un modello locale via Ollama.

Ogni fase è un comando indipendente (`crawl`, `embed`) che legge e scrive sul
database: si possono lanciare in momenti diversi e rilanciare senza rifare il
lavoro già fatto.

## Requisiti

- [uv](https://docs.astral.sh/uv/) (gestisce Python 3.13 e le dipendenze)
- [Docker](https://docs.docker.com/get-docker/) con Docker Compose (per il database PostgreSQL)
- [Ollama](https://ollama.com/download) (per gli embedding, solo per il comando `embed`)

## Configurazione

Copia il file di esempio e, se necessario, modifica i valori:

```sh
cp .env.example .env
```

| Variabile     | Default       | Descrizione                                                   |
| ------------- | ------------- | ------------------------------------------------------------- |
| `INFLUX_ENV`  | `development` | `production` manda i log solo su stderr (niente file), vedi "Log" |
| `DB_USER`     | `influx`      | Utente del database                                           |
| `DB_PASSWORD` | `influx`    | Password del database          |
| `DB_HOST`     | `localhost` | Host a cui si connette l'app   |
| `DB_PORT`     | `5432`      | Porta esposta sulla macchina   |
| `DB_NAME`     | `influx`    | Nome del database              |

| Variabile                | Default                  | Descrizione                                   |
| ------------------------ | ------------------------ | --------------------------------------------- |
| `OLLAMA_HOST`            | `http://localhost:11434` | Endpoint di Ollama                            |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text-v2-moe` | Modello per gli embedding                    |
| `EMBEDDING_DIMENSIONS`   | `768`                    | Dimensione dei vettori richiesta al modello   |
| `CHUNK_OVERLAP_WORDS`    | `50`                     | Parole condivise da due chunk consecutivi     |
| `OLLAMA_ENRICHMENT_MODEL`| `qwen3:8b`               | Modello generativo (letto, non ancora usato)  |

| Variabile         | Default           | Descrizione                                              |
| ----------------- | ----------------- | -------------------------------------------------------- |
| `JWT_ALGORITHM`   | `HS256`           | Algoritmo di firma dei token                             |
| `JWT_SECRET_PATH` | `secret.key`      | File con il segreto di firma, letto all'avvio dell'API   |
| `JWT_TTL_MINUTES` | `30`              | Durata dei token                                         |
| `APP_PORT`        | `8000`            | Porta host dell'API con `docker compose --profile api`   |

`EMBEDDING_DIMENSIONS` è sia la dimensione chiesta a Ollama sia la larghezza
della colonna `vector` dei chunk: cambiandola (o cambiando modello) va
ricreata la tabella (`docker compose down -v` e di nuovo `init-db`).
`nomic-embed-text-v2-moe` supporta qualsiasi valore tra 256 e 768 (Matryoshka):
256 riduce di tre volte spazio e tempo di ricerca a fronte di una perdita di
qualità contenuta.

Lo stesso `.env` è letto sia dall'applicazione (che costruisce la stringa di
connessione `postgresql+asyncpg://…`) sia da `docker-compose.yml`, quindi
l'istanza PostgreSQL avviata con Docker corrisponde sempre a ciò che l'app
si aspetta.

Le altre impostazioni (numero di worker, concorrenza, limiti di dimensione,
batching dello storage, dimensione e sovrapposizione dei chunk, logging) sono
costanti in [`src/influx/core/config.py`](src/influx/core/config.py).

## Avvio

### 1. Database

```sh
docker compose up -d --wait
```

Il comando attende che PostgreSQL sia pronto ad accettare connessioni.
L'immagine è `pgvector/pgvector`, cioè PostgreSQL con l'estensione `vector`
usata per gli embedding. I dati sono persistiti nel volume `postgres_data`;
per ripartire da zero (necessario anche se il volume era stato creato con la
vecchia immagine `postgres:latest`):

```sh
docker compose down -v
```

### 2. Dipendenze e tabelle

```sh
uv sync
uv run influx init-db
```

`init-db` abilita l'estensione `vector`, crea tutte le tabelle e, se non
esistono già, un utente di esempio (`mario.rossi@example.com`, password
`placeholder`) con un'organizzazione `Esempio` di cui è amministratore
(`Participation` con ruolo `ADMIN`). È idempotente: può essere rilanciato senza
problemi. Al termine stampa l'`id` dell'organizzazione, che serve al passo
successivo.

Lo stesso comando installa la row-level security (`src/influx/core/rls.py`):
crea il ruolo `influx_api` (senza login), abilita RLS su ogni tabella e
definisce le policy per cui una richiesta API vede e modifica solo le righe
delle organizzazioni di cui l'utente autenticato fa parte (scrittura solo con
ruolo `ADMIN`). Ogni transazione aperta da una route passa a `influx_api`
tramite `SET LOCAL`, quindi le policy valgono per l'API mentre CLI e worker,
collegati come `DB_USER` (proprietario delle tabelle), continuano a vedere
tutto. Aggiungere una tabella richiede una voce in `POLICIES`, altrimenti
`init-db` si rifiuta di partire.

### 3. Utente e organizzazione

Ogni crawl è legato a un'organizzazione, che a sua volta ha un utente
amministratore. `init-db` ne crea già una di esempio; per aggiungerne altre, al
momento non esiste un comando CLI, quindi si inseriscono direttamente in SQL:

```sh
docker compose exec postgres psql -U influx -d influx <<'SQL'
INSERT INTO "user" (name, last_name, email, hashed_password)
VALUES ('Anna', 'Bianchi', 'anna.bianchi@example.com', 'placeholder');

INSERT INTO organization (name, administrator_id)
VALUES ('Altra', currval('user_id_seq'));

INSERT INTO participation (organization_id, user_id, role)
VALUES (currval('organization_id_seq'), currval('user_id_seq'), 'ADMIN');

SELECT id, name FROM organization;
SQL
```

Se hai cambiato `DB_USER` o `DB_NAME` nel `.env`, adegua le opzioni `-U` e
`-d`.

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

Gli URL dello stesso sito vengono canonicalizzati prima di entrare in coda
(schema e host del root, `?utm_*`/`fbclid` rimossi, parametri ordinati), così
`http://esempio.it/x` e `https://www.esempio.it/x?fbclid=…` sono la stessa
pagina. Viene richiesto come pagina solo un path senza estensione o con
un'estensione da pagina (`PAGE_EXTENSIONS` in `config.py`); immagini, feed,
archivi e simili non vengono mai richiesti.

#### Escludere URL

Alcuni siti hanno "trappole" per i crawler: liste con pager combinatori,
calendari infiniti, filtri a faccette. Si escludono con regex applicate a
path + query dell'URL (mai all'host), da riga di comando o da file:

```sh
uv run influx crawl --organization-id 1 https://www.esempio.it \
  --exclude '^/ateneo/bandi[?]' \
  --exclude-file rules/esempio.txt
```

Il file ha una regex per riga; righe vuote e commenti `#` sono ignorati:

```
# pager multiplo di Drupal: /ateneo/bandi?page=,0,3,120 esplode in migliaia di URL
^/ateneo/bandi[?]
# feed per tassonomia
/feed$
```

Le regex non sono ancorate automaticamente: `^/ateneo/bandi[?]` esclude la
lista paginata ma lascia passare `/ateneo/bandi` e `/ateneo/bandi/2025`.

### 5. Embedding

Serve Ollama in esecuzione con il modello scaricato:

```sh
ollama pull nomic-embed-text-v2-moe
uv run influx embed --organization-id 1
```

Il comando prende le pagine dell'organizzazione (i documenti non sono ancora
gestiti), spezza il testo di ognuna in finestre di `MAX_WORDS_PER_CHUNK`
parole con `CHUNK_OVERLAP_WORDS` parole di sovrapposizione, chiede a Ollama i
vettori a lotti di `EMBEDDING_BATCH_SIZE` chunk e salva il risultato nella
tabella `contentchunk` (una riga per chunk: testo, posizione, embedding).

I valori di default sono tarati su `nomic-embed-text-v2-moe`, che legge al
massimo 512 token: in italiano il suo tokenizer produce circa 1,7 token per
parola, quindi 250 parole per chunk lasciano margine per testi ricchi di URL,
codici e nomi propri. Il modello vuole inoltre un prefisso diverso per
documenti (`search_document: `) e domande (`search_query: `); il servizio lo
aggiunge da solo prima di chiamare Ollama e non lo salva nel chunk. Un chunk
che supera comunque il contesto viene troncato con un avviso nel log, mai in
silenzio. Se cambi modello, rivedi `MAX_WORDS_PER_CHUNK` e i prefissi in
`config.py`.

È incrementale: ogni chunk memorizza l'hash del contenuto della pagina da cui
è stato generato, quindi al lancio successivo vengono rielaborate solo le
pagine il cui contenuto è cambiato dopo un nuovo crawl; le altre vengono
saltate. Ogni pagina è salvata in una transazione a sé, quindi un'interruzione
con Ctrl+C perde al massimo la pagina in corso. Per rigenerare tutto (ad
esempio dopo aver cambiato i parametri di chunking):

```sh
uv run influx embed --organization-id 1 --force
```

Al termine stampa un riepilogo: pagine elaborate, chunk prodotti, pagine
saltate perché invariate e pagine senza testo.

## Comandi disponibili

```
uv run influx init-db                                   # crea le tabelle
uv run influx crawl --organization-id <ID> <URL> [URL…] # avvia uno o più crawl
    [--exclude REGEX]…  [--exclude-file PATH]              #   escludendo URL per path+query
uv run influx embed --organization-id <ID> [--force]     # chunk + embedding delle pagine crawlate
```

## API in Docker

`docker-compose.yml` ha un profilo `api` che, oltre a PostgreSQL, avvia
l'API (immagine costruita dal `Dockerfile`, utente non root, `uvicorn
influx.main:app`) e un'istanza di Ollama:

```sh
head -c 64 /dev/urandom | base64 > secret.key   # segreto JWT (JWT_SECRET_PATH)
docker compose --profile api up -d --build --wait
docker compose exec ollama ollama pull nomic-embed-text-v2-moe
```

L'API risponde su `http://localhost:8000` (`APP_PORT`). Il servizio `app`
legge lo stesso `.env` e sovrascrive solo ciò che dipende dalla rete di
compose (`DB_HOST=postgres`, `OLLAMA_HOST=http://ollama:11434`,
`INFLUX_ENV=production`, il segreto JWT montato da `/run/secrets`). La stessa
immagine esegue anche la CLI:

```sh
docker compose --profile api run --rm app influx crawl --organization-id 1 https://esempio.it
```

### Health check

- `GET /health` — liveness: 200 appena il processo serve richieste.
- `GET /health/ready` — readiness: esegue `SELECT 1` sul database e
  `GET /api/tags` su Ollama; 503 (`application/problem+json`, con l'esito
  di ogni controllo in `checks`) finché uno dei due non risponde. È quello
  usato dall'`healthcheck` di compose.

### Arresto

Un `SIGTERM` (quello di `docker stop`) al comando `crawl` ferma i crawl in
corso in modo pulito: le richieste già in volo terminano, non ne partono di
nuove, quanto raccolto viene scritto sul database e i crawl ancora in coda
restano `PENDING`. Il processo esce con codice 143. Con molte richieste in
volo può servire più dei 10 s di default di Docker: alzare `stop_grace_period`.

## Log

In sviluppo la console mostra una riga per evento; lo stacktrace completo
degli errori finisce in `logs/influx.log` (rotazione automatica a 10 MB, 5
file conservati). Con `INFLUX_ENV=production` non c'è file: tutto, stacktrace
compresi, va su stderr, da dove lo raccoglie il runtime dei container.

## Struttura del progetto

```
src/influx/
├── __init__.py            # entrypoint CLI
├── main.py                # app FastAPI
├── auth/                  # login, JWT, dipendenze get_current_user / require_membership
├── core/                  # config, connessione al DB, RLS, logging, health check
├── crawler/               # crawl, scheduler, storage batch, modelli Page/Document/Link
├── ingestion/             # chunking, embedding via Ollama, modello ContentChunk
├── organization/          # Organization, Participation
└── user/                  # User
```
