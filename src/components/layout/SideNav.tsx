"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

interface NavItem {
  key: string;
  label: string;
  icon: string;
  href: string;
}

const items: readonly NavItem[] = [
  { key: "watch",   label: "標的池", icon: "◆", href: "/" },
  { key: "chart",   label: "圖表",   icon: "▦", href: "/" },
  { key: "score",   label: "評分",   icon: "★", href: "/" },
  { key: "risk",    label: "風控",   icon: "⚠", href: "/" },
  { key: "journal", label: "日誌",   icon: "✎", href: "/journal" },
];

function isActive(pathname: string | null, item: NavItem): boolean {
  if (!pathname) return false;
  if (item.key === "journal") return pathname.startsWith("/journal");
  if (item.key === "watch") return pathname === "/";
  return false;
}

export function SideNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col items-center gap-1 py-3 border-r border-border-subtle bg-bg-surface">
      {items.map((it) => {
        const active = isActive(pathname, it);
        return (
          <Link
            key={it.key}
            href={it.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "w-12 h-12 grid place-items-center rounded-sm text-[10px] gap-0.5",
              active
                ? "bg-bg-raised text-fg-primary border border-border-strong"
                : "text-fg-muted hover:text-fg-primary hover:bg-bg-raised/60"
            )}
          >
            <span className="text-[16px] leading-none">{it.icon}</span>
            <span>{it.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
