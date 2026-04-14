"use client";

import type { CreateResearchJobDto } from "@pm-agent/types";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import { defaultResearchForm } from "../../../lib/demo-data";

interface DraftState {
  newResearchForm: CreateResearchJobDto;
  setNewResearchForm: (form: CreateResearchJobDto) => void;
  patchNewResearchForm: (patch: Partial<CreateResearchJobDto>) => void;
  resetNewResearchForm: () => void;
  resetAllState: () => void;
}

function cloneDefaultResearchForm(): CreateResearchJobDto {
  return {
    ...defaultResearchForm,
    geo_scope: [...defaultResearchForm.geo_scope],
  };
}

export const useDraftStore = create<DraftState>()(
  persist(
    (set) => ({
      newResearchForm: cloneDefaultResearchForm(),
      setNewResearchForm: (newResearchForm) =>
        set({
          newResearchForm: {
            ...newResearchForm,
            geo_scope: [...(newResearchForm.geo_scope || [])],
          },
        }),
      patchNewResearchForm: (patch) =>
        set((state) => ({
          newResearchForm: {
            ...state.newResearchForm,
            ...patch,
            geo_scope: [...(patch.geo_scope ?? state.newResearchForm.geo_scope ?? [])],
          },
        })),
      resetNewResearchForm: () => set({ newResearchForm: cloneDefaultResearchForm() }),
      resetAllState: () => set({ newResearchForm: cloneDefaultResearchForm() }),
    }),
    {
      name: "pm-research-drafts",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        newResearchForm: state.newResearchForm,
      }),
      merge: (persistedState, currentState) => {
        const typedPersistedState = persistedState as Partial<DraftState> | undefined;
        return {
          ...currentState,
          ...typedPersistedState,
          newResearchForm: {
            ...cloneDefaultResearchForm(),
            ...(typedPersistedState?.newResearchForm ?? {}),
            geo_scope: [...(typedPersistedState?.newResearchForm?.geo_scope ?? cloneDefaultResearchForm().geo_scope ?? [])],
          },
        };
      },
    },
  ),
);
