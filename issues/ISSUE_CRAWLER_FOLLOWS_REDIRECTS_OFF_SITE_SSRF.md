# Crawler follows redirects to any host, including internal ones (SSRF), and stores the result under the original URL

**Priority: high**

## Problem

Same-site scoping is applied to the *requested* URL only (`SiteScope.classify` in
`crawler/application/service.py:132`). `ImpitHttpClient` follows up to 20 redirects
(`crawlee/http_clients/_impit.py:137-138`) and neither `handle_page` nor `_download_document`
(`crawler/application/crawler.py:119-153`, `229-256`) re-checks the final host. A page on the organization's
site that answers `302 Location: http://169.254.169.254/latest/meta-data/iam/security-credentials/`,
`http://postgres:5432`, `http://ollama:11434/api/tags` or `http://localhost:8000/health/ready` makes the
API container fetch it, and the body is saved as a `Page`/`Document` of the organization, readable by every
member via retrieval. Cloud metadata endpoints are the classic target; the compose network (`postgres`,
`ollama`) is reachable by name.

The organization "attacks" its own scope, but the *host* is the victim (credentials, internal services).
Once organizations/links can be created or edited through the API (`ISSUE_ORGANIZATION_API_MISSING.md`),
`Organization.domain` / `Link.url` become a direct SSRF vector as well (nothing validates them today,
despite the model comment "validated with tldextract").

Related correctness bug: the page is stored under `context.request.url`, not `loaded_url`, so a redirected
page is indexed under a URL that no longer serves it and redirect targets are not deduplicated.

## Approach

1. Disable automatic redirect following in the crawler's HTTP client (`ImpitHttpClient(follow_redirects=False)`)
   and handle 3xx in the handler: resolve `Location`, run it through `scope.canonical`/`scope.classify`, and
   only `add_requests` it if it is `PAGE`/`DOCUMENT`; otherwise drop it. Same for document downloads
   (loop manually with a small redirect cap).
2. Add a host deny-list check before any fetch: reject IP literals in private/loopback/link-local ranges
   (`ipaddress.ip_address(...).is_private / is_loopback / is_link_local / is_reserved`), `localhost`, and
   `.internal`/compose service names. Ideally resolve DNS first and check the resolved address too
   (DNS rebinding), or run the crawler with an egress policy that blocks RFC1918 + metadata ranges.
3. Validate `Organization.domain` (tldextract: must have a public suffix, not an IP) and `Link.url` (must be
   `https://` + a host whose registrable domain equals `organization.domain`) at write time, in the service
   layer, before the API exposes them.
4. Store pages under the final URL (`context.request.loaded_url`) after it passes the scope check.
