from __future__ import annotations

import io
import ipaddress
import json
import math
import re
import socket
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

try:  # pragma: no cover - exercised through integration flows
    from colorthief import ColorThief
except ImportError:  # pragma: no cover - optional at import time
    ColorThief = None

try:  # pragma: no cover - exercised through integration flows
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - optional at import time
    Image = None
    ImageDraw = None

from pm_agent_api.repositories.base import StateRepositoryProtocol
from pm_agent_api.runtime.repo_bootstrap import ensure_repo_paths

ensure_repo_paths()

from pm_agent_worker.tools.llm_runtime import create_llm_client, load_llm_settings, runtime_api_key_configured


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DesignMaterialService:
    IMAGE_VARIANTS = {"full", "thumbnail"}
    MAX_REMOTE_REDIRECTS = 5
    MIN_TREND_IMAGE_WIDTH = 240
    MIN_TREND_IMAGE_HEIGHT = 160
    GOOGLE_NEWS_DECODE_ENDPOINT = "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
    REMOTE_FETCH_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    FORBIDDEN_HOSTNAMES = {
        "localhost",
        "host.docker.internal",
        "metadata.google.internal",
        "metadata.google.internal.",
    }
    FORBIDDEN_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home", ".lan")

    def __init__(self, repository: StateRepositoryProtocol) -> None:
        self.repository = repository
        self.state_root = Path(getattr(repository, "_state_root"))
        self.materials_dir = self.state_root / "materials"
        self.objects_dir = self.materials_dir / "_objects"
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.object_store = getattr(repository, "_object_store", None)

    def _ensure_image_runtime(self) -> None:
        if Image is None:
            raise RuntimeError("缺少 Pillow 依赖，暂时无法处理图片上传。")

    def _material_path(self, material_id: str) -> Path:
        return self.materials_dir / f"{material_id}.json"

    def _material_object_dir(self, material_id: str) -> Path:
        return self.objects_dir / material_id

    def _read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _list_records(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for path in sorted(self.materials_dir.glob("*.json")):
            record = self._read_json(path)
            if not record:
                continue
            if user_id and str(record.get("user_id") or "").strip() != user_id:
                continue
            records.append(record)
        records.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return records

    def _load_record(self, material_id: str) -> Dict[str, Any]:
        record = self._read_json(self._material_path(material_id))
        if not record:
            raise KeyError(material_id)
        return record

    def _get_owned_record(self, material_id: str, user_id: str) -> Dict[str, Any]:
        record = self._load_record(material_id)
        if str(record.get("user_id") or "").strip() != user_id:
            raise KeyError(material_id)
        return record

    def _save_record(self, record: Dict[str, Any]) -> None:
        material_id = str(record.get("id") or "").strip()
        if not material_id:
            raise ValueError("素材记录缺少 id。")
        self._write_json(self._material_path(material_id), record)

    def _extension_for_mime(self, mime_type: str) -> str:
        normalized = str(mime_type or "").strip().lower()
        if normalized == "image/jpeg":
            return ".jpg"
        if normalized == "image/png":
            return ".png"
        if normalized == "image/webp":
            return ".webp"
        if normalized == "image/gif":
            return ".gif"
        return ".bin"

    def _api_image_url(self, material_id: str, variant: str) -> str:
        return f"/api/design/materials/{material_id}/image?variant={variant}"

    def _build_response(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(record.get("id") or ""),
            "user_id": str(record.get("user_id") or ""),
            "filename": str(record.get("filename") or ""),
            "original_url": record.get("original_url"),
            "thumbnail_url": self._api_image_url(str(record.get("id") or ""), "thumbnail"),
            "full_url": self._api_image_url(str(record.get("id") or ""), "full"),
            "width": int(record.get("width") or 0),
            "height": int(record.get("height") or 0),
            "file_size": int(record.get("file_size") or 0),
            "mime_type": str(record.get("mime_type") or "application/octet-stream"),
            "tags": list(record.get("tags") or []),
            "colors": list(record.get("colors") or []),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "source": str(record.get("source") or "upload"),
            "trend_id": record.get("trend_id"),
        }

    def _normalize_tag(self, name: str, category: str = "custom", tag_type: str = "manual", confidence: Optional[float] = None) -> Optional[Dict[str, Any]]:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            return None
        normalized_category = str(category or "custom").strip().lower()
        if normalized_category not in {"color", "style", "mood", "composition", "element", "custom"}:
            normalized_category = "custom"
        normalized_type = "auto" if str(tag_type or "").strip().lower() == "auto" else "manual"
        payload: Dict[str, Any] = {
            "name": cleaned_name,
            "category": normalized_category,
            "type": normalized_type,
        }
        if confidence is not None:
            payload["confidence"] = round(max(0.0, min(1.0, float(confidence))), 2)
        return payload

    def _dedupe_tags(self, tags: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in tags:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("category") or "").strip(), str(item.get("name") or "").strip().lower())
            if not key[1] or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _validate_image_bytes(self, data: bytes) -> Tuple[int, int]:
        self._ensure_image_runtime()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return int(image.width), int(image.height)

    def _extract_palette(self, data: bytes) -> List[str]:
        if ColorThief is not None:
            try:
                color_thief = ColorThief(io.BytesIO(data))
                return [self._rgb_to_hex(color) for color in color_thief.get_palette(color_count=5, quality=5)[:5]]
            except Exception:
                pass
        return self._fallback_palette(data)

    def _fallback_palette(self, data: bytes) -> List[str]:
        self._ensure_image_runtime()
        with Image.open(io.BytesIO(data)) as image:
            sample = image.convert("RGB")
            sample.thumbnail((80, 80))
            colors = sample.getcolors(maxcolors=6400) or []
        colors.sort(key=lambda item: item[0], reverse=True)
        palette: List[str] = []
        seen = set()
        for _, rgb in colors:
            hex_color = self._rgb_to_hex(rgb)
            if hex_color in seen:
                continue
            seen.add(hex_color)
            palette.append(hex_color)
            if len(palette) >= 5:
                break
        while len(palette) < 5:
            palette.append(palette[-1] if palette else "#CBD5E1")
        return palette[:5]

    def _rgb_to_hex(self, value: Sequence[int]) -> str:
        red, green, blue = [max(0, min(255, int(channel))) for channel in value[:3]]
        return f"#{red:02X}{green:02X}{blue:02X}"

    def _create_thumbnail(self, data: bytes) -> Tuple[bytes, str]:
        self._ensure_image_runtime()
        with Image.open(io.BytesIO(data)) as image:
            thumbnail = image.convert("RGBA")
            thumbnail.thumbnail((400, 400))
            buffer = io.BytesIO()
            thumbnail.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"

    def _parse_remote_image_url(self, url: str):
        cleaned = str(url or "").strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("仅支持导入 http 或 https 的公网图片地址。")
        if not parsed.hostname:
            raise ValueError("图片地址缺少有效域名。")
        if parsed.username or parsed.password:
            raise ValueError("图片地址不允许携带认证信息。")
        return parsed

    def _is_public_ip_address(self, value: str) -> Optional[bool]:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return None
        return address.is_global

    def _ensure_public_hostname(self, hostname: str) -> None:
        normalized = str(hostname or "").strip().lower().rstrip(".")
        if not normalized:
            raise ValueError("图片地址缺少有效域名。")
        if normalized in self.FORBIDDEN_HOSTNAMES or any(normalized.endswith(suffix) for suffix in self.FORBIDDEN_HOST_SUFFIXES):
            raise ValueError("仅允许导入公网图片地址。")

        ip_public = self._is_public_ip_address(normalized)
        if ip_public is not None:
            if not ip_public:
                raise ValueError("仅允许导入公网图片地址。")
            return

        try:
            resolved = socket.getaddrinfo(normalized, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror as error:
            raise ValueError(f"图片地址域名 `{normalized}` 无法解析。") from error

        resolved_hosts = {item[4][0] for item in resolved if item and item[4]}
        if not resolved_hosts:
            raise ValueError(f"图片地址域名 `{normalized}` 无法解析。")

        for resolved_host in resolved_hosts:
            if not self._is_public_ip_address(str(resolved_host)):
                raise ValueError("仅允许导入公网图片地址。")

    def _validate_remote_image_url(self, url: str) -> str:
        parsed = self._parse_remote_image_url(url)
        self._ensure_public_hostname(str(parsed.hostname or ""))
        return parsed.geturl()

    def _validate_trend_fetch_url(self, url: str) -> str:
        parsed = self._parse_remote_image_url(url)
        hostname = str(parsed.hostname or "").strip().lower().rstrip(".")
        if not hostname:
            raise ValueError("图片地址缺少有效域名。")
        self._ensure_public_hostname(hostname)
        return parsed.geturl()

    def _fetch_remote_image_response(self, url: str) -> httpx.Response:
        current_url = self._validate_remote_image_url(url)
        with httpx.Client(timeout=20.0, follow_redirects=False, headers=self.REMOTE_FETCH_HEADERS) as client:
            for _ in range(self.MAX_REMOTE_REDIRECTS + 1):
                response = client.get(current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        raise ValueError("远程图片地址返回了无效重定向。")
                    redirect_url = urljoin(str(response.url), location)
                    current_url = self._validate_remote_image_url(redirect_url)
                    continue
                response.raise_for_status()
                return response
        raise ValueError("远程图片地址重定向次数过多。")

    def _fetch_remote_html(self, url: str) -> Tuple[str, str]:
        current_url = self._validate_trend_fetch_url(url)
        headers = {
            "User-Agent": self.REMOTE_FETCH_HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with httpx.Client(timeout=20.0, follow_redirects=False, headers=headers) as client:
            for _ in range(self.MAX_REMOTE_REDIRECTS + 1):
                response = client.get(current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        raise ValueError("趋势来源页返回了无效重定向。")
                    current_url = self._validate_trend_fetch_url(urljoin(str(response.url), location))
                    continue
                response.raise_for_status()
                if "text/html" not in str(response.headers.get("content-type") or "").lower():
                    raise ValueError("趋势来源页不是可解析的 HTML。")
                return response.text, str(response.url)
        raise ValueError("趋势来源页重定向次数过多。")

    def _fetch_trend_image_response(self, url: str) -> httpx.Response:
        current_url = self._validate_trend_fetch_url(url)
        with httpx.Client(timeout=20.0, follow_redirects=False, headers=self.REMOTE_FETCH_HEADERS) as client:
            for _ in range(self.MAX_REMOTE_REDIRECTS + 1):
                response = client.get(current_url)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        raise ValueError("远程图片地址返回了无效重定向。")
                    current_url = self._validate_trend_fetch_url(urljoin(str(response.url), location))
                    continue
                response.raise_for_status()
                return response
        raise ValueError("远程图片地址重定向次数过多。")

    def _looks_like_google_news_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        host = parsed.netloc.lower().removeprefix("www.")
        return host == "news.google.com" and "/articles/" in parsed.path

    def _decode_google_news_source_url(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        article_id = parsed.path.rstrip("/").split("/")[-1]
        if not article_id:
            raise ValueError("Google News 链接缺少文章标识。")

        article_page = f"https://news.google.com/rss/articles/{article_id}"
        html, _ = self._fetch_remote_html(article_page)
        soup = BeautifulSoup(html, "html.parser")
        decoder_root = soup.select_one("c-wiz > div[data-n-a-sg][data-n-a-ts]")
        if decoder_root is None:
            raise ValueError("Google News 解码参数缺失。")
        signature = str(decoder_root.get("data-n-a-sg") or "").strip()
        timestamp = str(decoder_root.get("data-n-a-ts") or "").strip()
        if not signature or not timestamp:
            raise ValueError("Google News 解码参数不完整。")

        payload = (
            'f.req='
            + json.dumps(
                [[
                    [
                        "Fbv4je",
                        (
                            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{article_id}",{timestamp},"{signature}"]'
                        ),
                        None,
                        "generic",
                    ]
                ]],
                separators=(",", ":"),
            )
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": self.REMOTE_FETCH_HEADERS["User-Agent"],
            "Referer": "https://news.google.com/",
        }
        response = httpx.post(self.GOOGLE_NEWS_DECODE_ENDPOINT, data=payload, headers=headers, timeout=20.0)
        response.raise_for_status()
        decoded_url = self._extract_google_news_decode_url(response.text)
        return self._validate_trend_fetch_url(decoded_url)

    def _extract_google_news_decode_url(self, response_text: str) -> str:
        for line in response_text.splitlines():
            line = line.strip()
            if not line or not line.startswith("["):
                continue
            try:
                parsed_line = json.loads(line)
            except json.JSONDecodeError:
                continue
            stack = [parsed_line]
            while stack:
                current = stack.pop()
                if not isinstance(current, list):
                    continue
                if len(current) >= 3 and isinstance(current[2], str):
                    try:
                        candidate_json = json.loads(current[2])
                    except json.JSONDecodeError:
                        candidate_json = None
                    if (
                        isinstance(candidate_json, list)
                        and len(candidate_json) >= 2
                        and str(candidate_json[0]).strip() == "garturlres"
                        and isinstance(candidate_json[1], str)
                    ):
                        decoded_url = candidate_json[1].strip()
                        if decoded_url:
                            return decoded_url
                for item in current:
                    if isinstance(item, list):
                        stack.append(item)
        raise ValueError("Google News 原始文章来源解码失败。")

    def _resolve_trend_source_page_url(self, source_url: str) -> str:
        cleaned = str(source_url or "").strip()
        if not cleaned:
            raise ValueError("趋势来源链接为空。")
        if self._looks_like_google_news_url(cleaned):
            return self._decode_google_news_source_url(cleaned)
        return self._validate_trend_fetch_url(cleaned)

    def _extract_image_candidates_from_html(self, html_text: str, page_url: str) -> List[str]:
        soup = BeautifulSoup(html_text, "html.parser")
        candidates: List[str] = []
        seen = set()

        def push(url: str) -> None:
            candidate = str(url or "").strip()
            if not candidate:
                return
            try:
                normalized = self._validate_trend_fetch_url(urljoin(page_url, candidate))
            except ValueError:
                return
            if normalized in seen:
                return
            seen.add(normalized)
            candidates.append(normalized)

        selectors = [
            ("meta", "property", "og:image"),
            ("meta", "property", "og:image:url"),
            ("meta", "name", "twitter:image"),
            ("meta", "name", "twitter:image:src"),
            ("link", "rel", "image_src"),
        ]
        for tag_name, attr_name, attr_value in selectors:
            for tag in soup.find_all(tag_name):
                attr = tag.get(attr_name)
                if attr_name == "rel":
                    rel_values = [str(item).strip().lower() for item in (attr or [])]
                    if attr_value not in rel_values:
                        continue
                elif str(attr or "").strip().lower() != attr_value:
                    continue
                push(str(tag.get("content") or tag.get("href") or ""))

        for image in soup.find_all("img", src=True):
            classes = " ".join(str(item).strip().lower() for item in image.get("class", []))
            alt_text = str(image.get("alt") or "").strip().lower()
            source = str(image.get("src") or "")
            if any(token in classes or token in alt_text for token in ("avatar", "icon", "logo", "author", "profile")):
                continue
            if any(token in source.lower() for token in ("logo", "icon", "avatar", "sprite", "placeholder")):
                continue
            push(source)
            if len(candidates) >= 8:
                break
        return candidates

    def _fetch_best_trend_source_image(self, trend: Dict[str, Any]) -> Optional[Dict[str, str | bytes]]:
        source_urls = [str(item).strip() for item in (trend.get("source_urls") or []) if str(item).strip()]
        if not source_urls:
            return None

        for source_url in source_urls[:3]:
            try:
                page_url = self._resolve_trend_source_page_url(source_url)
                html_text, final_page_url = self._fetch_remote_html(page_url)
                image_candidates = self._extract_image_candidates_from_html(html_text, final_page_url)
            except Exception:
                continue

            for image_url in image_candidates:
                try:
                    response = self._fetch_trend_image_response(image_url)
                    mime_type = str(response.headers.get("content-type") or "").split(";")[0].strip().lower() or "image/png"
                    width, height = self._validate_image_bytes(response.content)
                    if width < self.MIN_TREND_IMAGE_WIDTH or height < self.MIN_TREND_IMAGE_HEIGHT:
                        continue
                    return {
                        "data": response.content,
                        "mime_type": mime_type,
                        "image_url": image_url,
                        "page_url": final_page_url,
                    }
                except Exception:
                    continue
        return None

    def _store_binary(self, material_id: str, variant: str, data: bytes, mime_type: str) -> Dict[str, Any]:
        if self.object_store and hasattr(self.object_store, "put_binary"):
            extension = self._extension_for_mime(mime_type)
            key = f"design/materials/{material_id}/{variant}{extension}"
            pointer = self.object_store.put_binary(key, data, content_type=mime_type)
            pointer["variant"] = variant
            return pointer

        extension = self._extension_for_mime(mime_type)
        object_dir = self._material_object_dir(material_id)
        object_dir.mkdir(parents=True, exist_ok=True)
        path = object_dir / f"{variant}{extension}"
        path.write_bytes(data)
        return {
            "storage": "local",
            "path": str(path),
            "content_type": mime_type,
            "size_bytes": len(data),
            "variant": variant,
            "stored_at": iso_now(),
        }

    def _delete_pointer(self, pointer: Optional[Dict[str, Any]]) -> None:
        if not isinstance(pointer, dict):
            return
        if str(pointer.get("storage") or "").strip() == "local":
            path = Path(str(pointer.get("path") or ""))
            if path.exists():
                path.unlink(missing_ok=True)
            return
        if self.object_store and hasattr(self.object_store, "delete"):
            self.object_store.delete(pointer)

    def resolve_image_variant(self, material_id: str, user_id: str, variant: str) -> Dict[str, Any]:
        if variant not in self.IMAGE_VARIANTS:
            raise ValueError("不支持的图片尺寸类型。")
        record = self._get_owned_record(material_id, user_id)
        pointer_key = "thumbnail_storage" if variant == "thumbnail" else "full_storage"
        pointer = record.get(pointer_key)
        if not isinstance(pointer, dict):
            raise KeyError(material_id)
        if str(pointer.get("storage") or "").strip() == "local":
            return {
                "kind": "file",
                "path": str(pointer.get("path") or ""),
                "media_type": str(pointer.get("content_type") or record.get("mime_type") or "application/octet-stream"),
            }
        if self.object_store and hasattr(self.object_store, "generate_presigned_url"):
            return {
                "kind": "redirect",
                "url": self.object_store.generate_presigned_url(str(pointer.get("key") or ""), expires_in=3600),
            }
        raise KeyError(material_id)

    def _llm_auto_tags(self, material: Dict[str, Any]) -> List[Dict[str, Any]]:
        settings = load_llm_settings()
        if not runtime_api_key_configured(settings):
            return []
        try:
            client = create_llm_client()
            payload = client.complete_json(
                [
                    {
                        "role": "system",
                        "content": "你是一个设计素材标签助手。请输出严格 JSON，帮助素材库生成风格标签。",
                    },
                    {
                        "role": "user",
                        "content": (
                            "请根据以下素材元数据生成标签 JSON，顶层结构必须是："
                            "{\"color\":[],\"style\":[],\"mood\":[],\"composition\":[],\"element\":[]}。\n"
                            "要求：每类最多 3 个中文标签，不要解释。\n"
                            f"文件名: {material.get('filename')}\n"
                            f"尺寸: {material.get('width')}x{material.get('height')}\n"
                            f"主色: {', '.join(material.get('colors') or [])}\n"
                            f"来源: {material.get('source')}\n"
                            f"已有关键词: {', '.join(str(tag.get('name') or '') for tag in (material.get('tags') or []))}"
                        ),
                    },
                ],
                temperature=0.2,
                max_tokens=800,
            )
        except Exception:
            return []

        if not isinstance(payload, dict):
            return []
        tags: List[Dict[str, Any]] = []
        for category in ("color", "style", "mood", "composition", "element"):
            values = payload.get(category)
            if not isinstance(values, list):
                continue
            for value in values[:3]:
                tag = self._normalize_tag(str(value or ""), category=category, tag_type="auto", confidence=0.7)
                if tag:
                    tags.append(tag)
        return tags

    def _fallback_auto_tags(self, material: Dict[str, Any]) -> List[Dict[str, Any]]:
        colors = [str(item).strip() for item in (material.get("colors") or []) if str(item).strip()]
        width = max(1, int(material.get("width") or 1))
        height = max(1, int(material.get("height") or 1))
        ratio = width / height
        filename = str(material.get("filename") or "").lower()

        tags: List[Dict[str, Any]] = []
        if colors:
            hue, saturation, lightness = self._hex_to_hsl(colors[0])
            if saturation < 0.1:
                tags.append(self._normalize_tag("中性色", category="color", tag_type="auto", confidence=0.72))
            elif hue < 0.12 or hue > 0.92:
                tags.append(self._normalize_tag("暖色调", category="color", tag_type="auto", confidence=0.74))
            elif 0.45 <= hue <= 0.75:
                tags.append(self._normalize_tag("冷色调", category="color", tag_type="auto", confidence=0.74))
            else:
                tags.append(self._normalize_tag("多色混合", category="color", tag_type="auto", confidence=0.65))

            tags.append(
                self._normalize_tag(
                    "高饱和" if saturation >= 0.55 else "低饱和",
                    category="color",
                    tag_type="auto",
                    confidence=0.66,
                )
            )
            tags.append(
                self._normalize_tag(
                    "深色基调" if lightness < 0.42 else "浅色基调",
                    category="color",
                    tag_type="auto",
                    confidence=0.64,
                )
            )

            if len(colors) >= 2:
                contrast = abs(self._relative_luminance(colors[0]) - self._relative_luminance(colors[1]))
                if contrast > 0.45:
                    tags.append(self._normalize_tag("高对比", category="style", tag_type="auto", confidence=0.62))
                else:
                    tags.append(self._normalize_tag("柔和层次", category="style", tag_type="auto", confidence=0.58))

        if ratio > 1.2:
            tags.append(self._normalize_tag("横版", category="composition", tag_type="auto", confidence=0.8))
        elif ratio < 0.85:
            tags.append(self._normalize_tag("竖版", category="composition", tag_type="auto", confidence=0.8))
        else:
            tags.append(self._normalize_tag("方形", category="composition", tag_type="auto", confidence=0.8))

        if "dashboard" in filename or "ui" in filename or "app" in filename or "web" in filename:
            tags.append(self._normalize_tag("界面", category="element", tag_type="auto", confidence=0.73))
            tags.append(self._normalize_tag("极简", category="style", tag_type="auto", confidence=0.58))
        if "poster" in filename or "banner" in filename:
            tags.append(self._normalize_tag("海报", category="element", tag_type="auto", confidence=0.73))
        if "icon" in filename:
            tags.append(self._normalize_tag("图标", category="element", tag_type="auto", confidence=0.72))
        if "illustration" in filename or "illust" in filename:
            tags.append(self._normalize_tag("插画", category="element", tag_type="auto", confidence=0.72))
        if "photo" in filename or "camera" in filename:
            tags.append(self._normalize_tag("摄影", category="element", tag_type="auto", confidence=0.72))

        if any(term in filename for term in ("gradient", "neon", "glow", "future", "ai")):
            tags.append(self._normalize_tag("科技感", category="style", tag_type="auto", confidence=0.64))
        if any(term in filename for term in ("paper", "grain", "texture", "fabric", "material")):
            tags.append(self._normalize_tag("材质感", category="style", tag_type="auto", confidence=0.64))

        brightness = sum(self._relative_luminance(color) for color in colors[:3]) / max(1, min(len(colors), 3)) if colors else 0.5
        if brightness > 0.7:
            tags.append(self._normalize_tag("清爽", category="mood", tag_type="auto", confidence=0.61))
        elif brightness < 0.28:
            tags.append(self._normalize_tag("沉稳", category="mood", tag_type="auto", confidence=0.61))
        else:
            tags.append(self._normalize_tag("平衡", category="mood", tag_type="auto", confidence=0.56))

        return [tag for tag in self._dedupe_tags([item for item in tags if item]) if tag]

    def auto_tag_material(self, material: Dict[str, Any]) -> List[Dict[str, Any]]:
        fallback_tags = self._fallback_auto_tags(material)
        llm_tags = self._llm_auto_tags(material)
        return self._dedupe_tags([*fallback_tags, *llm_tags])

    def _prepare_manual_tags(self, tags: Sequence[Any], default_category: str = "custom") -> List[Dict[str, Any]]:
        prepared: List[Dict[str, Any]] = []
        for item in tags:
            if isinstance(item, dict):
                tag = self._normalize_tag(
                    str(item.get("name") or ""),
                    category=str(item.get("category") or default_category),
                    tag_type=str(item.get("type") or "manual"),
                    confidence=item.get("confidence"),
                )
            else:
                tag = self._normalize_tag(str(item or ""), category=default_category, tag_type="manual")
            if tag:
                prepared.append(tag)
        return self._dedupe_tags(prepared)

    def upload_material(
        self,
        user_id: str,
        *,
        filename: str,
        mime_type: str,
        data: bytes,
        source: str = "upload",
        original_url: Optional[str] = None,
        trend_id: Optional[str] = None,
        manual_tags: Optional[Sequence[Any]] = None,
    ) -> Dict[str, Any]:
        if not str(mime_type or "").strip().lower().startswith("image/"):
            raise ValueError("仅支持上传图片素材。")
        try:
            width, height = self._validate_image_bytes(data)
            colors = self._extract_palette(data)
            thumbnail_bytes, thumbnail_mime = self._create_thumbnail(data)
        except OSError as error:
            raise ValueError("上传的文件不是有效图片，或图片内容已损坏。") from error
        material_id = str(uuid.uuid4())
        created_at = iso_now()
        record: Dict[str, Any] = {
            "id": material_id,
            "user_id": user_id,
            "filename": filename,
            "original_url": original_url,
            "width": width,
            "height": height,
            "file_size": len(data),
            "mime_type": mime_type,
            "colors": colors,
            "created_at": created_at,
            "updated_at": created_at,
            "source": source if source in {"upload", "url", "trend"} else "upload",
            "trend_id": trend_id,
            "full_storage": self._store_binary(material_id, "full", data, mime_type),
            "thumbnail_storage": self._store_binary(material_id, "thumbnail", thumbnail_bytes, thumbnail_mime),
            "tags": [],
        }
        auto_tags = self.auto_tag_material(record)
        record["tags"] = self._dedupe_tags([*auto_tags, *self._prepare_manual_tags(manual_tags or [])])
        self._save_record(record)
        return self._build_response(record)

    def upload_material_from_url(self, user_id: str, url: str, tags: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
        response = self._fetch_remote_image_response(url)
        content_type = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            raise ValueError("远程地址未返回图片内容。")
        if not content_type:
            content_type = "image/png"
        filename = url.rstrip("/").split("/")[-1] or f"remote-{uuid.uuid4().hex[:8]}.png"
        return self.upload_material(
            user_id,
            filename=filename,
            mime_type=content_type,
            data=response.content,
            source="url",
            original_url=url,
            manual_tags=tags,
        )

    def _render_trend_preview(self, trend: Dict[str, Any]) -> bytes:
        self._ensure_image_runtime()
        palette = [str(item).strip() for item in (trend.get("color_palette") or []) if str(item).strip()]
        if not palette:
            palette = ["#E2E8F0", "#CBD5E1", "#94A3B8", "#475569", "#0F172A"]
        canvas = Image.new("RGB", (1200, 900), palette[0])
        draw = ImageDraw.Draw(canvas)
        band_width = max(1, 1200 // max(1, len(palette)))
        for index, color in enumerate(palette):
            draw.rectangle((index * band_width, 0, (index + 1) * band_width, 900), fill=color)
        draw.rectangle((80, 90, 1120, 810), fill=(255, 255, 255))
        draw.rounded_rectangle((110, 120, 1090, 780), radius=42, outline=palette[-1], width=4, fill=palette[0])
        for index, color in enumerate(palette[:4]):
            offset_x = 160 + index * 220
            draw.ellipse((offset_x, 200, offset_x + 150, offset_x - 50 + 350), fill=color, outline=palette[-1], width=3)
        for index, color in enumerate(palette):
            draw.rounded_rectangle((140 + index * 180, 650, 280 + index * 180, 710), radius=20, fill=color)
        draw.rounded_rectangle((160, 520, 1040, 560), radius=16, fill=palette[-1])
        draw.rounded_rectangle((160, 585, 860, 615), radius=15, fill=palette[1] if len(palette) > 1 else palette[-1])
        buffer = io.BytesIO()
        canvas.save(buffer, format="PNG")
        return buffer.getvalue()

    def save_trend_material(self, user_id: str, trend: Dict[str, Any]) -> Dict[str, Any]:
        trend_name = str(trend.get("name") or "趋势灵感").strip() or "趋势灵感"
        fetched_source_image = self._fetch_best_trend_source_image(trend)
        image_bytes = fetched_source_image["data"] if fetched_source_image else self._render_trend_preview(trend)
        mime_type = str(fetched_source_image["mime_type"]) if fetched_source_image else "image/png"
        original_url = (
            str(fetched_source_image.get("page_url") or fetched_source_image.get("image_url") or "")
            if fetched_source_image
            else None
        )
        manual_tags: List[Dict[str, Any]] = []
        category = str(trend.get("category") or "style").strip()
        manual_tags.append(self._normalize_tag(category, category="style", tag_type="manual") or {})
        for keyword in (trend.get("keywords") or [])[:5]:
            tag = self._normalize_tag(str(keyword or ""), category="style", tag_type="manual")
            if tag:
                manual_tags.append(tag)
        for mood in (trend.get("mood_keywords") or [])[:3]:
            tag = self._normalize_tag(str(mood or ""), category="mood", tag_type="manual")
            if tag:
                manual_tags.append(tag)
        return self.upload_material(
            user_id,
            filename=f"{trend_name}{self._extension_for_mime(mime_type)}",
            mime_type=mime_type,
            data=image_bytes,
            source="trend",
            original_url=original_url,
            trend_id=str(trend.get("id") or "") or None,
            manual_tags=manual_tags,
        )

    def list_materials(
        self,
        user_id: str,
        *,
        tag: Optional[str] = None,
        category: Optional[str] = None,
        color: Optional[str] = None,
        page: int = 1,
        page_size: int = 30,
    ) -> Dict[str, Any]:
        normalized_tag = str(tag or "").strip().lower()
        normalized_category = str(category or "").strip().lower()
        normalized_color = str(color or "").strip().upper()
        records = self._list_records(user_id)
        filtered: List[Dict[str, Any]] = []
        for record in records:
            tags = [item for item in (record.get("tags") or []) if isinstance(item, dict)]
            tag_names = {str(item.get("name") or "").strip().lower() for item in tags}
            tag_categories = {str(item.get("category") or "").strip().lower() for item in tags}
            colors = {str(item).strip().upper() for item in (record.get("colors") or []) if str(item).strip()}
            if normalized_tag and normalized_tag not in tag_names:
                continue
            if normalized_category and normalized_category not in tag_categories:
                continue
            if normalized_color and normalized_color not in colors:
                continue
            filtered.append(record)
        safe_page = max(1, int(page or 1))
        safe_page_size = max(1, min(int(page_size or 30), 120))
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        items = [self._build_response(item) for item in filtered[start:end]]
        return {"items": items, "total": len(filtered), "page": safe_page, "page_size": safe_page_size}

    def get_material(self, material_id: str, user_id: str) -> Dict[str, Any]:
        return self._build_response(self._get_owned_record(material_id, user_id))

    def delete_material(self, material_id: str, user_id: str) -> Dict[str, Any]:
        record = self._get_owned_record(material_id, user_id)
        self._delete_pointer(record.get("full_storage"))
        self._delete_pointer(record.get("thumbnail_storage"))
        self._material_path(material_id).unlink(missing_ok=True)
        object_dir = self._material_object_dir(material_id)
        if object_dir.exists():
            for path in object_dir.glob("*"):
                path.unlink(missing_ok=True)
            object_dir.rmdir()
        return {"ok": True}

    def update_material_tags(self, material_id: str, user_id: str, add: Sequence[Any], remove: Sequence[str]) -> Dict[str, Any]:
        record = self._get_owned_record(material_id, user_id)
        remove_names = {str(item or "").strip().lower() for item in remove if str(item or "").strip()}
        existing_tags = [item for item in (record.get("tags") or []) if isinstance(item, dict)]
        remaining_tags = [item for item in existing_tags if str(item.get("name") or "").strip().lower() not in remove_names]
        updated_tags = self._dedupe_tags([*remaining_tags, *self._prepare_manual_tags(add)])
        record["tags"] = updated_tags
        record["updated_at"] = iso_now()
        self._save_record(record)
        return self._build_response(record)

    def list_all_tags(self, user_id: str) -> List[str]:
        seen = set()
        tags: List[str] = []
        for record in self._list_records(user_id):
            for item in (record.get("tags") or []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                key = name.lower()
                if not name or key in seen:
                    continue
                seen.add(key)
                tags.append(name)
        return sorted(tags, key=lambda item: item.lower())

    def _material_group_key(self, material: Dict[str, Any]) -> str:
        for priority in ("style", "mood", "composition", "element", "color", "custom"):
            for tag in (material.get("tags") or []):
                if not isinstance(tag, dict):
                    continue
                if str(tag.get("category") or "").strip().lower() == priority:
                    return str(tag.get("name") or "").strip() or priority
        if material.get("colors"):
            return str((material.get("colors") or ["默认"])[0])
        return "默认"

    def _tag_index(self, material: Dict[str, Any]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for tag in (material.get("tags") or []):
            if not isinstance(tag, dict):
                continue
            name = str(tag.get("name") or "").strip().lower()
            category = str(tag.get("category") or "").strip().lower()
            if name:
                mapping[name] = category or "custom"
        return mapping

    def _relation_score(self, left: Dict[str, Any], right: Dict[str, Any]) -> Tuple[float, List[str], Optional[str]]:
        left_tags = self._tag_index(left)
        right_tags = self._tag_index(right)
        shared = sorted(set(left_tags).intersection(right_tags))
        union = set(left_tags).union(right_tags)
        tag_score = len(shared) / len(union) if union else 0.0
        color_score = self._palette_similarity(left.get("colors") or [], right.get("colors") or [])
        weight = round((tag_score * 0.7) + (color_score * 0.3), 3)
        shared_category = None
        if shared:
            category_counts: Dict[str, int] = {}
            for item in shared:
                category_counts[left_tags.get(item, "custom")] = category_counts.get(left_tags.get(item, "custom"), 0) + 1
            shared_category = max(category_counts.items(), key=lambda item: item[1])[0]
        return weight, [name for name in shared][:8], shared_category

    def compute_material_relations(self, user_id: str) -> List[Dict[str, Any]]:
        materials = [self._build_response(record) for record in self._list_records(user_id)]
        links: List[Dict[str, Any]] = []
        for left_index, left in enumerate(materials):
            for right in materials[left_index + 1 :]:
                weight, shared_tags, shared_category = self._relation_score(left, right)
                if weight < 0.15:
                    continue
                links.append(
                    {
                        "source": left["id"],
                        "target": right["id"],
                        "weight": weight,
                        "shared_tags": shared_tags,
                        "shared_category": shared_category,
                    }
                )
        adjacency: Dict[str, List[Dict[str, Any]]] = {}
        for link in links:
            adjacency.setdefault(link["source"], []).append(link)
            adjacency.setdefault(link["target"], []).append(link)
        allowed_pairs = set()
        for node_id, node_links in adjacency.items():
            ranked = sorted(node_links, key=lambda item: float(item.get("weight") or 0), reverse=True)[:8]
            for link in ranked:
                allowed_pairs.add(tuple(sorted((str(link["source"]), str(link["target"])))))
        filtered: List[Dict[str, Any]] = []
        seen_pairs = set()
        for link in sorted(links, key=lambda item: float(item.get("weight") or 0), reverse=True):
            pair_key = tuple(sorted((str(link["source"]), str(link["target"]))))
            if pair_key not in allowed_pairs or pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            filtered.append(link)
        return filtered

    def get_material_network(self, user_id: str) -> Dict[str, Any]:
        records = self._list_records(user_id)
        group_lookup: Dict[str, int] = {}
        nodes: List[Dict[str, Any]] = []
        for record in records:
            response = self._build_response(record)
            group_key = self._material_group_key(record)
            if group_key not in group_lookup:
                group_lookup[group_key] = len(group_lookup) + 1
            nodes.append(
                {
                    "id": response["id"],
                    "label": Path(response["filename"]).stem or "素材",
                    "thumbnail": response["thumbnail_url"],
                    "tags": [str(tag.get("name") or "").strip() for tag in (response.get("tags") or []) if isinstance(tag, dict)],
                    "colors": list(response.get("colors") or []),
                    "group": group_lookup[group_key],
                    "source": response.get("source") or "upload",
                }
            )
        return {"nodes": nodes, "links": self.compute_material_relations(user_id)}

    def _hex_to_rgb(self, color: str) -> Tuple[int, int, int]:
        normalized = str(color or "").strip().lstrip("#")
        if len(normalized) != 6:
            return (203, 213, 225)
        try:
            return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return (203, 213, 225)

    def _srgb_channel_to_linear(self, channel: float) -> float:
        value = channel / 255.0
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    def _rgb_to_lab(self, color: str) -> Tuple[float, float, float]:
        red, green, blue = self._hex_to_rgb(color)
        red_l = self._srgb_channel_to_linear(red)
        green_l = self._srgb_channel_to_linear(green)
        blue_l = self._srgb_channel_to_linear(blue)
        x = (red_l * 0.4124 + green_l * 0.3576 + blue_l * 0.1805) / 0.95047
        y = (red_l * 0.2126 + green_l * 0.7152 + blue_l * 0.0722) / 1.0
        z = (red_l * 0.0193 + green_l * 0.1192 + blue_l * 0.9505) / 1.08883

        def f(value: float) -> float:
            return value ** (1 / 3) if value > 0.008856 else (7.787 * value) + (16 / 116)

        fx = f(x)
        fy = f(y)
        fz = f(z)
        return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))

    def _delta_e2000(self, left: Tuple[float, float, float], right: Tuple[float, float, float]) -> float:
        l1, a1, b1 = left
        l2, a2, b2 = right
        avg_lp = (l1 + l2) / 2.0
        c1 = math.sqrt(a1 * a1 + b1 * b1)
        c2 = math.sqrt(a2 * a2 + b2 * b2)
        avg_c = (c1 + c2) / 2.0
        g = 0.5 * (1 - math.sqrt((avg_c**7) / (avg_c**7 + 25**7))) if avg_c else 0.0
        a1p = (1 + g) * a1
        a2p = (1 + g) * a2
        c1p = math.sqrt(a1p * a1p + b1 * b1)
        c2p = math.sqrt(a2p * a2p + b2 * b2)
        avg_cp = (c1p + c2p) / 2.0
        h1p = (math.degrees(math.atan2(b1, a1p)) + 360) % 360 if c1p else 0.0
        h2p = (math.degrees(math.atan2(b2, a2p)) + 360) % 360 if c2p else 0.0
        delta_lp = l2 - l1
        delta_cp = c2p - c1p
        if not (c1p and c2p):
            delta_hp = 0.0
        elif abs(h2p - h1p) <= 180:
            delta_hp = h2p - h1p
        elif h2p <= h1p:
            delta_hp = h2p - h1p + 360
        else:
            delta_hp = h2p - h1p - 360
        delta_hp_term = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_hp / 2.0))
        if not (c1p and c2p):
            avg_hp = h1p + h2p
        elif abs(h1p - h2p) <= 180:
            avg_hp = (h1p + h2p) / 2.0
        elif (h1p + h2p) < 360:
            avg_hp = (h1p + h2p + 360) / 2.0
        else:
            avg_hp = (h1p + h2p - 360) / 2.0
        t = (
            1
            - 0.17 * math.cos(math.radians(avg_hp - 30))
            + 0.24 * math.cos(math.radians(2 * avg_hp))
            + 0.32 * math.cos(math.radians(3 * avg_hp + 6))
            - 0.20 * math.cos(math.radians(4 * avg_hp - 63))
        )
        delta_ro = 30 * math.exp(-(((avg_hp - 275) / 25) ** 2))
        rc = 2 * math.sqrt((avg_cp**7) / (avg_cp**7 + 25**7)) if avg_cp else 0.0
        sl = 1 + (0.015 * ((avg_lp - 50) ** 2)) / math.sqrt(20 + ((avg_lp - 50) ** 2))
        sc = 1 + 0.045 * avg_cp
        sh = 1 + 0.015 * avg_cp * t
        rt = -math.sin(math.radians(2 * delta_ro)) * rc
        return math.sqrt(
            (delta_lp / sl) ** 2
            + (delta_cp / sc) ** 2
            + (delta_hp_term / sh) ** 2
            + rt * (delta_cp / sc) * (delta_hp_term / sh)
        )

    def _palette_similarity(self, left_colors: Sequence[Any], right_colors: Sequence[Any]) -> float:
        left = [str(item).strip() for item in left_colors if str(item).strip()]
        right = [str(item).strip() for item in right_colors if str(item).strip()]
        if not left or not right:
            return 0.0
        comparisons: List[float] = []
        for left_color in left[:3]:
            left_lab = self._rgb_to_lab(left_color)
            best_similarity = 0.0
            for right_color in right[:3]:
                delta = self._delta_e2000(left_lab, self._rgb_to_lab(right_color))
                similarity = max(0.0, 1 - min(delta, 60.0) / 60.0)
                best_similarity = max(best_similarity, similarity)
            comparisons.append(best_similarity)
        return round(sum(comparisons) / max(1, len(comparisons)), 3)

    def _relative_luminance(self, color: str) -> float:
        red, green, blue = self._hex_to_rgb(color)

        def channel(value: int) -> float:
            normalized = value / 255.0
            return normalized / 12.92 if normalized <= 0.03928 else ((normalized + 0.055) / 1.055) ** 2.4

        return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

    def _hex_to_hsl(self, color: str) -> Tuple[float, float, float]:
        red, green, blue = [channel / 255.0 for channel in self._hex_to_rgb(color)]
        maximum = max(red, green, blue)
        minimum = min(red, green, blue)
        lightness = (maximum + minimum) / 2.0
        if maximum == minimum:
            return (0.0, 0.0, lightness)
        delta = maximum - minimum
        saturation = delta / (2.0 - maximum - minimum) if lightness > 0.5 else delta / (maximum + minimum)
        if maximum == red:
            hue = ((green - blue) / delta + (6 if green < blue else 0)) / 6.0
        elif maximum == green:
            hue = ((blue - red) / delta + 2) / 6.0
        else:
            hue = ((red - green) / delta + 4) / 6.0
        return (hue, saturation, lightness)
