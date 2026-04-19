"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchTodayTrend, fetchTrendHistory, refreshTrendPool, saveTrendAsMaterial } from "../../../lib/api-client";
import type { DesignTrend } from "../data/trend-types";

export function useTodayTrend() {
  return useQuery({
    queryKey: ["design-trend-today"],
    queryFn: fetchTodayTrend,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useTrendHistory(days = 30) {
  return useQuery({
    queryKey: ["design-trend-history", days],
    queryFn: () => fetchTrendHistory(days),
    staleTime: 5 * 60 * 1000,
  });
}

export function useRefreshTrendPool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: refreshTrendPool,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-trend-today"] });
      void queryClient.invalidateQueries({ queryKey: ["design-trend-history"] });
    },
  });
}

export function useSaveTrendToLibrary() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (trend: DesignTrend) => saveTrendAsMaterial(trend),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-materials"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-network"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-tags"] });
    },
  });
}
