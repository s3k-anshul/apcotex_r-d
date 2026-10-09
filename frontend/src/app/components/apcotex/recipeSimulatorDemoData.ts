import type { PatentRecipeStep } from "./recipeSimulatorPatentData";

export interface SpecRowTemplate {
  feature: string;
  unit: string;
  category?: string;
  dataType?: 'number' | 'text' | 'boolean';
  id: string;
}

export const SPEC_ROWS: SpecRowTemplate[] = [
  { id: "prop-1", feature: "BACN", unit: "%", category: "General", dataType: "number" },
  { id: "prop-2", feature: "Mooney (ML1+4 @ 100°C)", unit: "MU", category: "General", dataType: "number" },
  { id: "prop-3", feature: "Stress Relaxation", unit: "sec", category: "General", dataType: "number" },
  { id: "prop-4", feature: "pH", unit: "—", category: "General", dataType: "number" },
  { id: "prop-5", feature: "Total Solid Content", unit: "%", category: "General", dataType: "number" },
  { id: "prop-6", feature: "Gel Content", unit: "%", category: "General", dataType: "number" },
  { id: "prop-7", feature: "Tg", unit: "°C", category: "Thermal", dataType: "number" },
  { id: "prop-8", feature: "Volatile Matter", unit: "%", category: "General", dataType: "number" },
  { id: "prop-9", feature: "Particle Size", unit: "nm", category: "Physical", dataType: "number" },
  { id: "prop-10", feature: "Carboxylation", unit: "%", category: "General", dataType: "number" },
  { id: "prop-11", feature: "Density", unit: "g/ml", category: "Physical", dataType: "number" },
  { id: "prop-12", feature: "Thermal Colloidal Stability", unit: "%", category: "Stability", dataType: "number" },
  { id: "prop-13", feature: "Mechanical Colloidal Stability", unit: "%", category: "Stability", dataType: "number" },
  { id: "prop-14", feature: "Chemical Colloidal Stability", unit: "%", category: "Stability", dataType: "number" },
  { id: "prop-15", feature: "Number-average Molecular Weight (Mn)", unit: "g/mol", category: "Molecular", dataType: "number" },
  { id: "prop-16", feature: "Weight-average Molecular Weight (Mw)", unit: "g/mol", category: "Molecular", dataType: "number" },
  { id: "prop-17", feature: "Z-average Molecular Weight (Mz)", unit: "g/mol", category: "Molecular", dataType: "number" },
  { id: "prop-18", feature: "Z+1-average Molecular Weight (Mz+1)", unit: "g/mol", category: "Molecular", dataType: "number" },
  { id: "prop-19", feature: "Polydispersity Index (PDI)", unit: "—", category: "Molecular", dataType: "number" },
];

export interface RecipeProperty {
  id: string;
  name: string;
  value: string;
  unit: string;
  source?: string;
  patentRef?: string;
}

export interface EditableRecipeStage {
  id: string;
  stage_name: string;
  parameters: RecipeProperty[];
  omission_reason?: string;
  is_applicable?: boolean;
}

export interface EditableProcessConditions {
  reaction_time?: { value: string; unit: string };
  feeding_hours?: { monomer?: string; emulsifier?: string; catalyst?: string };
  temperature_profile?: { stage: string; value: string; unit: string }[];
}

export const CANONICAL_STAGE_NAMES = [
  "Reactor Charge",
  "Emulsifier Solution",
  "Catalyst Solution",
  "Monomer Mix",
  "Chemical Stripping",
  "Post Addition",
];

