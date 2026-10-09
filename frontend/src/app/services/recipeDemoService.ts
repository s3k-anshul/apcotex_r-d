/**
 * Development-only recipe fixtures.
 * Used only when VITE_RECIPE_DEMO_MODE=true.
 * Do NOT import this into patent/report code.
 */
import { isRecipeDemoMode } from "../config/recipeDemoMode";
import * as api from "./researchApi";

/** Stored in SavedRecipe.notes for idempotent seeding. */
export const DEMO_SEED_MARKER = "__apcotex_demo_seed__";
export const DEMO_RECIPE_NAME = "Demo NBR Recipe";

const DEMO_CYCLE_ID = "00000000-demo-cycle-0000-000000000001";

function demoParams(overrides: Record<string, string> = {}) {
  const base: Record<string, { value: string; unit: string }> = {
    "BD/ACN Ratio": { value: "74/26", unit: "" },
    Method: { value: "Cold Emulsion", unit: "" },
    Temperature: { value: "10", unit: "°C" },
    Water: { value: "185", unit: "phr" },
    Emulsifier: { value: "Potassium oleate 3.0", unit: "phr" },
    Initiator: { value: "KPS 0.35", unit: "phr" },
    "Chain Transfer Agent": { value: "t-DDM 0.45", unit: "phr" },
    Coagulant: { value: "CaCl2", unit: "" },
    Conversion: { value: "88", unit: "%" },
    "Reaction Time": { value: "8", unit: "h" },
  };
  Object.entries(overrides).forEach(([k, v]) => {
    if (base[k]) base[k] = { ...base[k], value: v };
  });
  return Object.entries(base).map(([name, { value, unit }]) => ({
    name,
    value,
    unit,
    source: "inferred",
    patent_ref: null,
  }));
}

