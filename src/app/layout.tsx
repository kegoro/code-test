import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant Terminal",
  description: "Professional personal quantitative trading terminal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className="dark">
      <body>{children}</body>
    </html>
  );
}
