"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { showApiError } from "@/lib/forms";
import type { User } from "@/types/api";

const optional = (schema: z.ZodString) =>
  z.union([z.literal(""), schema]).transform((v) => (v === "" ? null : v));

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter your name").max(200),
  phone: optional(z.string().regex(/^\+?[0-9 ()-]{6,20}$/, "Enter a valid phone number")),
  nationality: optional(z.string().regex(/^[A-Za-z]{2}$/, "Use the 2-letter country code, e.g. IN")),
  home_airport: optional(z.string().regex(/^[A-Za-z]{3}$/, "Use the 3-letter airport code, e.g. BOM")),
});
type Input_ = z.input<typeof schema>;
type Output = z.output<typeof schema>;

function ProfileForm({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const form = useForm<Input_, unknown, Output>({
    resolver: zodResolver(schema),
    defaultValues: {
      full_name: user.profile.full_name,
      phone: user.profile.phone ?? "",
      nationality: user.profile.nationality ?? "",
      home_airport: user.profile.home_airport ?? "",
    },
  });
  const { errors, isSubmitting, isDirty } = form.formState;

  async function onSubmit(values: Output) {
    try {
      const updated = await api<User>("/users/me/profile", { method: "PATCH", body: values });
      queryClient.setQueryData(["me"], updated);
      form.reset({
        full_name: updated.profile.full_name,
        phone: updated.profile.phone ?? "",
        nationality: updated.profile.nationality ?? "",
        home_airport: updated.profile.home_airport ?? "",
      });
      toast.success("Profile saved");
    } catch (error) {
      showApiError(error, form.setError, Object.keys(schema.shape));
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-5" noValidate>
      <FormField id="full_name" label="Full name" error={errors.full_name?.message}
        hint="As it appears on your passport.">
        <Input id="full_name" autoComplete="name" aria-invalid={!!errors.full_name}
          {...form.register("full_name")} />
      </FormField>
      <FormField id="email" label="Email">
        <Input id="email" value={user.email} disabled readOnly />
      </FormField>
      <FormField id="phone" label="Phone" error={errors.phone?.message}>
        <Input id="phone" type="tel" autoComplete="tel" placeholder="+91 98765 43210"
          aria-invalid={!!errors.phone} {...form.register("phone")} />
      </FormField>
      <div className="grid gap-5 sm:grid-cols-2">
        <FormField id="nationality" label="Nationality" error={errors.nationality?.message}
          hint="2-letter country code.">
          <Input id="nationality" maxLength={2} placeholder="IN" className="uppercase"
            aria-invalid={!!errors.nationality} {...form.register("nationality")} />
        </FormField>
        <FormField id="home_airport" label="Home airport" error={errors.home_airport?.message}
          hint="Used as the default departure airport.">
          <Input id="home_airport" maxLength={3} placeholder="BOM" className="uppercase"
            aria-invalid={!!errors.home_airport} {...form.register("home_airport")} />
        </FormField>
      </div>
      <div>
        <Button type="submit" disabled={isSubmitting || !isDirty}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
          Save profile
        </Button>
      </div>
    </form>
  );
}

export default function ProfilePage() {
  const { data: user } = useCurrentUser();
  return (
    <>
      <PageHeader title="Profile" description="Details the assistant can reuse when booking for you." />
      <Card>
        <CardContent>{user && <ProfileForm user={user} />}</CardContent>
      </Card>
    </>
  );
}
