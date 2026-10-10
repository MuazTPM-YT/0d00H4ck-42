"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export const ROLES = ["owner", "store", "supervisor", "qc", "dispatch", "accounts"] as const;
export type Role = (typeof ROLES)[number];

export type User = { id: number; name: string; email: string; role: Role; active: boolean };

export const ROLE_LABEL: Record<Role, string> = {
  owner: "Owner",
  store: "Store",
  supervisor: "Floor supervisor",
  qc: "QC inspector",
  dispatch: "Dispatch",
  accounts: "Accounts & sales",
};

const HOME: Record<Role, string> = {
  owner: "/owner",
  store: "/store",
  supervisor: "/floor",
  qc: "/qc",
  dispatch: "/dispatch",
  accounts: "/orders",
};

export const roleHome = (role: Role) => HOME[role];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me"), retry: false, staleTime: 60_000 });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<{ user: User }>("/auth/login", { method: "POST", json: body }),
    onSuccess: ({ user }) => qc.setQueryData(["me"], user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.clear();
      window.location.href = "/login";
    },
  });
}
