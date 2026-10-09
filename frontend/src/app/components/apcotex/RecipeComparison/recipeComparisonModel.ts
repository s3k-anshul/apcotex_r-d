/**
 * frontend/src/app/components/apcotex/RecipeComparison/recipeComparisonModel.ts
 *
 * Shared transformation layer for Recipe Comparison UI and Excel Export.
 * Dynamically computes the union of all stages, components, parameters,
 * target predictions, and process conditions across currently generated recipes.
 * Zero hardcoding of property or stage names. Missing values receive "—".
 */
import { getRecipeDisplayName, type EditableRecipe } from "../recipeSimulatorDemoData";

export interface ComparisonRecipeHeader {
  id: string;
  name: string;
  rank: number;
  confidence: number;
  targetFit: number | null;
  targetsMet: number | null;
  targetsTotal: number | null;
  isCompliant: boolean;
}

export interface ComparisonOverviewRow {
  label: string;
  values: (string | number)[];
}

export interface ComparisonTargetPropertyRow {
  property: string;
  target: string;
  unit: string;
  predictions: (string | number)[];
  statuses: ("PASS" | "NOT MET" | "UNKNOWN" | "—")[];
}

export interface ComparisonParameterRow {
  name: string;
  unit: string;
  values: (string | number | "—")[];
  numericValues: (number | null)[];
}

export interface ComparisonStageSection {
  stageName: string;
  parameters: ComparisonParameterRow[];
}

export interface ComparisonProcessConditionRow {
  name: string;
  unit: string;
  values: (string | number | "—")[];
  numericValues: (number | null)[];
}

export interface ComparisonPatentSupportRow {
  label: string;
  citations: string[];
}

export interface RecipeComparisonModel {
  targetMode: "STRICT_TARGET" | "GENERAL";
  targetCount: number;
  compoundName: string;
  recipes: ComparisonRecipeHeader[];
  overviewRows: ComparisonOverviewRow[];
  targetRows: ComparisonTargetPropertyRow[];
  stages: ComparisonStageSection[];
  processConditions: ComparisonProcessConditionRow[];
  patentSupport: ComparisonPatentSupportRow;
}

/**
 * Normalizes and extracts numeric value from string or number if available.
 */
function parseNumericValue(val: any): number | null {
  if (val === null || val === undefined) return null;
  if (typeof val === "number" && !isNaN(val)) return val;
  const s = String(val).trim();
  if (s === "" || s === "—" || s.toLowerCase() === "n/a") return null;
  const num = Number(s);
  return !isNaN(num) ? num : null;
}

/**
 * Builds the canonical RecipeComparisonModel from the currently generated recipes.
 * Single source of truth for both browser Comparison UI and Excel Export.
 */