function buildRecipeData(
  rank: number,
  compoundName = "Demo Polymer",
  overrides: Record<string, string> = {},
  options?: {
    processType?: string;
    tempRange?: { min: number; max: number; unit: string } | string;
    catalystSystem?: any;
    activatorSystem?: any;
    coagulationSystem?: any;
    targetAnalysis?: any;
  }
) {
  const water = overrides.Water || String(170 + rank * 5);
  const temp = overrides.Temperature || String(5 + rank * 2);
  const params = demoParams({
    Water: water,
    Temperature: temp,
    ...overrides,
  });

  const stages = [
    {
      stage_name: "Reactor Charge",
      is_applicable: true,
      parameters: [
        { name: "Initial Water", value: `${water} phr`, unit: "phr", source: "inferred", patent_ref: null },
        { name: "Initial Surfactant", value: "0.5 phr", unit: "phr", source: "inferred", patent_ref: null },
      ],
    },
    {
      stage_name: "Emulsifier Solution",
      is_applicable: true,
      parameters: [
        { name: "Emulsifier (Potassium oleate)", value: "3.0 phr", unit: "phr", source: "inferred", patent_ref: null },
        { name: "DI Water", value: "30 phr", unit: "phr", source: "inferred", patent_ref: null },
      ],
    },
    {
      stage_name: "Catalyst Solution",
      is_applicable: true,
      parameters: [
        { name: "Initiator (KPS)", value: "0.35 phr", unit: "phr", source: "inferred", patent_ref: null },
        { name: "Activator Solution", value: "0.10 phr", unit: "phr", source: "inferred", patent_ref: null },
      ],
    },
    {
      stage_name: "Monomer Mix",
      is_applicable: true,
      parameters: [
        { name: "Monomer Feed Ratio", value: overrides["BD/ACN Ratio"] || "74/26", unit: "wt%", source: "patent", patent_ref: "US20250075019A1" },
        { name: "Chain Transfer Agent (t-DDM)", value: "0.45 phr", unit: "phr", source: "patent", patent_ref: "US20250075019A1" },
      ],
    },
    {
      stage_name: "Chemical Stripping",
      is_applicable: true,
      parameters: [
        { name: "Shortstop Agent (DEHA)", value: "0.15 phr", unit: "phr", source: "ai_generated", patent_ref: null },
        { name: "Vacuum Stripping Temperature", value: "65 °C", unit: "°C", source: "ai_generated", patent_ref: null },
      ],
    },
    {
      stage_name: "Post Addition",
      is_applicable: true,
      parameters: [
        { name: "Antioxidant", value: "0.50 phr", unit: "phr", source: "inferred", patent_ref: null },
        { name: "Defoamer", value: "0.05 phr", unit: "phr", source: "inferred", patent_ref: null },
      ],
    },
  ];

  const process_type = options?.processType || "Batch";
  const temp_range = options?.tempRange || { min: Number(temp) - 1, max: Number(temp) + 1, unit: "°C" };
  const temp_range_str = typeof temp_range === "string" ? temp_range : `${temp_range.min}–${temp_range.max} ${temp_range.unit}`;

  const process_conditions = {
    process_type,
    temperature_range: temp_range,
    reaction_time: { value: "8", unit: "h" },
    feeding_hours: { monomer: "6", emulsifier: "4", catalyst: "2" },
    temperature_profile: [
      { stage: "Initial Charge", value: `${temp}`, unit: "°C" },
      { stage: "Polymerization", value: `${temp}`, unit: "°C" },
      { stage: "Chemical Stripping", value: "65", unit: "°C" },
    ],
  };

  const catalyst_system = options?.catalystSystem || {
    primary_catalyst: "Potassium persulfate (KPS)",
    primary_dosage: "0.35 phr",
    primary_dosage_phr: 0.35,
    alternatives: [
      {
        catalyst: "Ammonium persulfate",
        dosage: "0.30 phr",
        rationale: "Validated water-soluble thermal initiator alternative",
      },
    ],
  };

  const activator_system = options?.activatorSystem || {
    applicable: true,
    is_applicable: true,
    name: "Sodium formaldehyde sulfoxylate (SFS)",
    activator_name: "Sodium formaldehyde sulfoxylate (SFS)",
    dosage: "0.10 phr",
    dosage_phr: 0.10,
    stage: "Catalyst Solution / Redox Activation",
    addition_stage: "Catalyst Solution / Redox Activation",
    alternatives: [],
  };

  const coagulation_system = options?.coagulationSystem || {
    applicable: true,
    is_applicable: true,
    coagulant: "Calcium chloride",
    coagulant_name: "Calcium chloride",
    dosage: "2.0 phr",
    dosage_phr: 2.0,
    process_conditions: "Crumb isolation at 60°C",
    notes: "Aqueous electrolyte precipitation",
  };

  return {
    name: `Demo Recipe ${rank}`,
    compound: compoundName,
    process_type,
    temperature_range: temp_range_str,
    bd_acn_ratio: overrides["BD/ACN Ratio"] || "74/26",
    polymerization_method: "Cold Emulsion",
    temperature: `${temp}°C`,
    water: `${water} phr`,
    emulsifier: "Potassium oleate 3.0 phr",
    initiator: "KPS 0.35 phr",
    chain_transfer_agent: "t-DDM 0.45 phr",
    coagulant: "CaCl2",
    conversion: "88%",
    reaction_time: "8 h",
    expected_bound_acn: "26%",
    expected_mooney: "45",
    parameters: params,
    stages,
    process_conditions,
    catalyst_system,
    activator_system,
    coagulation_system,
    target_analysis: options?.targetAnalysis,
    patent_references: ["US20250075019A1"],
    rationale: `[DEMO] Development fixture recipe ${rank} for ${compoundName}.`,
    notes: `[DEMO] Fixture for UI workflow testing.`,
    __demo: true,
  };
}

/** Exactly 5 demo candidates matching API RecipeCandidate shape. */
export function getDemoRecipeCandidates(compoundName = "Demo Polymer") {
  return [1, 2, 3, 4, 5].map((rank) => {
    const recipe_data = buildRecipeData(rank, compoundName);
    return {
      id: `00000000-demo-cand-0000-00000000000${rank}`,
      cycle_id: DEMO_CYCLE_ID,
      rank,
      name: `Demo Recipe ${rank}`,
      recipe_data,
      patent_references: ["US20250075019A1"],
      evidence_coverage_score: 40 + rank * 8,
      is_selected: false,
      created_at: new Date().toISOString(),
      __demo: true,
    };
  });
}

