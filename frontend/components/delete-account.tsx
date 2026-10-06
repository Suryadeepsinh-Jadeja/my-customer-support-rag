"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api } from "@/lib/api";

export function DeleteAccount() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function remove(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api("/users/me", { method: "DELETE", body: { password } });
      queryClient.clear();
      toast.success("Your account and data have been deleted.");
      router.replace("/login");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <AlertDialog onOpenChange={() => { setPassword(""); setError(null); }}>
      <AlertDialogTrigger render={<Button variant="destructive" />}>
        <Trash2 aria-hidden /> Delete account
      </AlertDialogTrigger>
      <AlertDialogContent>
        <form onSubmit={remove} className="grid gap-4">
          <AlertDialogHeader>
            <AlertDialogTitle>Delete your account?</AlertDialogTitle>
            <AlertDialogDescription>
              Your documents, conversations, bookings history and profile are permanently
              deleted. Cancel any upcoming bookings first. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="delete-password">Password</Label>
            <Input
              id="delete-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-invalid={!!error}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <Button type="submit" variant="destructive" disabled={!password || pending}>
              {pending && <Loader2 className="animate-spin" aria-hidden />}
              Delete permanently
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}
