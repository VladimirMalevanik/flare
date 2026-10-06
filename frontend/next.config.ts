import type { NextConfig } from "next";

const scriptPolicy = process.env.NODE_ENV === "production"
  ? "script-src 'self' 'unsafe-inline'"
  : "script-src 'self' 'unsafe-inline' 'unsafe-eval'";

// The SDK is bundled locally. Only the configured Azure ingestion origin needs
// access; never allow arbitrary connection-string endpoints through the CSP.
function analyticsIngestionOrigin(): string | null {
  if (process.env.NEXT_PUBLIC_APPLICATION_INSIGHTS_ENABLED !== "true") return null;
  const connectionString = process.env.NEXT_PUBLIC_APPLICATION_INSIGHTS_CONNECTION_STRING ?? "";
  const entries = connectionString.split(";").filter((entry) => entry.trim()).map((entry) => {
    const separator = entry.indexOf("=");
    return [entry.slice(0, separator).trim().toLowerCase(), entry.slice(separator + 1).trim()];
  });
  const fields = Object.fromEntries(entries);
  const key = fields.instrumentationkey ?? "";
  const endpoint = fields.ingestionendpoint ?? "";
  if (connectionString.length > 2048 || new Set(entries.map(([name]) => name)).size !== entries.length
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(key)
    || !/^https:\/\/[a-z0-9-]+\.in\.applicationinsights\.azure\.com\/?$/.test(endpoint)) {
    throw new Error("Application Insights requires a valid public Azure connection string.");
  }
  return endpoint.replace(/\/$/, "");
}
const analyticsOrigin = analyticsIngestionOrigin();

// App Router navigation keeps the original document's CSP. These exact Sandbox
// origins must also be allowed when users reach Settings from another page.
// Paddle.js itself is loaded lazily, only after the Pro checkout button is used.
const contentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  `connect-src 'self' https://sandbox-api.paddle.com${analyticsOrigin ? ` ${analyticsOrigin}` : ""}`,
  "font-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "frame-src 'self' https://sandbox-buy.paddle.com https://sandbox-cdn.paddle.com",
  "img-src 'self' data: https://sandbox-cdn.paddle.com",
  "object-src 'none'",
  `${scriptPolicy} https://cdn.paddle.com`,
  "style-src 'self' 'unsafe-inline' https://sandbox-cdn.paddle.com",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  typedRoutes: true,
  turbopack: { root: __dirname },
  agentRules: false,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async redirects() {
    return [{
      source: "/:path*",
      has: [{ type: "host", value: "www.flare4u.tech" }],
      destination: "https://flare4u.tech/:path*",
      permanent: true,
    }];
  },
  async rewrites() {
    return [{
      source: "/api/:path*",
      destination: `${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/:path*`,
    }];
  },
};

export default nextConfig;
