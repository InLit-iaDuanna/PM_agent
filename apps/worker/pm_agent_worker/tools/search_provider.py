import base64
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from pm_agent_worker.tools.content_extractor import infer_authority_score, infer_source_type

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "msclkid",
    "fbclid",
    "gclid",
}

GENERIC_QUERY_TOKENS = {
    "ai",
    "app",
    "apps",
    "tool",
    "tools",
    "software",
    "platform",
    "product",
    "products",
    "market",
    "markets",
    "trend",
    "trends",
    "analysis",
    "report",
    "reports",
    "review",
    "reviews",
    "customer",
    "feedback",
    "smart",
    "official",
    "comparison",
    "alternatives",
    "user",
    "users",
    "pricing",
    "docs",
    "guide",
    "benchmark",
    "中国",
    "美国",
    "产品",
    "工具",
    "平台",
    "市场",
    "趋势",
    "报告",
    "分析",
    "评测",
    "评价",
    "用户反馈",
    "用户",
    "竞品",
    "对比",
    "替代",
    "定价",
    "文档",
    "官网",
    "社区",
}

LOW_VALUE_PATH_TOKENS = (
    "/tag/",
    "/tags/",
    "/topic/",
    "/topics/",
    "/category/",
    "/categories/",
    "/search",
    "/login",
    "/signup",
    "/register",
    "/account",
)

LISTICLE_TITLE_TOKENS = (
    "best ",
    "top ",
    "alternatives",
    "alternative to",
    "tools for",
    "software for",
    "roundup",
    "list of",
    "大全",
    "合集",
    "盘点",
    "推荐",
)

LOW_VALUE_HOST_TOKENS = (
    "pinterest.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
)

PRIMARY_SOURCE_HOST_TOKENS = (
    "docs.",
    "help.",
    "support.",
    "developer.",
    "developers.",
    "pricing",
    "plans",
)

QUERY_INTENT_PATTERNS = {
    "official": ("site:", "official", "官网", "文档", "docs", "help", "support", "developer", "developers"),
    "community": (
        "reddit",
        "forum",
        "community",
        "discussion",
        "feedback",
        "complaint",
        "complaints",
        "社区",
        "论坛",
        "评价",
        "评测",
        "review",
        "reviews",
    ),
    "comparison": ("comparison", "compare", "alternatives", "alternative", "vs", "对比", "替代", "竞品"),
    "analysis": ("analysis", "benchmark", "report", "trend", "trends", "insight", "趋势", "报告", "调研", "研究"),
    "pricing": ("pricing", "price", "plan", "plans", "billing", "cost", "定价", "套餐", "计费"),
}

TOPIC_ANCHOR_STOPWORDS = {
    "official",
    "docs",
    "documentation",
    "help",
    "support",
    "pricing",
    "price",
    "plan",
    "plans",
    "billing",
    "review",
    "reviews",
    "comparison",
    "comparisons",
    "alternatives",
    "alternative",
    "smart",
    "market",
    "markets",
    "trend",
    "trends",
    "analysis",
    "report",
    "reports",
    "benchmark",
    "reddit",
    "forum",
    "community",
    "官网",
    "文档",
    "帮助中心",
    "定价",
    "套餐",
    "计费",
    "评测",
    "评价",
    "社区",
    "论坛",
    "竞品",
    "替代",
    "对比",
    "市场",
    "趋势",
    "报告",
    "分析",
}

GENERIC_KNOWLEDGE_HOST_TOKENS = (
    "wikipedia.org",
    "britannica.com",
    "openai.com",
    "baike.baidu.com",
)

ENGLISH_MARKET_HINT_TOKENS = {
    "analysis",
    "benchmark",
    "billing",
    "case",
    "comparison",
    "docs",
    "glasses",
    "growth",
    "guide",
    "market",
    "official",
    "overview",
    "pricing",
    "report",
    "review",
    "smart",
    "study",
    "support",
    "trends",
    "adoption",
}


