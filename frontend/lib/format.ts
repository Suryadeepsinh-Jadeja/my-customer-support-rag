// Display helpers. Flight times from providers are local airport times without a
// timezone ("2026-10-20T14:42"), so they're formatted from the string, not converted.

export function money(amount: number, currency: string) {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function day(isoDate: string | null | undefined) {
  if (!isoDate) return "";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function time(localIso: string) {
  return localIso.slice(11, 16);
}

export function duration(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

export function dateRange(start: string | null, end: string | null) {
  if (!start) return "";
  return end && end !== start ? `${day(start)} – ${day(end)}` : day(start);
}
