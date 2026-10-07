import { Plane } from "lucide-react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-primary p-10 text-primary-foreground lg:flex">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <Plane className="size-5" aria-hidden />
          AI Travel Assistant
        </div>
        <div className="max-w-md space-y-3">
          <p className="text-3xl font-semibold leading-tight">
            Flights, hotels, cars, documents and travel support in one conversation.
          </p>
          <p className="text-primary-foreground/75">
            Ask in plain language. Nothing is booked, changed or cancelled without your
            confirmation.
          </p>
        </div>
        <p className="text-sm text-primary-foreground/60">
          Your documents stay private to your account.
        </p>
      </aside>
      <main className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">{children}</div>
      </main>
    </div>
  );
}
