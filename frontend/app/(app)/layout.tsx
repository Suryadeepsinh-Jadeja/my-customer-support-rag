"use client";

import { Loader2 } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/hooks/use-current-user";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { data: user, error, refetch } = useCurrentUser();

  if (!user) {
    return (
      <div className="grid min-h-screen place-items-center p-4">
        {error && !("status" in error && error.status === 401) ? (
          <div className="grid gap-3 text-center">
            <p className="text-muted-foreground">{error.message}</p>
            <Button variant="outline" onClick={() => refetch()}>Try again</Button>
          </div>
        ) : (
          <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
        )}
      </div>
    );
  }

  return (
    <div className="min-h-screen md:flex">
      <AppSidebar user={user} />
      <main className="min-w-0 flex-1 px-4 py-8 md:px-10">
        <div className="mx-auto max-w-3xl">{children}</div>
      </main>
    </div>
  );
}
