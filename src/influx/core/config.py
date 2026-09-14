from datetime import timedelta
from os import cpu_count, getenv
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

# "development" (default) or "production". Today it only decides where logs
# go (see core/logging.py); the compose app service sets it to production.
INFLUX_ENV = getenv("INFLUX_ENV", "development")

LOG_FILE = Path("logs/influx.log")
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "txt", "doc", "odt"})
PAGE_EXTENSIONS = frozenset({"html", "htm", "xhtml", "shtml", "php", "asp", "aspx", "jsp", "do", "cfm"})
TRACKING_PARAMS = frozenset({"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "_ga"})

DB_USER = getenv("DB_USER", "influx")
DB_PASSWORD = getenv("DB_PASSWORD", "influx")
DB_HOST = getenv("DB_HOST", "localhost")
DB_PORT = int(getenv("DB_PORT", "5432"))
DB_NAME = getenv("DB_NAME", "influx")

DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# NOLOGIN role every API transaction switches to, so that row-level security
# applies to requests while the CLI and the worker (connected as DB_USER, the
# table owner) keep seeing every row. Created by init-db, see core/rls.py.
DB_API_ROLE = "influx_api"

OLLAMA_HOST = getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_EMBEDDING_MODEL = getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text-v2-moe")
EMBEDDING_DIMENSIONS = int(getenv("EMBEDDING_DIMENSIONS", "768"))
EMBEDDING_DOCUMENT_PREFIX = "search_document: "
EMBEDDING_QUERY_PREFIX = "search_query: "

MAX_WORDS_PER_CHUNK = 250
EMBEDDING_BATCH_SIZE = 32
CHUNK_OVERLAP_WORDS = int(getenv("CHUNK_OVERLAP_WORDS", "50"))

# Question answering (retrieval/). The model is asked to answer from the
# RETRIEVAL_TOP_K nearest chunks only; at MAX_WORDS_PER_CHUNK words each they
# are about 2.5k tokens in Italian, which the context window must hold
# together with the prompt and the answer (Ollama's default of 4k would
# silently drop the head of the prompt).
OLLAMA_ANSWER_MODEL = getenv("OLLAMA_ANSWER_MODEL", "qwen3:8b")
RETRIEVAL_TOP_K = 6
ANSWER_CONTEXT_TOKENS = 8192
ANSWER_TEMPERATURE = 0.1
QUESTION_MAX_LENGTH = 1000


CRAWL_WORKERS = 2
CRAWL_MAX_CONCURRENCY = 10
CRAWL_RESPECT_ROBOTS_TXT = True
# An organization is crawled at most once per interval, whether an admin asks
# or the periodic sweep does (crawler/application/policy.py).
CRAWL_INTERVAL = timedelta(hours=24)
# How often the API checks for organizations due for their automatic crawl.
CRAWL_SWEEP_INTERVAL = timedelta(minutes=10)
DOCUMENT_MAX_CONCURRENCY = 4
MAX_DOCUMENT_BYTES = 70 * 1024 * 1024

STORAGE_BATCH_ROWS = 200
STORAGE_BATCH_BYTES = 32 * 1024 * 1024
STORAGE_FLUSH_INTERVAL = 10.0

# Document -> text conversion (ingestion/application/document_service.py).
# pdfminer is pure Python and CPU-bound, so each worker is a process; one
# core is left to the event loop and Postgres.
CONVERT_WORKERS = max(1, (cpu_count() or 2) - 1)
# Seconds one document may take before it is marked failed: a 1000-page PDF
# converts in about 35 s on a laptop, so this only catches pathological files.
CONVERT_TIMEOUT = 600
# A worker process is replaced after this many documents: pdfminer keeps
# per-document caches that never shrink.
CONVERT_TASKS_PER_WORKER = 50

JWT_ALGORITHM = getenv("JWT_ALGORITHM", "HS256")
JWT_SECRET_PATH = getenv("JWT_SECRET_PATH", "secret.key")
JWT_TTL_MINUTES = int(getenv("JWT_TTL_MINUTES", 30))
