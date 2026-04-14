"use client";

import { PropsWithChildren, createContext, useContext, useEffect } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthUserRecord, ChangePasswordDto, DeleteAccountDto, LoginUserDto, RegisterUserDto } from "@pm-agent/types";

import { useDraftStore } from "../research/store/draft-store";
import { useResearchUiStore } from "../research/store/ui-store";
import { ApiClientError, changePassword, deleteCurrentAccount, fetchCurrentUser, getApiErrorMessage, loginUser, logoutUser, registerUser } from "../../lib/api-client";

type AuthStatus = "loading" | "authenticated" | "anonymous" | "error";

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUserRecord | null;
  errorMessage: string | null;
  signIn: (payload: LoginUserDto) => Promise<void>;
  signUp: (payload: RegisterUserDto) => Promise<void>;
  signOut: () => Promise<void>;
  updatePassword: (payload: ChangePasswordDto) => Promise<void>;
  deleteAccount: (payload: DeleteAccountDto) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const AUTH_QUERY_KEY = ["auth", "me"] as const;

function clearPersistedResearchState() {
  useResearchUiStore.getState().resetAllState();
  useResearchUiStore.persist.clearStorage();
  useDraftStore.getState().resetAllState();
  useDraftStore.persist.clearStorage();
}

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiClientError && error.status === 401;
}

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const currentUserQuery = useQuery({
    queryKey: AUTH_QUERY_KEY,
    queryFn: fetchCurrentUser,
    retry: false,
    staleTime: 30_000,
  });

  let status: AuthStatus = "loading";
  if (currentUserQuery.isPending) {
    status = "loading";
  } else if (currentUserQuery.data) {
    status = "authenticated";
  } else if (isUnauthorized(currentUserQuery.error)) {
    status = "anonymous";
  } else if (currentUserQuery.error) {
    status = "error";
  } else {
    status = "anonymous";
  }

  useEffect(() => {
    if (status === "anonymous") {
      clearPersistedResearchState();
    }
  }, [status]);

  const signIn = async (payload: LoginUserDto) => {
    const session = await loginUser(payload);
    queryClient.setQueryData(AUTH_QUERY_KEY, session.user);
  };

  const signUp = async (payload: RegisterUserDto) => {
    const session = await registerUser(payload);
    queryClient.setQueryData(AUTH_QUERY_KEY, session.user);
  };

  const signOut = async () => {
    try {
      await logoutUser();
    } finally {
      clearPersistedResearchState();
      queryClient.clear();
      queryClient.setQueryData(AUTH_QUERY_KEY, null);
    }
  };

  const updatePassword = async (payload: ChangePasswordDto) => {
    const session = await changePassword(payload);
    queryClient.setQueryData(AUTH_QUERY_KEY, session.user);
  };

  const deleteAccount = async (payload: DeleteAccountDto) => {
    await deleteCurrentAccount(payload);
    clearPersistedResearchState();
    queryClient.clear();
    queryClient.setQueryData(AUTH_QUERY_KEY, null);
  };

  const refresh = async () => {
    await currentUserQuery.refetch();
  };

  return (
    <AuthContext.Provider
      value={{
        status,
        user: currentUserQuery.data ?? null,
        errorMessage: status === "error" ? getApiErrorMessage(currentUserQuery.error, "登录状态检查失败。") : null,
        signIn,
        signUp,
        signOut,
        updatePassword,
        deleteAccount,
        refresh,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
