"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormField } from "@/components/form-field";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { showApiError } from "@/lib/forms";
import type { CabinClass, Preferences, User } from "@/types/api";

const CABINS: { value: CabinClass; label: string }[] = [
  { value: "economy", label: "Economy" },
  { value: "premium_economy", label: "Premium economy" },
  { value: "business", label: "Business" },
  { value: "first", label: "First" },
];
const SEATS = [
  { value: "window", label: "Window" },
  { value: "aisle", label: "Aisle" },
  { value: "no_preference", label: "No preference" },
] as const;

const list = (pattern?: RegExp, message?: string) =>
  z
    .string()
    .transform((v) => v.split(",").map((s) => s.trim()).filter(Boolean))
    .refine((items) => items.length <= 10, "Up to 10 entries")
    .refine((items) => !pattern || items.every((i) => pattern.test(i)), message);

const schema = z.object({
  preferred_airports: list(/^[A-Za-z]{3}$/, "Use 3-letter airport codes, e.g. BOM, LHR").transform(
    (items) => items.map((i) => i.toUpperCase()),
  ),
  preferred_airlines: list(),
  preferred_cabin: z.enum(["economy", "premium_economy", "business", "first"]).nullable(),
  seat_preference: z.enum(["window", "aisle", "no_preference"]).nullable(),
  meal_preference: z.string().max(64).transform((v) => v.trim() || null),
  notes: z.string().max(1000).transform((v) => v.trim() || null),
  frequent_flyer_programs: z
    .array(
      z.object({
        airline: z.string().trim().min(2, "Enter the airline or programme"),
        number: z.string().trim(),
        // Masked number already on file; leaving `number` empty keeps it.
        number_masked: z.string(),
      }),
    )
    .max(10)
    .superRefine((programs, ctx) => {
      programs.forEach((p, i) => {
        if (!p.number && !p.number_masked) {
          ctx.addIssue({ code: "custom", path: [i, "number"], message: "Enter the membership number" });
        } else if (p.number && p.number.length < 3) {
          ctx.addIssue({ code: "custom", path: [i, "number"], message: "That number looks too short" });
        }
      });
    })
    .transform((programs) =>
      programs.map((p) => ({ airline: p.airline, number: p.number || undefined })),
    ),
});
type FormInput = z.input<typeof schema>;
type FormOutput = z.output<typeof schema>;

function toForm(p: Preferences): FormInput {
  return {
    preferred_airports: p.preferred_airports.join(", "),
    preferred_airlines: p.preferred_airlines.join(", "),
    preferred_cabin: p.preferred_cabin,
    seat_preference: p.seat_preference,
    meal_preference: p.meal_preference ?? "",
    notes: p.notes ?? "",
    frequent_flyer_programs: p.frequent_flyer_programs.map((f) => ({
      airline: f.airline,
      number: "",
      number_masked: f.number_masked,
    })),
  };
}

