"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bell,
  Bot,
  ClipboardCheck,
  Database,
  Gauge,
  ListChecks,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  ShieldCheck
} from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/decisions", label: "Decisions", icon: ClipboardCheck },
  { href: "/memory", label: "Memory", icon: Database },
  { href: "/agents", label: "Agents", icon: Bot },
  { href: "/audit", label: "Audit Ledger", icon: ScrollText }
];

const routeTitles = [
  { match: "/dashboard", title: "Founder Command Center" },
  { match: "/tasks", title: "Tasks" },
  { match: "/decisions", title: "Decision Review" },
  { match: "/memory", title: "Memory Ledger" },
  { match: "/agents", title: "Agent Monitoring" },
  { match: "/audit", title: "Audit Ledger" }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const pageTitle = useMemo(() => {
    return (
      routeTitles.find((item) => pathname.startsWith(item.match))?.title ??
      "BRAHMA COS"
    );
  }, [pathname]);

  return (
    <div className="min-h-screen bg-background">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 hidden border-r bg-card transition-all duration-200 lg:block",
          collapsed ? "w-20" : "w-64"
        )}
      >
        <SidebarContent
          pathname={pathname}
          collapsed={collapsed}
          onToggle={() => setCollapsed((value) => !value)}
        />
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/30"
            onClick={() => setMobileOpen(false)}
            type="button"
          />
          <aside className="relative h-full w-72 border-r bg-card">
            <SidebarContent
              pathname={pathname}
              collapsed={false}
              onNavigate={() => setMobileOpen(false)}
            />
          </aside>
        </div>
      ) : null}

      <div
        className={cn(
          "flex min-h-screen flex-col transition-all duration-200",
          collapsed ? "lg:pl-20" : "lg:pl-64"
        )}
      >
        <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur">
          <div className="flex h-16 items-center justify-between gap-4 px-4 sm:px-6">
            <div className="flex items-center gap-3">
              <Button
                aria-label="Open navigation"
                className="lg:hidden"
                onClick={() => setMobileOpen(true)}
                size="icon"
                type="button"
                variant="ghost"
              >
                <Menu className="h-5 w-5" aria-hidden="true" />
              </Button>
              <div>
                <p className="text-xs font-medium uppercase text-muted-foreground">
                  BRAHMA COS MVP
                </p>
                <p className="text-sm font-semibold sm:text-base">{pageTitle}</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                aria-label="Notifications"
                size="icon"
                type="button"
                variant="ghost"
              >
                <Bell className="h-5 w-5" aria-hidden="true" />
              </Button>
              <div className="hidden items-center gap-3 rounded-md border bg-card px-3 py-2 sm:flex">
                <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
                  FC
                </div>
                <div className="leading-tight">
                  <p className="text-sm font-medium">Founder</p>
                  <p className="mt-1 inline-flex items-center rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-500 animate-pulse">
                    DEMO MODE
                  </p>
                </div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}

function SidebarContent({
  pathname,
  collapsed,
  onToggle,
  onNavigate
}: {
  pathname: string;
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center justify-between gap-3 border-b px-4">
        <Link
          className={cn("flex min-w-0 items-center gap-3", collapsed && "justify-center")}
          href="/dashboard"
          onClick={onNavigate}
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="h-5 w-5" aria-hidden="true" />
          </div>
          {!collapsed ? (
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">BRAHMA COS</p>
              <p className="truncate text-xs text-muted-foreground">
                Cognitive OS
              </p>
            </div>
          ) : null}
        </Link>
        {onToggle ? (
          <Button
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="hidden lg:inline-flex"
            onClick={onToggle}
            size="icon"
            type="button"
            variant="ghost"
          >
            {collapsed ? (
              <PanelLeftOpen className="h-5 w-5" aria-hidden="true" />
            ) : (
              <PanelLeftClose className="h-5 w-5" aria-hidden="true" />
            )}
          </Button>
        ) : null}
      </div>

      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname.startsWith(item.href);

          return (
            <Link
              aria-label={item.label}
              className={cn(
                "flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                active && "bg-muted text-foreground",
                collapsed && "justify-center px-0"
              )}
              href={item.href}
              key={item.href}
              onClick={onNavigate}
              title={collapsed ? item.label : undefined}
            >
              <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
              {!collapsed ? <span>{item.label}</span> : null}
            </Link>
          );
        })}
      </nav>

      <div className="border-t p-4">
        <div
          className={cn(
            "rounded-md border border-amber-500/20 bg-amber-500/5 p-3 shadow-[0_0_15px_rgba(251,191,36,0.05)]",
            collapsed && "p-2 text-center"
          )}
        >
          <p className="flex items-center gap-1.5 text-xs font-semibold text-amber-500/90">
            {collapsed ? "UI" : (
              <>
                <ShieldCheck className="h-3 w-3" />
                <span>PROTOTYPE SYSTEM</span>
              </>
            )}
          </p>
          {!collapsed ? (
            <p className="mt-1.5 text-xs leading-relaxed text-amber-500/70">
              Mock data and local state. Awaiting live backend connection.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
