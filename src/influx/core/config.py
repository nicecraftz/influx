from os import getenv
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

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

OLLAMA_HOST = getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_EMBEDDING_MODEL = getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text-v2-moe")
# Requested from the model (nomic-embed-text-v2-moe accepts 256-768 via
# Matryoshka) and used as the width of the vector column, so changing it means
# recreating the chunk table.
EMBEDDING_DIMENSIONS = int(getenv("EMBEDDING_DIMENSIONS", "768"))

# nomic-embed-text-v2-moe is trained with task prefixes: documents and queries
# are embedded with different ones. Not stored, only prepended before embedding.
EMBEDDING_DOCUMENT_PREFIX = "search_document: "
EMBEDDING_QUERY_PREFIX = "search_query: "

OLLAMA_ENRICHMENT_MODEL = getenv("OLLAMA_ENRICHMENT_MODEL", "qwen3:8b")

# The embedding model reads at most 512 tokens and Italian text costs ~1.7
# tokens per word, so 250 words (~425 tokens) leaves room for the prefix and
# for token-heavy content (URLs, codes, names).
MAX_WORDS_PER_CHUNK = 250
CHUNK_OVERLAP_WORDS = 30  # words shared by two consecutive chunks
EMBEDDING_BATCH_SIZE = 32  # chunks per request to Ollama
CHUNK_OVERLAP_WORDS = int(getenv("CHUNK_OVERLAP_WORDS", "50"))

LOG_FILE = Path("logs/influx.log")
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

CRAWL_WORKERS = 2  # crawls running at the same time
CRAWL_MAX_CONCURRENCY = 10  # in-flight requests per crawl
CRAWL_RESPECT_ROBOTS_TXT = True
DOCUMENT_MAX_CONCURRENCY = 4  # attachment downloads in flight per crawl, on top of the pages
MAX_DOCUMENT_BYTES = 64 * 1024 * 1024  # larger attachments are skipped

STORAGE_BATCH_ROWS = 200
STORAGE_BATCH_BYTES = 32 * 1024 * 1024
STORAGE_FLUSH_INTERVAL = 5.0  # seconds
