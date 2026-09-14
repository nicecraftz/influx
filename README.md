# Influx

Crawler asincrono che, per ogni organizzazione, esplora il sito web indicato,
salva le pagine e i documenti trovati (PDF, DOCX, TXT, DOC, ODT), spezza il
testo in chunk e ne calcola gli embedding con un modello locale via Ollama.

Ogni fase è un comando indipendente (`crawl`, `convert`, `embed`) che legge e scrive sul
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
| `OLLAMA_ANSWER_MODEL`    | `qwen3:8b`               | Modello generativo per le risposte            |

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
(`Participation` con ruolo `SUPER_ADMIN`) e il cui sito
(`https://example.com`) è il primo `Link` abilitato. È idempotente: può essere
rilanciato senza problemi. Al termine stampa l'`id` dell'organizzazione, che
serve al passo successivo.

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

Ogni crawl è legato a un'organizzazione, identificata dal suo dominio
registrabile (`domain`, es. `esempio.it`). Chi la amministra è deciso solo da
`participation.role` (`SUPER_ADMIN`, `ADMIN`, `VIEWER`): un'organizzazione
nasce sempre insieme alla partecipazione del suo primo `SUPER_ADMIN` e a un
`Link` abilitato per il suo sito, da cui partono i crawl richiesti via API
(vedi "Crawl dall'API"). I sottodomini scoperti durante un crawl diventano
altri `Link`, disabilitati finché un amministratore non li attiva.
`init-db` ne crea già una di esempio (`mario.rossi@example.com` /
`placeholder`); per aggiungerne altre, al momento non esiste un comando CLI,
quindi si inseriscono direttamente in SQL. L'email va in minuscolo e la
password è un hash bcrypt (`uv run python -c "from influx.auth.application.password import encrypt_password; print(encrypt_password('...').decode())"`):

