from os import getenv
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "txt", "doc", "odt"})
# Database: defaults match .env.example and docker-compose.yml.
DB_USER = getenv("DB_USER", "influx")
DB_PASSWORD = getenv("DB_PASSWORD", "influx")
DB_HOST = getenv("DB_HOST", "localhost")
DB_PORT = int(getenv("DB_PORT", "5432"))
DB_NAME = getenv("DB_NAME", "influx")
DATABASE_URL = (
    f"postgresql+asyncpg://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Logging: console shows one line per event, the rotating file keeps stacktraces.
LOG_FILE = Path("logs/influx.log")
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# Storage batching: a flush happens when either threshold is hit or the interval elapses.
STORAGE_BATCH_ROWS = 200
STORAGE_BATCH_BYTES = 32 * 1024 * 1024
STORAGE_FLUSH_INTERVAL = 5.0  # seconds
