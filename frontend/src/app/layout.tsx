import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "BRAHMA COS | Command Center",
  description: "Cognitive Operating System for the Enterprise",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark antialiased h-full`}
    >
      <body className="min-h-full flex bg-background text-foreground">
        <Sidebar />
        <main className="flex-1 flex flex-col h-screen overflow-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}

