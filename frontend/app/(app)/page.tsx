"use client";

import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useCurrentUser } from "@/hooks/use-current-user";
import type { User } from "@/types/api";

function setupSteps(user: User) {
  const { profile, preferences } = user;
  return [
    { done: true, label: "Create your account", href: "/settings" },
    { done: !!profile.home_airport, label: "Set your home airport", href: "/profile" },
    { done: !!profile.nationality, label: "Add your nationality", href: "/profile" },
    {
      done: !!preferences.preferred_cabin || preferences.preferred_airlines.length > 0,
      label: "Choose your travel preferences",
      href: "/preferences",
    },
  ];
}

export default function HomePage() {
  const { data: user } = useCurrentUser();
  if (!user) return null;

  const firstName = user.profile.full_name.split(" ")[0] || "there";
  const steps = setupSteps(user);
  const remaining = steps.filter((s) => !s.done).length;

  return (
    <>
      <PageHeader
        title={`Hello, ${firstName}`}
        description="Flights, hotels, cars, documents and travel support."
      />
      <Card>
        <CardHeader>
          <CardTitle>Set up your account</CardTitle>
          <CardDescription>
            {remaining === 0
              ? "You're all set. The assistant will use these details to tailor results."
              : `${remaining} step${remaining > 1 ? "s" : ""} left. The assistant uses these details so you don't have to repeat them.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-1">
            {steps.map((step) => (
              <li key={step.label}>
                <Link
                  href={step.href}
                  className="flex items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-muted"
                >
                  {step.done ? (
                    <CheckCircle2 className="size-4 text-emerald-600" aria-label="Done" />
                  ) : (
                    <Circle className="size-4 text-muted-foreground" aria-label="To do" />
                  )}
                  <span className={step.done ? "text-muted-foreground line-through" : ""}>
                    {step.label}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
