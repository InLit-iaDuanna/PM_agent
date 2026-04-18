from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_URL_LENGTH = 2000
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 20
PRIVATE_HOST_PREFIXES = ("auth.", "login.", "accounts.")
PRIVATE_PATH_TOKENS = (
    "/login",
    "/log-in",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/oauth",
    "/auth",
    "/session",
    "/account",
)
PRIVATE_QUERY_KEYS = {"token", "sig", "signature", "auth", "session", "sessionid", "access_token", "authuser"}
LOGIN_WALL_TOKENS = ("sign in", "signin", "log in", "login", "登录", "注册", "继续访问", "continue")


class FetchPreflightError(RuntimeError):
    pass


class InvalidFetchUrlError(FetchPreflightError):
    pass


class PrivateAccessError(FetchPreflightError):
    pass


class AccessBlockedError(FetchPreflightError):
    pass


class UnsafeRedirectError(FetchPreflightError):
    def __init__(self, original_url: str, redirect_url: str) -> None:
        super().__init__(f"Unsafe redirect blocked: {original_url} -> {redirect_url}")
        self.original_url = original_url
        self.redirect_url = redirect_url


def infer_source_type(url: str) -> str:
    url_lower = url.lower()
    if any(token in url_lower for token in ("reddit.com", "news.ycombinator.com", "x.com", "twitter.com", "forum")):
        return "community"
    if any(token in url_lower for token in ("pricing", "plan", "plans", "billing")):
        return "pricing"
    if any(token in url_lower for token in ("blog", "news", "press")):
        return "article"
    if any(token in url_lower for token in ("docs", "help", "support")):
        return "documentation"
    if any(token in url_lower for token in ("review", "g2.com", "capterra", "producthunt")):
        return "review"
    return "web"


def infer_authority_score(url: str) -> float:
    host = urlparse(url).netloc.lower()
    if any(token in host for token in (".gov", ".edu", "docs.", "help.")):
        return 0.9
    if any(token in host for token in ("github.com", "medium.com", "substack.com", "techcrunch.com")):
        return 0.78
    return 0.72


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    selectors = [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "pubdate"}),
        ("meta", {"name": "publish_date"}),
        ("meta", {"name": "date"}),
    ]
    for name, attrs in selectors:
        element = soup.find(name, attrs=attrs)
        if element and element.get("content"):
            return element["content"]
    time_element = soup.find("time")
    if time_element and time_element.get("datetime"):
        return time_element["datetime"]
    return None


def _extract_meta_description(soup: BeautifulSoup) -> str:
    selectors = [
        ("meta", {"name": "description"}),
        ("meta", {"property": "og:description"}),
    ]
    for name, attrs in selectors:
        element = soup.find(name, attrs=attrs)
        if element and element.get("content"):
            return element["content"].strip()
    return ""


def _looks_like_noise(text: str) -> bool:
    normalized = " ".join(text.split())
    if len(normalized) < 40:
        return True
    lowered = normalized.lower()
    noise_tokens = (
        "copyright",
        "all rights reserved",
        "cookie",
        "privacy policy",
        "登录",
        "注册",
        "打开app",
        "app下载",
        "上一篇",
        "下一篇",
        "相关阅读",
        "责任编辑",
    )
    if any(token in lowered for token in noise_tokens):
        return True
    separators = normalized.count("|") + normalized.count("·") + normalized.count("/")
    return separators >= 8 and len(normalized) < 160


def _collect_text_blocks(soup: BeautifulSoup) -> list[str]:
    scoped_selectors = [
        "article h1",
        "article h2",
        "article h3",
        "article p",
        "article li",
        "main h1",
        "main h2",
        "main h3",
        "main p",
        "main li",
        "[role='main'] h1",
        "[role='main'] h2",
        "[role='main'] h3",
        "[role='main'] p",
        "[role='main'] li",
        ".article h1",
        ".article h2",
        ".article h3",
        ".article p",
        ".article li",
        ".content h1",
        ".content h2",
        ".content h3",
        ".content p",
        ".content li",
    ]
    fallback_selectors = ["h1", "h2", "h3", "p", "li", "td"]
    text_blocks: list[str] = []
    seen = set()

    for selector_group in (scoped_selectors, fallback_selectors):
        for selector in selector_group:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                normalized = " ".join(text.split())
                if normalized in seen or _looks_like_noise(normalized):
                    continue
                seen.add(normalized)
                text_blocks.append(normalized)
                if len(text_blocks) >= 36:
                    return text_blocks
        if text_blocks:
            return text_blocks
    return text_blocks


def _normalized_port(parsed) -> Optional[int]:
    if parsed.port is not None:
        return parsed.port
    if parsed.scheme == "https":
        return 443
    if parsed.scheme == "http":
        return 80
    return None


def _strip_www(hostname: str) -> str:
    return hostname[4:] if hostname.startswith("www.") else hostname


def _looks_like_private_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if any(hostname.startswith(prefix) for prefix in PRIVATE_HOST_PREFIXES):
        return True
    if any(token in path for token in PRIVATE_PATH_TOKENS):
        return True
    if query_keys.intersection(PRIVATE_QUERY_KEYS):
        return True
    return False


