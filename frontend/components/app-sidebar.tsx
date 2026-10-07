"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CalendarCheck,
  FileText,
  Loader2,
  LogOut,
  Menu,
  MessageSquare,
  Plane,
  Plus,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useSignOut } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { Conversation, User } from "@/types/api";

const NAV = [
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/bookings", label: "Bookings", icon: CalendarCheck },
  { href: "/profile", label: "Profile", icon: UserRound },
  { href: "/preferences", label: "Travel preferences", icon: SlidersHorizontal },
  { href: "/settings", label: "Settings", icon: Settings },
];

function initials(name: string, email: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return email.slice(0, 2).toUpperCase();
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

const link =
  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";

function DeleteConversation({ id, title, isActive }: { id: string; title: string; isActive: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api(`/conversations/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.removeQueries({ queryKey: ["conversation", id] });
      // Only leave the page if the conversation being deleted is the one on screen.
      if (isActive) router.replace("/");
      toast.success("Conversation deleted.");
    },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <AlertDialog>
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="size-7 text-muted-foreground hover:text-destructive"
            aria-label={`Delete conversation: ${title}`}
          />
        }
      >
        <Trash2 className="size-3.5" />
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>
            The messages are removed. Your bookings and documents are not affected.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
            {remove.isPending && <Loader2 className="animate-spin" aria-hidden />}
            Delete
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function Conversations({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<Conversation[]>("/conversations"),
  });
  if (!conversations?.length) return null;
  return (
    <div className="grid min-h-0 gap-1">
      <p className="px-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Conversations
      </p>
      <ul className="grid gap-0.5 overflow-y-auto">
        {conversations.slice(0, 30).map((c) => {
          const active = pathname === `/chat/${c.id}`;
          return (
            // min-w-0: a grid item defaults to min-width:auto, so a long title would
            // force the row wider than the sidebar and push the button out of view.
            // The button is a sibling of the link, not a child: a link may not contain
            // another interactive element. It sits on top of the row's right edge.
            <li key={c.id} className="group relative min-w-0">
              <Link
                href={`/chat/${c.id}`}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(link, "py-1.5 pr-9", active && "bg-muted font-medium text-foreground")}
              >
                <MessageSquare className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{c.title}</span>
              </Link>
              <span
                className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100"
              >
                <DeleteConversation id={c.id} title={c.title} isActive={active} />
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function SidebarContent({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  const signOut = useSignOut();

  return (
    <div className="flex h-full flex-col gap-5 overflow-hidden p-4">
      <Link href="/" onClick={onNavigate} className="flex items-center gap-2 px-2 font-semibold">
        <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
          <Plane className="size-4" aria-hidden />
        </span>
        AI Travel Assistant
      </Link>

      <Button
        render={<Link href="/" onClick={onNavigate} />}
        nativeButton={false}
        variant={pathname === "/" ? "secondary" : "outline"}
        className="justify-start"
      >
        <Plus aria-hidden /> New conversation
      </Button>

      <nav aria-label="Main" className="grid gap-1">
        {[...NAV, ...(user.role === "admin" ? [{ href: "/admin", label: "Admin", icon: ShieldCheck }] : [])].map(({ href, label, icon: Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(link, active && "bg-muted font-medium text-foreground")}
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <Conversations onNavigate={onNavigate} />

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
