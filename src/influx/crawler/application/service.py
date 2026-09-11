import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from urllib.parse import urldefrag, urljoin, urlsplit

import tldextract
from parsel import Selector

from influx.core.config import ALLOWED_EXTENSIONS

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


def is_valid_document(raw_url: str) -> bool:
    """True when the URL's path ends in one of the document extensions we ingest."""
    path = PurePosixPath(urlsplit(raw_url).path)
    return path.suffix.removeprefix(".").lower() in ALLOWED_EXTENSIONS


def host_of(raw_url: str) -> str:
    return (urlsplit(raw_url).hostname or "").lower()


def link_origin(raw_url: str) -> str:
    """Canonical form for a discovered host: `https://host`. Sites link to their
    own subdomains with a mix of schemes; normalising keeps one Link row per host."""
    return f"https://{host_of(raw_url)}"


def registrable_domain(host: str) -> str:
    """`www.esempio.it` -> `esempio.it`, `www.ox.ac.uk` -> `ox.ac.uk`. Empty when unknown."""
    return _extract(host).top_domain_under_public_suffix


@dataclass(frozen=True)
class SiteScope:
    """Decides what a link found during a crawl of `root_url` means for us."""

    root_url: str
    hosts: frozenset[str]  # the site itself: exact host plus its apex alias
    domain: str  # registrable domain that groups the subdomains

    @classmethod
    def for_root(cls, root_url: str) -> "SiteScope":
        host = host_of(root_url)
        if not host:
            raise ValueError(f"root_url has no host: {root_url!r}")
        domain = registrable_domain(host)
        hosts = {host}
        # www.esempio.it and esempio.it are one site, whichever one we started from.
        if host.startswith("www."):
            hosts.add(host.removeprefix("www."))
        elif host == domain:
            hosts.add(f"www.{host}")
        return cls(root_url=root_url, hosts=frozenset(hosts), domain=domain)

    def classify(self, url: str) -> LinkKind:
        host = host_of(url)
        if host in self.hosts:
            return LinkKind.DOCUMENT if is_valid_document(url) else LinkKind.PAGE
        if self.domain and registrable_domain(host) == self.domain:
            return LinkKind.SUBDOMAIN
        return LinkKind.EXTERNAL


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
