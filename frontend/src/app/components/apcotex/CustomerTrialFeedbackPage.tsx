import { useEffect, useState, type CSSProperties } from "react";
import {
  History,
  Loader,
  Sparkles,
  Eye,
  Pencil,
  Save,
  CheckCircle2,
  AlertCircle,
  Clock,
  Activity,
  Layers,
  Thermometer,
  ChevronLeft,
  ChevronRight,
  X,
} from "lucide-react";
import { useRecipe } from "../../contexts/RecipeContext";
import { Step3CustomerTrialFeedback, EditableRecipeDetailTable } from "./RecipeSimulatorSteps";
import {
  SavedRecipesPanel,
  RecipePropertiesEditor,
  MetaBlock,
  DetailOverlay,
  type SavedRecipe,
} from "./SavedRecipesPanel";
import {
  convertToEditableRecipe,
  editableRecipeToRecipeData,
  getRecipeDisplayName,
  type EditableRecipe,
  type RecipeProperty,
  type EditableProcessConditions,
} from "./recipeSimulatorDemoData";
import { createSavedRecipesBatch } from "../../services/researchApi";
import { ensureDemoSavedRecipe } from "../../services/recipeDemoService";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const BORDER = "#E5E7EB";
const TEXT = "#1F2937";
const BG = "#F7FAFC";

const card: CSSProperties = {
  background: "white",
  border: `1px solid ${BORDER}`,
  borderRadius: 8,
  boxShadow: "0 1px 3px rgba(31,95,168,0.06)",
};

