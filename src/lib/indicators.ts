export function sma(values: readonly number[], period: number): number | null {
  if (period <= 0 || !Number.isFinite(period)) return null;
  if (values.length < period) return null;
  let sum = 0;
  for (let i = values.length - period; i < values.length; i++) {
    const v = values[i];
    if (v === undefined || !Number.isFinite(v)) return null;
    sum += v;
  }
  return sum / period;
}

export function avgWindow(
  values: readonly number[],
  period: number,
  endExclusiveIndex: number
): number | null {
  if (period <= 0 || !Number.isFinite(period)) return null;
  const startIdx = endExclusiveIndex - period;
  if (startIdx < 0 || endExclusiveIndex > values.length) return null;
  let sum = 0;
  for (let i = startIdx; i < endExclusiveIndex; i++) {
    const v = values[i];
    if (v === undefined || !Number.isFinite(v)) return null;
    sum += v;
  }
  return sum / period;
}
