/**
 * Canonical env name: FINMIND_API_TOKEN
 * Legacy alias accepted for back-compat: FINMIND_TOKEN
 */
export function resolveFinmindToken(): string | undefined {
  const primary = process.env.FINMIND_API_TOKEN;
  if (primary && primary.trim().length > 0) return primary.trim();
  const legacy = process.env.FINMIND_TOKEN;
  if (legacy && legacy.trim().length > 0) return legacy.trim();
  return undefined;
}

export function maskToken(token: string | undefined): string {
  if (!token) return "undefined";
  if (token.length <= 5) return "***";
  return `${token.substring(0, 5)}...`;
}
