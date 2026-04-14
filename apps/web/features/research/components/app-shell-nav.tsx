"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePathname } from "next/navigation";

import { cn } from "@pm-agent/ui";

import { useAuth } from "../../auth/auth-provider";

const baseNavItems = [
  { href: "/", label: "首页" },
  { href: "/research/new", label: "新建研究" },
  { href: "/settings/runtime", label: "服务设置" },
  { href: "/settings/account", label: "账号设置" },
];

const adminNavItem = { href: "/settings/admin", label: "管理设置" };

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShellNav() {
  const pathname = usePathname();
  const auth = useAuth();

  const navItems = useMemo(
    () => (auth.user?.role === "admin" ? [...baseNavItems, adminNavItem] : baseNavItems),
    [auth.user?.role],
  );

  return (
    <nav className="inline-flex flex-wrap items-center gap-2 rounded-[24px] border border-[color:var(--border-soft)] bg-[rgba(255,252,246,0.6)] p-2 text-sm text-[color:var(--muted)] shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
      {navItems.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            className={cn(
              "rounded-2xl px-3.5 py-2 transition",
              active
                ? "border border-[color:var(--accent)] bg-[linear-gradient(135deg,_rgba(29,76,116,1),_rgba(23,32,51,0.98))] text-white shadow-[0_12px_30px_rgba(29,76,116,0.18)]"
                : "border border-transparent text-[color:var(--muted)] hover:border-[color:var(--border-soft)] hover:bg-[rgba(255,255,255,0.56)] hover:text-[color:var(--ink)]",
            )}
            href={item.href}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
