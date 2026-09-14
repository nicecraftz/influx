"""Blob -> Markdown with MarkItDown, the CPU-bound half of the document pipeline.

Free of database imports on purpose: `convert_blob` runs inside the worker
processes of document_service.py, and every worker imports this module when
it starts.
"""

import io
import signal
from functools import cache
from types import FrameType

from markitdown import MarkItDown, StreamInfo


class ConversionTimeout(BaseException):
    """BaseException, not Exception: MarkItDown's PDF converter wraps its work
    in `except Exception` and falls back to a second, unbounded pdfminer pass,
    which would swallow the alarm and defeat the timeout."""


@cache
def _markitdown() -> MarkItDown:
    return MarkItDown(enable_plugins=False)

def convert_blob(blob: bytes, *, extension: str | None, content_type: str | None, timeout: int) -> str:
    """Markdown for `blob`. `extension` (".pdf") and `content_type` tell
    MarkItDown which converter to use; either may be None.

    Raises ConversionTimeout after `timeout` seconds, and MarkItDown's own
    UnsupportedFormatException / FileConversionException otherwise.
    """

    def on_alarm(signum: int, frame: FrameType | None) -> None:
        raise ConversionTimeout(f"{timeout} s")

    # SIGALRM is delivered between bytecodes, which is enough for pdfminer's
    # pure-Python loops; the pdfium calls pdfplumber makes are per page and
    # return quickly. Only valid in the main thread, which a pool worker is.
    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.alarm(timeout)
    try:
        result = _markitdown().convert_stream(
            io.BytesIO(blob), stream_info=StreamInfo(extension=extension, mimetype=content_type)
        )
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return result.markdown