export function getRecipeDisplayName(recipe: any): string {
  if (!recipe) return "Recipe";
  if (recipe.display_name && /^Recipe\s+\d+$/i.test(String(recipe.display_name).trim())) {
    return String(recipe.display_name).trim();
  }
  if (recipe.recipe_data?.display_name && /^Recipe\s+\d+$/i.test(String(recipe.recipe_data.display_name).trim())) {
    return String(recipe.recipe_data.display_name).trim();
  }
  if (typeof recipe.rank === "number" && recipe.rank >= 1 && recipe.rank <= 20) {
    return `Recipe ${recipe.rank}`;
  }
  const nameStr = String(recipe.name || recipe.recipe_name || recipe.displayName || "");
  const match = nameStr.match(/Recipe\s*(\d+)/i);
  if (match) {
    return `Recipe ${match[1]}`;
  }
  return nameStr || "Recipe";
}

export interface EditableRecipe {
  id: string;
  name: string;
  display_name?: string;
  fullName?: string;
  rank: number;
  confidence: number;
  evidenceCoverage?: number;
  patentSupport: string;
  topPick?: boolean;
  properties: RecipeProperty[];
  stages: EditableRecipeStage[];
  process_conditions?: EditableProcessConditions;
  // Target analysis & real confidence scoring fields
  targetFit?: number | null;
  targetsMet?: number | null;
  targetsTotal?: number | null;
  targetAnalysis?: any;
  confidenceAnalysis?: any;
  // Include raw data for passing to steps
  raw_data?: any; 
}

// Convert from API LLM structure to EditableRecipe structure
export function convertToEditableRecipe(recipe: any): EditableRecipe {
  const recipeData = recipe.recipe_data || {};
  const rawStages = recipeData.stages || [];
  
  let editableStages: EditableRecipeStage[] = [];
  let props: RecipeProperty[] = [];

  if (Array.isArray(rawStages) && rawStages.length > 0) {
    editableStages = rawStages.map((s: any, sIdx: number) => {
      const stageParams: RecipeProperty[] = (s.parameters || []).map((p: any, pIdx: number) => ({
        id: `prop-s${sIdx}-p${pIdx}`,
        name: p.name,
        value: String(p.value ?? ""),
        unit: p.unit || "",
        source: p.source,
        patentRef: p.patent_ref,
      }));
      props.push(...stageParams);
      const isApp = s.is_applicable !== false && stageParams.length > 0;
      return {
        id: `stage-${sIdx}`,
        stage_name: s.stage_name || `Stage ${sIdx + 1}`,
        parameters: stageParams,
        is_applicable: isApp,
        omission_reason: s.omission_reason || (!isApp ? "This stage was omitted based on the modeled synthesis pathway." : undefined),
      };
    });
  } else {
    // Legacy fallback: flat parameters when stages are absent
    const params = recipeData.parameters || [];
    props = params.map((p: any, i: number) => ({
      id: `prop-${i}`,
      name: p.name,
      value: String(p.value ?? ""),
      unit: p.unit || "",
      source: p.source,
      patentRef: p.patent_ref,
    }));
  }

  // If completely empty, provide fallback compound and method info
  if (props.length === 0 && editableStages.length === 0) {
    const method = recipeData.polymerization_method || recipeData.method || '';
    const compound = recipeData.compound || recipe.name || 'Unknown';
    if (method) {
      props.push({ id: 'method', name: 'Polymerization Method', value: method, unit: '' });
    }
    props.push({ id: 'compound', name: 'Target Compound', value: compound, unit: '' });
  }

  const patList = (recipe.patent_references && recipe.patent_references.length > 0)
    ? recipe.patent_references
    : (recipeData.patent_references || []);
  const patentSupportText = patList.length > 0
    ? patList.join(", ")
    : "No direct patent support identified in the selected report.";

  const ta = recipe.target_analysis || recipeData.target_analysis;
  const ca = recipe.confidence_analysis || recipeData.confidence_analysis;
  const targetFit = recipe.target_fit_score ?? ta?.target_fit_score ?? null;
  const targetsMet = recipe.targets_met ?? ta?.targets_met ?? null;
  const targetsTotal = recipe.targets_total ?? ta?.targets_total ?? null;
  const displayName = getRecipeDisplayName(recipe);
  const confScore = recipe.confidence_score ?? recipeData.confidence_score ?? ca?.score ?? 0;
  const evidScore = recipe.evidence_coverage_score ?? recipeData.evidence_coverage_score ?? 0;

  return {
    id: recipe.id,
    name: displayName,
    display_name: displayName,
    fullName: recipe.name || displayName,
    rank: recipe.rank,
    confidence: confScore,
    evidenceCoverage: evidScore,
    targetFit: targetFit,
    targetsMet: targetsMet,
    targetsTotal: targetsTotal,
    targetAnalysis: ta,
    confidenceAnalysis: ca,
    patentSupport: patentSupportText,
    topPick: recipe.rank === 1,
    properties: props,
    stages: editableStages,
    process_conditions: recipeData.process_conditions,
    raw_data: recipeData,
  };
}