def _validate_fetch_url(url: str) -> None:
    if len(url) > MAX_URL_LENGTH:
        raise InvalidFetchUrlError("URL is too long")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise InvalidFetchUrlError("Unsupported URL scheme")
    if not parsed.hostname or "." not in parsed.hostname:
        raise InvalidFetchUrlError("URL hostname is invalid")
    if parsed.username or parsed.password:
        raise InvalidFetchUrlError("URL credentials are not allowed")
    if _looks_like_private_url(url):
        raise PrivateAccessError("URL points to a private or authenticated page")


def _is_permitted_redirect(original_url: str, redirect_url: str) -> bool:
    parsed_original = urlparse(original_url)
    parsed_redirect = urlparse(redirect_url)
    if parsed_redirect.username or parsed_redirect.password:
        return False
    if parsed_original.scheme != parsed_redirect.scheme:
        if not (parsed_original.scheme == "http" and parsed_redirect.scheme == "https"):
            return False
    if _normalized_port(parsed_original) != _normalized_port(parsed_redirect):
        return False
    return _strip_www((parsed_original.hostname or "").lower()) == _strip_www((parsed_redirect.hostname or "").lower())


async def _fetch_response_with_safe_redirects(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
    depth: int = 0,
) -> httpx.Response:
    if depth > MAX_REDIRECTS:
        raise UnsafeRedirectError(url, url)

    response = await client.get(url, headers=headers, follow_redirects=False)
    if response.status_code in {301, 302, 303, 307, 308}:
        redirect_location = response.headers.get("location")
        if not redirect_location:
            raise InvalidFetchUrlError("Redirect is missing a location header")
        redirect_url = urljoin(str(response.url), redirect_location)
        if _looks_like_private_url(redirect_url):
            raise PrivateAccessError("Redirect target requires authentication")
        if not _is_permitted_redirect(str(response.url), redirect_url):
            raise UnsafeRedirectError(str(response.url), redirect_url)
        return await _fetch_response_with_safe_redirects(client, redirect_url, headers, depth + 1)
    return response


def _looks_like_login_wall(soup: BeautifulSoup, final_url: str) -> bool:
    if _looks_like_private_url(final_url):
        return True

    password_input_present = any(str(element.get("type") or "").strip().lower() == "password" for element in soup.find_all("input"))
    if not password_input_present:
        return False

    title_parts: list[str] = []
    if soup.title and soup.title.string:
        title_parts.append(soup.title.string.strip())
    h1 = soup.find("h1")
    if h1:
        title_parts.append(h1.get_text(" ", strip=True))
    title_text = " ".join(part for part in title_parts if part).lower()

    form_actions = " ".join(str(form.get("action") or "").strip().lower() for form in soup.find_all("form"))
    visible_text_parts: list[str] = []
    for element in soup.find_all(["h1", "h2", "p", "label", "button"]):
        text = element.get_text(" ", strip=True)
        if text:
            visible_text_parts.append(text)
        if len(visible_text_parts) >= 8:
            break
    visible_text = " ".join(visible_text_parts).lower()
    combined_text = " ".join(part for part in (title_text, form_actions, visible_text) if part)
    return any(token in combined_text for token in LOGIN_WALL_TOKENS)


async def _fetch_and_extract_page_with_client(url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    _validate_fetch_url(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    response = await _fetch_response_with_safe_redirects(client, url, headers)
    mitigation_header = str(response.headers.get("cf-mitigated") or "").strip().lower()
    server_header = str(response.headers.get("server") or "").strip().lower()
    if response.status_code in {401, 403, 451} and (
        mitigation_header == "challenge"
        or "cloudflare" in server_header
        or "captcha" in str(response.text or "").lower()
        or "attention required" in str(response.text or "").lower()
    ):
        raise AccessBlockedError("Fetched page is protected by an anti-bot or access challenge")
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        raise ValueError(f"Unsupported content type: {content_type}")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag_name in ("script", "style", "noscript", "svg", "nav", "aside", "footer", "form", "button", "input"):
        for tag in soup.find_all(tag_name):
            tag.decompose()

    if _looks_like_login_wall(soup, str(response.url)):
        raise PrivateAccessError("Fetched page is an authentication wall")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else url

    text_blocks = _collect_text_blocks(soup)
    meta_description = _extract_meta_description(soup)

    full_text = "\n".join(text_blocks)
    snippet = text_blocks[0] if text_blocks else meta_description or title
    if len(full_text) < 120 and meta_description:
        full_text = "\n".join([snippet, meta_description]).strip()
    return {
        "url": str(response.url),
        "title": title,
        "text": full_text,
        "snippet": snippet,
        "meta_description": meta_description,
        "published_at": extract_published_at(soup),
        "source_type": infer_source_type(str(response.url)),
        "authority_score": infer_authority_score(str(response.url)),
    }


async def fetch_and_extract_page(url: str, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    if client is not None:
        return await _fetch_and_extract_page_with_client(url, client)

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as managed_client:
        return await _fetch_and_extract_page_with_client(url, managed_client)
