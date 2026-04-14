"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type PanelTab = "stable-report" | "latest-draft" | "evidence" | "chat" | "diff";

const DEFAULT_CHAT_DRAFT = "如果我要优先切入 AI 产品团队，产品上最应该先做什么？";

interface JobScopedUiState {
  activeTab: PanelTab;
  selectedClaimId?: string;
  selectedTaskId?: string;
  chatDraft: string;
}

interface ResearchUiState {
  currentJobId?: string;
  activeTab: PanelTab;
  selectedClaimId?: string;
  selectedTaskId?: string;
  chatDraft: string;
  byJobId: Record<string, JobScopedUiState>;
  setCurrentJobId: (jobId: string) => void;
  setActiveTab: (tab: PanelTab) => void;
  setSelectedClaimId: (claimId?: string) => void;
  setSelectedTaskId: (taskId?: string) => void;
  setChatDraft: (draft: string) => void;
  resetJobState: (jobId: string) => void;
  resetAllState: () => void;
}

const defaultJobState = (): JobScopedUiState => ({
  activeTab: "stable-report",
  selectedClaimId: undefined,
  selectedTaskId: undefined,
  chatDraft: DEFAULT_CHAT_DRAFT,
});

function getJobState(byJobId: Record<string, JobScopedUiState>, jobId?: string): JobScopedUiState {
  if (!jobId) {
    return defaultJobState();
  }
  return byJobId[jobId] ?? defaultJobState();
}

export const useResearchUiStore = create<ResearchUiState>()(
  persist(
    (set, get) => ({
      currentJobId: undefined,
      activeTab: "stable-report",
      selectedClaimId: undefined,
      selectedTaskId: undefined,
      chatDraft: DEFAULT_CHAT_DRAFT,
      byJobId: {},
      setCurrentJobId: (jobId) => {
        const scopedState = getJobState(get().byJobId, jobId);
        set({
          currentJobId: jobId,
          activeTab: scopedState.activeTab,
          selectedClaimId: scopedState.selectedClaimId,
          selectedTaskId: scopedState.selectedTaskId,
          chatDraft: scopedState.chatDraft,
        });
      },
      setActiveTab: (activeTab) => {
        const currentJobId = get().currentJobId;
        const byJobId = get().byJobId;
        set({
          activeTab,
          byJobId: currentJobId
            ? {
                ...byJobId,
                [currentJobId]: {
                  ...getJobState(byJobId, currentJobId),
                  activeTab,
                },
              }
            : byJobId,
        });
      },
      setSelectedClaimId: (selectedClaimId) => {
        const currentJobId = get().currentJobId;
        const byJobId = get().byJobId;
        set({
          selectedClaimId,
          byJobId: currentJobId
            ? {
                ...byJobId,
                [currentJobId]: {
                  ...getJobState(byJobId, currentJobId),
                  selectedClaimId,
                },
              }
            : byJobId,
        });
      },
      setSelectedTaskId: (selectedTaskId) => {
        const currentJobId = get().currentJobId;
        const byJobId = get().byJobId;
        set({
          selectedTaskId,
          byJobId: currentJobId
            ? {
                ...byJobId,
                [currentJobId]: {
                  ...getJobState(byJobId, currentJobId),
                  selectedTaskId,
                },
              }
            : byJobId,
        });
      },
      setChatDraft: (chatDraft) => {
        const currentJobId = get().currentJobId;
        const byJobId = get().byJobId;
        set({
          chatDraft,
          byJobId: currentJobId
            ? {
                ...byJobId,
                [currentJobId]: {
                  ...getJobState(byJobId, currentJobId),
                  chatDraft,
                },
              }
            : byJobId,
        });
      },
      resetJobState: (jobId) => {
        const nextByJobId = { ...get().byJobId };
        delete nextByJobId[jobId];
        const shouldResetCurrent = get().currentJobId === jobId;
        const resetState = defaultJobState();
        set({
          byJobId: nextByJobId,
          ...(shouldResetCurrent
            ? {
                currentJobId: undefined,
                activeTab: resetState.activeTab,
                selectedClaimId: resetState.selectedClaimId,
                selectedTaskId: resetState.selectedTaskId,
                chatDraft: resetState.chatDraft,
              }
            : {}),
        });
      },
      resetAllState: () =>
        set({
          currentJobId: undefined,
          activeTab: "stable-report",
          selectedClaimId: undefined,
          selectedTaskId: undefined,
          chatDraft: DEFAULT_CHAT_DRAFT,
          byJobId: {},
        }),
    }),
    {
      name: "pm-research-ui-state",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        currentJobId: state.currentJobId,
        activeTab: state.activeTab,
        selectedClaimId: state.selectedClaimId,
        selectedTaskId: state.selectedTaskId,
        chatDraft: state.chatDraft,
        byJobId: state.byJobId,
      }),
    },
  ),
);
