/**
 * Central recipe DEMO MODE flag.
 * Enable with VITE_RECIPE_DEMO_MODE=true (e.g. frontend/.env.development).
 * When false/absent, real cycle + LLM generation paths are used.
 */
export function isRecipeDemoMode(): boolean {
  const raw = String(import.meta.env.VITE_RECIPE_DEMO_MODE ?? "").toLowerCase();
  return raw === "true" || raw === "1" || raw === "yes";
}
