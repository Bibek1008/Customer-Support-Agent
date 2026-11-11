import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Support Desk — A little help. A clear answer.",
  description: "Get help with returns, shipping, billing, and warranties, backed by approved support documents.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
