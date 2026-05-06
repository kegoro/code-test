export function formatPrice(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPct(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function formatVolume(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}億`;
  if (value >= 1e4) return `${(value / 1e4).toFixed(1)}萬`;
  return value.toString();
}

export function safeDivide(numerator: number, denominator: number): number | null {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator)) return null;
  if (denominator === 0) return null;
  return numerator / denominator;
}

export function changeTone(changePct: number): "up" | "down" | "flat" {
  if (!Number.isFinite(changePct) || changePct === 0) return "flat";
  return changePct > 0 ? "up" : "down";
}
