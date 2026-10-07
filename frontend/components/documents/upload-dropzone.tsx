"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Progress } from "@/components/ui/progress";
import { ApiError, uploadFile } from "@/lib/api";
import { ACCEPTED_TYPES, MAX_UPLOAD_MB } from "@/lib/documents";
import { cn } from "@/lib/utils";
import type { TravelDocument } from "@/types/api";

type Upload = { id: number; name: string; progress: number };

export function UploadDropzone() {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);

  async function uploadOne(file: File) {
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`${file.name} is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    const id = Date.now() + Math.random();
    setUploads((u) => [...u, { id, name: file.name, progress: 0 }]);
    try {
      const doc = await uploadFile<TravelDocument>("/documents", file, (progress) =>
        setUploads((u) => u.map((x) => (x.id === id ? { ...x, progress } : x))),
      );
      queryClient.setQueryData<TravelDocument[]>(["documents", ""], (list) =>
        list ? [doc, ...list] : list,
      );
      queryClient.invalidateQueries({ queryKey: ["documents"] });
      toast.success(`${doc.filename} uploaded. Processing has started.`);
    } catch (error) {
      toast.error(
        error instanceof ApiError ? `${file.name}: ${error.message}` : `${file.name} failed to upload.`,
      );
    } finally {
      setUploads((u) => u.filter((x) => x.id !== id));
    }
  }

  function handleFiles(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((file) => void uploadOne(file));
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="grid gap-3">
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors focus-within:border-primary focus-within:ring-3 focus-within:ring-ring/40 hover:bg-muted/50",
          dragging && "border-primary bg-primary/5",
        )}
      >
        <span className="grid size-10 place-items-center rounded-full bg-primary/10 text-primary">
          <FileUp className="size-5" aria-hidden />
        </span>
        <span className="font-medium">Drop files here or click to upload</span>
        <span className="text-sm text-muted-foreground">
          Passports, visas, tickets, boarding passes, hotel and car bookings, insurance.
          PDF, Word, text, PNG or JPEG up to {MAX_UPLOAD_MB} MB.
        </span>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_TYPES}
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </label>

      {uploads.length > 0 && (
        <ul className="grid gap-2" aria-live="polite">
          {uploads.map((u) => (
            <li key={u.id} className="grid gap-1.5 rounded-lg border p-3 text-sm">
              <div className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{u.name}</span>
                <span className="tabular-nums text-muted-foreground">{u.progress}%</span>
              </div>
              <Progress value={u.progress} aria-label={`Uploading ${u.name}`} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