```sh
docker compose exec postgres psql -U influx -d influx <<'SQL'
INSERT INTO "user" (name, last_name, email, hashed_password)
VALUES ('Anna', 'Bianchi', 'anna.bianchi@example.com', '$2b$12$...');

INSERT INTO organization (name, domain)
VALUES ('Altra', 'altra.it');

INSERT INTO participation (organization_id, user_id, role)
VALUES (currval('organization_id_seq'), currval('user_id_seq'), 'SUPER_ADMIN');

INSERT INTO link (organization_id, url, enabled)
VALUES (currval('organization_id_seq'), 'https://altra.it', true);

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
sono conclusi. La CLI è lo strumento dell'operatore: crawla gli URL indicati
senza passare dai `Link` né dal limite giornaliero dell'API.

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

### 5. Conversione dei documenti

```sh
uv run influx convert --organization-id 1
```

Il comando prende i documenti dell'organizzazione (i blob salvati dal crawl)
e ne estrae il testo in Markdown con [MarkItDown](https://github.com/microsoft/markitdown)
(PDF via pdfminer/pdfplumber, DOCX, TXT), salvandolo nella colonna `text`
della tabella `document`, accanto al blob. I formati che MarkItDown non
gestisce (`.doc`, `.odt`) e i file corrotti vengono segnati come falliti con
il motivo in `conversion_error`.

La conversione è CPU-bound e in puro Python, quindi gira in un pool di
`CONVERT_WORKERS` processi (i core della macchina meno uno). Come riferimento,
un PDF di 1000 pagine si converte in circa 35 s su un portatile: 4000 PDF da
8 MB sono nell'ordine delle ore, non dei minuti. Un documento che supera
`CONVERT_TIMEOUT` secondi viene segnato come fallito e il pool passa al
successivo.

Un PDF scansionato (solo immagini, senza livello di testo) si converte in un
attimo ma produce zero caratteri: il riepilogo finale li conta come "without
text" e il log segnala l'URL. Per quelli serve OCR, che oggi non è previsto.

È incrementale come `embed`: ogni documento memorizza l'hash del blob da cui
è stato estratto il testo, quindi al lancio successivo vengono riconvertiti
solo i documenti nuovi o cambiati dopo un nuovo crawl. Un documento fallito
non viene ritentato finché non si passa `--force`, che riconverte tutto:

```sh
uv run influx convert --organization-id 1 --force
```

Ogni documento è salvato in una transazione a sé: un'interruzione con Ctrl+C
perde al massimo i documenti in corso nei worker.

### 6. Embedding

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
uv run influx convert --organization-id <ID> [--force]   # estrae il testo dei documenti crawlati
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

### Crawl dall'API

L'API esegue i crawl nello stesso processo (uno scheduler avviato con l'app,
`crawler/application/scheduler.py`) secondo la regola in
`crawler/application/policy.py`: un crawl di un'organizzazione è un `Crawl`
per ogni suo `Link` abilitato, e un'organizzazione viene crawlata al massimo
una volta ogni `CRAWL_INTERVAL` (24 ore), chiunque lo chieda.

- `POST /api/v1/crawler/organizations/{id}` — un `ADMIN` o `SUPER_ADMIN`
  dell'organizzazione richiede il crawl: 202 con la lista dei `Crawl`
  accodati. Se l'organizzazione è già stata crawlata nelle ultime 24 ore
  risponde 429 con `Retry-After` e `next_allowed_at`; 409 se non ha `Link`
  abilitati o è inattiva.
- `GET /api/v1/crawler/organizations/{id}` — i crawl dell'organizzazione,
  dal più recente (`limit`/`offset`), per ogni membro.
- `GET /api/v1/crawler/{crawl_id}` — un crawl con stato, contatori ed
  eventuale errore; 404 se non appartiene alle organizzazioni del chiamante.

Ogni `CRAWL_SWEEP_INTERVAL` (10 minuti) l'API accoda un crawl automatico
(`automated = true`) per le organizzazioni attive con almeno un `Link`
abilitato che non hanno crawl negli ultimi `CRAWL_INTERVAL`: una richiesta
manuale sposta quindi in avanti di 24 ore il prossimo crawl automatico. Conta
la creazione del `Crawl`, non il suo esito: un crawl fallito non riapre la
finestra (resta la CLI).

All'avvio l'API riprende i crawl rimasti `PENDING` da un processo precedente
e chiude come `FAILED` quelli che erano `ONGOING` quando è terminato. Lo
scheduler vive nel processo dell'API: va eseguita con un solo worker uvicorn
(com'è nel `Dockerfile`), altrimenti ogni worker accoderebbe gli stessi crawl.

### Domande e risposte

Il chatbot è a domanda singola, senza memoria della conversazione: ogni
richiesta viene risolta da sola.

- `POST /api/v1/retrieval/organizations/{id}` — un membro dell'organizzazione
  manda `{"question": "..."}` (da 3 a `QUESTION_MAX_LENGTH` caratteri) e
  riceve la risposta:

  ```json
  {
    "id": 12,
    "question": "Quando posso immatricolarmi?",
    "answer": "Le immatricolazioni sono aperte dal 15 luglio al 30 settembre [1].",
    "sources": [
      {"index": 1, "url": "https://…/immatricolazioni", "title": "Immatricolazioni", "similarity": 0.71, "excerpt": "…"}
    ],
    "latency_ms": 4310
  }
  ```

  La domanda viene trasformata in vettore con lo stesso modello dei chunk
  (`retrieval/application/search_service.py`), i `RETRIEVAL_TOP_K` chunk più
  vicini dell'organizzazione (distanza coseno sull'indice HNSW, filtrata per
  tenant) vengono passati numerati a `OLLAMA_ANSWER_MODEL` con l'istruzione di
  rispondere nella lingua della domanda, solo in base ai passaggi, citandoli
  come `[n]`, e di dire chiaramente quando non contengono la risposta
  (`retrieval/application/answer_service.py`). `sources[n-1]` è il passaggio
  citato come `[n]`; `similarity` è la similarità coseno con la domanda.

  Risponde 409 se l'organizzazione è inattiva o non ha ancora chunk
  (`embed` mai eseguito), 503 se Ollama non risponde o non ha il modello
  (`ollama pull qwen3:8b`).
- `GET /api/v1/retrieval/organizations/{id}/metrics` — per ogni membro:
  domande totali e nelle ultime 24 ore, latenza media, similarità media del
  miglior passaggio e data dell'ultima domanda. Ogni risposta viene registrata
  nella tabella `question` (testo, risposta, similarità, latenza, chi ha
  chiesto).

Oggi rispondono solo le pagine: i documenti convertiti con `convert` non
sono ancora spezzati in chunk.

### Arresto

Un `SIGTERM` (quello di `docker stop`) al comando `crawl` o all'API ferma i
crawl in corso in modo pulito: le richieste già in volo terminano, non ne
partono di nuove, quanto raccolto viene scritto sul database e i crawl ancora
in coda restano `PENDING` (l'API li riprende al riavvio). La CLI esce con
codice 143. Con molte richieste in volo può servire più dei 10 s di default
di Docker: alzare `stop_grace_period`.

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
├── crawler/               # crawl, scheduler, policy giornaliera, storage batch, modelli Page/Document/Link
├── ingestion/             # conversione documenti (MarkItDown), chunking, embedding via Ollama, modello ContentChunk
├── retrieval/             # domanda -> chunk più vicini -> risposta generata da Ollama, modello Question
├── organization/          # Organization, Participation
└── user/                  # User
```
