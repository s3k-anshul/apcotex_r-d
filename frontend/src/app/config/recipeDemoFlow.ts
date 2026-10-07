/**
 * Pure helpers for Recipe Simulator DEMO MODE decisions.
 * Kept free of Vite/React imports so regression tests can run in Node.
 *
 * Contract:
 * - When demoMode is true, fixtures are used regardless of research_run_id.
 * - generateRecipes must not depend on a stale in-memory cycle object.
 */

/** Demo fixtures for Step 2 whenever demo mode is on (report optional). */
export function shouldUseDemoCreateCycle(
  demoMode: boolean,
  _researchRunId?: string | null
): boolean {
  return demoMode === true;
}

/**
 * Demo generate path must key off the env flag alone.
 * Relying on isDemoEntity(cycle) after createCycle is unsafe (stale closure).
 */
export function shouldUseDemoGenerateRecipes(demoMode: boolean): boolean {
  return demoMode === true;
}

/** Expected fixture count for Step 2. */
export const DEMO_CANDIDATE_COUNT = 5;
