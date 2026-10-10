"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type SubmitEvent, type SyntheticEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";

// shared submit logic for master forms: native checks inline first, then server field errors
export function useMasterForm<T>(path: string, id: number | null, onDone: () => void) {
  const qc = useQueryClient();
  const [errors, setErrors] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (body: T) => api(`/masters/${path}${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", json: body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["masters"] });
      onDone();
    },
    onError: (err) => setErrors({ [err instanceof ApiError && err.field ? err.field : "form"]: err.message }),
  });

  const formProps = {
    noValidate: true,
    onInvalidCapture: (e: SyntheticEvent<HTMLFormElement>) => {
      const el = e.target as HTMLInputElement;
      // browsers say "match the requested format"; our title says which format
      const message = el.validity.patternMismatch && el.title ? el.title : el.validationMessage;
      setErrors((prev) => ({ ...prev, [el.name || el.id || "form"]: message }));
    },
  };

  // returns true when the browser checks pass and the request was sent
  function submit(e: SubmitEvent<HTMLFormElement>, body: () => T) {
    e.preventDefault();
    setErrors({});
    const blank = Array.from(e.currentTarget.elements).find((el) => el instanceof HTMLInputElement && el.required && el.value.length > 0 && !el.value.trim()) as HTMLInputElement | undefined;
    if (blank) {
      setErrors({ [blank.name || blank.id || "form"]: "Enter a value, not just spaces" });
      blank.focus();
      return false;
    }
    if (!e.currentTarget.checkValidity()) return;
    save.mutate(body());
  }

  return { errors, setErrors, save, formProps, submit };
}
