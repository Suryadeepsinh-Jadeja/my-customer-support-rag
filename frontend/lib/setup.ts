import type { User } from "@/types/api";

/** Account set-up steps the assistant benefits from (shown as a banner on the chat page). */
export function setupSteps(user: User) {
  const { profile, preferences } = user;
  return [
    { done: !!profile.home_airport, label: "Set your home airport", href: "/profile" },
    { done: !!profile.nationality, label: "Add your nationality", href: "/profile" },
    { done: !!profile.phone, label: "Add a phone number", href: "/profile" },
    {
      done: !!preferences.preferred_cabin || preferences.preferred_airlines.length > 0,
      label: "Choose your travel preferences",
      href: "/preferences",
    },
  ];
}
