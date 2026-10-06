"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, LogOut } from "lucide-react";
import { useTheme } from "next-themes";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useSignOut } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { showApiError } from "@/lib/forms";

const schema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(10, "Use at least 10 characters").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords don't match" });
type Values = z.infer<typeof schema>;

function ChangePassword() {
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const { errors, isSubmitting } = form.formState;

  async function onSubmit({ confirm: _confirm, ...values }: Values) {
    try {
      await api("/users/me/password", { method: "POST", body: values });
      form.reset({ current_password: "", new_password: "", confirm: "" });
      toast.success("Password changed. Other devices have been signed out.");
    } catch (error) {
      showApiError(error, form.setError, ["current_password", "new_password"]);
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-4" noValidate>
      <FormField id="current_password" label="Current password" error={errors.current_password?.message}>
        <Input id="current_password" type="password" autoComplete="current-password"
          aria-invalid={!!errors.current_password} {...form.register("current_password")} />
      </FormField>
      <FormField id="new_password" label="New password" error={errors.new_password?.message}
        hint="At least 10 characters.">
        <Input id="new_password" type="password" autoComplete="new-password"
          aria-invalid={!!errors.new_password} {...form.register("new_password")} />
      </FormField>
      <FormField id="confirm" label="Confirm new password" error={errors.confirm?.message}>
        <Input id="confirm" type="password" autoComplete="new-password"
          aria-invalid={!!errors.confirm} {...form.register("confirm")} />
      </FormField>
      <div>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
          Change password
        </Button>
      </div>
    </form>
  );
}

export default function SettingsPage() {
  const signOut = useSignOut();
  const { theme, setTheme } = useTheme();

  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Password</CardTitle>
          </CardHeader>
          <CardContent>
            <ChangePassword />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {(["system", "light", "dark"] as const).map((t) => (
              <Button key={t} variant={theme === t ? "secondary" : "outline"} size="sm"
                aria-pressed={theme === t} onClick={() => setTheme(t)}>
                {t[0].toUpperCase() + t.slice(1)}
              </Button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sessions</CardTitle>
            <CardDescription>
              Sign out of every browser and device where you&apos;re signed in, including this one.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="destructive" onClick={() => signOut(true)}>
              <LogOut aria-hidden />
              Sign out everywhere
            </Button>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
