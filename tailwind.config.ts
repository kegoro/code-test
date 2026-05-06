import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "rgb(var(--bg-base) / <alpha-value>)",
          surface: "rgb(var(--bg-surface) / <alpha-value>)",
          raised: "rgb(var(--bg-raised) / <alpha-value>)",
          inset: "rgb(var(--bg-inset) / <alpha-value>)",
        },
        border: {
          subtle: "rgb(var(--border-subtle) / <alpha-value>)",
          strong: "rgb(var(--border-strong) / <alpha-value>)",
        },
        fg: {
          primary: "rgb(var(--fg-primary) / <alpha-value>)",
          secondary: "rgb(var(--fg-secondary) / <alpha-value>)",
          muted: "rgb(var(--fg-muted) / <alpha-value>)",
        },
        accent: {
          cyan: "rgb(var(--accent-cyan) / <alpha-value>)",
          violet: "rgb(var(--accent-violet) / <alpha-value>)",
        },
        signal: {
          up: "rgb(var(--signal-up) / <alpha-value>)",
          down: "rgb(var(--signal-down) / <alpha-value>)",
          warn: "rgb(var(--signal-warn) / <alpha-value>)",
          danger: "rgb(var(--signal-danger) / <alpha-value>)",
          info: "rgb(var(--signal-info) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        "num-xs": ["11px", { lineHeight: "14px", letterSpacing: "0.02em" }],
        "num-sm": ["12px", { lineHeight: "16px", letterSpacing: "0.01em" }],
        "num-md": ["14px", { lineHeight: "18px" }],
        "num-lg": ["18px", { lineHeight: "22px" }],
        "num-xl": ["28px", { lineHeight: "32px" }],
      },
      borderRadius: {
        xs: "2px",
        sm: "4px",
        md: "6px",
      },
    },
  },
  plugins: [],
};

export default config;
