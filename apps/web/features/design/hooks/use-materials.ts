"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteMaterial,
  fetchAllMaterialTags,
  fetchMaterial,
  fetchMaterialNetwork,
  fetchMaterials,
  updateMaterialTags,
  uploadMaterial,
  uploadMaterialFromUrl,
} from "../../../lib/api-client";
import type { MaterialList, UpdateMaterialTagsPayload } from "../data/trend-types";

export function useMaterials(params?: {
  tag?: string;
  category?: string;
  color?: string;
  page?: number;
  page_size?: number;
}) {
  return useQuery({
    queryKey: ["design-materials", params ?? {}],
    queryFn: () => fetchMaterials(params),
    placeholderData: (previous) => previous as MaterialList | undefined,
  });
}

export function useMaterial(materialId?: string | null) {
  return useQuery({
    queryKey: ["design-material", materialId],
    queryFn: () => fetchMaterial(materialId || ""),
    enabled: Boolean(materialId),
  });
}

export function useMaterialTags() {
  return useQuery({
    queryKey: ["design-material-tags"],
    queryFn: fetchAllMaterialTags,
    staleTime: 5 * 60 * 1000,
  });
}

export function useMaterialNetwork() {
  return useQuery({
    queryKey: ["design-material-network"],
    queryFn: fetchMaterialNetwork,
    staleTime: 60 * 1000,
  });
}

export function useUploadMaterial() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => uploadMaterial(file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-materials"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-network"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-tags"] });
    },
  });
}

export function useUploadMaterialFromUrl() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ url, tags = [] }: { url: string; tags?: string[] }) => uploadMaterialFromUrl(url, tags),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-materials"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-network"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-tags"] });
    },
  });
}

export function useDeleteMaterial() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (materialId: string) => deleteMaterial(materialId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-materials"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-network"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-tags"] });
    },
  });
}

export function useUpdateMaterialTags(materialId?: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UpdateMaterialTagsPayload) => updateMaterialTags(materialId || "", payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["design-materials"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-network"] });
      void queryClient.invalidateQueries({ queryKey: ["design-material-tags"] });
      if (materialId) {
        void queryClient.invalidateQueries({ queryKey: ["design-material", materialId] });
      }
    },
  });
}
