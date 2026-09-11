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