/** Rebuild API recipe_data from local EditableRecipe edits (preserves structure and non-parameter fields). */
export function editableRecipeToRecipeData(recipe: EditableRecipe): any {
  const base = { ...(recipe.raw_data || {}) };

  if (recipe.stages && recipe.stages.length > 0) {
    base.stages = recipe.stages.map((s) => ({
      stage_name: s.stage_name,
      is_applicable: s.parameters.length > 0,
      omission_reason: s.omission_reason || null,
      parameters: s.parameters.map((p) => ({
        name: p.name,
        value: p.value,
        unit: p.unit || "",
        source: p.source || "inferred",
        patent_ref: p.patentRef || null,
      })),
    }));

    // Synchronize flat parameters array across all stages for backwards compatibility
    base.parameters = recipe.stages.flatMap((s) =>
      s.parameters.map((p) => ({
        name: p.name,
        value: p.value,
        unit: p.unit || "",
        source: p.source || "inferred",
        patent_ref: p.patentRef || null,
      }))
    );
  } else {
    base.parameters = recipe.properties.map((p) => ({
      name: p.name,
      value: p.value,
      unit: p.unit || "",
      source: p.source || "inferred",
      patent_ref: p.patentRef || null,
    }));
  }

  if (recipe.process_conditions) {
    base.process_conditions = recipe.process_conditions;
  }
  base.confidence_score = recipe.confidence;

  return base;
}

export function getPolymerizationRecipeSteps(
  recipeData: any,
): PatentRecipeStep[] {
  // If no raw data is available, return empty
  if (!recipeData) return [];

  // Prefer the dynamic stages structure (from the new LLM schema)
  const stages = recipeData.stages || [];
  if (stages.length > 0) {
    const steps: PatentRecipeStep[] = [];
    let idx = 1;
    stages.forEach((stage: any) => {
      const stageName: string = stage.stage_name || 'Stage';
      (stage.parameters || []).forEach((param: any) => {
        steps.push({
          param: `${stageName} — ${param.name}`,
          step: `PR#${String(idx).padStart(2, '0')}`,
          desc: `${param.name}: ${param.value}${param.unit ? ' ' + param.unit : ''}${param.source === 'patent' && param.patent_ref ? ` [${param.patent_ref}]` : ''}`,
          temp: '',
          duration: '',
        });
        idx++;
      });
    });
    return steps;
  }

  // Fallback: use flat parameters list when stages are absent
  const params = recipeData.parameters || [];
  if (params.length > 0) {
    return params.map((param: any, i: number) => ({
      param: param.name,
      step: `PR#${String(i + 1).padStart(2, '0')}`,
      desc: `${param.name}: ${param.value}${param.unit ? ' ' + param.unit : ''}${param.source === 'patent' && param.patent_ref ? ` [${param.patent_ref}]` : ''}`,
      temp: '',
      duration: '',
    }));
  }

  // Final fallback: return empty (no NBR-specific hardcoded steps)
  return [];
}

export interface CustomerFeedbackOption {
  id: string;
  label: string;
  checked: boolean;
}

