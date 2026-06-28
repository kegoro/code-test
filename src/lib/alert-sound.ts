"use client";

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (ctx) return ctx;
  const W = window as unknown as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  const Cls = W.AudioContext ?? W.webkitAudioContext;
  if (!Cls) return null;
  ctx = new Cls();
  return ctx;
}

function tone(audio: AudioContext, freq: number, start: number, dur: number, gain: number): void {
  const osc = audio.createOscillator();
  const g = audio.createGain();
  osc.type = "sine";
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0, audio.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, audio.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + start + dur);
  osc.connect(g).connect(audio.destination);
  osc.start(audio.currentTime + start);
  osc.stop(audio.currentTime + start + dur + 0.02);
}

export function playAlertBeep(grade: "A" | "B" = "A"): void {
  const audio = getCtx();
  if (!audio) return;
  if (audio.state === "suspended") {
    void audio.resume();
  }
  if (grade === "A") {
    // Bright two-tone for A-grade
    tone(audio, 880, 0, 0.14, 0.35);
    tone(audio, 1320, 0.16, 0.18, 0.30);
  } else {
    tone(audio, 660, 0, 0.16, 0.25);
  }
}

/** Call this once on the first real user gesture so the AudioContext starts unsuspended. */
export function primeAlertSound(): void {
  const audio = getCtx();
  if (!audio) return;
  if (audio.state === "suspended") {
    void audio.resume();
  }
}
