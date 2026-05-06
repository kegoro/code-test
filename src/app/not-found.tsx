export default function NotFound() {
  return (
    <main className="h-screen w-screen grid place-items-center bg-bg-base text-fg-secondary">
      <div className="text-center">
        <div className="font-mono text-[11px] tracking-[0.2em] text-fg-muted">404</div>
        <div className="mt-2 text-[14px]">頁面不存在</div>
      </div>
    </main>
  );
}