class SearchProviderUnavailable(RuntimeError):
    def __init__(self, message: str, cooldown_seconds: float = 120.0, diagnostics: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.cooldown_seconds = float(cooldown_seconds)
        self.diagnostics = diagnostics or {}


class SearchResults(list):
    def __init__(self, items: Optional[Sequence[Dict[str, Any]]] = None, diagnostics: Optional[Dict[str, Any]] = None):
        super().__init__(items or [])
        self.diagnostics = diagnostics or {}


def _decode_duckduckgo_link(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        uddg = query.get("uddg", [])
        if uddg:
            return unquote(uddg[0])
    return url


def _decode_bing_link(url: str) -> str:
    parsed = urlparse(url)
    if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
        query = parse_qs(parsed.query)
        for key in ("u", "url", "r"):
            values = query.get(key, [])
            if values:
                candidate = unquote(values[0]).strip()
                if re.fullmatch(r"a1[a-zA-Z0-9_-]+", candidate):
                    payload = candidate[2:]
                    padding = "=" * (-len(payload) % 4)
                    try:
                        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("ascii")).decode("utf-8")
                    except Exception:
                        decoded = ""
                    if decoded.startswith(("http://", "https://")):
                        return decoded
                return candidate
    return url


def _normalize_result_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return url
    query_items = []
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key.lower() in TRACKING_QUERY_KEYS:
            continue
        for value in values:
            query_items.append((key, value))
    normalized_query = urlencode(sorted(query_items), doseq=True)
    normalized_path = parsed.path.rstrip("/") or "/"
    normalized_host = parsed.netloc.lower()
    if normalized_host.endswith(":80") and parsed.scheme == "http":
        normalized_host = normalized_host[:-3]
    if normalized_host.endswith(":443") and parsed.scheme == "https":
        normalized_host = normalized_host[:-4]
    return urlunparse((parsed.scheme, normalized_host, normalized_path, "", normalized_query, ""))


def _is_ad_or_tracking_url(url: str) -> bool:
    lowered = url.lower()
    parsed = urlparse(lowered)
    host = parsed.netloc
    path = parsed.path
    if any(token in host for token in ("duckduckgo.com", "bing.com")) and any(token in path for token in ("/y.js", "/aclick", "/ck/")):
        return True
    return any(
        token in lowered
        for token in (
            "googleadservices.com",
            "doubleclick.net",
            "/aclick?",
            "ad_domain=",
            "ad_provider=",
            "utm_medium=cpc",
            "msclkid=",
        )
    )


def _is_supported_result_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc and not _is_ad_or_tracking_url(url)


def _looks_like_low_value_page(url: str, title: str, snippet: str) -> bool:
    lowered_title = title.lower()
    lowered_snippet = snippet.lower()
    combined = f"{lowered_title} {lowered_snippet}"
    low_value_tokens = (
        "sign in",
        "log in",
        "subscribe",
        "download app",
        "404",
        "not found",
        "cookie policy",
        "privacy policy",
        "登录",
        "注册",
        "下载",
        "广告",
    )
    if any(token in combined for token in low_value_tokens):
        return True
    parsed = urlparse(url)
    if any(token in parsed.netloc.lower() for token in LOW_VALUE_HOST_TOKENS):
        return True
    return any(token in parsed.path.lower() for token in LOW_VALUE_PATH_TOKENS)


def _query_tokens(query: str) -> List[str]:
    tokens: List[str] = []
    for token in re.findall(r"[a-z0-9][a-z0-9\-_/.]+|[\u4e00-\u9fff]{2,}", query.lower()):
        cleaned = token.strip()
        if len(cleaned) < 2:
            continue
        if cleaned not in tokens:
            tokens.append(cleaned)
    return tokens


def _strong_query_tokens(query: str) -> List[str]:
    return [token for token in _query_tokens(query) if token not in GENERIC_QUERY_TOKENS]


def _topic_anchor_tokens(query: str) -> List[str]:
    anchors: List[str] = []
    for token in _strong_query_tokens(query):
        if token in TOPIC_ANCHOR_STOPWORDS:
            continue
        if token in GENERIC_QUERY_TOKENS:
            continue
        if token.startswith("site:"):
            continue
        if re.fullmatch(r"20[1-3][0-9]", token):
            continue
        if "." in token and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        if len(token) < 2:
            continue
        if token not in anchors:
            anchors.append(token)
    return anchors[:6]


def _normalize_alias_tokens(tokens: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    for token in tokens or ():
        cleaned = str(token or "").strip().lower()
        if not cleaned:
            continue
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _topic_phrase_anchors(anchor_tokens: Sequence[str]) -> List[str]:
    phrases: List[str] = []
    normalized_tokens = [str(token or "").strip().lower() for token in anchor_tokens if str(token or "").strip()]
    for size in (3, 2):
        if len(normalized_tokens) < size:
            continue
        for index in range(0, len(normalized_tokens) - size + 1):
            phrase = " ".join(normalized_tokens[index : index + size]).strip()
            if len(phrase.replace(" ", "")) < 6:
                continue
            if phrase not in phrases:
                phrases.append(phrase)
    for token in normalized_tokens:
        if len(token) < 4:
            continue
        if token not in phrases:
            phrases.append(token)
    return phrases[:6]


def _normalize_entity_signal(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())


def _topic_host_signals(query: str) -> List[str]:
    signals: List[str] = []
    normalized_tokens = [_normalize_entity_signal(token) for token in _topic_anchor_tokens(query)]
    normalized_tokens = [token for token in normalized_tokens if token]
    for size in (3, 2):
        if len(normalized_tokens) < size:
            continue
        for index in range(0, len(normalized_tokens) - size + 1):
            phrase = "".join(normalized_tokens[index : index + size]).strip()
            if len(phrase) < 6:
                continue
            if phrase not in signals:
                signals.append(phrase)
    for token in normalized_tokens:
        if len(token) < 4:
            continue
        if token not in signals:
            signals.append(token)
    return signals[:8]


def _normalized_host_labels(host: str) -> List[str]:
    labels = [part.strip().lower() for part in str(host or "").split(".") if part.strip()]
    if len(labels) > 1:
        labels = labels[:-1]
    normalized: List[str] = []
    for label in labels:
        cleaned = _normalize_entity_signal(label)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _topic_match_features(query: str, title: str, snippet: str, url_text: str) -> Dict[str, Any]:
    anchor_tokens = _topic_anchor_tokens(query)
    phrase_anchors = _topic_phrase_anchors(anchor_tokens)
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    url_lower = url_text.lower()
    title_matched_tokens = [token for token in anchor_tokens if token in title_lower]
    text_matched_tokens = [token for token in anchor_tokens if token in snippet_lower or token in url_lower]
    title_hits = len(title_matched_tokens)
    text_hits = len(text_matched_tokens)
    distinct_token_hits = len(dict.fromkeys([*title_matched_tokens, *text_matched_tokens]))
    phrase_hits = sum(1 for phrase in phrase_anchors if phrase in title_lower or phrase in snippet_lower or phrase in url_lower)
    sparse_match = bool(anchor_tokens) and len(anchor_tokens) >= 3 and phrase_hits == 0 and distinct_token_hits <= 1
    match_score = float(title_hits * 2.2 + text_hits * 1.3 + phrase_hits * 5.0)
    mismatch = bool(anchor_tokens) and ((distinct_token_hits == 0 and phrase_hits == 0) or sparse_match)
    weak_match = bool(anchor_tokens) and not mismatch and match_score < 2.0
    return {
        "anchor_tokens": anchor_tokens,
        "phrase_anchors": phrase_anchors,
        "title_hits": title_hits,
        "text_hits": text_hits,
        "distinct_token_hits": distinct_token_hits,
        "phrase_hits": phrase_hits,
        "match_score": match_score,
        "mismatch": mismatch,
        "weak_match": weak_match,
        "sparse_match": sparse_match,
    }


def _host_topic_alignment_adjustment(query: str, host: str, source_type: str, intent_tags: Sequence[str]) -> float:
    host_signals = _topic_host_signals(query)
    host_labels = _normalized_host_labels(host)
    if not host_signals or not host_labels:
        return 0.0

    matched_signals = [signal for signal in host_signals if signal in host_labels]
    if not matched_signals:
        return 0.0

    score = 18.0
    if source_type in {"pricing", "documentation", "web"}:
        score += 4.0
    if any(tag in {"official", "pricing"} for tag in intent_tags):
        score += 4.0
    if len(matched_signals) >= 2:
        score += 2.0
    return min(28.0, score)


def _query_site_domains(query: str) -> List[str]:
    domains: List[str] = []
    for match in re.findall(r"site:([a-z0-9][a-z0-9.-]+\.[a-z]{2,})", str(query or "").lower()):
        domain = match.strip().strip(".")
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _host_matches_site_domains(host: str, site_domains: Sequence[str]) -> bool:
    normalized_host = str(host or "").strip().lower()
    return any(normalized_host == domain or normalized_host.endswith(f".{domain}") for domain in site_domains)


def _is_homepage(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.path or "/").strip("/") == ""


def _extract_years(text: str) -> List[int]:
    years = []
    for match in re.findall(r"\b(20[1-3][0-9])\b", str(text or "")):
        try:
            year = int(match)
        except ValueError:
            continue
        if year not in years:
            years.append(year)
    return years


def _freshness_adjustment(title: str, snippet: str) -> float:
    years = _extract_years(f"{title} {snippet}")
    if not years:
        return 0.0
    freshest = max(years)
    if freshest >= 2025:
        return 3.5
    if freshest == 2024:
        return 1.5
    if freshest <= 2022:
        return -3.0
    return 0.0


def _looks_like_empty_search_response(html: str, provider_name: str) -> bool:
    lowered = " ".join(str(html or "").lower().split())
    if not lowered:
        return True

    generic_no_result_tokens = (
        "no results",
        "no result",
        "did not match any documents",
        "there are no results for",
        "没有找到",
        "未找到",
        "找不到",
        "无结果",
    )
    if any(token in lowered for token in generic_no_result_tokens):
        return True

    if provider_name == "bing":
        return any(
            token in lowered
            for token in (
                'class="b_no"',
                "class='b_no'",
                "no results found for",
                "<div id='b_content'></div>",
                '<div id="b_content"></div>',
                "<ol id='b_results'></ol>",
                '<ol id="b_results"></ol>',
            )
        )

    if provider_name == "brave":
        return any(
            token in lowered
            for token in (
                'data-type="noresult"',
                "data-type='noresult'",
                "no results found",
                "try checking your spelling",
            )
        )

    if provider_name == "duckduckgo":
        return any(
            token in lowered
            for token in (
                "no results.",
                "no  results.",
                "did not match any documents",
                "zero_click_wrapper",
            )
        )

    return False


def _query_intent_tags(query: str) -> List[str]:
    lowered = str(query or "").lower()
    tags: List[str] = []
    for tag, patterns in QUERY_INTENT_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            tags.append(tag)
    return tags


def _intent_alignment_adjustment(source_type: str, intent_tags: Sequence[str]) -> float:
    if not intent_tags:
        return 0.0

    score = 0.0
    normalized_type = str(source_type or "").strip().lower()
    tag_set = set(intent_tags)

    if "official" in tag_set:
        if normalized_type in {"documentation", "pricing", "web"}:
            score += 8.0
        elif normalized_type in {"community", "review"}:
            score -= 7.0
    if "community" in tag_set:
        if normalized_type in {"community", "review"}:
            score += 8.0
        elif normalized_type in {"documentation", "pricing"}:
            score -= 5.0
    if "comparison" in tag_set:
        if normalized_type in {"review", "article", "web"}:
            score += 5.0
        elif normalized_type == "community":
            score += 2.0
    if "analysis" in tag_set:
        if normalized_type in {"article", "web", "documentation"}:
            score += 4.0
        elif normalized_type == "community":
            score -= 2.0
    if "pricing" in tag_set:
        if normalized_type == "pricing":
            score += 10.0
        elif normalized_type == "community":
            score -= 4.0

    return score


def _looks_like_listicle_or_roundup(url: str, title: str) -> bool:
    lowered_title = str(title or "").lower()
    lowered_path = urlparse(url).path.lower()
    return any(token in lowered_title for token in LISTICLE_TITLE_TOKENS) or any(
        token in lowered_path for token in ("/best-", "/top-", "/roundup", "/alternatives", "/vs-", "/compare")
    )


def _score_result(
    result: Dict[str, Any],
    query: str,
    preferred_source_types: Sequence[str],
    preferred_domains: Sequence[str],
    topic_alias_tokens: Optional[Sequence[str]] = None,
) -> float:
    url = result["url"]
    title = (result.get("title") or "").strip()
    snippet = (result.get("snippet") or "").strip()
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    source_type = result.get("source_type") or infer_source_type(url)
    query_tokens = _query_tokens(query)
    strong_query_tokens = _strong_query_tokens(query)
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    url_text = f"{host} {path}"
    topic_features = _topic_match_features(query, title, snippet, url_text)
    strong_title_hits = sum(1 for token in strong_query_tokens if token in title_lower)
    strong_text_hits = sum(1 for token in strong_query_tokens if token in snippet_lower or token in url_text)
    site_domains = _query_site_domains(query)
    intent_tags = _query_intent_tags(query)
    homepage = _is_homepage(url)
    listicle_like = _looks_like_listicle_or_roundup(url, title)
    authority_score = infer_authority_score(url)

    alias_tokens = _normalize_alias_tokens(topic_alias_tokens)
    host_signal = _normalize_entity_signal(host)
    alias_match_tokens: List[str] = []
    alias_bonus_score = 0.0
    for alias in alias_tokens:
        matched = False
        alias_signal = alias.lower()
        normalized_alias_signal = _normalize_entity_signal(alias)
        if alias_signal and alias_signal in title_lower:
            alias_bonus_score += 6.0
            matched = True
        elif alias_signal and (alias_signal in snippet_lower or alias_signal in url_text):
            alias_bonus_score += 3.0
            matched = True
        elif normalized_alias_signal and normalized_alias_signal in host_signal:
            alias_bonus_score += 4.0
            matched = True
        if matched:
            alias_match_tokens.append(alias)
    score = 0.0
    score += 6.0 if title else -4.0
    score += 3.0 if snippet else -2.0
    score += min(11.0, sum(1.8 for token in query_tokens if token in title_lower or token in snippet_lower))
    score += min(7.0, sum(1.1 for token in query_tokens if token in url_text))
    score += min(14.0, strong_title_hits * 4.0 + strong_text_hits * 2.5)
    score += min(18.0, topic_features["match_score"] * 2.8)

    if source_type in preferred_source_types:
        score += 18.0
    if any(domain in host for domain in preferred_domains):
        score += 20.0
    score += authority_score * 8.0
    score += min(12.0, alias_bonus_score)
    score += _intent_alignment_adjustment(source_type, intent_tags)
    score += _host_topic_alignment_adjustment(query, host, source_type, intent_tags)

    if source_type == "documentation":
        score += 10.0
    elif source_type == "pricing":
        score += 9.0
    elif source_type == "review":
        score += 8.0
    elif source_type == "community":
        score += 6.0
    elif source_type == "article":
        score += 4.0

    if any(token in host for token in PRIMARY_SOURCE_HOST_TOKENS):
        score += 6.0
    if any(token in host for token in ("g2.com", "capterra.com", "reddit.com", "github.com")):
        score += 5.0
    if any(token in title_lower for token in ("pricing", "plan", "review", "benchmark", "case study", "guide", "comparison", "alternatives", "vs")):
        score += 4.0
    if any(token in snippet_lower for token in ("updated", "2024", "2025", "2026", "最新", "报告", "调查", "用户", "pricing", "review")):
        score += 2.0
    if any(token in host for token in ("docs.", "support.", "help.", "pricing", "plans")) and any(token in url_text for token in query_tokens):
        score += 6.0
    score += _freshness_adjustment(title, snippet)
    if site_domains and any(domain in host for domain in site_domains):
        score += 12.0
        if any(host == domain or host.endswith(f".{domain}") for domain in site_domains):
            score += 4.0
    elif site_domains:
        score -= 8.0
    if strong_query_tokens and strong_title_hits == 0 and strong_text_hits == 0:
        score -= 18.0
    elif strong_query_tokens and strong_title_hits == 0 and strong_text_hits == 1:
        score -= 6.0
    if alias_tokens and not alias_match_tokens:
        score -= 12.0
    if topic_features["mismatch"]:
        score -= 36.0
    elif topic_features["weak_match"]:
        score -= 10.0
    if homepage and source_type not in {"documentation", "pricing", "review"}:
        score -= 4.5
    if any(token in path for token in ("/collections/", "/roundup/", "/top-", "/best-")) and not strong_title_hits:
        score -= 8.0
    if listicle_like and source_type not in {"review", "documentation"}:
        score -= 9.0
    if listicle_like and strong_title_hits == 0:
        score -= 6.0
    if _looks_like_low_value_page(url, title, snippet):
        score -= 30.0
    if source_type == "article" and not strong_query_tokens and not preferred_domains:
        score -= 2.0
    if source_type in {"web", "article"} and homepage and not any(domain in host for domain in preferred_domains):
        score -= 3.0
    if any(token in host for token in GENERIC_KNOWLEDGE_HOST_TOKENS):
        if topic_features["mismatch"]:
            score -= 24.0
        elif topic_features["match_score"] < 2.0:
            score -= 10.0
    if parsed.scheme == "https":
        score += 1.5
    if len(parsed.path.split("/")) >= 3:
        score += 1.0

    score += alias_bonus_score
    if alias_tokens and not alias_match_tokens:
        score -= 10.0

    result["topic_anchor_tokens"] = topic_features["anchor_tokens"]
    result["topic_phrase_anchors"] = topic_features["phrase_anchors"]
    result["topic_match_score"] = round(topic_features["match_score"], 2)
    result["topic_mismatch"] = bool(topic_features["mismatch"])
    result["topic_sparse_match"] = bool(topic_features["sparse_match"])
    result["strong_query_hits"] = int(strong_title_hits + strong_text_hits)
    result["alias_match_tokens"] = alias_match_tokens
    result["alias_match_score"] = round(alias_bonus_score, 2)
    result["alias_required"] = bool(alias_tokens)
    result["alias_mismatch"] = bool(alias_tokens and not alias_match_tokens)
    return score


def _extend_unique_results(
    base: Sequence[Dict[str, Any]],
    extras: Sequence[Dict[str, Any]],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    merged = list(base)
    seen_urls = {str(item.get("url") or "").strip() for item in merged if str(item.get("url") or "").strip()}
    for item in extras:
        url = str(item.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append(item)
        if limit is not None and len(merged) >= limit:
            break
    return merged


def _finalize_scored_results(query: str, merged_results: Sequence[Dict[str, Any]], max_results: int) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen_urls = set()
    seen_signatures = set()
    for result in sorted(merged_results, key=lambda item: item.get("score", 0), reverse=True):
        normalized_url = _normalize_result_url(result["url"])
        if normalized_url in seen_urls:
            continue
        if not _is_supported_result_url(normalized_url):
            continue
        signature = f"{urlparse(normalized_url).netloc.lower()}::{(result.get('title') or '').strip().lower()[:120]}"
        if signature in seen_signatures:
            continue
        seen_urls.add(normalized_url)
        seen_signatures.add(signature)
        deduped.append({**result, "url": normalized_url})

    site_domains = _query_site_domains(query)
    if site_domains:
        deduped = [item for item in deduped if _host_matches_site_domains(urlparse(item["url"]).netloc.lower(), site_domains)]

    if any(bool(item.get("alias_required")) for item in deduped):
        alias_matches = [item for item in deduped if item.get("alias_match_tokens")]
        if alias_matches:
            # Prefer alias matches first, but do not collapse the result pool to a
            # single host when only a thin slice matched the alias heuristic.
            if len(alias_matches) >= min(max_results, 3):
                deduped = alias_matches
            else:
                deduped = _extend_unique_results(
                    alias_matches,
                    deduped,
                    limit=max(max_results * 2, len(alias_matches)),
                )

    topic_anchors = _topic_anchor_tokens(query)
    if topic_anchors:
        topic_filtered_source = list(deduped)
        strict_topic_matches = [
            item
            for item in deduped
            if not bool(item.get("topic_mismatch"))
            and not bool(item.get("topic_sparse_match"))
            and float(item.get("topic_match_score", 0) or 0) >= 2.0
        ]
        weak_topic_matches = [
            item
            for item in deduped
            if not bool(item.get("topic_mismatch"))
            and not bool(item.get("topic_sparse_match"))
            and float(item.get("topic_match_score", 0) or 0) > 0
        ]
        broad_topic_matches = [
            item
            for item in topic_filtered_source
            if float(item.get("score", 0) or 0) >= 16.0 and int(item.get("strong_query_hits", 0) or 0) >= 1
        ]
        selected_topic_matches = strict_topic_matches or weak_topic_matches or broad_topic_matches
        if selected_topic_matches:
            fallback_topic_matches = [
                item
                for item in topic_filtered_source
                if item not in selected_topic_matches
                and (
                    not bool(item.get("topic_mismatch"))
                    or (
                        float(item.get("score", 0) or 0) >= 18.0
                        and int(item.get("strong_query_hits", 0) or 0) >= 1
                    )
                )
            ]
            deduped = _extend_unique_results(
                selected_topic_matches,
                [*weak_topic_matches, *broad_topic_matches, *fallback_topic_matches],
                limit=max(max_results * 2, len(selected_topic_matches)),
            )
        else:
            deduped = []

    diversified: List[Dict[str, Any]] = []
    host_counts: Dict[str, int] = {}
    scored_results = sorted(deduped, key=lambda item: item.get("score", 0), reverse=True)
    for result in scored_results:
        host = urlparse(result["url"]).netloc.lower()
        current_count = host_counts.get(host, 0)
        source_type = result.get("source_type") or infer_source_type(result["url"])
        max_per_host = 2 if source_type in {"documentation", "pricing", "review"} else 1
        if len(deduped) <= max_results:
            max_per_host = max(max_per_host, 2)
        if result.get("score", 0) < 2 and len(diversified) >= max(1, max_results // 2):
            continue
        if current_count >= max_per_host:
            continue
        host_counts[host] = current_count + 1
        diversified.append(result)
        if len(diversified) >= max_results:
            break

    return diversified[:max_results] or scored_results[:max_results]


class DuckDuckGoSearchProvider:
    DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
    BING_SEARCH_URL = "https://www.bing.com/search"
    BRAVE_SEARCH_URL = "https://search.brave.com/search"

    def __init__(self) -> None:
        self._provider_backoff_until: Dict[str, float] = {}

    def _provider_reason_code(self, error: Exception) -> str:
        message = str(error or "").strip().lower()
        if "timeout" in message:
            return "timeout"
        if "challenge" in message or "traffic" in message:
            return "challenge"
        if "parser mismatch" in message or "unexpected payload" in message:
            return "parser_mismatch"
        if "request error" in message:
            return "request_error"
        if "http 429" in message:
            return "http_429"
        if "http 403" in message:
            return "http_403"
        if "http 451" in message:
            return "http_451"
        return "unavailable"

    def _prefers_english_market(self, query: str) -> bool:
        latin_tokens = [token.lower() for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{1,}", query)]
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{1,}", query)
        if latin_tokens and not cjk_tokens:
            return True
        if not latin_tokens:
            return False
        english_hint_hits = sum(1 for token in latin_tokens if token in ENGLISH_MARKET_HINT_TOKENS)
        if english_hint_hits >= 2 and len(latin_tokens) >= 3:
            return True
        return len(latin_tokens) >= len(cjk_tokens) + 2

    def _build_request_headers(self, query: str) -> Dict[str, str]:
        return {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9" if self._prefers_english_market(query) else "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _provider_params(self, query: str, params: Dict[str, Any]) -> Dict[str, Any]:
        next_params = dict(params)
        if self._prefers_english_market(query):
            next_params.setdefault("cc", "us")
            next_params.setdefault("mkt", "en-US")
            next_params.setdefault("setlang", "en-US")
        return next_params

    def _provider_timeout(self, provider_name: str) -> httpx.Timeout:
        if provider_name == "duckduckgo":
            return httpx.Timeout(6.0, connect=3.0)
        return httpx.Timeout(8.0, connect=4.0)

    def _provider_available(self, provider_name: str) -> bool:
        return time.monotonic() >= float(self._provider_backoff_until.get(provider_name, 0.0) or 0.0)

    def _mark_provider_available(self, provider_name: str) -> None:
        self._provider_backoff_until.pop(provider_name, None)

    def _mark_provider_unavailable(self, provider_name: str, cooldown_seconds: float) -> None:
        resume_at = time.monotonic() + max(5.0, float(cooldown_seconds or 0))
        current = float(self._provider_backoff_until.get(provider_name, 0.0) or 0.0)
        self._provider_backoff_until[provider_name] = max(current, resume_at)

    def _should_stop_search(self, results: Sequence[Dict[str, Any]], query: str, max_results: int) -> bool:
        if not results:
            return False
        if _query_site_domains(query):
            return True
        intent_tags = set(_query_intent_tags(query))
        top_result = results[0]
        top_score = float(top_result.get("score", 0) or 0)
        top_source_type = str(top_result.get("source_type") or infer_source_type(top_result.get("url") or "")).strip().lower()
        strong_results = [item for item in results[:max_results] if float(item.get("score", 0) or 0) >= 18.0]
        unique_hosts = {
            urlparse(str(item.get("url") or "")).netloc.lower()
            for item in results[:max_results]
            if str(item.get("url") or "").strip()
        }
        strong_hosts = {
            urlparse(str(item.get("url") or "")).netloc.lower()
            for item in strong_results
            if str(item.get("url") or "").strip()
        }
        if intent_tags.intersection({"official", "pricing"}) and top_source_type in {"community", "review"}:
            return False
        if max_results <= 1 and top_score >= 10.0:
            return True
        if (
            intent_tags.intersection({"official", "pricing"})
            and top_score >= 24.0
            and top_source_type in {"documentation", "pricing", "web"}
        ):
            return True
        if len(results) >= max_results and float(results[max_results - 1].get("score", 0) or 0) >= 10.0:
            return True
        required_host_coverage = 1 if max_results <= 2 else 2
        if len(strong_results) >= min(max_results, 3) and len(strong_hosts) >= required_host_coverage:
            return True
        if top_score >= 30.0 and len(results) >= min(max_results, 3) and len(unique_hosts) >= required_host_coverage:
            return True
        return False

    def _bing_html_param_variants(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        return [
            {"q": query},
            self._provider_params(query, {"q": query, "count": max(max_results, 10)}),
        ]

    def _parse_bing_html_results(self, html: str, query: str, max_results: int) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        for item in soup.select("li.b_algo"):
            anchor = item.select_one("h2 a")
            if not anchor or not anchor.get("href"):
                continue
            resolved_url = _decode_bing_link(anchor["href"])
            if not _is_supported_result_url(resolved_url):
                continue
            snippet_element = item.select_one(".b_caption p")
            results.append(
                {
                    "url": resolved_url,
                    "title": anchor.get_text(" ", strip=True),
                    "snippet": snippet_element.get_text(" ", strip=True) if snippet_element else "",
                    "query": query,
                }
            )
            if len(results) >= max_results:
                break
        return results

    async def search(
        self,
        query: str,
        max_results: int = 5,
        preferred_source_types: Optional[Sequence[str]] = None,
        preferred_domains: Optional[Sequence[str]] = None,
        topic_alias_tokens: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        providers = (
            ("bing", self._search_bing_html),
            ("bing-rss", self._search_bing_rss),
            ("brave", self._search_brave_html),
            ("duckduckgo", self._search_duckduckgo_html),
        )
        preferred_source_types = tuple(preferred_source_types or ())
        preferred_domains = tuple(dict.fromkeys([*_query_site_domains(query), *(preferred_domains or ())]))
        merged_results: List[Dict[str, Any]] = []
        last_error = None
        successful_provider_count = 0
        provider_attempts: List[Dict[str, Any]] = []
        stop_reason: Optional[str] = None

        def build_diagnostics(returned_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
            return {
                "query": query,
                "returned_result_count": len(returned_results),
                "successful_provider_count": successful_provider_count,
                "provider_attempts": provider_attempts,
                "stop_reason": stop_reason,
            }

        for provider_name, provider in providers:
            if not self._provider_available(provider_name):
                provider_attempts.append(
                    {
                        "provider": provider_name,
                        "status": "skipped_backoff",
                        "reason": "provider cooldown active",
                        "reason_code": "cooldown",
                    }
                )
                continue
            started_at = time.monotonic()
            try:
                results = await provider(query, max_results=max_results * 2)
            except SearchProviderUnavailable as error:
                last_error = error
                self._mark_provider_unavailable(provider_name, error.cooldown_seconds)
                provider_attempts.append(
                    {
                        "provider": provider_name,
                        "status": "unavailable",
                        "reason": str(error),
                        "reason_code": self._provider_reason_code(error),
                        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
                    }
                )
                continue
            except Exception as error:
                last_error = error
                if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
                    self._mark_provider_unavailable(provider_name, 120.0)
                provider_attempts.append(
                    {
                        "provider": provider_name,
                        "status": "error",
                        "reason": str(error),
                        "reason_code": self._provider_reason_code(error),
                        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
                    }
                )
                continue
            successful_provider_count += 1
            self._mark_provider_available(provider_name)
            provider_attempts.append(
                {
                    "provider": provider_name,
                    "status": "results" if results else "empty",
                    "result_count": len(results),
                    "elapsed_ms": round((time.monotonic() - started_at) * 1000),
                }
            )
            for result in results:
                result["provider"] = provider_name
                result["source_type"] = infer_source_type(result["url"])
                result["score"] = _score_result(
                    result,
                    query,
                    preferred_source_types,
                    preferred_domains,
                    topic_alias_tokens=topic_alias_tokens,
                )
                merged_results.append(result)
            if merged_results:
                provisional_results = _finalize_scored_results(query, merged_results, max_results)
                if self._should_stop_search(provisional_results, query, max_results):
                    stop_reason = "sufficient_results"
                    return SearchResults(provisional_results, diagnostics=build_diagnostics(provisional_results))

        if not merged_results and last_error and successful_provider_count == 0:
            diagnostics = build_diagnostics([])
            if isinstance(last_error, SearchProviderUnavailable):
                raise SearchProviderUnavailable(
                    str(last_error),
                    cooldown_seconds=last_error.cooldown_seconds,
                    diagnostics=diagnostics,
                ) from last_error
            raise SearchProviderUnavailable(str(last_error), cooldown_seconds=8.0, diagnostics=diagnostics) from last_error
        final_results = _finalize_scored_results(query, merged_results, max_results)
        if provider_attempts and not stop_reason:
            stop_reason = "provider_exhausted"
        return SearchResults(final_results, diagnostics=build_diagnostics(final_results))

    async def _fetch_html(self, url: str, params: Dict[str, Any], query: str, provider_name: str) -> str:
        headers = self._build_request_headers(query)
        timeout = self._provider_timeout(provider_name)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                status_code = int(error.response.status_code) if error.response is not None else 0
                if status_code in {403, 429, 451}:
                    cooldown_seconds = 30.0 if status_code == 429 else 25.0
                    raise SearchProviderUnavailable(f"{provider_name} unavailable: HTTP {status_code}", cooldown_seconds=cooldown_seconds) from error
                if status_code >= 500:
                    raise SearchProviderUnavailable(f"{provider_name} unavailable: HTTP {status_code}", cooldown_seconds=12.0) from error
                raise
            except httpx.TimeoutException as error:
                raise SearchProviderUnavailable(f"{provider_name} timeout", cooldown_seconds=8.0) from error
            except httpx.RequestError as error:
                raise SearchProviderUnavailable(f"{provider_name} request error", cooldown_seconds=8.0) from error
        return response.text

    async def _search_duckduckgo_html(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        html = await self._fetch_html(self.DUCKDUCKGO_SEARCH_URL, self._provider_params(query, {"q": query}), query, "duckduckgo")
        if "anomaly-modal" in html or "Please complete the following challenge" in html:
            raise SearchProviderUnavailable("duckduckgo challenge", cooldown_seconds=25.0)
        soup = BeautifulSoup(html, "html.parser")
        results: List[Dict[str, Any]] = []
        for anchor in soup.select("a.result__a"):
            href = anchor.get("href")
            if not href:
                continue
            result_url = _decode_duckduckgo_link(href)
            if not _is_supported_result_url(result_url):
                continue
            parent = anchor.find_parent(class_="result")
            snippet_element = parent.select_one(".result__snippet") if parent else None
            snippet = snippet_element.get_text(" ", strip=True) if snippet_element else ""
            results.append(
                {
                    "url": result_url,
                    "title": anchor.get_text(" ", strip=True),
                    "snippet": snippet,
                    "query": query,
                }
            )
            if len(results) >= max_results:
                break
        if not results and not _looks_like_empty_search_response(html, "duckduckgo"):
            raise SearchProviderUnavailable("duckduckgo html parser mismatch", cooldown_seconds=12.0)
        return results

    async def _search_bing_html(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        last_error = None
        saw_confirmed_zero_results = False
        for params in self._bing_html_param_variants(query, max_results):
            try:
                html = await self._fetch_html(self.BING_SEARCH_URL, params, query, "bing")
            except Exception as error:
                last_error = error
                continue
            results = self._parse_bing_html_results(html, query, max_results)
            if results:
                return results
            if any(token in html.lower() for token in ("bnp_container", "challenge", "unusual traffic")):
                raise SearchProviderUnavailable("bing html challenge", cooldown_seconds=25.0)
            if _looks_like_empty_search_response(html, "bing"):
                saw_confirmed_zero_results = True
                continue
            raise SearchProviderUnavailable("bing html parser mismatch", cooldown_seconds=12.0)
        if last_error:
            raise last_error
        if saw_confirmed_zero_results:
            return []
        return []

    async def _search_brave_html(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        html = await self._fetch_html(
            self.BRAVE_SEARCH_URL,
            self._provider_params(query, {"q": query, "source": "web"}),
            query,
            "brave",
        )
        soup = BeautifulSoup(html, "html.parser")
        result_nodes = soup.select('div[data-type="web"]')
        if not result_nodes and "too many requests" in html.lower():
            raise SearchProviderUnavailable("brave rate limited", cooldown_seconds=25.0)
        if not result_nodes and not _looks_like_empty_search_response(html, "brave"):
            raise SearchProviderUnavailable("brave html parser mismatch", cooldown_seconds=12.0)

        results: List[Dict[str, Any]] = []
        for item in result_nodes:
            anchor = item.select_one("a[href]")
            if not anchor or not anchor.get("href"):
                continue
            result_url = anchor.get("href", "").strip()
            if not _is_supported_result_url(result_url):
                continue
            title_element = item.select_one(".title")
            snippet_element = item.select_one(".content")
            results.append(
                {
                    "url": result_url,
                    "title": title_element.get_text(" ", strip=True) if title_element else anchor.get_text(" ", strip=True),
                    "snippet": snippet_element.get_text(" ", strip=True) if snippet_element else "",
                    "query": query,
                }
            )
            if len(results) >= max_results:
                break
        return results

    async def _search_bing_rss(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        xml_text = await self._fetch_html(
            self.BING_SEARCH_URL,
            self._provider_params(query, {"q": query, "count": max_results, "format": "rss"}),
            query,
            "bing-rss",
        )
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as error:
            if str(xml_text or "").strip():
                raise SearchProviderUnavailable("bing rss parser mismatch", cooldown_seconds=12.0) from error
            return []
        normalized_root_tag = str(root.tag or "").strip().lower()
        if normalized_root_tag not in {"rss", "feed"}:
            raise SearchProviderUnavailable("bing rss unexpected payload", cooldown_seconds=12.0)

        results: List[Dict[str, Any]] = []
        for item in root.findall("./channel/item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            if not _is_supported_result_url(link):
                continue
            results.append(
                {
                    "url": link,
                    "title": (item.findtext("title") or "").strip(),
                    "snippet": (item.findtext("description") or "").strip(),
                    "query": query,
                }
            )
            if len(results) >= max_results:
                break
        return results
