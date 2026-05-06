import { TopBar } from "./TopBar";
import { SideNav } from "./SideNav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen w-screen grid grid-rows-[48px_1fr_28px] grid-cols-[64px_1fr] bg-bg-base text-fg-primary overflow-hidden">
      <div className="col-span-2 row-start-1"><TopBar /></div>
      <div className="row-start-2"><SideNav /></div>
      <main className="row-start-2 col-start-2 min-w-0 min-h-0 overflow-hidden">{children}</main>
      <footer
        role="status"
        className="col-span-2 row-start-3 flex items-center justify-between px-4 border-t border-border-subtle bg-bg-surface text-[11px] text-fg-muted"
      >
        <div className="flex gap-4">
          <span>Engine: <span className="text-signal-up">READY</span></span>
          <span>Risk: <span className="text-signal-warn">WARN</span></span>
          <span>Bot: <span className="text-fg-secondary">IDLE</span></span>
        </div>
        <div className="num">v0.1.0 · Phase 1</div>
      </footer>
    </div>
  );
}
