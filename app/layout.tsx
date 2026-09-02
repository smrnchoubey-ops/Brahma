import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "BRAHMA COS MVP",
  description: "Frontend prototype for the BRAHMA Cognitive OS MVP"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
