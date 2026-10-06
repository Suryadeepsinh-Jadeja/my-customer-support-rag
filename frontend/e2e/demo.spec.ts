import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

// The §84 demo, end to end in a real browser against the real API (with the rule-based
// fake LLM and the mock booking provider, see e2e/start-backend.mjs).

const PASSWORD = "e2e correct horse battery";
const FIXTURES = path.join(__dirname, "fixtures");

function inDays(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return {
    label: `${d.toLocaleString("en-US", { month: "long" })} ${d.getDate()}`,
    iso: d.toISOString().slice(0, 10),
  };
}

async function ask(page: Page, question: string) {
  await page.getByLabel("Message").fill(question);
  await page.keyboard.press("Enter");
}

test("register, upload, ask, book, confirm, cancel", async ({ page }) => {
  // 1. Register.
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Asha Mehta");
  await page.getByLabel("Email").fill(`e2e.${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Confirm password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "AI Travel Assistant" })).toBeVisible();

  await page.goto("/profile");
  await page.getByLabel("Home airport").fill("BOM");
  const save = page.getByRole("button", { name: "Save profile" });
  await save.click();
  await expect(save).toBeDisabled();

  // 2-3. Upload passport, flight ticket and hotel booking; see them processed.
  await page.goto("/documents");
  await page.locator('input[type="file"]').setInputFiles(
    ["passport.txt", "ticket.txt", "hotel.txt"].map((f) => path.join(FIXTURES, f)),
  );
  await expect(page.getByText("Ready for AI")).toHaveCount(3, { timeout: 60_000 });

  // 4-6. Questions answered from the documents and the policies, with sources.
  await page.goto("/");
  await ask(page, "What is my flight number?");
  await expect(page.getByText(/your flight number is LX154/)).toBeVisible();
  await expect(page.getByText(/Based on your ticket\.txt/).first()).toBeVisible();
  await expect(page).toHaveURL(/\/chat\//);
  const conversation = page.url();

  await ask(page, "What time do I arrive?");
  await expect(page.getByText(/you arrive at 07:10 in ZRH/)).toBeVisible();

  await ask(page, "What is my baggage allowance?");
  await expect(page.getByText(/baggage allowance is 1 x 23 kg/)).toBeVisible();
  await expect(page.getByText(/Source: Baggage Policy/).first()).toBeVisible();

  // 7. Book a flight: results, select, confirm.
  const day = inDays(30);
  await ask(page, `Book my flight to London for ${day.label}`);
  const selects = page.getByRole("button", { name: /^Select / });
  await expect(selects).toHaveCount(5);
  await expect(page.getByText(/BOM \d\d:\d\d → LHR/).first()).toBeVisible();
  await selects.first().click();

  await page.getByRole("button", { name: "Review & confirm" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Confirm booking");
  await expect(dialog).toContainText("Nothing is booked until you confirm");
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/Booked \(test booking\)/).first()).toBeVisible();

  await page.getByRole("link", { name: "Bookings" }).click();
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible();
  await expect(page.getByText("Test booking").first()).toBeVisible();

  // 8. Cancel: the provider's refund quote, confirm, cancelled.
  await page.goto(conversation);
  await ask(page, "Cancel my flight");
  await expect(page.getByText(/refunds .* under the provider's terms/)).toBeVisible();
  await page.getByRole("button", { name: "Review & confirm" }).click();
  await expect(dialog).toContainText("Cancel booking?");
  await expect(dialog).toContainText("Refund");
  await dialog.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/^Cancelled .*Refund:/).first()).toBeVisible();

  await page.goto("/bookings");
  await page.getByRole("tab", { name: /Cancelled/ }).click();
  await expect(page.getByText("Cancelled", { exact: true })).toBeVisible();
});
