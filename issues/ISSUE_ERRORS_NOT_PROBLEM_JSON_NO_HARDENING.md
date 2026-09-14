# Unhandled errors bypass problem+json, no request id, docs public, no CORS/security headers

**Priority: low**

## Problem

- Any exception not derived from `ProblemDetailsException`/`HTTPException` (e.g. the Ollama
  `ConnectionError`, a DB outage) is answered by Starlette's default handler: `text/plain`
  `Internal Server Error`, contradicting the RFC 9457 contract the rest of the API follows, and with no
  correlation id to find the stacktrace in the log.
- `/docs`, `/redoc` and `/openapi.json` are served unauthenticated; harmless now, but they enumerate the
  stub routes and will document every future endpoint publicly.
- No CORS configuration (a browser front-end will need it), no `Strict-Transport-Security`,
  `X-Content-Type-Options`, `Cache-Control: no-store` on token/answer responses.
- `OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")` tells Swagger to POST form data, but the route
  takes JSON, so the "Authorize" button never works.
- uvicorn runs without `--proxy-headers` / `--forwarded-allow-ips`, so behind the reverse proxy the app
  will see the proxy's IP (matters for rate limiting) and `http` as scheme.

## Approach

- `app.add_exception_handler(Exception, …)` returning a 500 problem+json with an `instance`/`request_id`
  (middleware setting `X-Request-ID`, echoed in log records via a `contextvar` filter).
- `FastAPI(docs_url=None if INFLUX_ENV == "production" else "/docs", …)` or protect them with auth.
- `CORSMiddleware` driven by an `ALLOWED_ORIGINS` env var; a tiny middleware for the static security
  headers; `--proxy-headers --forwarded-allow-ips` in the Dockerfile CMD.
- Either accept `OAuth2PasswordRequestForm` on login too, or switch to `HTTPBearer` for the docs.
