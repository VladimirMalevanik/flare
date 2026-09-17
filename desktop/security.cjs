"use strict";

const PRODUCTION_APP_URL = "https://flare4u.tech/";
const PRODUCTION_APP_ORIGINS = new Set([
  "https://flare4u.tech",
  "https://www.flare4u.tech",
]);
const GITHUB_AUTH_HOSTS = new Set(["github.com", "www.github.com"]);

function parseUrl(value) {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

function isLoopbackHostname(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

function resolveAppUrl(value, { allowInsecureLocalhost = false } = {}) {
  const candidate = parseUrl(value || PRODUCTION_APP_URL);
  if (!candidate || candidate.username || candidate.password) {
    throw new Error("FLARE_APP_URL must be an absolute URL without embedded credentials");
  }

  const secure = candidate.protocol === "https:";
  const localDevelopment = allowInsecureLocalhost
    && candidate.protocol === "http:"
    && isLoopbackHostname(candidate.hostname);

  if (!secure && !localDevelopment) {
    throw new Error("FLARE_APP_URL must use HTTPS (HTTP is allowed only for local development)");
  }

  return candidate.toString();
}

function resolveRuntimeAppUrl(environmentUrl, { isPackaged }) {
  return resolveAppUrl(
    isPackaged ? PRODUCTION_APP_URL : environmentUrl || PRODUCTION_APP_URL,
    { allowInsecureLocalhost: !isPackaged },
  );
}

function createNavigationPolicy(appUrl) {
  const configuredApp = parseUrl(appUrl);
  if (!configuredApp) throw new Error("A valid application URL is required");

  const appOrigins = new Set(PRODUCTION_APP_ORIGINS);
  appOrigins.add(configuredApp.origin);

  function classify(value) {
    const candidate = parseUrl(value);
    if (!candidate) return "blocked";

    if (appOrigins.has(candidate.origin)) return "app";
    if (candidate.protocol === "https:" && GITHUB_AUTH_HOSTS.has(candidate.hostname)) return "auth";
    if (candidate.protocol === "https:" || candidate.protocol === "mailto:") return "external";
    return "blocked";
  }

  function isTrustedAppOrigin(value) {
    const candidate = parseUrl(value);
    return Boolean(candidate && appOrigins.has(candidate.origin));
  }

  return { classify, isTrustedAppOrigin };
}

function isAudioOnlyMediaRequest(details = {}) {
  if (details.mediaType) return details.mediaType === "audio";
  const mediaTypes = Array.isArray(details.mediaTypes) ? details.mediaTypes : [];
  return mediaTypes.length > 0
    && mediaTypes.includes("audio")
    && !mediaTypes.includes("video");
}

module.exports = {
  PRODUCTION_APP_URL,
  createNavigationPolicy,
  isAudioOnlyMediaRequest,
  resolveAppUrl,
  resolveRuntimeAppUrl,
};
