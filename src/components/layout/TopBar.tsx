export function TopBar() {
  return (
    <header className="flex items-center justify-between px-4 border-b border-border-subtle bg-bg-surface">
      <div className="flex items-center gap-3">
        <div className="size-5 rounded-xs bg-gradient-to-br from-accent-cyan to-accent-violet" />
        <span className="font-mono text-[12px] tracking-[0.18em] text-fg-primary">
          QUANT · TERMINAL
        </span>
        <span className="text-[10px] text-fg-muted px-2 py-0.5 border border-border-subtle rounded-xs">
          PAPER
        </span>
      </div>

      <nav className="flex items-center gap-1">
        {["Overview", "Strategy", "Backtest", "Journal"].map((item, i) => (
          <button
            key={item}
            type="button"
            className={
              "px-3 py-1 text-[12px] rounded-xs border " +
              (i === 0
                ? "border-border-strong text-fg-primary bg-bg-raised"
                : "border-transparent text-fg-secondary hover:text-fg-primary")
            }
          >
            {item}
          </button>
        ))}
      </nav>

      <div className="flex items-center gap-3 text-[11px] num text-fg-secondary">
        <span className="flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-signal-up" /> Live Data
        </span>
        <span>2026/05/05 13:30:42</span>
      </div>
    </header>
  );
}
