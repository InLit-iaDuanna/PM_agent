const DEFAULT_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const SAME_ORIGIN_API_BASE_URL = "same-origin";
const STORAGE_KEY = "pm-agent-api-base-url";
const API_BASE_URL_EVENT = "pm-agent:api-base-url-changed";
const LOCAL_FALLBACK_PORTS = [8000, 8001, 8002, 8003, 8004, 8005];

function normalizeApiBaseUrl(value?: string | null): string {
  const normalized = (value || "").trim();
  if (!normalized) {
    return "";
  }
  if (normalized === "/" || normalized.toLowerCase() === SAME_ORIGIN_API_BASE_URL) {
    return SAME_ORIGIN_API_BASE_URL;
  }
  return normalized.replace(/\/$/, "");
}

function resolveApiBaseUrl(value: string): string {
  if (value !== SAME_ORIGIN_API_BASE_URL) {
    return value;
  }
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "";
}

function parseUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isLoopbackHost(hostname?: string | null): boolean {
  return hostname === "127.0.0.1" || hostname === "localhost";
}

function shouldPreferDefaultOverStored(storedValue: string, defaultValue: string): boolean {
  if (storedValue === SAME_ORIGIN_API_BASE_URL || defaultValue === SAME_ORIGIN_API_BASE_URL) {
    return false;
  }
  const storedUrl = parseUrl(storedValue);
  const defaultUrl = parseUrl(defaultValue);
  if (!storedUrl || !defaultUrl) {
    return false;
  }

  return (
    isLoopbackHost(storedUrl.hostname) &&
    isLoopbackHost(defaultUrl.hostname) &&
    storedUrl.port === "8000" &&
    defaultUrl.port !== storedUrl.port
  );
}

function localApiCandidates(seedUrls: string[]): string[] {
  const hosts = new Set<string>();
  for (const value of seedUrls) {
    const parsed = parseUrl(value);
    if (parsed && isLoopbackHost(parsed.hostname)) {
      hosts.add(parsed.hostname);
      hosts.add("127.0.0.1");
      hosts.add("localhost");
    }
  }

  if (typeof window !== "undefined" && isLoopbackHost(window.location.hostname)) {
    hosts.add(window.location.hostname);
    hosts.add("127.0.0.1");
    hosts.add("localhost");
  }

  return Array.from(hosts).flatMap((hostname) => LOCAL_FALLBACK_PORTS.map((port) => `http://${hostname}:${port}`));
}

export function getApiBaseUrl(): string {
  const defaultValue = normalizeApiBaseUrl(DEFAULT_API_BASE_URL);
  if (typeof window === "undefined") {
    return resolveApiBaseUrl(defaultValue);
  }

  const storedValue = normalizeApiBaseUrl(window.localStorage.getItem(STORAGE_KEY));
  if (storedValue && shouldPreferDefaultOverStored(storedValue, defaultValue)) {
    window.localStorage.setItem(STORAGE_KEY, defaultValue);
    return resolveApiBaseUrl(defaultValue);
  }

  return resolveApiBaseUrl(storedValue || defaultValue);
}

export function setApiBaseUrl(value: string): void {
  if (typeof window === "undefined") {
    return;
  }
  const normalizedValue = normalizeApiBaseUrl(value);
  window.localStorage.setItem(STORAGE_KEY, normalizedValue);
  window.dispatchEvent(new CustomEvent<string>(API_BASE_URL_EVENT, { detail: normalizedValue }));
}

export function subscribeApiBaseUrl(callback: (value: string) => void): () => void {
  if (typeof window === "undefined") {
    return () => {};
  }

  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) {
      return;
    }
    callback(getApiBaseUrl());
  };

  const onCustomEvent = (event: Event) => {
    const nextValue = (event as CustomEvent<string>).detail;
    callback(resolveApiBaseUrl(nextValue || getApiBaseUrl()));
  };

  window.addEventListener("storage", onStorage);
  window.addEventListener(API_BASE_URL_EVENT, onCustomEvent as EventListener);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(API_BASE_URL_EVENT, onCustomEvent as EventListener);
  };
}

export function getDefaultApiBaseUrl(): string {
  return resolveApiBaseUrl(normalizeApiBaseUrl(DEFAULT_API_BASE_URL));
}

export function getApiBaseUrlCandidates(): string[] {
  const currentBaseUrl = getApiBaseUrl();
  const defaultBaseUrl = getDefaultApiBaseUrl();
  const candidates = [currentBaseUrl, defaultBaseUrl, ...localApiCandidates([currentBaseUrl, defaultBaseUrl])];
  return Array.from(new Set(candidates.map((item) => normalizeApiBaseUrl(item)).filter(Boolean)));
}
