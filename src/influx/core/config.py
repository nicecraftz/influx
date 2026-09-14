from os import getenv
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

OLLAMA_ENRICHMENT_MODEL = getenv("OLLAMA_ENRICHMENT_MODEL", "qwen3:8b")
MAX_WORDS_PER_CHUNK = 250
EMBEDDING_BATCH_SIZE = 32
CHUNK_OVERLAP_WORDS = int(getenv("CHUNK_OVERLAP_WORDS", "50"))


CRAWL_WORKERS = 2
CRAWL_MAX_CONCURRENCY = 10
CRAWL_RESPECT_ROBOTS_TXT = True
DOCUMENT_MAX_CONCURRENCY = 4
MAX_DOCUMENT_BYTES = 70 * 1024 * 1024

STORAGE_BATCH_ROWS = 200
STORAGE_BATCH_BYTES = 32 * 1024 * 1024
STORAGE_FLUSH_INTERVAL = 10.0

JWT_ALGORITHM = getenv("JWT_ALGORITHM", "HS256")
JWT_SECRET_PATH = getenv("JWT_SECRET_PATH", "secret.key")
JWT_TTL_MINUTES = int(getenv("JWT_TTL_MINUTES", 30))
