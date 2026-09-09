import type { Metadata } from "next";
import "./globals.css";
import "./review.css";

export const metadata: Metadata = {
  title: "SpecGuard · Requirement review",
  description: "Review requirements against exact source evidence.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
