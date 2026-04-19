"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { DesignTrend, MaterialItem, TrendCategory } from "../data/trend-types";

export interface TrendRecord {
  date: string;
  trend: DesignTrend;
  category: TrendCategory;
  dice_face: number;
  saved_to_library: boolean;
}

interface DesignStoreState {
  trend_history: Record<string, TrendRecord>;
  saved_trends: string[];
  has_rolled_today: boolean;
  selected_material_id: string | null;
  network_view_active: boolean;
  materials_snapshot: Record<string, MaterialItem>;
  highlight_node_id: string | null;
  recordTrendRoll: (record: TrendRecord) => void;
  hydrateTrendHistory: (records: TrendRecord[]) => void;
  toggleSaveTrend: (trendId: string) => void;
  markTrendSavedForDate: (date: string, saved: boolean) => void;
  setHasRolledToday: (value: boolean) => void;
  setSelectedMaterialId: (value: string | null) => void;
  setNetworkViewActive: (value: boolean) => void;
  setMaterialsSnapshot: (items: MaterialItem[]) => void;
  setHighlightNodeId: (value: string | null) => void;
  reset: () => void;
}

export const useDesignStore = create<DesignStoreState>()(
  persist(
    (set, get) => ({
      trend_history: {},
      saved_trends: [],
      has_rolled_today: false,
      selected_material_id: null,
      network_view_active: false,
      materials_snapshot: {},
      highlight_node_id: null,
      recordTrendRoll: (record) =>
        set((state) => ({
          trend_history: {
            ...state.trend_history,
            [record.date]: record,
          },
          has_rolled_today: true,
        })),
      hydrateTrendHistory: (records) =>
        set((state) => {
          const next = { ...state.trend_history };
          for (const record of records) {
            next[record.date] = record;
          }
          return { trend_history: next };
        }),
      toggleSaveTrend: (trendId) =>
        set((state) => ({
          saved_trends: state.saved_trends.includes(trendId)
            ? state.saved_trends.filter((item) => item !== trendId)
            : [...state.saved_trends, trendId],
        })),
      markTrendSavedForDate: (date, saved) =>
        set((state) => ({
          trend_history: state.trend_history[date]
            ? {
                ...state.trend_history,
                [date]: {
                  ...state.trend_history[date],
                  saved_to_library: saved,
                },
              }
            : state.trend_history,
        })),
      setHasRolledToday: (value) => set({ has_rolled_today: value }),
      setSelectedMaterialId: (value) => set({ selected_material_id: value }),
      setNetworkViewActive: (value) => set({ network_view_active: value }),
      setMaterialsSnapshot: (items) =>
        set(() => ({
          materials_snapshot: Object.fromEntries(items.map((item) => [item.id, item])),
        })),
      setHighlightNodeId: (value) => set({ highlight_node_id: value }),
      reset: () =>
        set({
          trend_history: {},
          saved_trends: [],
          has_rolled_today: false,
          selected_material_id: null,
          network_view_active: false,
          materials_snapshot: {},
          highlight_node_id: null,
        }),
    }),
    {
      name: "pm-design-state",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        trend_history: state.trend_history,
        saved_trends: state.saved_trends,
        has_rolled_today: state.has_rolled_today,
        selected_material_id: state.selected_material_id,
        network_view_active: state.network_view_active,
        highlight_node_id: state.highlight_node_id,
      }),
      merge: (persistedState, currentState) => ({
        ...currentState,
        ...(persistedState as Partial<DesignStoreState> | undefined),
        materials_snapshot: currentState.materials_snapshot,
      }),
    },
  ),
);

export function buildTrendRecordFromRoll(roll: {
  date: string;
  trend: DesignTrend;
  dice_face: number;
  dice_category: TrendCategory;
}): TrendRecord {
  const saved = get().saved_trends.includes(roll.trend.id);
  return {
    date: roll.date,
    trend: roll.trend,
    category: roll.trend.category || roll.dice_category,
    dice_face: roll.dice_face,
    saved_to_library: saved,
  };
}

function get() {
  return useDesignStore.getState();
}
