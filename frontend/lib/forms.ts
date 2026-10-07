import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";

import { ApiError } from "@/lib/api";

/** Show an API error: field-level issues go next to their inputs, the rest as a toast. */
export function showApiError<T extends FieldValues>(
  error: unknown,
  setError?: UseFormSetError<T>,
  knownFields: readonly string[] = [],
) {
  if (error instanceof ApiError) {
    let placed = false;
    if (setError) {
      for (const { field, issue } of error.fields) {
        const name = field.split(".")[0];
        if (knownFields.includes(name)) {
          setError(name as Path<T>, { message: issue });
          placed = true;
        }
      }
    }
    if (!placed) toast.error(error.message);
    return;
  }
  toast.error("Something went wrong. Please try again.");
}
