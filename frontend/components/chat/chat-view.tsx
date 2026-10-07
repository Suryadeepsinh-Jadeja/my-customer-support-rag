"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, FileText, Loader2, Paperclip, Plane, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  BookingCardView,
  ConfirmationCardView,
  OfferCard,
  selectMessage,
  SourceChips,
} from "@/components/chat/cards";
import { RichText } from "@/components/chat/rich-text";
import { StatusBadge } from "@/components/documents/document-status";
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
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/hooks/use-current-user";
import { ApiError, api, uploadFile } from "@/lib/api";
import { ACCEPTED_TYPES, isInFlight, MAX_UPLOAD_MB } from "@/lib/documents";
import { setupSteps } from "@/lib/setup";
import { cn } from "@/lib/utils";
import type {
  ChatMessage,
  ChatResponse,
  ConfirmResponse,
  ConversationDetail,
  Offer,
  TravelDocument,
} from "@/types/api";

const SUGGESTIONS = [
  "What is my flight number?",
  "Are my documents in order for my trip?",
  "What is the baggage allowance?",
  "Find me a flight to London",
];

// ---------------------------------------------------------------- pieces

function SetupBanner() {
  const { data: user } = useCurrentUser();
  if (!user) return null;
  const todo = setupSteps(user).filter((s) => !s.done);
  if (todo.length === 0) return null;
  return (
    <div className="mb-4 rounded-xl border bg-muted/40 px-4 py-3 text-sm">
      <span className="font-medium">Finish setting up your account</span>
      <span className="text-muted-foreground"> so you don&apos;t have to repeat yourself: </span>
      {todo.map((step, i) => (
        <span key={step.label}>
          {i > 0 && ", "}
          <Link href={step.href} className="underline underline-offset-2">
            {step.label.toLowerCase()}
          </Link>
        </span>
      ))}
      .
    </div>
  );
}

function UploadedDocument({ initial }: { initial: TravelDocument }) {
  const { data: doc = initial } = useQuery({
    queryKey: ["document-status", initial.id],
    queryFn: () => api<TravelDocument>(`/documents/${initial.id}`),
    initialData: initial,
    refetchInterval: (q) => (q.state.data && isInFlight(q.state.data) ? 2000 : false),
  });
  return (
    <div className="ml-auto flex w-fit max-w-full items-center gap-3 rounded-xl border bg-card px-3 py-2 text-sm">
      <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <Link href={`/documents/${doc.id}`} className="truncate font-medium hover:underline">
        {doc.filename}
      </Link>
      <StatusBadge status={doc.status} />
    </div>
  );
}

function Message({
  message,
  last,
  busy,
  onSelect,
  onConfirmed,
}: {
  message: ChatMessage;
  last: boolean;
  busy: boolean;
  onSelect: (offer: Offer) => void;
  onConfirmed: (result: ConfirmResponse | null) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-primary-foreground">
        {message.text}
      </div>
    );
  }
  return (
    <div className="grid max-w-full grid-cols-1 gap-3">
      <div
        className={cn(
          "rounded-2xl rounded-bl-sm bg-muted px-4 py-3",
          message.type === "ERROR" && "bg-destructive/10 text-destructive",
        )}
      >
        <RichText text={message.text} />
      </div>
      <SourceChips sources={message.sources} />
      {message.cards.length > 0 && (
        <div className="grid grid-cols-1 gap-2">
          {message.cards.map((card, i) => {
            if (card.type === "booking") return <BookingCardView key={i} booking={card} />;
            if (card.type === "confirmation") {
              return (
                <ConfirmationCardView
                  key={card.confirmation_id}
                  card={card}
                  actionable={last && new Date(card.expires_at) > new Date()}
                  onDone={onConfirmed}
                />
              );
            }
            return <OfferCard key={i} offer={card} onSelect={onSelect} disabled={busy} />;
          })}
        </div>
      )}
    </div>
  );
}

