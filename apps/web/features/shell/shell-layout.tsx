"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { Sidebar, type NavJob } from "@pm-agent/ui";

import { useAuth } from "../auth/auth-provider";
import { fetchResearchJobs } from "../../lib/api-client";
import { TopBar } from "./top-bar";
import { StatusBar } from "./status-bar";
import { QuickSearchPanel } from "./quick-search-panel";

type JobForNav = {
  id: string;
  topic: string;
  status: string;
  updated_at?: string;
  created_at?: string;
};

function toNavJob(job: JobForNav): NavJob {
  const activeStatuses = ["running", "planning", "verifying", "synthesizing"];
  let status: NavJob["status"] = "completed";
  if (activeStatuses.includes(job.status)) {
    status = job.status as NavJob["status"];
  } else if (job.status === "failed") {
    status = "failed";
  } else if (job.status === "cancelled") {
    status = "cancelled";
  } else {
    status = "completed";
  }
  return { id: job.id, topic: job.topic, status };
}

function sortByUpdated(jobs: JobForNav[]) {
  return [...jobs].sort((a, b) => {
    const at = a.updated_at || a.created_at || "";
    const bt = b.updated_at || b.created_at || "";
    return bt.localeCompare(at);
  });
}

interface ShellLayoutProps {
  children: ReactNode;
}

/**
 * ShellLayout — 三栏工作台布局
 *
 * 替换原来的 AppChrome，结构：
 *   ┌──────────────────────────────────────────────┐
 *   │ TopBar (52px, sticky)                        │
 *   ├────────┬─────────────────────────────────────┤
 *   │Sidebar │ Main content (flex-1, overflow-y)   │
 *   ├────────┴─────────────────────────────────────┤
 *   │ StatusBar (26px)                             │
 *   └──────────────────────────────────────────────┘
 */
export function ShellLayout({ children }: ShellLayoutProps) {
  const [searchOpen, setSearchOpen] = useState(false);

  const jobsQuery = useQuery({
    queryKey: ["research-jobs"],
    queryFn: fetchResearchJobs,
    refetchInterval: ({ state }) => {
      const jobs = Array.isArray(state.data) ? state.data : [];
      return jobs.some((j) => !["completed", "failed", "cancelled"].includes(j.status)) ? 4000 : 15000;
    },
    staleTime: 3000,
  });

  const auth = useAuth();
  const recentJobs: NavJob[] = sortByUpdated(Array.isArray(jobsQuery.data) ? jobsQuery.data : [])
    .slice(0, 5)
    .map(toNavJob);

  const isAdmin = auth.user?.role === "admin";

  const openSearch = useCallback(() => setSearchOpen(true), []);
  const closeSearch = useCallback(() => setSearchOpen(false), []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      {/* TopBar */}
      <TopBar onSearchOpen={openSearch} />

      {/* Body: Sidebar + Main */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <Sidebar
          recentJobs={recentJobs}
          isAdmin={isAdmin}
        />

        {/* Main content */}
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] px-5 py-7 sm:px-7 lg:py-9">
            {children}
          </div>
        </main>
      </div>

      {/* StatusBar */}
      <StatusBar />

      {/* Quick Search */}
      {searchOpen && (
        <QuickSearchPanel
          jobs={Array.isArray(jobsQuery.data) ? jobsQuery.data : []}
          onClose={closeSearch}
        />
      )}
    </div>
  );
}
