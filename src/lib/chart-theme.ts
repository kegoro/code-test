type RGBTriple = [number, number, number];

function readVar(name: string, fallback: RGBTriple): string {
  if (typeof window === "undefined") {
    return `rgb(${fallback.join(",")})`;
  }
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  if (!raw) return `rgb(${fallback.join(",")})`;
  return `rgb(${raw.replaceAll(" ", ",")})`;
}

function readVarAlpha(name: string, alpha: number, fallback: RGBTriple): string {
  if (typeof window === "undefined") {
    return `rgba(${fallback.join(",")},${alpha})`;
  }
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  if (!raw) return `rgba(${fallback.join(",")},${alpha})`;
  return `rgba(${raw.replaceAll(" ", ",")},${alpha})`;
}

// Returns klinecharts DeepPartial<Styles>. Typed as a record to avoid coupling
// to klinecharts' internal type re-exports while still being narrow enough.
export function buildKLineTheme(): Record<string, unknown> {
  const fgPrimary = readVar("--fg-primary", [232, 236, 244]);
  const fgSecondary = readVar("--fg-secondary", [168, 176, 192]);
  const fgMuted = readVar("--fg-muted", [110, 120, 140]);
  const borderSubtle = readVar("--border-subtle", [28, 33, 44]);
  const borderStrong = readVar("--border-strong", [46, 54, 70]);
  const bgRaised = readVar("--bg-raised", [18, 22, 30]);
  const bgInset = readVar("--bg-inset", [5, 7, 10]);
  const accentCyan = readVar("--accent-cyan", [56, 189, 248]);

  const up = readVar("--signal-up", [34, 197, 94]);
  const down = readVar("--signal-down", [239, 68, 68]);
  const upTransparent = readVarAlpha("--signal-up", 0.35, [34, 197, 94]);
  const downTransparent = readVarAlpha("--signal-down", 0.35, [239, 68, 68]);

  return {
    grid: {
      show: true,
      horizontal: { show: true, size: 1, color: borderSubtle, style: "dashed", dashedValue: [2, 4] },
      vertical: { show: true, size: 1, color: borderSubtle, style: "dashed", dashedValue: [2, 4] },
    },
    candle: {
      type: "candle_solid",
      bar: {
        upColor: up,
        downColor: down,
        noChangeColor: fgMuted,
        upBorderColor: up,
        downBorderColor: down,
        noChangeBorderColor: fgMuted,
        upWickColor: up,
        downWickColor: down,
        noChangeWickColor: fgMuted,
      },
      tooltip: {
        showRule: "follow_cross",
        showType: "standard",
        text: { color: fgSecondary, marginLeft: 8, marginTop: 6, marginRight: 8, marginBottom: 6 },
      },
      priceMark: {
        last: {
          show: true,
          line: { show: true, style: "dashed", dashedValue: [4, 4], size: 1 },
          text: {
            show: true,
            color: "#FFFFFF",
            backgroundColor: accentCyan,
            paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
            borderRadius: 2,
          },
        },
        high: { show: true, color: fgMuted },
        low: { show: true, color: fgMuted },
      },
    },
    indicator: {
      ohlc: { upColor: upTransparent, downColor: downTransparent, noChangeColor: fgMuted },
      bars: [{ style: "fill", borderStyle: "solid", borderSize: 1, borderDashedValue: [2, 2], upColor: upTransparent, downColor: downTransparent, noChangeColor: fgMuted }],
      lines: [
        { size: 1, color: "#fbbf24" },  // MA5  amber
        { size: 1, color: accentCyan }, // MA10 cyan
        { size: 1, color: "#a78bfa" },  // MA30 violet
        { size: 1, color: "#f472b6" },  // MA60 pink
        { size: 1, color: "#f87171" },  // MA240 red
      ],
      tooltip: {
        showRule: "always",
        showType: "standard",
        text: { color: fgSecondary, marginTop: 6, marginRight: 8, marginBottom: 6, marginLeft: 8 },
      },
    },
    xAxis: {
      axisLine: { show: true, color: borderStrong, size: 1 },
      tickLine: { show: true, size: 1, length: 3, color: borderStrong },
      tickText: { color: fgMuted, size: 10 },
    },
    yAxis: {
      axisLine: { show: true, color: borderStrong, size: 1 },
      tickLine: { show: true, size: 1, length: 3, color: borderStrong },
      tickText: { color: fgMuted, size: 10 },
    },
    crosshair: {
      show: true,
      horizontal: {
        show: true,
        line: { show: true, style: "dashed", dashedValue: [4, 2], size: 1, color: fgMuted },
        text: {
          show: true,
          color: "#FFFFFF",
          size: 10,
          paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
          borderRadius: 2,
          borderSize: 1,
          borderColor: borderStrong,
          backgroundColor: bgRaised,
        },
      },
      vertical: {
        show: true,
        line: { show: true, style: "dashed", dashedValue: [4, 2], size: 1, color: fgMuted },
        text: {
          show: true,
          color: "#FFFFFF",
          size: 10,
          paddingLeft: 4, paddingRight: 4, paddingTop: 2, paddingBottom: 2,
          borderRadius: 2,
          borderSize: 1,
          borderColor: borderStrong,
          backgroundColor: bgRaised,
        },
      },
    },
    separator: { size: 1, color: borderSubtle },
    background: { color: bgInset },
  };
}

export const MA_PERIODS: readonly [number, number, number, number, number] = [5, 10, 30, 60, 240];
