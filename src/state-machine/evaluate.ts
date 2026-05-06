import type { Grade, NoTradeFlag, ScoreCardData } from "@/types/scoring";

export interface ScoringInput {
  scoreA: number;
  scoreB: number;
  scoreC: number;
  noTradeFlags: readonly NoTradeFlag[];
  notes?: string;
}

const clamp = (n: number): number => {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 10) return 10;
  return n;
};

export function computeGrade(input: ScoringInput): Grade {
  if (input.noTradeFlags.length > 0) return "F";
  const a = clamp(input.scoreA);
  const b = clamp(input.scoreB);
  const c = clamp(input.scoreC);
  const avg = (a + b + c) / 3;
  if (a >= 8 && b >= 7 && c >= 8) return "A";
  if (avg >= 7 && a >= 6 && b >= 6 && c >= 6) return "B";
  if (avg >= 5) return "C";
  return "F";
}

export function evaluateScoring(input: ScoringInput): ScoreCardData {
  return {
    grade: computeGrade(input),
    scoreA: clamp(input.scoreA),
    scoreB: clamp(input.scoreB),
    scoreC: clamp(input.scoreC),
    noTradeFlags: input.noTradeFlags,
    notes: input.notes,
  };
}

export function isNoTradeBlocked(input: ScoringInput): boolean {
  return input.noTradeFlags.length > 0;
}
