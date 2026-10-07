/**
 * Regression checks for Recipe Simulator demo-mode decision helpers.
 * Run: node --experimental-strip-types src/app/config/recipeDemoFlow.test.ts
 * (Node 22+) or via the npm script if configured.
 */
import assert from "node:assert/strict";
import {
  DEMO_CANDIDATE_COUNT,
  shouldUseDemoCreateCycle,
  shouldUseDemoGenerateRecipes,
} from "./recipeDemoFlow.ts";

// CASE A — no patent report
assert.equal(shouldUseDemoCreateCycle(true, null), true);
assert.equal(shouldUseDemoGenerateRecipes(true), true);

// CASE B — patent report selected must NOT block demo fixtures
assert.equal(shouldUseDemoCreateCycle(true, "some-research-run-uuid"), true);
assert.equal(shouldUseDemoGenerateRecipes(true), true);

// Production — demo off
assert.equal(shouldUseDemoCreateCycle(false, null), false);
assert.equal(shouldUseDemoCreateCycle(false, "run-id"), false);
assert.equal(shouldUseDemoGenerateRecipes(false), false);

assert.equal(DEMO_CANDIDATE_COUNT, 5);

console.log("recipeDemoFlow regression checks passed");