export function buildRecipeComparisonModel(
  recipes: EditableRecipe[],
  cycle?: any
): RecipeComparisonModel {
  if (!recipes || recipes.length === 0) {
    return {
      targetMode: "GENERAL",
      targetCount: 0,
      compoundName: cycle?.target_compound || "Polymer Formulation",
      recipes: [],
      overviewRows: [],
      targetRows: [],
      stages: [],
      processConditions: [],
      patentSupport: { label: "Patent Support", citations: [] },
    };
  }

  const compoundName =
    cycle?.target_compound ||
    (recipes[0] as any)?.raw_data?.compound ||
    (recipes[0] as any)?.raw_data?.target_compound ||
    "Polymer Formulation";

  // ── 1. Target Mode Assessment ──────────────────────────────────────────────
  const cycleTargets = (
    cycle?.target_properties ||
    cycle?.target_specs ||
    []
  ).filter((t: any) => {
    if (!t) return false;
    const hasMin =
      t.min !== undefined && t.min !== null && String(t.min).trim() !== "";
    const hasMax =
      t.max !== undefined && t.max !== null && String(t.max).trim() !== "";
    const hasTarget =
      (t.target !== undefined &&
        t.target !== null &&
        String(t.target).trim() !== "") ||
      (t.value !== undefined &&
        t.value !== null &&
        String(t.value).trim() !== "");
    return hasMin || hasMax || hasTarget;
  });

  const firstRecipeProps = recipes[0]?.targetAnalysis?.properties || [];
  const isTargetMode =
    cycleTargets.length > 0 ||
    firstRecipeProps.length > 0 ||
    recipes.some((r) => (r.targetsTotal ?? 0) > 0);

  const targetMode: "STRICT_TARGET" | "GENERAL" = isTargetMode
    ? "STRICT_TARGET"
    : "GENERAL";

  // ── 2. Recipe Headers ──────────────────────────────────────────────────────
  const recipeHeaders: ComparisonRecipeHeader[] = recipes.map((r, idx) => {
    const isCompliant =
      r.targetsTotal !== null &&
      r.targetsTotal !== undefined &&
      r.targetsTotal > 0 &&
      r.targetsMet === r.targetsTotal;

    return {
      id: r.id || `recipe-${idx + 1}`,
      name: getRecipeDisplayName(r),
      rank: r.rank || idx + 1,
      confidence: r.confidence ?? 0,
      targetFit: r.targetFit ?? null,
      targetsMet: r.targetsMet ?? null,
      targetsTotal: r.targetsTotal ?? null,
      isCompliant,
    };
  });

  // ── 3. Recipe Overview Rows ────────────────────────────────────────────────
  const overviewRows: ComparisonOverviewRow[] = [
    {
      label: "Recipe Name",
      values: recipes.map((r) => getRecipeDisplayName(r)),
    },
    {
      label: "Target Fit",
      values: recipes.map((r) =>
        r.targetFit !== null && r.targetFit !== undefined
          ? `${r.targetFit}%`
          : "N/A"
      ),
    },
    {
      label: "Targets Met",
      values: recipes.map((r) =>
        r.targetsTotal !== null &&
        r.targetsTotal !== undefined &&
        r.targetsTotal > 0
          ? `${r.targetsMet ?? 0}/${r.targetsTotal}`
          : isTargetMode
          ? "0/0"
          : "N/A"
      ),
    },
    {
      label: "Confidence Score",
      values: recipes.map((r) => `${r.confidence ?? 0}%`),
    },
  ];

  // ── 4. Target Properties & Predictions (Dynamic Union) ──────────────────────
  const targetPropMap = new Map<
    string,
    {
      name: string;
      unit: string;
      targetDisplay: string;
    }
  >();

  // A. Seed from cycle target properties
  for (const ct of cycleTargets) {
    const name = (ct.feature || ct.name || ct.property || ct.id || "").trim();
    if (!name) continue;
    let targetDisplay = "";
    const u = ct.unit ? ` ${ct.unit}` : "";
    if (
      ct.min !== undefined &&
      ct.max !== undefined &&
      String(ct.min).trim() !== "" &&
      String(ct.max).trim() !== ""
    ) {
      targetDisplay = `${ct.min}–${ct.max}${u}`;
    } else if (ct.min !== undefined && String(ct.min).trim() !== "") {
      targetDisplay = `≥ ${ct.min}${u}`;
    } else if (ct.max !== undefined && String(ct.max).trim() !== "") {
      targetDisplay = `≤ ${ct.max}${u}`;
    } else if (ct.target !== undefined && String(ct.target).trim() !== "") {
      targetDisplay = `${ct.target}${u}`;
    }
    targetPropMap.set(name.toLowerCase(), {
      name,
      unit: ct.unit || "",
      targetDisplay: targetDisplay || "—",
    });
  }

  // B. Seed / supplement from recipe targetAnalysis properties
  for (const recipe of recipes) {
    const evaluatedProps = recipe.targetAnalysis?.properties || [];
    for (const ep of evaluatedProps) {
      const name = (ep.property || ep.name || "").trim();
      if (!name) continue;
      const key = name.toLowerCase();
      if (!targetPropMap.has(key)) {
        targetPropMap.set(key, {
          name,
          unit: ep.unit || "",
          targetDisplay: ep.target_display || "—",
        });
      } else {
        const existing = targetPropMap.get(key)!;
        if (!existing.targetDisplay || existing.targetDisplay === "—") {
          existing.targetDisplay = ep.target_display || "—";
        }
        if (!existing.unit && ep.unit) {
          existing.unit = ep.unit;
        }
      }
    }
  }

  const targetRows: ComparisonTargetPropertyRow[] = [];
  if (isTargetMode) {
    for (const [_, targetInfo] of targetPropMap) {
      const predictions: (string | number)[] = [];
      const statuses: ("PASS" | "NOT MET" | "—")[] = [];

      for (const recipe of recipes) {
        const evaluatedProps = recipe.targetAnalysis?.properties || [];
        const matched = evaluatedProps.find((ep: any) => {
          const epName = (ep.property || ep.name || "").toLowerCase().trim();
          const tName = targetInfo.name.toLowerCase().trim();
          return (
            epName === tName ||
            epName.includes(tName) ||
            tName.includes(epName)
          );
        });

        if (matched) {
          const valDisplay =
            matched.predicted_display ||
            (matched.predicted_value !== undefined &&
            matched.predicted_value !== null
              ? `${matched.predicted_value} ${matched.unit || targetInfo.unit}`.trim()
              : "—");
          predictions.push(valDisplay);
          if (matched.status === "UNKNOWN" || matched.target_status === "UNKNOWN") {
            statuses.push("UNKNOWN");
          } else {
            statuses.push(matched.passed ? "PASS" : "NOT MET");
          }
        } else {
          // Check raw_data.predicted_properties fallback
          const rawPreds = recipe.raw_data?.predicted_properties || [];
          const rawMatch = rawPreds.find((rp: any) => {
            const rpName = (rp.property || "").toLowerCase().trim();
            const tName = targetInfo.name.toLowerCase().trim();
            return (
              rpName === tName ||
              rpName.includes(tName) ||
              tName.includes(rpName)
            );
          });
          if (rawMatch && rawMatch.predicted_value !== undefined) {
            predictions.push(String(rawMatch.predicted_value));
            statuses.push("—");
          } else {
            predictions.push("—");
            statuses.push("—");
          }
        }
      }

      targetRows.push({
        property: targetInfo.name,
        target: targetInfo.targetDisplay,
        unit: targetInfo.unit,
        predictions,
        statuses,
      });
    }
  }

  // ── 5. Stages & Parameters (Dynamic Union) ──────────────────────────────────
  const stageOrder: string[] = [];
  const stageParamsMap = new Map<
    string,
    {
      canonicalName: string;
      paramOrder: string[];
      paramUnits: Map<string, string>;
      recipeParamValues: Map<
        string,
        Map<number, { val: string | number; num: number | null }>
      >;
    }
  >();

  recipes.forEach((recipe, rIdx) => {
    const stages = recipe.stages || [];
    stages.forEach((stage) => {
      const rawStageName = (stage.stage_name || "Synthesis Stage").trim();
      const normStageKey = rawStageName.toLowerCase();

      if (!stageParamsMap.has(normStageKey)) {
        stageOrder.push(normStageKey);
        stageParamsMap.set(normStageKey, {
          canonicalName: rawStageName,
          paramOrder: [],
          paramUnits: new Map(),
          recipeParamValues: new Map(),
        });
      }

      const stageData = stageParamsMap.get(normStageKey)!;
      (stage.parameters || []).forEach((param) => {
        const pName = (param.name || "").trim();
        if (!pName) return;
        const pKey = pName.toLowerCase();

        if (!stageData.paramOrder.includes(pKey)) {
          stageData.paramOrder.push(pKey);
        }
        if (!stageData.paramUnits.has(pKey) && param.unit) {
          stageData.paramUnits.set(pKey, param.unit.trim());
        }

        if (!stageData.recipeParamValues.has(pKey)) {
          stageData.recipeParamValues.set(pKey, new Map());
        }

        const rawVal =
          param.value !== undefined && param.value !== null
            ? String(param.value).trim()
            : "";
        const numVal = parseNumericValue(rawVal);

        stageData.recipeParamValues.get(pKey)!.set(rIdx, {
          val: rawVal || "—",
          num: numVal,
        });
      });
    });
  });

  const stageSections: ComparisonStageSection[] = [];
  for (const stageKey of stageOrder) {
    const sData = stageParamsMap.get(stageKey)!;
    const parameters: ComparisonParameterRow[] = [];

    for (const pKey of sData.paramOrder) {
      // Find original display casing
      let displayName = pKey;
      for (const recipe of recipes) {
        const stage = (recipe.stages || []).find(
          (s) => (s.stage_name || "").toLowerCase().trim() === stageKey
        );
        const p = (stage?.parameters || []).find(
          (param) => (param.name || "").toLowerCase().trim() === pKey
        );
        if (p?.name) {
          displayName = p.name.trim();
          break;
        }
      }

      const unit = sData.paramUnits.get(pKey) || "—";
      const values: (string | number | "—")[] = [];
      const numericValues: (number | null)[] = [];

      for (let rIdx = 0; rIdx < recipes.length; rIdx++) {
        const rValEntry = sData.recipeParamValues.get(pKey)?.get(rIdx);
        if (rValEntry && rValEntry.val !== "") {
          values.push(rValEntry.val);
          numericValues.push(rValEntry.num);
        } else {
          values.push("—");
          numericValues.push(null);
        }
      }

      parameters.push({
        name: displayName,
        unit,
        values,
        numericValues,
      });
    }

    stageSections.push({
      stageName: sData.canonicalName,
      parameters,
    });
  }

  // ── 6. Process Conditions (Dynamic Union) ───────────────────────────────────
  const processConditions: ComparisonProcessConditionRow[] = [];

  // Reaction Time
  const hasReactionTime = recipes.some(
    (r) =>
      r.process_conditions?.reaction_time?.value ||
      r.raw_data?.process_conditions?.reaction_time?.value
  );
  if (hasReactionTime) {
    const values: (string | number | "—")[] = [];
    const numericValues: (number | null)[] = [];
    let rtUnit = "h";

    recipes.forEach((r) => {
      const pc = r.process_conditions || r.raw_data?.process_conditions || {};
      const rt = pc.reaction_time;
      if (rt && rt.value !== undefined && rt.value !== null) {
        const valStr = String(rt.value).trim();
        const num = parseNumericValue(valStr);
        if (rt.unit) rtUnit = rt.unit;
        values.push(valStr);
        numericValues.push(num);
      } else {
        values.push("—");
        numericValues.push(null);
      }
    });

    processConditions.push({
      name: "Reaction Time",
      unit: rtUnit,
      values,
      numericValues,
    });
  }

  // Feeding Hours
  const hasFeedingHours = recipes.some(
    (r) =>
      r.process_conditions?.feeding_hours ||
      r.raw_data?.process_conditions?.feeding_hours
  );
  if (hasFeedingHours) {
    const values: (string | number | "—")[] = [];
    const numericValues: (number | null)[] = [];

    recipes.forEach((r) => {
      const pc = r.process_conditions || r.raw_data?.process_conditions || {};
      const fh = pc.feeding_hours;
      if (fh) {
        if (typeof fh === "string") {
          values.push(fh);
        } else if (typeof fh === "object") {
          const parts = Object.entries(fh)
            .filter(([_, v]) => v !== undefined && v !== null && String(v).trim() !== "")
            .map(([k, v]) => `${k.charAt(0).toUpperCase() + k.slice(1)}: ${v}h`);
          values.push(parts.length > 0 ? parts.join(", ") : "—");
        } else {
          values.push(String(fh));
        }
      } else {
        values.push("—");
      }
      numericValues.push(null);
    });

    processConditions.push({
      name: "Feeding Hours",
      unit: "—",
      values,
      numericValues,
    });
  }

  // Temperature Profile
  const hasTempProfile = recipes.some(
    (r) =>
      r.process_conditions?.temperature_profile ||
      r.raw_data?.process_conditions?.temperature_profile
  );
  if (hasTempProfile) {
    const values: (string | number | "—")[] = [];
    const numericValues: (number | null)[] = [];

    recipes.forEach((r) => {
      const pc = r.process_conditions || r.raw_data?.process_conditions || {};
      const tp = pc.temperature_profile;
      if (Array.isArray(tp) && tp.length > 0) {
        const parts = tp.map((t: any) =>
          `${t.stage ? t.stage + ": " : ""}${t.value}${t.unit || "°C"}`
        );
        values.push(parts.join("; "));
      } else if (typeof tp === "string" && tp.trim()) {
        values.push(tp);
      } else {
        values.push("—");
      }
      numericValues.push(null);
    });

    processConditions.push({
      name: "Temperature Profile",
      unit: "°C",
      values,
      numericValues,
    });
  }

  // Dynamic extra process condition keys
  const knownKeys = new Set([
    "reaction_time",
    "feeding_hours",
    "temperature_profile",
  ]);
  const extraKeys = new Set<string>();
  recipes.forEach((r) => {
    const pc = r.process_conditions || r.raw_data?.process_conditions || {};
    Object.keys(pc).forEach((k) => {
      if (!knownKeys.has(k)) {
        extraKeys.add(k);
      }
    });
  });

  extraKeys.forEach((key) => {
    const label = key
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
    const values: (string | number | "—")[] = [];
    const numericValues: (number | null)[] = [];

    recipes.forEach((r) => {
      const pc = r.process_conditions || r.raw_data?.process_conditions || {};
      const val = pc[key];
      if (val !== undefined && val !== null) {
        const s = typeof val === "object" ? JSON.stringify(val) : String(val);
        values.push(s || "—");
        numericValues.push(parseNumericValue(s));
      } else {
        values.push("—");
        numericValues.push(null);
      }
    });

    processConditions.push({
      name: label,
      unit: "—",
      values,
      numericValues,
    });
  });

  // ── 7. Patent Support ───────────────────────────────────────────────────────
  const patentSupport: ComparisonPatentSupportRow = {
    label: "Patent Support",
    citations: recipes.map((r) => {
      if (r.patentSupport && r.patentSupport.trim()) {
        return r.patentSupport;
      }
      const rawList =
        (r as any).patent_references ||
        (r as any).raw_data?.patent_references ||
        [];
      return Array.isArray(rawList) && rawList.length > 0
        ? rawList.join(", ")
        : "No direct patent support";
    }),
  };

  return {
    targetMode,
    targetCount: targetRows.length,
    compoundName,
    recipes: recipeHeaders,
    overviewRows,
    targetRows,
    stages: stageSections,
    processConditions,
    patentSupport,
  };
}
