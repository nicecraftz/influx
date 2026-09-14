# Ollama down → `ConnectionError` is not caught → HTTP 500 instead of the documented 503

**Priority: medium**

## Problem

`ollama.AsyncClient._request` converts `httpx.ConnectError` into the **built-in** `ConnectionError`
(`ollama/_client.py:737-738`). `answer_question` (`retrieval/application/answer_service.py:58`) only
catches `(ResponseError, httpx.HTTPError)`, so when Ollama is not running / not reachable the request ends
with an unhandled exception: a plain-text `500 Internal Server Error`, a full stacktrace in the log for every
question, and the README's promise of 503 is false exactly when it matters (Ollama restarting, model
loading). The `embed` CLI dies with a traceback for the same reason.

## Approach

- Catch `ConnectionError` (and `httpx.TimeoutException` once a timeout exists) alongside the others in
  `answer_question`, map to `AnswerUnavailable`.
- Centralise this in a small wrapper in `ingestion/application/embedding_service.py` /
  `answer_service.py` (`async def _call_ollama(coro)`) so every Ollama call maps errors the same way; the
  CLI can then print one line instead of a traceback.
- Add a test with Ollama unreachable (`OLLAMA_HOST=http://127.0.0.1:1`) asserting 503 + problem+json.
