"use client";

import { Home, LogOut, Menu, Plane, Settings, SlidersHorizontal, UserRound, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useSignOut } from "@/hooks/use-current-user";
import { cn } from "@/lib/utils";
import type { User } from "@/types/api";

// Conversations, Documents and Bookings join this list as their phases land.
const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/profile", label: "Profile", icon: UserRound },
  { href: "/preferences", label: "Travel preferences", icon: SlidersHorizontal },
  { href: "/settings", label: "Settings", icon: Settings },
];

function initials(name: string, email: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return email.slice(0, 2).toUpperCase();
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function SidebarContent({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const signOut = useSignOut();

  return (
    <div className="flex h-full flex-col gap-6 p-4">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2 px-2 font-semibold">
        <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
          <Plane className="size-4" aria-hidden />
        </span>
        AI Travel Assistant
      </Link>

      <nav aria-label="Main" className="grid gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                active && "bg-muted font-medium text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto grid gap-3 border-t pt-4">
        <div className="flex items-center gap-3 px-2">
          <Avatar>
            <AvatarFallback>{initials(user.profile.full_name, user.email)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0 text-sm">
            <p className="truncate font-medium">{user.profile.full_name || "Traveller"}</p>
            <p className="truncate text-muted-foreground">{user.email}</p>
          </div>
        </div>
        <Button variant="ghost" className="justify-start" onClick={() => signOut()}>
          <LogOut aria-hidden />
          Sign out
        </Button>
      </div>
    </div>
  );
}

export function AppSidebar({ user }: { user: User }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      {/* Desktop */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r bg-sidebar md:block">
        <SidebarContent user={user} />
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background/95 px-4 py-2 backdrop-blur md:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setOpen(true)}>
          <Menu />
        </Button>
        <span className="font-semibold">AI Travel Assistant</span>
      </div>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-sidebar shadow-xl">
            <Button
              variant="ghost"
              size="icon"
              aria-label="Close menu"
              className="absolute right-2 top-2"
              onClick={() => setOpen(false)}
            >
              <X />
            </Button>
            <SidebarContent user={user} onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}