function DeleteConversation({ id }: { id: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => api(`/conversations/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.removeQueries({ queryKey: ["conversation", id] });
      router.replace("/");
      toast.success("Conversation deleted.");
    },
    onError: (error) => toast.error(error.message),
  });
  return (
    <AlertDialog>
      <AlertDialogTrigger render={<Button variant="ghost" size="icon" aria-label="Delete conversation" />}>
        <Trash2 />
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

// ------------------------------------------------------------------ view

export function ChatView({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null); // optimistic user message
  const [uploads, setUploads] = useState<TravelDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api<ConversationDetail>(`/conversations/${conversationId}`),
    enabled: !!conversationId,
  });
  const messages = conversation.data?.messages ?? [];

  const send = useMutation({
    mutationFn: (message: string) =>
      api<ChatResponse>("/chat", {
        method: "POST",
        body: { conversation_id: conversationId ?? null, message },
      }),
    onMutate: (message) => {
      setPending(message);
      setText("");
    },
    onSuccess: async (response, message) => {
      if (!conversationId) {
        // Seed the new conversation's cache so the page switch shows it instantly.
        const now = new Date().toISOString();
        queryClient.setQueryData<ConversationDetail>(["conversation", response.conversation_id], {
          id: response.conversation_id,
          title: message.slice(0, 60),
          active_agent: response.agent,
          created_at: now,
          updated_at: now,
          messages: [
            { id: -2, role: "user", text: message, type: null, sources: [], cards: [], agent: null, created_at: now },
            { id: -1, role: "assistant", text: response.message.text, type: response.message.type,
              sources: response.message.sources, cards: response.message.cards,
              agent: response.agent, created_at: now },
          ],
        });
        router.replace(`/chat/${response.conversation_id}`);
      } else {
        await queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      }
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      setPending(null);
    },
    onError: (error, message) => {
      setPending(null);
      setText(message);
      toast.error(error.message);
    },
  });

  function submit(message: string) {
    const trimmed = message.trim();
    if (trimmed && !send.isPending) send.mutate(trimmed);
  }

  async function onConfirmed(result: ConfirmResponse | null) {
    queryClient.invalidateQueries({ queryKey: ["bookings"] });
    if (conversationId) {
      await queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    }
    if (result?.booking) queryClient.invalidateQueries({ queryKey: ["booking", result.booking.id] });
  }

  async function upload(files: FileList | null) {
    const file = files?.[0];
    if (fileRef.current) fileRef.current.value = "";
    if (!file) return;
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      toast.error(`${file.name} is larger than ${MAX_UPLOAD_MB} MB.`);
      return;
    }
    setUploading(true);
    try {
      const doc = await uploadFile<TravelDocument>("/documents", file);
      setUploads((u) => [...u, doc]);
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : `${file.name} failed to upload.`);
    } finally {
      setUploading(false);
    }
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pending, uploads.length]);

  const empty = !conversationId && !pending;

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col md:min-h-[calc(100dvh-4rem)]">
      <header className="mb-4 flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">AI Travel Assistant</h1>
          <p className="text-muted-foreground">Flights, hotels, cars, documents and travel support.</p>
        </div>
        {conversationId && <DeleteConversation id={conversationId} />}
      </header>

      {!conversationId && <SetupBanner />}

      <section aria-label="Conversation" aria-live="polite" className="flex flex-1 flex-col gap-5 pb-4">
        {empty && (
          <div className="grid flex-1 place-items-center py-10 text-center">
            <div className="grid max-w-md gap-4">
              <span className="mx-auto grid size-12 place-items-center rounded-2xl bg-primary text-primary-foreground">
                <Plane className="size-6" aria-hidden />
              </span>
              <p className="text-muted-foreground">
                Ask about your trips, documents or travel policies, or search and book flights,
                hotels, cars and excursions.
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <Button key={s} variant="outline" size="sm" onClick={() => submit(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        )}

        {conversation.isPending && conversationId && (
          <div className="grid gap-3">
            <Skeleton className="ml-auto h-10 w-2/3" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {conversation.error && <p className="text-sm text-destructive">{conversation.error.message}</p>}

        {messages.map((m, i) => (
          <Message
            key={m.id}
            message={m}
            last={i === messages.length - 1 && !pending}
            busy={send.isPending}
            onSelect={(offer) => submit(selectMessage(offer))}
            onConfirmed={onConfirmed}
          />
        ))}
        {pending && (
          <>
            <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-primary-foreground">
              {pending}
            </div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Thinking…
            </div>
          </>
        )}
        {uploads.map((doc) => <UploadedDocument key={doc.id} initial={doc} />)}
        <div ref={endRef} />
      </section>

      <form
        className="sticky bottom-0 -mx-4 border-t bg-background/95 px-4 pb-4 pt-3 backdrop-blur md:-mx-10 md:px-10"
        onSubmit={(e) => {
          e.preventDefault();
          submit(text);
        }}
      >
        <div className="flex items-end gap-2 rounded-2xl border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40">
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED_TYPES}
            className="hidden"
            onChange={(e) => upload(e.target.files)}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Upload a travel document"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? <Loader2 className="animate-spin" /> : <Paperclip />}
          </Button>
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(text);
              }
            }}
            placeholder="Ask about your travel plans..."
            aria-label="Message"
            rows={1}
            maxLength={4000}
            className="max-h-40 min-h-9 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          />
          <Button type="submit" size="icon" aria-label="Send" disabled={!text.trim() || send.isPending}>
            {send.isPending ? <Loader2 className="animate-spin" /> : <ArrowUp />}
          </Button>
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Bookings are only made after you press Confirm. Results marked “Test booking” are not real.
        </p>
      </form>
    </div>
  );
}