/** Build zero-valued competitor columns from competitor list + property list. */
export function buildInitialCompetitorValues(
  competitors: { id: string; name: string }[],
  props: SpecRowTemplate[]
): Record<string, Record<string, string>> {
  const result: Record<string, Record<string, string>> = {};
  props.forEach(p => {
    result[p.feature] = {};
    competitors.forEach(c => {
      result[p.feature][c.id] = '';
    });
  });
  return result;
}

/** Default target values for customer feedback (empty — filled by user). */
export const CUSTOMER_FEEDBACK_TARGET_VALUES: Record<string, string> = {};

export const CUSTOMER_FEEDBACK_PROPERTIES: SpecRowTemplate[] = [
  { id: "cf-prop-1", feature: "MH", unit: "lb-in", category: "Testing", dataType: "number" },
  { id: "cf-prop-2", feature: "Ts1", unit: "min", category: "Testing", dataType: "number" },
  { id: "cf-prop-3", feature: "Ts2", unit: "min", category: "Testing", dataType: "number" },
  { id: "cf-prop-4", feature: "T10", unit: "min", category: "Testing", dataType: "number" },
  { id: "cf-prop-5", feature: "T50", unit: "min", category: "Testing", dataType: "number" },
  { id: "cf-prop-6", feature: "T90", unit: "min", category: "Testing", dataType: "number" },
  { id: "cf-prop-7", feature: "Hardness", unit: "Shore A", category: "Testing", dataType: "number" },
  { id: "cf-prop-8", feature: "Tensile Strength", unit: "MPa", category: "Testing", dataType: "number" },
  { id: "cf-prop-9", feature: "Elongation at Break", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-10", feature: "Modulus at 100%", unit: "MPa", category: "Testing", dataType: "number" },
  { id: "cf-prop-11", feature: "Modulus at 300%", unit: "MPa", category: "Testing", dataType: "number" },
  { id: "cf-prop-12", feature: "Tear Strength", unit: "N/mm", category: "Testing", dataType: "number" },
  { id: "cf-prop-13", feature: "Compression Set", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-14", feature: "Abrasion Resistance", unit: "mm³", category: "Testing", dataType: "number" },
  { id: "cf-prop-15", feature: "Volume Swell (IRM 903)", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-16", feature: "Weight Change (Isooctane)", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-17", feature: "Change in Hardness (Aged)", unit: "Points", category: "Testing", dataType: "number" },
  { id: "cf-prop-18", feature: "Change in Tensile Strength", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-19", feature: "Change in Elongation", unit: "%", category: "Testing", dataType: "number" },
  { id: "cf-prop-20", feature: "Processing Oil", unit: "phr", category: "Formulation", dataType: "number" },
];

// Re-export type definitions for usage
export interface OptimizedRecipe {
  id: string;
  revision: string;
  name: string;
  description: string;
  changes: Array<{
    parameter: string;
    previous: string;
    revised: string;
    rationale: string;
  }>;
  impacts: Array<{
    property: string;
    expectedChange: string;
    description: string;
  }>;
  properties: RecipeProperty[];
  raw_data?: any;
}

export interface MeasuredValueRow {
  property: string;
  target: string;
  actual: string;
}

export type TransferredSpecData = {
  property: string;
  unit: string;
  min: string;
  max: string;
  competitors: Record<string, string>; // name -> value
};

// Type alias for backward compatibility with RecipeSimulatorSteps
// In production mode these are replaced by LLM-generated recipes.
export type PolymerizationRecipe = EditableRecipe;

// Placeholder demo constants used only in DEMO MODE (VITE_RECIPE_DEMO_MODE=true)
export const POLYMERIZATION_RECIPES: PolymerizationRecipe[] = [];
export const OPTIMIZED_RECIPES: OptimizedRecipe[] = [];

export const DEFAULT_CUSTOMER_FEEDBACK = "Product performance meets expectations.";
export const DEMO_CUSTOMER_NOTES = "Trial conducted under standard plant conditions.";

export const DEMO_TARGET_VALUES: Record<string, string> = {};

