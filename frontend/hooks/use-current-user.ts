"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";

import { api, ApiError } from "@/lib/api";
import type { User } from "@/types/api";

/** The signed-in user. Sends the visitor to sign-in when the session is gone. */
export function useCurrentUser() {
  const router = useRouter();
  const query = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/users/me") });

  useEffect(() => {
    if (query.error instanceof ApiError && query.error.status === 401) {
      router.replace("/login");
    }
  }, [query.error, router]);

  return query;
}

export function useSignOut() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useCallback(
    async (everywhere = false) => {
      try {
        await api(everywhere ? "/auth/logout-all" : "/auth/logout", { method: "POST" });
      } finally {
        // Clear every cached query so the next user starts from nothing.
        queryClient.clear();
        router.replace("/login");
      }
    },
    [queryClient, router],
  );
}