function fmtDate(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function CustomerTrialFeedbackPage() {
  const {
    createTrial,
    generateOptimization,
    optimizing,
    optimizedCandidates,
    trial,
    loadTrial,
    saveSavedRecipe,
    updateOptimizedCandidateData,
    error,
    resetContext,
    clearError,
    demoMode,
  } = useRecipe();

  const [showPrevious, setShowPrevious] = useState(false);
  const [showOptimized, setShowOptimized] = useState(false);

  // ── Session-Persisted Workflow State ──────────────────────────────────────────
  const [selectedRecipe, setSelectedRecipe] = useState<SavedRecipe | null>(() => {
    try {
      const stored = sessionStorage.getItem("ctf_selectedRecipe");
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  });

  const [viewStep, setViewStep] = useState<"input" | "results">(() => {
    const stored = sessionStorage.getItem("ctf_viewStep");
    if (stored === "results" || stored === "input") return stored;
    return "input";
  });

  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(() => {
    try {
      const stored = sessionStorage.getItem("ctf_selectedCandidateIds");
      return stored ? new Set(JSON.parse(stored)) : new Set();
    } catch {
      return new Set();
    }
  });

  const [editingRevisions, setEditingRevisions] = useState<EditableRecipe[]>(() => {
    try {
      const stored = sessionStorage.getItem("ctf_editingRevisions");
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const [activeModal, setActiveModal] = useState<{
    id: string;
    mode: "view" | "edit";
  } | null>(null);

  const [batchNames, setBatchNames] = useState<Record<string, string>>(() => {
    try {
      const stored = sessionStorage.getItem("ctf_batchNames");
      return stored ? JSON.parse(stored) : {};
    } catch {
      return {};
    }
  });

  const [showBatchSaveModal, setShowBatchSaveModal] = useState(false);
  const [batchSaving, setBatchSaving] = useState(false);
  const [showParentDetailModal, setShowParentDetailModal] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [seedReady, setSeedReady] = useState(!demoMode);

  // ── Session Storage Sync ──────────────────────────────────────────────────────
  useEffect(() => {
    if (selectedRecipe) {
      sessionStorage.setItem("ctf_selectedRecipe", JSON.stringify(selectedRecipe));
    } else {
      sessionStorage.removeItem("ctf_selectedRecipe");
    }
  }, [selectedRecipe]);

  useEffect(() => {
    sessionStorage.setItem("ctf_viewStep", viewStep);
  }, [viewStep]);

  useEffect(() => {
    sessionStorage.setItem(
      "ctf_selectedCandidateIds",
      JSON.stringify(Array.from(selectedCandidateIds))
    );
  }, [selectedCandidateIds]);

  useEffect(() => {
    if (Object.keys(batchNames).length > 0) {
      sessionStorage.setItem("ctf_batchNames", JSON.stringify(batchNames));
    }
  }, [batchNames]);

  useEffect(() => {
    if (editingRevisions.length > 0) {
      sessionStorage.setItem("ctf_editingRevisions", JSON.stringify(editingRevisions));
    }
  }, [editingRevisions]);

  useEffect(() => {
    if (trial?.id) {
      sessionStorage.setItem("ctf_trialId", trial.id);
    }
  }, [trial?.id]);

  // ── Session Initialization on Mount ───────────────────────────────────────────
  useEffect(() => {
    clearError();
    // Restore trial and candidates if available in sessionStorage but not loaded in context
    const storedTrialId = sessionStorage.getItem("ctf_trialId");
    if (storedTrialId && !trial && loadTrial) {
      loadTrial(storedTrialId).catch((err) => {
        console.warn("Could not restore trial from storage:", err);
      });
    }

    let cancelled = false;
    (async () => {
      if (!demoMode) {
        setSeedReady(true);
        return;
      }
      try {
        await ensureDemoSavedRecipe();
      } catch (e) {
        console.warn("Demo recipe seed skipped:", e);
      } finally {
        if (!cancelled) setSeedReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Sync editing revisions from optimizedCandidates when candidates arrive or update
  useEffect(() => {
    if (optimizedCandidates?.length) {
      setEditingRevisions((prev) => {
        if (
          prev.length === optimizedCandidates.length &&
          prev.every((p) => optimizedCandidates.some((o: any) => o.id === p.id))
        ) {
          return prev;
        }
        return optimizedCandidates.map(convertToEditableRecipe);
      });
      const names: Record<string, string> = {};
      optimizedCandidates.forEach((o: any) => {
        names[o.id] = o.name || `Revision ${o.revision_label || ""}`.trim();
      });
      setBatchNames((prev) => ({ ...names, ...prev }));
    }
  }, [optimizedCandidates]);

  const handleSelectRecipe = (recipe: SavedRecipe) => {
    setSelectedRecipe(recipe);
    setViewStep("input");
    setStatusMsg(null);
    setEditingRevisions([]);
    setSelectedCandidateIds(new Set());
    sessionStorage.removeItem("ctf_trialId");
    sessionStorage.removeItem("ctf_editingRevisions");
    sessionStorage.removeItem("ctf_selectedCandidateIds");
    sessionStorage.removeItem("ctf_batchNames");
    resetContext();
  };

  const handleChangeRecipe = () => {
    if (editingRevisions.length > 0 || trial) {
      const ok = window.confirm(
        "Change parent recipe? This will clear the current trial optimization session."
      );
      if (!ok) return;
    }
    sessionStorage.removeItem("ctf_selectedRecipe");
    sessionStorage.removeItem("ctf_trialId");
    sessionStorage.removeItem("ctf_viewStep");
    sessionStorage.removeItem("ctf_editingRevisions");
    sessionStorage.removeItem("ctf_selectedCandidateIds");
    sessionStorage.removeItem("ctf_batchNames");
    setSelectedRecipe(null);
    setEditingRevisions([]);
    setSelectedCandidateIds(new Set());
    setViewStep("input");
    setStatusMsg(null);
    resetContext();
  };

  const handleToggleSelect = (recipeId: string) => {
    setSelectedCandidateIds((prev) => {
      const next = new Set(prev);
      if (next.has(recipeId)) {
        next.delete(recipeId);
      } else {
        next.add(recipeId);
      }
      return next;
    });
  };

  const handleSubmitFeedback = async (payload: {
    feedback_text: string;
    actual_values: Record<string, string>;
    target_values: Record<string, string>;
  }) => {
    if (!selectedRecipe) return;
    setStatusMsg(null);
    try {
      const newTrial = await createTrial({
        saved_recipe_id: selectedRecipe.id,
        ...payload,
      });
      if (newTrial?.id) {
        sessionStorage.setItem("ctf_trialId", newTrial.id);
      }
      await generateOptimization();
      setViewStep("results");
      setStatusMsg("Generated exactly 3 optimized recipe revisions.");
    } catch (err: any) {
      console.error("Trial optimization failed:", err);
      setStatusMsg(err?.message || "Failed to generate optimization revisions");
      throw err;
    }
  };

  const handleGenerateRevisions = async () => {
    setStatusMsg(null);
    try {
      await generateOptimization();
      setViewStep("results");
      setStatusMsg("Regenerated 3 revised recipes.");
    } catch (e: any) {
      setStatusMsg(e?.message || "Failed to generate revisions");
    }
  };

  // Batch Save Selected Recipes (Saves exactly what the user edited!)
  const handleSaveBatch = async () => {
    if (!selectedRecipe || !trial || selectedCandidateIds.size === 0) return;
    setBatchSaving(true);
    setStatusMsg(null);
    try {
      const selectedRecipes = editingRevisions.filter((r) => selectedCandidateIds.has(r.id));

      // 1. Persist local candidate edits in backend draft
      await Promise.all(
        selectedRecipes.map((r) => {
          const customName = (batchNames[r.id] || r.name).trim() || r.name;
          const recipeData = editableRecipeToRecipeData(r);
          return updateOptimizedCandidateData(r.id, {
            recipe_data: recipeData,
            name: customName,
          }).catch((err) => console.warn("Candidate draft update skipped:", err));
        })
      );

      // 2. Prepare batch items with the FINAL EDITED RECIPE DATA!
      const batchItems = selectedRecipes.map((r) => {
        const customName = (batchNames[r.id] || r.name).trim() || r.name;
        const recipeData = editableRecipeToRecipeData(r);
        return {
          recipe_name: customName,
          recipe_data: recipeData, // FINAL EDITED VERSION
          target_properties: selectedRecipe.target_properties || [],
          competitor_properties: selectedRecipe.competitor_properties || [],
          parent_recipe_id: selectedRecipe.id,
          source_trial_id: trial.id,
          source_optimized_id: String(r.id).includes("demo") ? null : r.id,
          source_cycle_id: selectedRecipe.source_cycle_id || null,
          recipe_kind: "OPTIMIZED" as const,
        };
      });

      const res = await createSavedRecipesBatch(batchItems);
      const savedCount = res?.total_saved ?? res?.saved_count ?? batchItems.length;

      setShowBatchSaveModal(false);
      setSelectedCandidateIds(new Set());
      setStatusMsg(
        `Successfully saved ${savedCount} optimized recipe${savedCount === 1 ? "" : "s"} independently. You can open them from Previous Optimized Recipes.`
      );
    } catch (e: any) {
      console.error(e);
      setStatusMsg(e?.message || "Failed to save selected recipes");
    } finally {
      setBatchSaving(false);
    }
  };

  // ── Callbacks for Editing Revisions ──────────────────────────────────────────

  const onUpdateRecipeName = (recipeId: string, name: string) => {
    setEditingRevisions((prev) =>
      prev.map((r) => (r.id === recipeId ? { ...r, name } : r))
    );
    setSaveNames((prev) => ({ ...prev, [recipeId]: name }));
  };

  const onUpdateProperty = (
    recipeId: string,
    propertyId: string,
    updates: Partial<RecipeProperty>
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) =>
        r.id === recipeId
          ? {
              ...r,
              properties: r.properties.map((p) =>
                p.id === propertyId ? { ...p, ...updates } : p
              ),
            }
          : r
      )
    );
  };

  const onAddProperty = (recipeId: string, property: RecipeProperty) => {
    setEditingRevisions((prev) =>
      prev.map((r) =>
        r.id === recipeId ? { ...r, properties: [...r.properties, property] } : r
      )
    );
  };

  const onDeleteProperty = (recipeId: string, propertyId: string) => {
    setEditingRevisions((prev) =>
      prev.map((r) =>
        r.id === recipeId
          ? { ...r, properties: r.properties.filter((p) => p.id !== propertyId) }
          : r
      )
    );
  };

  const onUpdateStageParameter = (
    recipeId: string,
    stageId: string,
    paramId: string,
    updates: Partial<RecipeProperty>
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).map((stg) => {
          if (stg.id !== stageId) return stg;
          return {
            ...stg,
            parameters: stg.parameters.map((p) =>
              p.id === paramId ? { ...p, ...updates } : p
            ),
          };
        });
        const newProps = newStages.flatMap((s) => s.parameters);
        return {
          ...r,
          stages: newStages,
          properties: newProps.length > 0 ? newProps : r.properties,
        };
      })
    );
  };

  const onAddStageParameter = (
    recipeId: string,
    stageId: string,
    param: RecipeProperty
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).map((stg) => {
          if (stg.id !== stageId) return stg;
          return {
            ...stg,
            parameters: [...stg.parameters, param],
          };
        });
        const newProps = newStages.flatMap((s) => s.parameters);
        return {
          ...r,
          stages: newStages,
          properties: newProps.length > 0 ? newProps : r.properties,
        };
      })
    );
  };

  const onDeleteStageParameter = (
    recipeId: string,
    stageId: string,
    paramId: string
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).map((stg) => {
          if (stg.id !== stageId) return stg;
          return {
            ...stg,
            parameters: stg.parameters.filter((p) => p.id !== paramId),
          };
        });
        const newProps = newStages.flatMap((s) => s.parameters);
        return {
          ...r,
          stages: newStages,
          properties: newProps.length > 0 ? newProps : r.properties,
        };
      })
    );
  };

  const onUpdateProcessConditions = (
    recipeId: string,
    conditions: EditableProcessConditions
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) =>
        r.id === recipeId ? { ...r, process_conditions: conditions } : r
      )
    );
  };

  const onAddStage = (recipeId: string, stageName: string) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = [
          ...(r.stages || []),
          {
            id: `stage-${Date.now()}`,
            stage_name: stageName,
            parameters: [],
            is_applicable: true,
          },
        ];
        return { ...r, stages: newStages };
      })
    );
  };

  const onDeleteStage = (recipeId: string, stageId: string) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).filter((s) => s.id !== stageId);
        const newProps = newStages.flatMap((s) => s.parameters);
        return {
          ...r,
          stages: newStages,
          properties: newProps.length > 0 ? newProps : r.properties,
        };
      })
    );
  };

  const onUpdateStageName = (
    recipeId: string,
    stageId: string,
    name: string
  ) => {
    setEditingRevisions((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).map((s) =>
          s.id === stageId ? { ...s, stage_name: name } : s
        );
        return { ...r, stages: newStages };
      })
    );
  };

  const onResetRecipe = (recipeId: string) => {
    const original = optimizedCandidates.find((c: any) => c.id === recipeId);
    if (original) {
      setEditingRevisions((prev) =>
        prev.map((r) => (r.id === recipeId ? convertToEditableRecipe(original) : r))
      );
    }
  };

  const handleSaveModalEdits = async (recipeId: string) => {
    const edited = editingRevisions.find((r) => r.id === recipeId);
    if (!edited) return;
    try {
      const recipeData = editableRecipeToRecipeData(edited);
      const name = (saveNames[recipeId] || edited.name || "").trim();
      await updateOptimizedCandidateData(recipeId, {
        recipe_data: recipeData,
        name: name || undefined,
      });
      setStatusMsg(`Saved modifications to draft revision "${edited.name}".`);
    } catch (e: any) {
      console.warn("Could not persist candidate edit immediately:", e);
    }
    setActiveModal(null);
  };

  const handleSaveRevision = async (optId: string) => {
    if (!selectedRecipe || !trial) return;
    const edited = editingRevisions.find((r) => r.id === optId);
    if (!edited) return;

    setSavingId(optId);
    setStatusMsg(null);
    try {
      const recipeData = editableRecipeToRecipeData(edited);
      const name =
        (saveNames[optId] || "").trim() ||
        edited.name ||
        `Revision of ${selectedRecipe.recipe_name}`;

      // Persist user-edited recipe data to candidate draft if available
      try {
        await updateOptimizedCandidateData(optId, {
          recipe_data: recipeData,
          name,
        });
      } catch (err) {
        console.warn("Candidate pre-save update skipped:", err);
      }

      await saveSavedRecipe({
        recipe_name: name,
        recipe_data: recipeData,
        target_properties: selectedRecipe.target_properties || [],
        competitor_properties: selectedRecipe.competitor_properties || [],
        parent_recipe_id: selectedRecipe.id,
        source_trial_id: trial.id,
        source_optimized_id: String(optId).includes("demo") ? null : optId,
        source_cycle_id: selectedRecipe.source_cycle_id || null,
        recipe_kind: "OPTIMIZED",
      });
      setStatusMsg(`Successfully saved revision "${name}" to Previous Optimized Recipes.`);
    } catch (e: any) {
      setStatusMsg(e?.message || "Failed to save revision");
    } finally {
      setSavingId(null);
    }
  };

  const activeEdit = activeModal
    ? editingRevisions.find((r) => r.id === activeModal.id)
    : null;
  const activeOpt = activeModal
    ? optimizedCandidates.find((o: any) => o.id === activeModal.id)
    : null;

  return (
    <div style={{ padding: "28px 32px 48px" }}>
      <div
        style={{
          marginBottom: 24,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          flexWrap: "wrap",
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
            Trial Feedback
          </h1>
          <p style={{ color: "#6B7280", fontSize: "0.875rem", margin: 0 }}>
            Select a saved recipe, submit trial results, and generate revised formulations
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            onClick={() => setShowPrevious(true)}
            disabled={!seedReady}
            style={headerBtn(seedReady)}
          >
            <History size={16} />
            Previous Recipes
          </button>
          <button
            onClick={() => setShowOptimized(true)}
            disabled={!seedReady}
            style={headerBtn(seedReady)}
          >
            <Sparkles size={16} />
            Previous Optimized Recipes
          </button>
        </div>
      </div>

      {(error || statusMsg) && (
        <div
          style={{
            background:
              error || statusMsg?.includes("Failed")
                ? "#FEE2E2"
                : "rgba(31,183,181,0.1)",
            border: `1px solid ${
              error || statusMsg?.includes("Failed") ? "#FCA5A5" : TEAL
            }`,
            color:
              error || statusMsg?.includes("Failed") ? "#991B1B" : "#0F766E",
            padding: 12,
            borderRadius: 6,
            marginBottom: 20,
            fontSize: "0.875rem",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          {error || statusMsg?.includes("Failed") ? (
            <AlertCircle size={16} />
          ) : (
            <CheckCircle2 size={16} />
          )}
          <span>{error || statusMsg}</span>
        </div>
      )}

      {!selectedRecipe ? (
        <div
          style={{
            ...card,
            padding: 40,
            textAlign: "center",
          }}
        >
          <p style={{ color: "#6B7280", marginBottom: 16, fontSize: "0.9375rem" }}>
            Select a recipe to submit trial feedback and optimize.
          </p>
          <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
            <button onClick={() => setShowPrevious(true)} style={tealBtn}>
              Open Previous Recipe
            </button>
            <button onClick={() => setShowOptimized(true)} style={tealBtn}>
              Open Optimized Recipe
            </button>
          </div>
        </div>
      ) : (
        <>
          <div style={{ ...card, padding: 20, marginBottom: 20 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: "0.7rem",
                    fontWeight: 700,
                    color: BLUE,
                    textTransform: "uppercase",
                    marginBottom: 4,
                  }}
                >
                  Selected Recipe
                </div>
                <h2
                  style={{
                    margin: "0 0 8px",
                    color: TEXT,
                    fontSize: "1.05rem",
                    fontWeight: 700,
                  }}
                >
                  {getRecipeDisplayName(selectedRecipe)}
                </h2>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 10,
                    fontSize: "0.8125rem",
                    color: "#6B7280",
                  }}
                >
                  <span>
                    Created by:{" "}
                    <strong style={{ color: TEXT }}>
                      {selectedRecipe.created_by_name || "—"}
                    </strong>
                  </span>
                  <span>·</span>
                  <span>Created: {fmtDate(selectedRecipe.created_at)}</span>
                  <span>·</span>
                  <span>Updated: {fmtDate(selectedRecipe.updated_at)}</span>
                  <span>·</span>
                  <span>Expires: {fmtDate(selectedRecipe.expires_at)}</span>
                  <span>·</span>
                  <span
                    style={{
                      background:
                        selectedRecipe.recipe_kind === "OPTIMIZED"
                          ? "rgba(31,183,181,0.12)"
                          : "rgba(31,95,168,0.1)",
                      color:
                        selectedRecipe.recipe_kind === "OPTIMIZED" ? TEAL : BLUE,
                      padding: "1px 8px",
                      borderRadius: 10,
                      fontWeight: 600,
                    }}
                  >
                    {selectedRecipe.recipe_kind === "OPTIMIZED"
                      ? "Optimized"
                      : "Original"}
                  </span>
                  {(selectedRecipe.optimization_number ||
                    selectedRecipe.revision_number) > 0 && (
                    <>
                      <span>·</span>
                      <span>
                        Optimization:{" "}
                        {selectedRecipe.optimization_number ??
                          selectedRecipe.revision_number}
                      </span>
                    </>
                  )}
                  {selectedRecipe.parent_recipe_name && (
                    <>
                      <span>·</span>
                      <span>Parent: {getRecipeDisplayName({ recipe_name: selectedRecipe.parent_recipe_name })}</span>
                    </>
                  )}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <button
                  onClick={() => setShowParentDetailModal(true)}
                  style={{
                    ...outlineBtn,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    color: BLUE,
                    borderColor: BLUE,
                    fontWeight: 700,
                  }}
                  title="View complete structure, stages, parameters, and process conditions of the selected parent recipe"
                >
                  <Eye size={15} /> View Parent Recipe
                </button>
                <button onClick={() => setShowPrevious(true)} style={outlineBtn}>
                  Open Previous Recipe
                </button>
                <button onClick={() => setShowOptimized(true)} style={outlineBtn}>
                  Open Optimized Recipe
                </button>
                <button onClick={handleChangeRecipe} style={outlineBtn}>
                  Change Recipe
                </button>
              </div>
            </div>
          </div>

          {viewStep === "input" && (
            <div>
              {editingRevisions.length > 0 && (
                <div
                  style={{
                    background: "rgba(31,183,181,0.08)",
                    border: `1.5px solid ${TEAL}`,
                    borderRadius: 8,
                    padding: "12px 18px",
                    marginBottom: 18,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <CheckCircle2 size={18} color={TEAL} />
                    <span style={{ fontSize: "0.875rem", fontWeight: 600, color: BLUE }}>
                      {editingRevisions.length} optimized recipe revisions have been generated for this trial.
                    </span>
                  </div>
                  <button
                    onClick={() => setViewStep("results")}
                    style={{
                      background: TEAL,
                      color: "white",
                      border: "none",
                      borderRadius: 6,
                      padding: "8px 16px",
                      fontSize: "0.8125rem",
                      fontWeight: 700,
                      cursor: "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                    title="Return to existing generated optimized recipes without regenerating"
                  >
                    Next: View Generated Recipes <ChevronRight size={15} />
                  </button>
                </div>
              )}

              <Step3CustomerTrialFeedback
                selectedRecipeName={getRecipeDisplayName(selectedRecipe)}
                submitLabel="Optimize Recipe"
                hideBack
                onNext={editingRevisions.length > 0 ? () => setViewStep("results") : undefined}
                nextLabel="Next"
                onSubmitFeedback={handleSubmitFeedback}
              />
            </div>
          )}

          {viewStep === "results" && (
            <div style={{ marginBottom: 24 }}>
              {/* Results Header with Back and Regenerate buttons */}
              <div
                style={{
                  ...card,
                  padding: 18,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 16,
                  flexWrap: "wrap",
                  marginBottom: 20,
                  borderLeft: `4px solid ${TEAL}`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <button
                    onClick={() => setViewStep("input")}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      background: "white",
                      border: `1px solid ${BORDER}`,
                      borderRadius: 6,
                      padding: "8px 14px",
                      fontSize: "0.8125rem",
                      fontWeight: 600,
                      color: "#374151",
                      cursor: "pointer",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
                    }}
                    title="Return to trial feedback input without regenerating or losing recipes"
                  >
                    <ChevronLeft size={16} /> Back
                  </button>
                  <div>
                    <h3
                      style={{
                        margin: "0 0 2px",
                        color: BLUE,
                        fontSize: "1rem",
                        fontWeight: 700,
                      }}
                    >
                      Optimized Recipe Recommendations
                    </h3>
                    <p style={{ margin: 0, color: "#6B7280", fontSize: "0.8125rem" }}>
                      3 formulation revisions generated from trial feedback and target specifications.
                    </p>
                  </div>
                </div>

                <button
                  onClick={handleGenerateRevisions}
                  disabled={optimizing}
                  style={{
                    background: optimizing ? "#9CA3AF" : TEAL,
                    color: "white",
                    border: "none",
                    borderRadius: 7,
                    padding: "10px 20px",
                    fontSize: "0.8125rem",
                    fontWeight: 700,
                    cursor: optimizing ? "not-allowed" : "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                  title="Explicitly call LLM again to re-optimize recipes"
                >
                  {optimizing ? (
                    <>
                      <Loader size={16} style={{ animation: "spin 1s linear infinite" }} />
                      Optimizing…
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} /> Regenerate 3 Revised Recipes
                    </>
                  )}
                </button>
              </div>

              {/* Candidate Recipe Cards */}
              {editingRevisions.map((recipe) => {
                const opt = optimizedCandidates.find((o: any) => o.id === recipe.id);
                const isSelected = selectedCandidateIds.has(recipe.id);
                const changes =
                  opt?.changed_parameters ||
                  opt?.optimization_details?.changes ||
                  (recipe.raw_data && recipe.raw_data.changed_parameters) ||
                  [];
                const confidence =
                  opt?.confidence_score ??
                  (recipe.raw_data && recipe.raw_data.confidence_score) ??
                  recipe.confidence ??
                  75;
                const strategy =
                  opt?.optimization_strategy ||
                  (recipe.raw_data && recipe.raw_data.optimization_strategy) ||
                  "Target Optimization Strategy";
                const outcome =
                  opt?.expected_outcome ||
                  (recipe.raw_data && recipe.raw_data.expected_outcome) ||
                  "Revision designed to address trial requirements while balancing colloidal stability.";
                const impact =
                  opt?.expected_impact ||
                  (recipe.raw_data && recipe.raw_data.expected_impact) ||
                  "Adjusts synthesis levers to satisfy target specifications without compromising processing consistency.";
                const tradeoffs =
                  opt?.tradeoffs ||
                  (recipe.raw_data && recipe.raw_data.tradeoffs);

                const candCompound =
                  opt?.recipe_data?.compound ||
                  recipe.raw_data?.compound ||
                  selectedRecipe?.recipe_data?.compound;
                const candProcessType =
                  opt?.recipe_data?.process_type ||
                  opt?.recipe_data?.process_conditions?.process_type ||
                  recipe.raw_data?.process_type ||
                  recipe.raw_data?.process_conditions?.process_type;
                const candTemp =
                  opt?.recipe_data?.temperature_range ||
                  opt?.recipe_data?.process_conditions?.temperature_range ||
                  recipe.raw_data?.temperature_range ||
                  recipe.raw_data?.process_conditions?.temperature_range;
                const candTempStr = candTemp
                  ? typeof candTemp === "object"
                    ? `${candTemp.min}–${candTemp.max} ${candTemp.unit || "°C"}`
                    : String(candTemp)
                  : null;

                const catalystSys =
                  opt?.recipe_data?.catalyst_system ||
                  recipe.raw_data?.catalyst_system;
                const activatorSys =
                  opt?.recipe_data?.activator_system ||
                  recipe.raw_data?.activator_system;
                const coagulationSys =
                  opt?.recipe_data?.coagulation_system ||
                  recipe.raw_data?.coagulation_system;

                const evaluatedProps: any[] =
                  opt?.recipe_data?.target_analysis?.evaluated_properties ||
                  opt?.target_analysis?.evaluated_properties ||
                  recipe.raw_data?.target_analysis?.evaluated_properties ||
                  [];

                return (
                  <div
                    key={recipe.id}
                    style={{
                      ...card,
                      padding: 20,
                      marginBottom: 20,
                      border: isSelected ? `2px solid ${TEAL}` : `1px solid ${BORDER}`,
                      boxShadow: isSelected
                        ? "0 4px 14px rgba(31,183,181,0.18)"
                        : "0 1px 3px rgba(0,0,0,0.05)",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "flex-start",
                        marginBottom: 14,
                        gap: 12,
                        flexWrap: "wrap",
                      }}
                    >
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                          <h4 style={{ margin: 0, color: BLUE, fontSize: "1.05rem", fontWeight: 700 }}>
                            {recipe.name}
                            {opt?.revision_label ? ` (${opt.revision_label})` : ""}
                          </h4>
                          {isSelected && (
                            <span
                              style={{
                                background: "rgba(31,183,181,0.15)",
                                color: TEAL,
                                fontWeight: 700,
                                fontSize: "0.75rem",
                                padding: "2px 10px",
                                borderRadius: 12,
                                border: `1px solid ${TEAL}`,
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 4,
                              }}
                            >
                              <CheckCircle2 size={13} color={TEAL} /> Selected
                            </span>
                          )}
                          {candCompound && (
                            <span
                              style={{
                                background: "rgba(31,95,168,0.08)",
                                color: BLUE,
                                fontWeight: 700,
                                fontSize: "0.75rem",
                                padding: "2px 10px",
                                borderRadius: 12,
                                border: `1px solid rgba(31,95,168,0.25)`,
                              }}
                            >
                              Polymer: {candCompound}
                            </span>
                          )}
                          {candProcessType && (
                            <span
                              style={{
                                background: "rgba(107,114,128,0.1)",
                                color: "#374151",
                                fontWeight: 700,
                                fontSize: "0.75rem",
                                padding: "2px 10px",
                                borderRadius: 12,
                                border: `1px solid rgba(107,114,128,0.25)`,
                              }}
                            >
                              Process: {candProcessType}
                            </span>
                          )}
                          {candTempStr && (
                            <span
                              style={{
                                background: "rgba(245,158,11,0.1)",
                                color: "#B45309",
                                fontWeight: 700,
                                fontSize: "0.75rem",
                                padding: "2px 10px",
                                borderRadius: 12,
                                border: `1px solid rgba(245,158,11,0.3)`,
                              }}
                            >
                              Temp: {candTempStr}
                            </span>
                          )}
                          <span
                            style={{
                              background: "rgba(31,183,181,0.12)",
                              color: "#0D9488",
                              fontWeight: 700,
                              fontSize: "0.75rem",
                              padding: "2px 10px",
                              borderRadius: 12,
                              border: `1px solid rgba(31,183,181,0.3)`,
                            }}
                          >
                            {strategy}
                          </span>
                          {/* Target Fit Badge */}
                          <span
                            style={{
                              background: (opt?.target_fit_score !== null && opt?.target_fit_score !== undefined)
                                ? "rgba(16,185,129,0.12)"
                                : (recipe.targetFit !== null && recipe.targetFit !== undefined)
                                  ? "rgba(16,185,129,0.12)"
                                  : "rgba(100,116,139,0.1)",
                              color: (opt?.target_fit_score !== null && opt?.target_fit_score !== undefined)
                                ? "#059669"
                                : (recipe.targetFit !== null && recipe.targetFit !== undefined)
                                  ? "#059669"
                                  : "#475569",
                              fontWeight: 700,
                              fontSize: "0.75rem",
                              padding: "2px 10px",
                              borderRadius: 12,
                              border: `1px solid rgba(16,185,129,0.3)`,
                            }}
                          >
                            Target Fit: {opt?.target_fit_score !== null && opt?.target_fit_score !== undefined
                              ? `${opt.target_fit_score}%`
                              : (recipe.targetFit !== null && recipe.targetFit !== undefined
                                ? `${recipe.targetFit}%`
                                : "N/A")}
                          </span>
                          {/* Targets Met Badge if targets exist */}
                          {(opt?.targets_total || recipe.targetsTotal) ? (
                            <span
                              style={{
                                background: (opt?.targets_met === opt?.targets_total)
                                  ? "rgba(16,185,129,0.12)"
                                  : "rgba(239,68,68,0.12)",
                                color: (opt?.targets_met === opt?.targets_total)
                                  ? "#059669"
                                  : "#DC2626",
                                fontWeight: 700,
                                fontSize: "0.75rem",
                                padding: "2px 10px",
                                borderRadius: 12,
                                border: `1px solid rgba(16,185,129,0.3)`,
                              }}
                            >
                              Targets Met: {opt?.targets_met ?? recipe.targetsMet ?? 0}/{opt?.targets_total ?? recipe.targetsTotal ?? 0}
                            </span>
                          ) : null}
                          <span
                            style={{
                              background: "rgba(31,95,168,0.1)",
                              color: BLUE,
                              fontWeight: 700,
                              fontSize: "0.75rem",
                              padding: "2px 10px",
                              borderRadius: 12,
                              border: `1px solid rgba(31,95,168,0.2)`,
                            }}
                            title="Dynamic confidence score derived from context, formulation feasibility, and target alignment"
                          >
                            Confidence: {confidence}%
                          </span>
                        </div>
                      </div>

                      {/* Interaction Actions: [ View ] [ Edit ] [ Select ] */}
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <button
                          onClick={() => setActiveModal({ id: recipe.id, mode: "view" })}
                          style={actionBtn}
                          title="View complete formulation in read-only modal"
                        >
                          <Eye size={14} /> View
                        </button>
                        <button
                          onClick={() => setActiveModal({ id: recipe.id, mode: "edit" })}
                          style={{
                            ...actionBtn,
                            background: BLUE,
                            color: "white",
                            border: "none",
                          }}
                          title="Edit recipe parameters, stages, and process conditions"
                        >
                          <Pencil size={14} /> Edit
                        </button>
                        <button
                          onClick={() => handleToggleSelect(recipe.id)}
                          style={{
                            border: `1.5px solid ${isSelected ? TEAL : BORDER}`,
                            color: isSelected ? TEAL : BLUE,
                            background: isSelected ? "rgba(31,183,181,0.12)" : "white",
                            borderRadius: 6,
                            padding: "6px 14px",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                            cursor: "pointer",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                          title={isSelected ? "Deselect candidate" : "Select candidate for saving"}
                        >
                          {isSelected && <CheckCircle2 size={13} color={TEAL} />}
                          {isSelected ? "Selected" : "Select"}
                        </button>
                      </div>
                    </div>

                    {/* Expected Outcome Callout */}
                    <div
                      style={{
                        background: "rgba(31,183,181,0.06)",
                        borderLeft: `3px solid ${TEAL}`,
                        borderRadius: "0 6px 6px 0",
                        padding: "10px 14px",
                        marginBottom: 10,
                        fontSize: "0.8125rem",
                        color: "#1F2937",
                        lineHeight: 1.5,
                      }}
                    >
                      <strong style={{ color: BLUE }}>Expected Outcome:</strong>{" "}
                      {outcome}
                    </div>

                    {/* Expected Impact & Tradeoffs Callout */}
                    <div
                      style={{
                        background: "rgba(31,95,168,0.05)",
                        borderLeft: `3px solid ${BLUE}`,
                        borderRadius: "0 6px 6px 0",
                        padding: "10px 14px",
                        marginBottom: 14,
                        fontSize: "0.8125rem",
                        color: "#1F2937",
                        lineHeight: 1.5,
                      }}
                    >
                      <div>
                        <strong style={{ color: BLUE }}>Expected Impact:</strong>{" "}
                        {impact}
                      </div>
                      {tradeoffs && (
                        <div style={{ marginTop: 4, color: "#4B5563" }}>
                          <strong style={{ color: "#4B5563" }}>Tradeoffs:</strong>{" "}
                          {tradeoffs}
                        </div>
                      )}
                    </div>

                    {/* Technical Systems: Catalyst, Activator, Coagulation */}
                    {(catalystSys || activatorSys || coagulationSys) && (
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                          gap: 10,
                          marginBottom: 14,
                        }}
                      >
                        {catalystSys && (
                          <div
                            style={{
                              background: "#F8FAFC",
                              border: `1px solid ${BORDER}`,
                              borderRadius: 6,
                              padding: "10px 12px",
                              fontSize: "0.8125rem",
                            }}
                          >
                            <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                              Catalyst / Initiator System
                            </div>
                            <div style={{ color: TEXT, fontWeight: 600 }}>
                              {catalystSys.primary_catalyst || "Primary Initiator"} ({catalystSys.primary_dosage || "0.35 phr"})
                            </div>
                            {catalystSys.alternatives && catalystSys.alternatives.length > 0 ? (
                              <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                                <em>Alternatives:</em>{" "}
                                {catalystSys.alternatives.map((a: any) => `${a.catalyst || a.name} (${a.dosage || "alt"})`).join("; ")}
                              </div>
                            ) : (
                              <div style={{ fontSize: "0.75rem", color: "#94A3B8", marginTop: 4 }}>
                                No validated alternative identified
                              </div>
                            )}
                          </div>
                        )}

                        {activatorSys && (
                          <div
                            style={{
                              background: "#F8FAFC",
                              border: `1px solid ${BORDER}`,
                              borderRadius: 6,
                              padding: "10px 12px",
                              fontSize: "0.8125rem",
                            }}
                          >
                            <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                              Activator System
                            </div>
                            {activatorSys.applicable ? (
                              <>
                                <div style={{ color: TEXT, fontWeight: 600 }}>
                                  {activatorSys.name || activatorSys.activator_name || "Redox Activator"} ({activatorSys.dosage || "0.10 phr"})
                                </div>
                                <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                                  Stage: {activatorSys.stage || activatorSys.addition_stage || "Catalyst Solution"}
                                </div>
                              </>
                            ) : (
                              <div style={{ color: "#64748B", fontStyle: "italic" }}>
                                Not applicable / Not required
                              </div>
                            )}
                          </div>
                        )}

                        {coagulationSys && (
                          <div
                            style={{
                              background: "#F8FAFC",
                              border: `1px solid ${BORDER}`,
                              borderRadius: 6,
                              padding: "10px 12px",
                              fontSize: "0.8125rem",
                            }}
                          >
                            <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                              Coagulation System
                            </div>
                            {coagulationSys.applicable ? (
                              <>
                                <div style={{ color: TEXT, fontWeight: 600 }}>
                                  {coagulationSys.coagulant || coagulationSys.coagulant_name || "Coagulant"} ({coagulationSys.dosage || "2.0 phr"})
                                </div>
                                <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                                  Conditions: {coagulationSys.process_conditions || "Standard coagulation"}
                                </div>
                              </>
                            ) : (
                              <div style={{ color: "#64748B", fontStyle: "italic" }}>
                                Not applicable / Not required
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}

                    {/* Target Properties Evaluation Table */}
                    {evaluatedProps.length > 0 && (
                      <div style={{ marginBottom: 14 }}>
                        <div
                          style={{
                            fontSize: "0.75rem",
                            fontWeight: 700,
                            color: BLUE,
                            marginBottom: 8,
                            textTransform: "uppercase",
                          }}
                        >
                          Target Properties Evaluation
                        </div>
                        <table
                          style={{
                            width: "100%",
                            borderCollapse: "collapse",
                            fontSize: "0.8125rem",
                          }}
                        >
                          <thead>
                            <tr style={{ background: BG }}>
                              {["Property", "Target / Range", "Prediction", "Status", "Rationale"].map((col) => (
                                <th
                                  key={col}
                                  style={{
                                    padding: "8px 10px",
                                    textAlign: "left",
                                    border: `1px solid ${BORDER}`,
                                    color: BLUE,
                                    fontSize: "0.75rem",
                                    fontWeight: 700,
                                  }}
                                >
                                  {col}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {evaluatedProps.map((p: any, idx: number) => {
                              const isMet = p.passed ?? p.meets_target ?? (p.status === "MEETS_TARGET" || p.target_status === "MEETS TARGET");
                              return (
                                <tr key={p.property || p.name || idx}>
                                  <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}`, fontWeight: 600, color: TEXT }}>
                                    {p.property || p.name}
                                  </td>
                                  <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}`, color: "#374151" }}>
                                    {p.target_display || p.target || p.target_value || "—"}
                                  </td>
                                  <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}`, fontWeight: 600, color: TEXT }}>
                                    {p.predicted_display || (p.predicted_value !== undefined ? String(p.predicted_value) : "—")}
                                  </td>
                                  <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}` }}>
                                    <span
                                      style={{
                                        display: "inline-block",
                                        padding: "2px 8px",
                                        borderRadius: 12,
                                        fontSize: "0.72rem",
                                        fontWeight: 700,
                                        background: isMet ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                                        color: isMet ? "#059669" : "#DC2626",
                                        border: `1px solid ${isMet ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)"}`,
                                      }}
                                    >
                                      {isMet ? "MEETS TARGET" : "OUTSIDE TARGET"}
                                    </span>
                                  </td>
                                  <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}`, color: "#4B5563", fontSize: "0.75rem" }}>
                                    {p.reasoning || "—"}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Modified Parameters comparison table */}
                    {changes.length > 0 && (
                      <div style={{ marginBottom: 4 }}>
                        <div
                          style={{
                            fontSize: "0.75rem",
                            fontWeight: 700,
                            color: BLUE,
                            marginBottom: 8,
                            textTransform: "uppercase",
                          }}
                        >
                          Modified Parameters
                        </div>
                        <table
                          style={{
                            width: "100%",
                            borderCollapse: "collapse",
                            fontSize: "0.8125rem",
                          }}
                        >
                          <thead>
                            <tr style={{ background: BG }}>
                              {["Parameter", "Previous", "Revised", "Unit", "Rationale"].map(
                                (col) => (
                                  <th
                                    key={col}
                                    style={{
                                      padding: "8px 10px",
                                      textAlign: "left",
                                      border: `1px solid ${BORDER}`,
                                      color: BLUE,
                                      fontSize: "0.75rem",
                                      fontWeight: 700,
                                    }}
                                  >
                                    {col}
                                  </th>
                                )
                              )}
                            </tr>
                          </thead>
                          <tbody>
                            {changes.map((change: any, idx: number) => (
                              <tr key={change.parameter || change.name || idx}>
                                <td
                                  style={{
                                    padding: "8px 10px",
                                    border: `1px solid ${BORDER}`,
                                    fontWeight: 600,
                                    color: TEXT,
                                  }}
                                >
                                  {change.parameter || change.name}
                                </td>
                                <td
                                  style={{
                                    padding: "8px 10px",
                                    border: `1px solid ${BORDER}`,
                                    color: "#6B7280",
                                  }}
                                >
                                  {change.previous ?? change.old_value ?? change.original ?? "—"}
                                </td>
                                <td
                                  style={{
                                    padding: "8px 10px",
                                    border: `1px solid ${BORDER}`,
                                    color: TEAL,
                                    fontWeight: 700,
                                  }}
                                >
                                  {change.revised ?? change.new_value ?? change.value ?? "—"}
                                </td>
                                <td
                                  style={{
                                    padding: "8px 10px",
                                    border: `1px solid ${BORDER}`,
                                    color: "#6B7280",
                                  }}
                                >
                                  {change.unit || "phr"}
                                </td>
                                <td
                                  style={{
                                    padding: "8px 10px",
                                    border: `1px solid ${BORDER}`,
                                    color: "#4B5563",
                                    fontSize: "0.75rem",
                                  }}
                                >
                                  {change.reason || change.impact || "Target modification"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Multi-Select Action Area at bottom of candidates */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  flexWrap: "wrap",
                  gap: 12,
                  padding: "14px 20px",
                  marginTop: 10,
                  marginBottom: 24,
                  borderRadius: 8,
                  background: selectedCandidateIds.size > 0 ? "rgba(31,183,181,0.08)" : "#F9FAFB",
                  border: `1.5px solid ${selectedCandidateIds.size > 0 ? TEAL : BORDER}`,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                  <button
                    onClick={() => setViewStep("input")}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                      background: "white",
                      border: `1px solid ${BORDER}`,
                      borderRadius: 6,
                      padding: "8px 16px",
                      fontSize: "0.8125rem",
                      fontWeight: 600,
                      color: "#374151",
                      cursor: "pointer",
                    }}
                    title="Return to trial feedback input while preserving generated revisions"
                  >
                    <ChevronLeft size={16} /> Back
                  </button>
                  <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                    {selectedCandidateIds.size > 0
                      ? `Selected: ${selectedCandidateIds.size} recipe${selectedCandidateIds.size === 1 ? "" : "s"}`
                      : "Select one or more recipes to save"}
                  </span>
                  {editingRevisions.length > 0 && (
                    <button
                      onClick={() => {
                        if (selectedCandidateIds.size === editingRevisions.length) {
                          setSelectedCandidateIds(new Set());
                        } else {
                          setSelectedCandidateIds(new Set(editingRevisions.map((r) => r.id)));
                        }
                      }}
                      style={{
                        background: "none",
                        border: "none",
                        color: TEAL,
                        fontWeight: 600,
                        fontSize: "0.8125rem",
                        cursor: "pointer",
                        textDecoration: "underline",
                      }}
                    >
                      {selectedCandidateIds.size === editingRevisions.length
                        ? "Deselect All"
                        : `Select All (${editingRevisions.length})`}
                    </button>
                  )}
                </div>

                <button
                  onClick={() => setShowBatchSaveModal(true)}
                  disabled={selectedCandidateIds.size === 0}
                  style={{
                    background: TEAL,
                    color: "white",
                    border: "none",
                    borderRadius: 7,
                    padding: "10px 22px",
                    fontSize: "0.8125rem",
                    fontWeight: 700,
                    cursor: selectedCandidateIds.size === 0 ? "not-allowed" : "pointer",
                    opacity: selectedCandidateIds.size === 0 ? 0.5 : 1,
                    boxShadow: selectedCandidateIds.size > 0 ? "0 2px 4px rgba(31,183,181,0.25)" : "none",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                  }}
                >
                  Save Selected Recipes {selectedCandidateIds.size > 0 ? `(${selectedCandidateIds.size})` : ""}
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Multi-Select Batch Save Dialog ──────────────────────────────────── */}
      {showBatchSaveModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 10000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
          onClick={() => !batchSaving && setShowBatchSaveModal(false)}
        >
          <div
            style={{
              background: "white",
              borderRadius: 10,
              maxWidth: 580,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              padding: 24,
              boxShadow: "0 10px 30px rgba(0,0,0,0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <h3 style={{ margin: 0, color: BLUE, fontSize: "1.0625rem", fontWeight: 700 }}>
                Save Selected Optimized Recipes ({selectedCandidateIds.size})
              </h3>
              <button
                onClick={() => setShowBatchSaveModal(false)}
                disabled={batchSaving}
                style={{ background: "none", border: "none", cursor: "pointer", color: "#6B7280", fontSize: "1.25rem" }}
              >
                ✕
              </button>
            </div>
            <p style={{ margin: "0 0 16px", color: "#4B5563", fontSize: "0.8125rem", lineHeight: 1.5 }}>
              Specify an independent custom name for each selected recipe before saving to Previous Optimized Recipes:
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 }}>
              {editingRevisions
                .filter((r) => selectedCandidateIds.has(r.id))
                .map((r, idx) => {
                  const opt = optimizedCandidates.find((o: any) => o.id === r.id);
                  const confidence =
                    opt?.confidence_score ??
                    (r.raw_data && r.raw_data.confidence_score) ??
                    r.confidence ??
                    80;
                  return (
                    <div
                      key={r.id}
                      style={{
                        background: BG,
                        border: `1px solid ${BORDER}`,
                        borderRadius: 8,
                        padding: 12,
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <span style={{ fontSize: "0.75rem", fontWeight: 700, color: BLUE }}>
                          {idx + 1}. {r.name} {opt?.revision_label ? `(${opt.revision_label})` : ""}
                        </span>
                        <span style={{ fontSize: "0.75rem", color: TEAL, fontWeight: 600 }}>
                          Confidence: {confidence}%
                        </span>
                      </div>
                      <input
                        type="text"
                        value={batchNames[r.id] ?? r.name}
                        onChange={(e) =>
                          setBatchNames((prev) => ({ ...prev, [r.id]: e.target.value }))
                        }
                        placeholder={`Name for Revision ${opt?.revision_label || idx + 1}`}
                        style={{
                          padding: "8px 10px",
                          border: `1px solid ${BORDER}`,
                          borderRadius: 6,
                          fontSize: "0.875rem",
                          color: TEXT,
                          background: "white",
                          fontWeight: 600,
                        }}
                      />
                    </div>
                  );
                })}
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                onClick={() => setShowBatchSaveModal(false)}
                disabled={batchSaving}
                style={{
                  background: "white",
                  color: "#4B5563",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 6,
                  padding: "8px 16px",
                  fontSize: "0.8125rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSaveBatch}
                disabled={batchSaving}
                style={{
                  background: TEAL,
                  color: "white",
                  border: "none",
                  borderRadius: 6,
                  padding: "9px 20px",
                  fontSize: "0.8125rem",
                  fontWeight: 700,
                  cursor: batchSaving ? "not-allowed" : "pointer",
                  opacity: batchSaving ? 0.7 : 1,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                {batchSaving ? <Loader size={14} style={{ animation: "spin 1s linear infinite" }} /> : null}
                {batchSaving ? "Saving Selected…" : `Save Selected (${selectedCandidateIds.size})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Parent Recipe View Modal ────────────────────────────────────────── */}
      {showParentDetailModal && selectedRecipe && (
        <DetailOverlay
          title={`Parent Recipe: ${getRecipeDisplayName(selectedRecipe)} (${selectedRecipe.recipe_kind === "OPTIMIZED" ? "Optimized" : "Original"})`}
          onClose={() => setShowParentDetailModal(false)}
        >
          <MetaBlock recipe={selectedRecipe} />
          <RecipePropertiesEditor
            recipe={convertToEditableRecipe({
              id: selectedRecipe.id,
              name: selectedRecipe.recipe_name,
              recipe_data: selectedRecipe.recipe_data,
              evidence_coverage_score: 0,
              patent_references: [],
              rank: 0,
            })}
            readOnly
          />
        </DetailOverlay>
      )}

      {/* Panels for Opening Saved Recipes */}
      <SavedRecipesPanel
        open={showPrevious}
        onClose={() => setShowPrevious(false)}
        mode="select"
        kind="NORMAL"
        onSelect={handleSelectRecipe}
      />
      <SavedRecipesPanel
        open={showOptimized}
        onClose={() => setShowOptimized(false)}
        mode="select"
        kind="OPTIMIZED"
        onSelect={handleSelectRecipe}
      />

      {/* ── View Modal (Structured Vertical Formulation) ────────────────────── */}
      {activeModal && activeModal.mode === "view" && activeEdit && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
          onClick={() => setActiveModal(null)}
        >
          <div
            style={{
              background: "white",
              borderRadius: 8,
              padding: 24,
              maxWidth: 820,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              position: "relative",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setActiveModal(null)}
              style={{
                position: "absolute",
                top: 16,
                right: 16,
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "1.5rem",
                lineHeight: 1,
                color: "#6B7280",
              }}
            >
              &times;
            </button>

            <div style={{ marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
                <h3 style={{ margin: 0, color: BLUE, fontSize: "1.125rem", fontWeight: 700 }}>
                  {activeEdit.name}
                </h3>
                {(activeOpt?.recipe_data?.compound || activeEdit.raw_data?.compound || selectedRecipe?.recipe_data?.compound) && (
                  <span
                    style={{
                      background: "rgba(31,95,168,0.08)",
                      color: BLUE,
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      padding: "2px 10px",
                      borderRadius: 12,
                      border: `1px solid rgba(31,95,168,0.25)`,
                    }}
                  >
                    Polymer: {activeOpt?.recipe_data?.compound || activeEdit.raw_data?.compound || selectedRecipe?.recipe_data?.compound}
                  </span>
                )}
                {(activeOpt?.recipe_data?.process_type || activeOpt?.recipe_data?.process_conditions?.process_type || activeEdit.raw_data?.process_type) && (
                  <span
                    style={{
                      background: "rgba(107,114,128,0.1)",
                      color: "#374151",
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      padding: "2px 10px",
                      borderRadius: 12,
                      border: `1px solid rgba(107,114,128,0.25)`,
                    }}
                  >
                    Process: {activeOpt?.recipe_data?.process_type || activeOpt?.recipe_data?.process_conditions?.process_type || activeEdit.raw_data?.process_type}
                  </span>
                )}
                <span
                  style={{
                    background: "rgba(31,95,168,0.1)",
                    color: BLUE,
                    fontWeight: 700,
                    fontSize: "0.75rem",
                    padding: "3px 10px",
                    borderRadius: 12,
                    border: `1px solid rgba(31,95,168,0.2)`,
                  }}
                >
                  Confidence Score:{" "}
                  {activeOpt?.confidence_score ??
                    (activeEdit.raw_data && activeEdit.raw_data.confidence_score) ??
                    activeEdit.confidence ??
                    75}%
                </span>
                {activeOpt?.optimization_strategy && (
                  <span
                    style={{
                      background: "rgba(31,183,181,0.12)",
                      color: "#0D9488",
                      fontWeight: 700,
                      fontSize: "0.75rem",
                      padding: "3px 10px",
                      borderRadius: 12,
                    }}
                  >
                    {activeOpt.optimization_strategy}
                  </span>
                )}
              </div>
            </div>

            {/* Expected Outcome & Impact in View Modal */}
            <div
              style={{
                background: "rgba(31,183,181,0.06)",
                borderLeft: `3px solid ${TEAL}`,
                borderRadius: "0 6px 6px 0",
                padding: "10px 14px",
                marginBottom: 10,
                fontSize: "0.8125rem",
                color: TEXT,
              }}
            >
              <strong style={{ color: BLUE }}>Expected Outcome:</strong>{" "}
              {activeOpt?.expected_outcome ||
                (activeEdit.raw_data && activeEdit.raw_data.expected_outcome) ||
                "Formulation optimized to satisfy trial objectives."}
            </div>

            <div
              style={{
                background: "rgba(31,95,168,0.05)",
                borderLeft: `3px solid ${BLUE}`,
                borderRadius: "0 6px 6px 0",
                padding: "10px 14px",
                marginBottom: 16,
                fontSize: "0.8125rem",
                color: TEXT,
              }}
            >
              <div>
                <strong style={{ color: BLUE }}>Expected Impact:</strong>{" "}
                {activeOpt?.expected_impact ||
                  (activeEdit.raw_data && activeEdit.raw_data.expected_impact) ||
                  "Maintains chemical balance, aqueous polymerization kinetics, and processing feasibility."}
              </div>
              {(activeOpt?.tradeoffs || (activeEdit.raw_data && activeEdit.raw_data.tradeoffs)) && (
                <div style={{ marginTop: 4, color: "#4B5563" }}>
                  <strong>Tradeoffs:</strong>{" "}
                  {activeOpt?.tradeoffs || activeEdit.raw_data?.tradeoffs}
                </div>
              )}
            </div>

            {/* Technical Systems: Catalyst, Activator, Coagulation */}
            {(() => {
              const catSys = activeOpt?.recipe_data?.catalyst_system || activeEdit.raw_data?.catalyst_system;
              const actSys = activeOpt?.recipe_data?.activator_system || activeEdit.raw_data?.activator_system;
              const coagSys = activeOpt?.recipe_data?.coagulation_system || activeEdit.raw_data?.coagulation_system;
              if (!catSys && !actSys && !coagSys) return null;
              return (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: 10,
                    marginBottom: 16,
                  }}
                >
                  {catSys && (
                    <div style={{ background: "#F8FAFC", border: `1px solid ${BORDER}`, borderRadius: 6, padding: "10px 12px", fontSize: "0.8125rem" }}>
                      <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                        Catalyst / Initiator System
                      </div>
                      <div style={{ color: TEXT, fontWeight: 600 }}>
                        {catSys.primary_catalyst || "Primary Initiator"} ({catSys.primary_dosage || "0.35 phr"})
                      </div>
                      {catSys.alternatives && catSys.alternatives.length > 0 ? (
                        <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                          <em>Alternatives:</em> {catSys.alternatives.map((a: any) => `${a.catalyst || a.name} (${a.dosage || "alt"})`).join("; ")}
                        </div>
                      ) : (
                        <div style={{ fontSize: "0.75rem", color: "#94A3B8", marginTop: 4 }}>
                          No validated alternative identified
                        </div>
                      )}
                    </div>
                  )}

                  {actSys && (
                    <div style={{ background: "#F8FAFC", border: `1px solid ${BORDER}`, borderRadius: 6, padding: "10px 12px", fontSize: "0.8125rem" }}>
                      <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                        Activator System
                      </div>
                      {actSys.applicable ? (
                        <>
                          <div style={{ color: TEXT, fontWeight: 600 }}>
                            {actSys.name || actSys.activator_name || "Redox Activator"} ({actSys.dosage || "0.10 phr"})
                          </div>
                          <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                            Stage: {actSys.stage || actSys.addition_stage || "Catalyst Solution"}
                          </div>
                        </>
                      ) : (
                        <div style={{ color: "#64748B", fontStyle: "italic" }}>
                          Not applicable / Not required
                        </div>
                      )}
                    </div>
                  )}

                  {coagSys && (
                    <div style={{ background: "#F8FAFC", border: `1px solid ${BORDER}`, borderRadius: 6, padding: "10px 12px", fontSize: "0.8125rem" }}>
                      <div style={{ fontWeight: 700, color: BLUE, fontSize: "0.75rem", marginBottom: 4, textTransform: "uppercase" }}>
                        Coagulation System
                      </div>
                      {coagSys.applicable ? (
                        <>
                          <div style={{ color: TEXT, fontWeight: 600 }}>
                            {coagSys.coagulant || coagSys.coagulant_name || "Coagulant"} ({coagSys.dosage || "2.0 phr"})
                          </div>
                          <div style={{ fontSize: "0.75rem", color: "#64748B", marginTop: 4 }}>
                            Conditions: {coagSys.process_conditions || "Standard coagulation"}
                          </div>
                        </>
                      ) : (
                        <div style={{ color: "#64748B", fontStyle: "italic" }}>
                          Not applicable / Not required
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Target Properties Evaluation Table in View Modal */}
            {(() => {
              const evalProps =
                activeOpt?.recipe_data?.target_analysis?.evaluated_properties ||
                activeOpt?.target_analysis?.evaluated_properties ||
                activeEdit.raw_data?.target_analysis?.evaluated_properties ||
                [];
              if (!evalProps.length) return null;
              return (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: "0.75rem", fontWeight: 700, color: BLUE, marginBottom: 8, textTransform: "uppercase" }}>
                    Target Properties Evaluation
                  </div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
                    <thead>
                      <tr style={{ background: BG }}>
                        {["Property", "Target / Range", "Prediction", "Status", "Rationale"].map((col) => (
                          <th key={col} style={{ padding: "7px 10px", textAlign: "left", border: `1px solid ${BORDER}`, color: BLUE, fontSize: "0.75rem", fontWeight: 700 }}>
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {evalProps.map((p: any, idx: number) => {
                        const isMet = p.passed ?? p.meets_target ?? (p.status === "MEETS_TARGET" || p.target_status === "MEETS TARGET");
                        return (
                          <tr key={p.property || p.name || idx}>
                            <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, fontWeight: 600, color: TEXT }}>
                              {p.property || p.name}
                            </td>
                            <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, color: "#374151" }}>
                              {p.target_display || p.target || p.target_value || "—"}
                            </td>
                            <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, fontWeight: 600, color: TEXT }}>
                              {p.predicted_display || (p.predicted_value !== undefined ? String(p.predicted_value) : "—")}
                            </td>
                            <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}` }}>
                              <span
                                style={{
                                  display: "inline-block",
                                  padding: "2px 8px",
                                  borderRadius: 12,
                                  fontSize: "0.72rem",
                                  fontWeight: 700,
                                  background: isMet ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                                  color: isMet ? "#059669" : "#DC2626",
                                  border: `1px solid ${isMet ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)"}`,
                                }}
                              >
                                {isMet ? "MEETS TARGET" : "OUTSIDE TARGET"}
                              </span>
                            </td>
                            <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, color: "#4B5563", fontSize: "0.75rem" }}>
                              {p.reasoning || "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              );
            })()}

            {/* Changed Parameters Table */}
            {activeOpt?.changed_parameters && activeOpt.changed_parameters.length > 0 && (
              <div style={{ marginBottom: 18 }}>
                <div style={{ fontSize: "0.75rem", fontWeight: 700, color: BLUE, marginBottom: 8, textTransform: "uppercase" }}>
                  Changed Parameters
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
                  <thead>
                    <tr style={{ background: BG }}>
                      {["Parameter", "Previous", "Revised", "Unit", "Reason"].map((col) => (
                        <th
                          key={col}
                          style={{
                            padding: "7px 10px",
                            textAlign: "left",
                            border: `1px solid ${BORDER}`,
                            color: BLUE,
                            fontSize: "0.75rem",
                            fontWeight: 700,
                          }}
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {activeOpt.changed_parameters.map((cp: any, idx: number) => (
                      <tr key={idx}>
                        <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, fontWeight: 600 }}>
                          {cp.name || cp.parameter}
                        </td>
                        <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, color: "#6B7280" }}>
                          {cp.old_value ?? cp.previous ?? "—"}
                        </td>
                        <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, color: TEAL, fontWeight: 700 }}>
                          {cp.new_value ?? cp.revised ?? "—"}
                        </td>
                        <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}` }}>
                          {cp.unit || "phr"}
                        </td>
                        <td style={{ padding: "7px 10px", border: `1px solid ${BORDER}`, color: "#4B5563", fontSize: "0.75rem" }}>
                          {cp.reason || "Optimized"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Stages Rendered One Below Another */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {activeEdit.stages && activeEdit.stages.length > 0 ? (
                activeEdit.stages.map((stage, sIdx) => (
                  <div
                    key={stage.id}
                    style={{
                      background: "#FFFFFF",
                      border: `1px solid ${BORDER}`,
                      borderRadius: 7,
                      padding: "12px 16px",
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        marginBottom: 8,
                        paddingBottom: 4,
                        borderBottom: "1.5px solid #F1F5F9",
                      }}
                    >
                      <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                        {sIdx + 1}. {stage.stage_name}
                      </span>
                      {stage.parameters && stage.parameters.length > 0 && (
                        <span style={{ fontSize: "0.75rem", color: "#64748B", background: "#F1F5F9", padding: "2px 8px", borderRadius: 12 }}>
                          {stage.parameters.length} parameter{stage.parameters.length === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>

                    {stage.parameters.length === 0 ? (
                      <div style={{ padding: "4px 0" }}>
                        <div style={{ fontSize: "0.8125rem", color: "#64748B", fontWeight: 600, marginBottom: 4 }}>
                          Not Applicable
                        </div>
                        <div
                          style={{
                            background: "rgba(241, 245, 249, 0.7)",
                            borderLeft: `3px solid ${TEAL}`,
                            padding: "6px 10px",
                            borderRadius: "0 6px 6px 0",
                            fontSize: "0.75rem",
                            color: "#334155",
                          }}
                        >
                          <strong style={{ color: BLUE }}>AI Reason:</strong>{" "}
                          {stage.omission_reason || "This stage is omitted based on synthesis modeling."}
                        </div>
                      </div>
                    ) : (
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
                        <thead>
                          <tr style={{ background: BG }}>
                            {["Parameter", "Value", "Unit"].map((col) => (
                              <th
                                key={col}
                                style={{
                                  padding: "6px 10px",
                                  textAlign: "left",
                                  border: `1px solid ${BORDER}`,
                                  color: BLUE,
                                  fontSize: "0.75rem",
                                  fontWeight: 700,
                                }}
                              >
                                {col}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {stage.parameters.map((p) => (
                            <tr key={p.id}>
                              <td style={{ padding: "6px 10px", border: `1px solid ${BORDER}`, fontWeight: 600 }}>
                                {p.name}
                              </td>
                              <td style={{ padding: "6px 10px", border: `1px solid ${BORDER}`, color: BLUE, fontWeight: 700 }}>
                                {p.value}
                              </td>
                              <td style={{ padding: "6px 10px", border: `1px solid ${BORDER}`, color: "#6B7280" }}>
                                {p.unit}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                ))
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
                  <thead>
                    <tr style={{ background: BG }}>
                      {["Parameter", "Value", "Unit"].map((col) => (
                        <th
                          key={col}
                          style={{
                            padding: "8px 10px",
                            textAlign: "left",
                            border: `1px solid ${BORDER}`,
                            color: BLUE,
                          }}
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {activeEdit.properties.map((p) => (
                      <tr key={p.id}>
                        <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}` }}>{p.name}</td>
                        <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}`, fontWeight: 700, color: BLUE }}>{p.value}</td>
                        <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}` }}>{p.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* Process Conditions */}
              {activeEdit.process_conditions && (
                <div
                  style={{
                    background: "#FFFFFF",
                    border: `1px solid ${BORDER}`,
                    borderRadius: 7,
                    padding: "12px 16px",
                  }}
                >
                  <div
                    style={{
                      marginBottom: 8,
                      paddingBottom: 4,
                      borderBottom: "1.5px solid #F1F5F9",
                    }}
                  >
                    <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                      Process Conditions
                    </span>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: "0.8125rem" }}>
                    {activeEdit.process_conditions.reaction_time && (
                      <div>
                        <strong>Reaction Time:</strong> {activeEdit.process_conditions.reaction_time.value}{" "}
                        {activeEdit.process_conditions.reaction_time.unit}
                      </div>
                    )}
                    {activeEdit.process_conditions.feeding_hours && (
                      <div>
                        <strong>Feeding Hours:</strong> Monomer: {activeEdit.process_conditions.feeding_hours.monomer || "N/A"},{" "}
                        Emulsifier: {activeEdit.process_conditions.feeding_hours.emulsifier || "N/A"},{" "}
                        Catalyst: {activeEdit.process_conditions.feeding_hours.catalyst || "N/A"}
                      </div>
                    )}
                    {activeEdit.process_conditions.temperature_profile &&
                      activeEdit.process_conditions.temperature_profile.length > 0 && (
                        <div>
                          <strong>Temperature Profile:</strong>
                          <div style={{ paddingLeft: 8, marginTop: 4 }}>
                            {activeEdit.process_conditions.temperature_profile.map((t, idx) => (
                              <span key={idx} style={{ marginRight: 12 }}>
                                {t.stage}: <strong>{t.value} {t.unit}</strong>
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>
                </div>
              )}
            </div>

            <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end" }}>
              <button
                onClick={() => setActiveModal(null)}
                style={{
                  background: TEAL,
                  color: "white",
                  border: "none",
                  borderRadius: 6,
                  padding: "8px 18px",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Edit Modal (Editable Recipe Detail Table) ────────────────────────── */}
      {activeModal && activeModal.mode === "edit" && activeEdit && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
          onClick={() => setActiveModal(null)}
        >
          <div
            style={{
              background: "white",
              borderRadius: 8,
              padding: 24,
              maxWidth: 960,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              position: "relative",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={() => setActiveModal(null)}
              style={{
                position: "absolute",
                top: 16,
                right: 16,
                background: "none",
                border: "none",
                cursor: "pointer",
                fontSize: "1.5rem",
                lineHeight: 1,
                color: "#6B7280",
              }}
            >
              &times;
            </button>

            <h3 style={{ margin: "0 0 16px", color: BLUE, fontWeight: 700, fontSize: "1.125rem" }}>
              {activeEdit.name} — Edit Formulation
            </h3>

            <EditableRecipeDetailTable
              recipe={activeEdit}
              onUpdateRecipeName={onUpdateRecipeName}
              onUpdateProperty={onUpdateProperty}
              onAddProperty={onAddProperty}
              onDeleteProperty={onDeleteProperty}
              onResetRecipe={onResetRecipe}
              onUpdateStageParameter={onUpdateStageParameter}
              onAddStageParameter={onAddStageParameter}
              onDeleteStageParameter={onDeleteStageParameter}
              onUpdateProcessConditions={onUpdateProcessConditions}
              onAddStage={onAddStage}
              onDeleteStage={onDeleteStage}
              onUpdateStageName={onUpdateStageName}
            />

            <div
              style={{
                marginTop: 20,
                display: "flex",
                justifyContent: "flex-end",
                gap: 10,
                paddingTop: 16,
                borderTop: `1px solid ${BORDER}`,
              }}
            >
              <button
                onClick={() => setActiveModal(null)}
                style={{
                  background: "white",
                  color: "#4B5563",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 6,
                  padding: "8px 16px",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => handleSaveModalEdits(activeEdit.id)}
                style={{
                  background: TEAL,
                  color: "white",
                  border: "none",
                  borderRadius: 6,
                  padding: "8px 18px",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const headerBtn = (ready: boolean): CSSProperties => ({
  display: "flex",
  alignItems: "center",
  gap: 8,
  background: "white",
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  padding: "8px 16px",
  fontSize: "0.875rem",
  fontWeight: 600,
  color: "#374151",
  cursor: ready ? "pointer" : "wait",
  opacity: ready ? 1 : 0.7,
});

const tealBtn: CSSProperties = {
  background: TEAL,
  color: "white",
  border: "none",
  borderRadius: 7,
  padding: "11px 22px",
  fontSize: "0.875rem",
  fontWeight: 700,
  cursor: "pointer",
};

const outlineBtn: CSSProperties = {
  border: `1px solid ${BORDER}`,
  background: "white",
  borderRadius: 6,
  padding: "8px 14px",
  fontSize: "0.8125rem",
  fontWeight: 600,
  color: BLUE,
  cursor: "pointer",
};

const actionBtn: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  border: `1px solid ${BORDER}`,
  background: "white",
  color: BLUE,
  borderRadius: 6,
  padding: "6px 12px",
  fontSize: "0.75rem",
  fontWeight: 600,
  cursor: "pointer",
};