export function getDemoCycle(compoundName = "Demo Polymer") {
  return {
    id: DEMO_CYCLE_ID,
    research_run_id: null,
    compound_name: compoundName,
    status: "STEP2",
    target_properties: [],
    competitor_data: [],
    selected_candidate_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    candidates: getDemoRecipeCandidates(compoundName),
    __demo: true,
  };
}

/** Exactly 3 demo revisions for CTF development flow with Phase 2 technical constraints and target analysis. */
export function getDemoRevisedRecipes(
  parentName = DEMO_RECIPE_NAME,
  compoundName = "Demo Polymer",
  constraints: { processType?: string; tempRange?: any } = {},
  targets: any[] = []
) {
  const pType = constraints.processType || "Batch";
  const tRange = constraints.tempRange || { min: 8, max: 12, unit: "°C" };

  // Generate demonstration evaluated properties reflecting target compliance
  const propList = targets.length > 0 ? targets : [{ name: "Target Property", target: "45", range: "40–50", unit: "MU" }];

  const evalPropsA = propList.map((t: any) => ({
    name: t.name || t.property || "Target Property",
    property: t.name || t.property || "Target Property",
    unit: t.unit || "MU",
    target_display: t.range ? `${t.target || "45"} (Range: ${t.range})` : (t.target || t.value || "45"),
    predicted_display: "45.0",
    predicted_value: 45.0,
    status: "MEETS_TARGET",
    target_status: "MEETS TARGET",
    passed: true,
    meets_target: true,
    reasoning: "Adjusted formulation levers satisfy target point and range.",
  }));

  const evalPropsB = propList.map((t: any) => ({
    name: t.name || t.property || "Target Property",
    property: t.name || t.property || "Target Property",
    unit: t.unit || "MU",
    target_display: t.range ? `${t.target || "45"} (Range: ${t.range})` : (t.target || t.value || "45"),
    predicted_display: "46.2",
    predicted_value: 46.2,
    status: "MEETS_TARGET",
    target_status: "MEETS TARGET",
    passed: true,
    meets_target: true,
    reasoning: "Alternative balanced initiator & CTA loading meets target within tolerance.",
  }));

  const evalPropsC = propList.map((t: any, idx: number) => ({
    name: t.name || t.property || "Target Property",
    property: t.name || t.property || "Target Property",
    unit: t.unit || "MU",
    target_display: t.range ? `${t.target || "45"} (Range: ${t.range})` : (t.target || t.value || "45"),
    predicted_display: idx === 0 ? "54.5" : "45.0",
    predicted_value: idx === 0 ? 54.5 : 45.0,
    status: idx === 0 ? "OUTSIDE_TARGET" : "MEETS_TARGET",
    target_status: idx === 0 ? "OUTSIDE TARGET" : "MEETS TARGET",
    passed: idx !== 0,
    meets_target: idx !== 0,
    reasoning: idx === 0
      ? "Higher polymerization rate tradeoff exceeds target boundary."
      : "Maintains secondary target compliance.",
  }));

  const tAnalysisA = {
    evaluated_properties: evalPropsA,
    target_fit_score: 100,
    targets_met: evalPropsA.length,
    targets_total: evalPropsA.length,
  };

  const tAnalysisB = {
    evaluated_properties: evalPropsB,
    target_fit_score: 100,
    targets_met: evalPropsB.length,
    targets_total: evalPropsB.length,
  };

  const tAnalysisC = {
    evaluated_properties: evalPropsC,
    target_fit_score: Math.round(((evalPropsC.length - 1) / evalPropsC.length) * 100),
    targets_met: evalPropsC.length - 1,
    targets_total: evalPropsC.length,
  };

  const recipeA = buildRecipeData(1, compoundName, { Water: "190", Temperature: "8" }, {
    processType: pType,
    tempRange: tRange,
    targetAnalysis: tAnalysisA,
  });

  const recipeB = buildRecipeData(2, compoundName, {
    Water: "200",
    "Chain Transfer Agent": "t-DDM 0.55",
    Temperature: "12",
  }, {
    processType: pType,
    tempRange: tRange,
    targetAnalysis: tAnalysisB,
  });

  const recipeC = buildRecipeData(3, compoundName, { Temperature: "15", Conversion: "90" }, {
    processType: pType,
    tempRange: tRange,
    targetAnalysis: tAnalysisC,
  });

  return [
    {
      id: "00000000-demo-rev-0000-000000000001",
      trial_id: "00000000-demo-trial-0000-000000000001",
      revision_label: "A",
      name: `${parentName} - Revision A (Conservative Adjustment)`,
      recipe_data: recipeA,
      changed_parameters: [
        {
          parameter: "Water",
          previous: "185",
          revised: "190",
          rationale: "[DEMO] Increase water for processability",
        },
      ],
      predicted_impacts: [
        { property: "Mooney", previous_value: "45", predicted_value: "43" },
      ],
      confidence_score: 88,
      target_fit_score: 100,
      targets_met: evalPropsA.length,
      targets_total: evalPropsA.length,
      target_analysis: tAnalysisA,
      is_selected: false,
      created_at: new Date().toISOString(),
      __demo: true,
    },
    {
      id: "00000000-demo-rev-0000-000000000002",
      trial_id: "00000000-demo-trial-0000-000000000001",
      revision_label: "B",
      name: `${parentName} - Revision B (Balanced Tuning)`,
      recipe_data: recipeB,
      changed_parameters: [
        {
          parameter: "Chain Transfer Agent",
          previous: "0.45",
          revised: "0.55",
          rationale: "[DEMO] Adjust MW for Mooney target",
        },
      ],
      predicted_impacts: [
        { property: "Mooney", previous_value: "40", predicted_value: "47" },
      ],
      confidence_score: 82,
      target_fit_score: 100,
      targets_met: evalPropsB.length,
      targets_total: evalPropsB.length,
      target_analysis: tAnalysisB,
      is_selected: false,
      created_at: new Date().toISOString(),
      __demo: true,
    },
    {
      id: "00000000-demo-rev-0000-000000000003",
      trial_id: "00000000-demo-trial-0000-000000000001",
      revision_label: "C",
      name: `${parentName} - Revision C (Outside-Target Process Variant)`,
      recipe_data: recipeC,
      changed_parameters: [
        {
          parameter: "Temperature",
          previous: "10",
          revised: "15",
          rationale: "[DEMO] Slightly warmer polymerization",
        },
      ],
      predicted_impacts: [
        {
          property: "Conversion",
          previous_value: "88",
          predicted_value: "90",
        },
      ],
      confidence_score: 62,
      target_fit_score: tAnalysisC.target_fit_score,
      targets_met: tAnalysisC.targets_met,
      targets_total: tAnalysisC.targets_total,
      target_analysis: tAnalysisC,
      is_selected: false,
      created_at: new Date().toISOString(),
      __demo: true,
    },
  ];
}

export function isDemoEntity(entity: any): boolean {
  return Boolean(entity?.__demo || entity?.recipe_data?.__demo);
}

/**
 * Idempotent: ensure one Demo NBR Recipe exists via real saved-recipe API.
 * No-op when demo mode is off.
 */
export async function ensureDemoSavedRecipe(): Promise<any | null> {
  if (!isRecipeDemoMode()) return null;

  const existing = await api.listSavedRecipes({ includeExpired: false });
  const found = (existing || []).find(
    (r: any) =>
      r.notes === DEMO_SEED_MARKER ||
      (r.recipe_name === DEMO_RECIPE_NAME && r.revision_number === 0)
  );
  if (found) return found;

  return api.createSavedRecipe({
    recipe_name: DEMO_RECIPE_NAME,
    recipe_data: buildRecipeData(1),
    target_properties: [],
    competitor_properties: [],
    notes: DEMO_SEED_MARKER,
  });
}
