import { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router";
import { CheckCircle2, History } from "lucide-react";
import { useRecipe } from "../../contexts/RecipeContext";
import {
  Step1TargetSpec,
  Step2PolymerizationRecommendations,
} from "./RecipeSimulatorSteps";
import { SavedRecipesPanel } from "./SavedRecipesPanel";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";

const STEPS = [
  { num: 1, label: "Input Properties" },
  { num: 2, label: "Generate 5 Recipes" },
];

function Stepper({ current }: { current: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        marginBottom: 28,
        overflowX: "auto",
      }}
    >
      {STEPS.map((step, i) => {
        const done = current > step.num;
        const active = current === step.num;
        return (
          <div
            key={step.num}
            style={{
              display: "flex",
              alignItems: "center",
              flex: i < STEPS.length - 1 ? 1 : undefined,
              minWidth: 0,
            }}
          >
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 6,
                minWidth: 120,
              }}
            >
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  background: done ? TEAL : active ? BLUE : "#E5E7EB",
                  color: done || active ? "white" : "#9CA3AF",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 700,
                  fontSize: "0.875rem",
                  flexShrink: 0,
                }}
              >
                {done ? (
                  <CheckCircle2 size={16} strokeWidth={2.5} />
                ) : (
                  step.num
                )}
              </div>
              <span
                style={{
                  fontSize: "0.7rem",
                  color: done ? TEAL : active ? BLUE : "#9CA3AF",
                  fontWeight: active ? 600 : 500,
                  textAlign: "center",
                  lineHeight: 1.3,
                  maxWidth: 130,
                }}
              >
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div
                style={{
                  flex: 1,
                  height: 2,
                  background: done ? TEAL : "#E5E7EB",
                  margin: "0 8px",
                  marginBottom: 22,
                  minWidth: 24,
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function RecipeSimulator() {
  const navigate = useNavigate();
  const { cycle, candidates, resetGenerationSession, error, loadDemoSession, demoMode, clearError } =
    useRecipe();
  const [step, setStep] = useState<number>(() => {
    const saved = sessionStorage.getItem("recipeSimulatorActiveStep");
    if (saved === "2" || saved === "1") return Number(saved);
    return 1;
  });
  const [showPrevious, setShowPrevious] = useState(false);

  // Keep step synced with sessionStorage
  useEffect(() => {
    sessionStorage.setItem("recipeSimulatorActiveStep", String(step));
  }, [step]);

  // Restore step 2 if candidates already exist and no step was explicitly set in sessionStorage
  useEffect(() => {
    const saved = sessionStorage.getItem("recipeSimulatorActiveStep");
    if (!saved && (candidates?.length > 0 || cycle?.candidates?.length > 0)) {
      setStep(2);
    }
  }, [candidates?.length, cycle?.candidates?.length]);

  // Auto-advance to Step 2 when generation completes
  const prevStatusRef = useRef<string | null>(null);
  useEffect(() => {
    if (!cycle) {
      prevStatusRef.current = null;
      return;
    }
    const prev = prevStatusRef.current;
    prevStatusRef.current = cycle.status;

    // Transition from GENERATING to STEP2 takes user to Step 2
    if (prev === "GENERATING" && cycle.status === "STEP2") {
      setStep(2);
    }
  }, [cycle?.status]);

  // Drop stale errors when entering the simulator
  useEffect(() => {
    clearError();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleGenerateNewRecipe = () => {
    if ((candidates && candidates.length > 0) || cycle) {
      const ok = window.confirm(
        "Start a new recipe generation? This will clear the active Recipe Simulator workflow."
      );
      if (!ok) return;
    }
    clearError();
    resetGenerationSession();
    sessionStorage.removeItem("recipeSimulatorActiveStep");
    setStep(1);
  };

  return (
    <div style={{ padding: "28px 32px 48px" }}>
      <div
        style={{
          marginBottom: 24,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
        }}
      >
        <div>
          <h1
            style={{
              color: BLUE,
              fontSize: "1.25rem",
              fontWeight: 700,
              marginBottom: 4,
            }}
          >
            Recipe Simulator
          </h1>
          <p style={{ color: "#6B7280", fontSize: "0.875rem" }}>
            AI-powered formulation prediction · Step {step} of {STEPS.length}
          </p>
        </div>

        <div style={{ display: "flex", gap: 12 }}>
          <button
            onClick={() => setShowPrevious(true)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              background: "white",
              border: `1px solid #E5E7EB`,
              borderRadius: 6,
              padding: "8px 16px",
              fontSize: "0.875rem",
              fontWeight: 600,
              color: "#374151",
              cursor: "pointer",
            }}
          >
            <History size={16} />
            Previous Recipes
          </button>

          <button
            onClick={handleGenerateNewRecipe}
            style={{
              background: TEAL,
              border: "none",
              borderRadius: 6,
              padding: "8px 16px",
              fontSize: "0.875rem",
              fontWeight: 600,
              color: "white",
              cursor: "pointer",
            }}
          >
            Generate New Recipe
          </button>
        </div>
      </div>

      <Stepper current={step} />

      {error && (
        <div
          style={{
            background: "#FEE2E2",
            border: "1px solid #FCA5A5",
            color: "#991B1B",
            padding: 12,
            borderRadius: 6,
            marginBottom: 24,
          }}
        >
          {error}
        </div>
      )}

      {step === 1 && (
        <Step1TargetSpec
          onBack={() => navigate("/literature-review")}
          onContinue={() => setStep(2)}
        />
      )}

      {step === 2 && (
        <Step2PolymerizationRecommendations onBack={() => setStep(1)} />
      )}

      <SavedRecipesPanel
        open={showPrevious}
        onClose={() => setShowPrevious(false)}
        mode="browse"
        kind="NORMAL"
      />
    </div>
  );
}
