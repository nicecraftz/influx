import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlsplit, urlunsplit

import tldextract
from parsel import Selector

from influx.core.config import ALLOWED_EXTENSIONS, PAGE_EXTENSIONS, TRACKING_PARAMS

# Offline: the bundled public-suffix snapshot is plenty and avoids a network
# fetch (and a cache dir) at import time.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

_WHITESPACE = re.compile(r"\s+")

# Text nodes under these elements are chrome, not content, when we have to
# fall back from <main> to <body>.
_BODY_TEXT_XPATH = (
    "//body//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)"
    " and not(ancestor::nav) and not(ancestor::header) and not(ancestor::footer)"
    " and not(ancestor::template)]"
)


class LinkKind(Enum):
    PAGE = "page"  # same site, crawl it
    DOCUMENT = "document"  # same site, allowed extension, download it
    SUBDOMAIN = "subdomain"  # same registrable domain, other host: record as Link
    EXTERNAL = "external"  # ignore
    IGNORED = "ignored"  # same site, but neither page nor document, or excluded by a rule


def _extension(raw_url: str) -> str:
    return PurePosixPath(urlsplit(raw_url).path).suffix.removeprefix(".").lower()


def is_valid_document(raw_url: str) -> bool:
    """True when the URL's path ends in one of the document extensions we ingest."""
    return _extension(raw_url) in ALLOWED_EXTENSIONS


def is_page_like(raw_url: str) -> bool:
    """True when the path could be an HTML page: no extension, or a page one."""
    extension = _extension(raw_url)
    return not extension or extension in PAGE_EXTENSIONS


def host_of(raw_url: str) -> str:
    return (urlsplit(raw_url).hostname or "").lower()


def link_origin(raw_url: str) -> str:
    """Canonical form for a discovered host: `https://host`. Sites link to their
    own subdomains with a mix of schemes; normalising keeps one Link row per host."""
    return f"https://{host_of(raw_url)}"


def registrable_domain(host: str) -> str:
    """`www.esempio.it` -> `esempio.it`, `www.ox.ac.uk` -> `ox.ac.uk`. Empty when unknown."""
    return _extract(host).top_domain_under_public_suffix


class UrlRules:
    """Regexes that exclude URLs from a crawl, matched with `re.search` against
    the path plus query (`/ateneo/bandi?page=1`), never the host.

    Built from a text file with one pattern per line; blank lines and lines
    starting with `#` are ignored. Patterns are anchored by the author, so
    `^/ateneo/bandi[?]` excludes the paginated list but not `/ateneo/bandi/2025`.
    """

    def __init__(self, patterns: Iterable[str] = ()) -> None:
        self._patterns = [re.compile(pattern) for pattern in patterns]

    @classmethod
    def from_file(cls, path: str | Path) -> "UrlRules":
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        return cls(line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#"))

    def __len__(self) -> int:
        return len(self._patterns)

    def __add__(self, other: "UrlRules") -> "UrlRules":
        merged = UrlRules()
        merged._patterns = self._patterns + other._patterns
        return merged

    def is_excluded(self, url: str) -> bool:
        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        return any(pattern.search(target) for pattern in self._patterns)


@dataclass(frozen=True)
class SiteScope:
    """Decides what a link found during a crawl of `root_url` means for us."""

    root_url: str
    scheme: str  # scheme of the root: same-site links are rewritten to it
    host: str  # host of the root: same-site links are rewritten to it
    hosts: frozenset[str]  # the site itself: exact host plus its apex alias
    domain: str  # registrable domain that groups the subdomains
    rules: UrlRules = field(default_factory=UrlRules)

    @classmethod
    def for_root(cls, root_url: str, rules: UrlRules | None = None) -> "SiteScope":
        parts = urlsplit(root_url)
        host = (parts.hostname or "").lower()
        if not host:
            raise ValueError(f"root_url has no host: {root_url!r}")
        domain = registrable_domain(host)
        hosts = {host}
        # www.esempio.it and esempio.it are one site, whichever one we started from.
        if host.startswith("www."):
            hosts.add(host.removeprefix("www."))
        elif host == domain:
            hosts.add(f"www.{host}")
        return cls(
            root_url=root_url,
            scheme=parts.scheme,
            host=host,
            hosts=frozenset(hosts),
            domain=domain,
            rules=rules or UrlRules(),
        )

    def classify(self, url: str) -> LinkKind:
        host = host_of(url)
        if host in self.hosts:
            if self.rules.is_excluded(url):
                return LinkKind.IGNORED
            if is_valid_document(url):
                return LinkKind.DOCUMENT
            return LinkKind.PAGE if is_page_like(url) else LinkKind.IGNORED
        if self.domain and registrable_domain(host) == self.domain:
            return LinkKind.SUBDOMAIN
        return LinkKind.EXTERNAL

    def canonical(self, url: str) -> str:
        """One spelling per same-site resource, so the queue and the DB never see
        the same page twice as `http://esempio.it/x`, `https://www.esempio.it/x` and
        `https://www.esempio.it/x?fbclid=...`. Other hosts are left untouched."""
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if host not in self.hosts:
            return url
        netloc = self.host if parts.port is None else f"{self.host}:{parts.port}"
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking_param(k)]
        return urlunsplit((self.scheme, netloc, parts.path or "/", urlencode(sorted(query)), ""))


def _is_tracking_param(name: str) -> bool:
    return name in TRACKING_PARAMS or name.startswith("utm_")


def absolute_links(selector: Selector, base_url: str) -> set[str]:
    """Every http(s) href on the page, resolved against `base_url`, fragments dropped."""
    links: set[str] = set()
    for href in selector.css("a::attr(href)").getall():
        href = href.strip()
        if not href:
            continue
        url, _ = urldefrag(urljoin(base_url, href))
        if urlsplit(url).scheme in ("http", "https"):
            links.add(url)
    return links


def extract_text(selector: Selector) -> str:
    """Visible text of the page: `<main>` when present, otherwise the body minus chrome."""
    nodes = selector.css("main ::text").getall()
    if not nodes:
        nodes = selector.xpath(_BODY_TEXT_XPATH).getall()
    lines = (_WHITESPACE.sub(" ", node).strip() for node in nodes)
    return "\n".join(line for line in lines if line)