function PreferencesForm({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const form = useForm<FormInput, unknown, FormOutput>({
    resolver: zodResolver(schema),
    defaultValues: toForm(user.preferences),
  });
  const programs = useFieldArray({ control: form.control, name: "frequent_flyer_programs" });
  const { errors, isSubmitting, isDirty } = form.formState;

  async function onSubmit(values: FormOutput) {
    try {
      const updated = await api<User>("/users/me/preferences", { method: "PUT", body: values });
      queryClient.setQueryData(["me"], updated);
      form.reset(toForm(updated.preferences));
      toast.success("Preferences saved");
    } catch (error) {
      showApiError(error, form.setError, Object.keys(schema.shape));
    }
  }

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="grid gap-6" noValidate>
      <Card>
        <CardHeader>
          <CardTitle>Flights</CardTitle>
          <CardDescription>
            Used to rank results. Anything you ask for explicitly always takes priority.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-5">
          <FormField id="preferred_airports" label="Preferred airports"
            error={errors.preferred_airports?.message} hint="Comma-separated codes, e.g. BOM, LHR">
            <Input id="preferred_airports" placeholder="BOM, LHR" className="uppercase"
              aria-invalid={!!errors.preferred_airports} {...form.register("preferred_airports")} />
          </FormField>
          <FormField id="preferred_airlines" label="Preferred airlines"
            error={errors.preferred_airlines?.message} hint="Comma-separated, e.g. Lufthansa, SWISS">
            <Input id="preferred_airlines" placeholder="Lufthansa, SWISS"
              aria-invalid={!!errors.preferred_airlines} {...form.register("preferred_airlines")} />
          </FormField>
          <div className="grid gap-5 sm:grid-cols-2">
            <FormField id="preferred_cabin" label="Cabin class">
              <Controller
                control={form.control}
                name="preferred_cabin"
                render={({ field }) => (
                  <Select items={CABINS} value={field.value} onValueChange={(v) => field.onChange(v)}>
                    <SelectTrigger id="preferred_cabin" className="w-full">
                      <SelectValue placeholder="No preference" />
                    </SelectTrigger>
                    <SelectContent>
                      {CABINS.map((c) => (
                        <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </FormField>
            <FormField id="seat_preference" label="Seat">
              <Controller
                control={form.control}
                name="seat_preference"
                render={({ field }) => (
                  <Select items={SEATS} value={field.value} onValueChange={(v) => field.onChange(v)}>
                    <SelectTrigger id="seat_preference" className="w-full">
                      <SelectValue placeholder="No preference" />
                    </SelectTrigger>
                    <SelectContent>
                      {SEATS.map((s) => (
                        <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            </FormField>
          </div>
          <FormField id="meal_preference" label="Meal preference" error={errors.meal_preference?.message}>
            <Input id="meal_preference" placeholder="Vegetarian" {...form.register("meal_preference")} />
          </FormField>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Frequent flyer programmes</CardTitle>
          <CardDescription>
            Numbers are stored securely and only ever shown masked.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {programs.fields.length === 0 && (
            <p className="text-sm text-muted-foreground">No programmes added.</p>
          )}
          {programs.fields.map((field, index) => {
            const err = errors.frequent_flyer_programs?.[index];
            return (
              <div key={field.id} className="grid items-start gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <FormField id={`ff-airline-${index}`} label="Airline or programme" error={err?.airline?.message}>
                  <Input id={`ff-airline-${index}`} placeholder="Miles & More"
                    aria-invalid={!!err?.airline}
                    {...form.register(`frequent_flyer_programs.${index}.airline`)} />
                </FormField>
                <FormField id={`ff-number-${index}`} label="Membership number" error={err?.number?.message}
                  hint={field.number_masked ? `On file: ${field.number_masked}. Leave blank to keep.` : undefined}>
                  <Input id={`ff-number-${index}`} autoComplete="off"
                    placeholder={field.number_masked || "Number"} aria-invalid={!!err?.number}
                    {...form.register(`frequent_flyer_programs.${index}.number`)} />
                </FormField>
                <Button type="button" variant="ghost" size="icon" className="sm:mt-6"
                  aria-label={`Remove programme ${index + 1}`} onClick={() => programs.remove(index)}>
                  <Trash2 />
                </Button>
              </div>
            );
          })}
          {programs.fields.length < 10 && (
            <div>
              <Button type="button" variant="outline" size="sm"
                onClick={() => programs.append({ airline: "", number: "", number_masked: "" })}>
                <Plus aria-hidden />
                Add programme
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Anything else</CardTitle>
        </CardHeader>
        <CardContent>
          <FormField id="notes" label="Notes for the assistant" error={errors.notes?.message}
            hint="E.g. “I prefer morning flights” or “travelling with a toddler”.">
            <Textarea id="notes" rows={3} {...form.register("notes")} />
          </FormField>
        </CardContent>
      </Card>

      <div>
        <Button type="submit" disabled={isSubmitting || !isDirty}>
          {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
          Save preferences
        </Button>
      </div>
    </form>
  );
}

export default function PreferencesPage() {
  const { data: user } = useCurrentUser();
  return (
    <>
      <PageHeader title="Travel preferences"
        description="The assistant uses these when searching and recommending." />
      {user && <PreferencesForm user={user} />}
    </>
  );
}
