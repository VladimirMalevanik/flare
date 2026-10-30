/** Consume a reset fragment once; keep the token out of URLs and persistent storage. */
export function consumeResetToken(location: Pick<Location, "hash" | "pathname">, history: Pick<History, "replaceState">): string {
  const parameters = new URLSearchParams(location.hash.replace(/^#/, ""));
  const tokens = parameters.getAll("token");
  try {
    history.replaceState(null, "", location.pathname);
  } catch {
    return "";
  }
  return tokens.length === 1 && /^[A-Za-z0-9_-]{43}$/.test(tokens[0]) ? tokens[0] : "";
}
