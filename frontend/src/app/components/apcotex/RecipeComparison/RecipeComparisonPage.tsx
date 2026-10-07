/**
 * frontend/src/app/components/apcotex/RecipeComparison/RecipeComparisonPage.tsx
 *
 * Dedicated Comparison Page for the currently generated 5 polymerization recipes.
 * Operates purely on the active in-memory/cycle state without fetching saved recipes,
 * without re-querying the database, and without triggering recipe regeneration upon return.
 */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import { ChevronLeft, Download, RefreshCw, AlertCircle } from "lucide-react";
import { useRecipe } from "../../../contexts/RecipeContext";
import { convertToEditableRecipe } from "../recipeSimulatorDemoData";
import { buildRecipeComparisonModel } from "./recipeComparisonModel";
import { exportRecipeComparisonToExcel } from "./recipeExcelExporter";
import { RecipeComparisonTable } from "./RecipeComparisonTable";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const BORDER = "#E5E7EB";

export function RecipeComparisonPage() {
  const navigate = useNavigate();
  const { candidates, cycle } = useRecipe();
  const [downloading, setDownloading] = useState(false);

  // Derive editable recipes from current generation context
  const recipes = useMemo(() => {
    const rawList =
      candidates?.length > 0
        ? candidates
        : cycle?.candidates?.length > 0
        ? cycle.candidates
        : [];
    return rawList.map(convertToEditableRecipe);
  }, [candidates, cycle?.candidates]);

  // Build unified comparison model consumed by both UI and Excel exporter
  const comparisonModel = useMemo(() => {
    return buildRecipeComparisonModel(recipes, cycle);
  }, [recipes, cycle]);

  const handleDownloadExcel = async () => {
    if (recipes.length === 0) return;
    setDownloading(true);
    try {
      const compound =
        cycle?.target_compound ||
        (recipes[0] as any)?.raw_data?.compound ||
        "Polymer_Formulation";
      await exportRecipeComparisonToExcel(comparisonModel, compound);
    } catch (err) {
      console.error("Failed to export Excel comparison:", err);
      alert("Failed to export Excel comparison. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  const handleBack = () => {
    // Preserve current generation session state and navigate back to Step 2
    sessionStorage.setItem("recipeSimulatorActiveStep", "2");
    navigate("/recipe-simulator");
  };

  if (recipes.length < 2) {
    return (
      <div style={{ padding: "32px 36px 60px", maxWidth: 1000, margin: "0 auto" }}>
        <button
          onClick={handleBack}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            background: "white",
            border: `1px solid ${BORDER}`,
            borderRadius: 7,
            padding: "9px 18px",
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "#374151",
            cursor: "pointer",
            marginBottom: 24,
          }}
        >
          <ChevronLeft size={16} /> Return to Recipe Simulator
        </button>

        <div
          style={{
            background: "white",
            border: `1px solid ${BORDER}`,
            borderRadius: 12,
            padding: "48px 32px",
            textAlign: "center",
            boxShadow: "0 2px 8px rgba(0,0,0,0.05)",
          }}
        >
          <AlertCircle size={44} color="#94A3B8" style={{ marginBottom: 16 }} />
          <h2 style={{ color: BLUE, fontSize: "1.25rem", fontWeight: 700, margin: "0 0 8px" }}>
            No Active Generation Set Available
          </h2>
          <p style={{ color: "#64748B", fontSize: "0.875rem", maxWidth: 500, margin: "0 auto 24px" }}>
            At least 2 generated recipes are required for side-by-side comparison. Please generate polymerization recipes in the Recipe Simulator first.
          </p>
          <button
            onClick={handleBack}
            style={{
              background: TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "10px 24px",
              fontWeight: 700,
              fontSize: "0.875rem",
              cursor: "pointer",
            }}
          >
            Go to Recipe Simulator
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "28px 32px 60px" }}>
      {/* ── Top Navigation & Page Title Bar ── */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 16,
          marginBottom: 20,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button
            onClick={handleBack}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "white",
              border: `1px solid ${BORDER}`,
              borderRadius: 7,
              padding: "10px 18px",
              fontSize: "0.875rem",
              fontWeight: 600,
              color: "#374151",
              cursor: "pointer",
              boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
            }}
            title="Return to generated recipes in Step 2"
          >
            <ChevronLeft size={16} /> Back
          </button>

          <div>
            <h1
              style={{
                color: BLUE,
                fontSize: "1.25rem",
                fontWeight: 800,
                margin: "0 0 3px",
              }}
            >
              Recipe Comparison
            </h1>
            <p style={{ color: "#64748B", fontSize: "0.8125rem", margin: 0 }}>
              Comparing {recipes.length} candidate polymerization recipes side-by-side · {comparisonModel.compoundName}
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={handleDownloadExcel}
            disabled={downloading}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              background: TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "10px 22px",
              fontSize: "0.875rem",
              fontWeight: 700,
              cursor: downloading ? "wait" : "pointer",
              boxShadow: "0 2px 6px rgba(31,183,181,0.3)",
              opacity: downloading ? 0.75 : 1,
            }}
          >
            {downloading ? <RefreshCw size={16} className="animate-spin" /> : <Download size={16} />}
            Download Excel
          </button>
        </div>
      </div>

      {/* ── Mode Summary Banner ── */}
      <div
        style={{
          background:
            comparisonModel.targetMode === "STRICT_TARGET"
              ? "rgba(31,183,181,0.08)"
              : "#F8FAFC",
          border: `1.5px solid ${
            comparisonModel.targetMode === "STRICT_TARGET" ? TEAL : "#CBD5E1"
          }`,
          borderRadius: 8,
          padding: "10px 18px",
          marginBottom: 20,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <span
          style={{
            background:
              comparisonModel.targetMode === "STRICT_TARGET" ? TEAL : "#64748B",
            color: "white",
            padding: "3px 9px",
            borderRadius: 5,
            fontSize: "0.72rem",
            fontWeight: 800,
            letterSpacing: "0.5px",
          }}
        >
          {comparisonModel.targetMode === "STRICT_TARGET"
            ? "TARGET MODE"
            : "GENERAL RECIPE MODE"}
        </span>
        <span style={{ fontSize: "0.8125rem", color: BLUE, fontWeight: 600 }}>
          {comparisonModel.targetMode === "STRICT_TARGET"
            ? `${comparisonModel.targetCount} target property objectives compared. All evaluated deterministically by backend.`
            : "No explicit target properties provided. Formulations generated from product specifications and patent evidence."}
        </span>
      </div>

      {/* ── Side-by-Side Comparison Table ── */}
      <RecipeComparisonTable model={comparisonModel} />
    </div>
  );
}
