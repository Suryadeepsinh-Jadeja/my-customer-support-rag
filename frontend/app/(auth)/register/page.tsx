"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { showApiError } from "@/lib/forms";
import type { AuthResponse } from "@/types/api";

const schema = z
  .object({
    full_name: z.string().trim().min(1, "Enter your name").max(200),
    email: z.email("Enter a valid email address"),
    password: z.string().min(10, "Use at least 10 characters").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, {
    path: ["confirm"],
    message: "Passwords don't match",
  });
type Values = z.infer<typeof schema>;

export default function RegisterPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit({ confirm: _confirm, ...values }: Values) {
    try {
      const result = await api<AuthResponse>("/auth/register", { method: "POST", body: values });
      queryClient.setQueryData(["me"], result.user);
      router.replace("/");
    } catch (error) {
      showApiError(error, form.setError, ["full_name", "email", "password"]);
    }
  }

  return (
    <div className="grid gap-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
        <p className="text-sm text-muted-foreground">
          One place for your bookings, documents and travel questions.
        </p>
      </div>
      <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
        <FormField id="full_name" label="Full name" error={errors.full_name?.message}
          hint="As it appears on your passport.">
          <Input id="full_name" autoComplete="name" autoFocus
            aria-invalid={!!errors.full_name} {...form.register("full_name")} />
        </FormField>
        <FormField id="email" label="Email" error={errors.email?.message}>
          <Input id="email" type="email" autoComplete="email"
            aria-invalid={!!errors.email} {...form.register("email")} />
        </FormField>
        <FormField id="password" label="Password" error={errors.password?.message}
          hint="At least 10 characters.">
          <Input id="password" type="password" autoComplete="new-password"
            aria-invalid={!!errors.password} {...form.register("password")} />
        </FormField>
        <FormField id="confirm" label="Confirm password" error={errors.confirm?.message}>
          <Input id="confirm" type="password" autoComplete="new-password"
            aria-invalid={!!errors.confirm} {...form.register("confirm")} />
        </FormField>
        <Button type="submit" size="lg" disabled={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
          Create account
        </Button>
      </form>
      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-foreground underline underline-offset-4">
          Sign in
        </Link>
      </p>
    </div>
  );
}
