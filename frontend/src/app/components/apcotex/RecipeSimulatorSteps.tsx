import { useEffect, useMemo, useState, useRef } from "react";
import { useNavigate } from "react-router";
import {
  ChevronLeft,
  ChevronRight,
  Loader,
  Sparkles,
  Trophy,
  Plus,
  Trash2,
  Edit2,
  CheckCircle2,
  X,
  Download,
  Columns3,
} from "lucide-react";
// Removed PatentResearchReport import
import type { PatentRecipeStep } from "./recipeSimulatorPatentData";
import {
  buildPatentColumnValues,
  getPatentColumns,
  getPatentSourceRecipeSteps,
} from "./recipeSimulatorPatentData";
import {
  buildInitialCompetitorValues,
  CUSTOMER_FEEDBACK_PROPERTIES,
  CUSTOMER_FEEDBACK_TARGET_VALUES,
  DEFAULT_CUSTOMER_FEEDBACK,
  DEMO_CUSTOMER_NOTES,
  DEMO_TARGET_VALUES,
  getPolymerizationRecipeSteps,
  OPTIMIZED_RECIPES,
  POLYMERIZATION_RECIPES,
  type CustomerFeedbackOption,
  type OptimizedRecipe,
  type PolymerizationRecipe,
  type EditableRecipe,
  type EditableRecipeStage,
  type EditableProcessConditions,
  type RecipeProperty,
  type TransferredSpecData,
  type SpecRowTemplate,
  convertToEditableRecipe,
  editableRecipeToRecipeData,
} from "./recipeSimulatorDemoData";
import { buildRecipeComparisonModel } from "./RecipeComparison/recipeComparisonModel";
import { exportRecipeComparisonToExcel } from "./RecipeComparison/recipeExcelExporter";
import { PatentReportViewer } from "./PatentReportViewer";
import { SelectPatentReportModal } from "./SelectPatentReportModal";
import { useProperties } from "../../contexts/PropertyContext";
import { CustomerFeedbackProvider, useCustomerFeedbackProperties } from "../../contexts/CustomerFeedbackContext";
import { usePatentResearch } from "../../contexts/PatentResearchContext";
import { useRecipe } from "../../contexts/RecipeContext";
import { createSavedRecipesBatch } from "../../services/researchApi";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const RED = "#D93A2F";
const TEXT = "#1F2937";
const BORDER = "#E5E7EB";
const BG = "#F7FAFC";

const card = {
  background: "white",
  border: `1px solid ${BORDER}`,
  borderRadius: 8,
  boxShadow: "0 1px 3px rgba(31,95,168,0.06)",
};

function RecipeDetailTable({
  title,
  steps,
}: {
  title: string;
  steps: PatentRecipeStep[];
}) {
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ ...card, overflow: "hidden" }}>
        <div
          style={{
            padding: "12px 16px",
            borderBottom: `1px solid ${BORDER}`,
            background: "rgba(31,95,168,0.07)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={{ fontSize: "0.875rem", fontWeight: 600, color: TEXT }}>
            {title}
          </span>
          <span style={{ fontSize: "0.75rem", color: "#9CA3AF" }}>
            PR#01–PR#10
          </span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              borderCollapse: "collapse",
              minWidth: 600,
              width: "100%",
            }}
          >
            <thead>
              <tr style={{ background: BG }}>
                {[
                  "Parameter",
                  "Step ID",
                  "Recipe Description",
                  "Temperature",
                  "Duration",
                ].map((h, i) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 14px",
                      textAlign: i === 0 ? "left" : "center",
                      fontSize: "0.75rem",
                      fontWeight: 700,
                      color: BLUE,
                      borderBottom: `1.5px solid ${BORDER}`,
                      borderRight: `1px solid ${BORDER}`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {steps.map((row, i) => (
                <tr
                  key={row.step}
                  style={{
                    borderTop: `1px solid ${BORDER}`,
                    background: i % 2 === 0 ? "white" : "rgba(247,250,252,0.5)",
                  }}
                >
                  <td
                    style={{
                      padding: "10px 14px",
                      fontSize: "0.8125rem",
                      color: TEXT,
                      fontWeight: 500,
                      borderRight: `1px solid ${BORDER}`,
                    }}
                  >
                    {row.param}
                  </td>
                  <td
                    style={{
                      padding: "10px 14px",
                      fontSize: "0.8125rem",
                      color: BLUE,
                      fontWeight: 600,
                      textAlign: "center",
                      borderRight: `1px solid ${BORDER}`,
                    }}
                  >
                    {row.step}
                  </td>
                  <td
                    style={{
                      padding: "10px 14px",
                      fontSize: "0.8125rem",
                      color: TEXT,
                      borderRight: `1px solid ${BORDER}`,
                      lineHeight: 1.4,
                    }}
                  >
                    {row.desc}
                  </td>
                  <td
                    style={{
                      padding: "10px 14px",
                      fontSize: "0.8125rem",
                      textAlign: "center",
                      borderRight: `1px solid ${BORDER}`,
                    }}
                  >
                    {row.temp}
                  </td>
                  <td
                    style={{
                      padding: "10px 14px",
                      fontSize: "0.8125rem",
                      textAlign: "center",
                    }}
                  >
                    {row.duration}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function EditableRecipeDetailTable({
  recipe,
  onUpdateRecipeName,
  onUpdateProperty,
  onAddProperty,
  onDeleteProperty,
  onResetRecipe,
  onUpdateStageParameter,
  onAddStageParameter,
  onDeleteStageParameter,
  onUpdateProcessConditions,
  onAddStage,
  onDeleteStage,
  onUpdateStageName,
}: {
  recipe: EditableRecipe;
  onUpdateRecipeName?: (recipeId: string, name: string) => void;
  onUpdateProperty: (recipeId: string, propertyId: string, updates: Partial<RecipeProperty>) => void;
  onAddProperty: (recipeId: string, property: RecipeProperty) => void;
  onDeleteProperty: (recipeId: string, propertyId: string) => void;
  onResetRecipe: (recipeId: string) => void;
  onUpdateStageParameter?: (recipeId: string, stageId: string, paramId: string, updates: Partial<RecipeProperty>) => void;
  onAddStageParameter?: (recipeId: string, stageId: string, param: RecipeProperty) => void;
  onDeleteStageParameter?: (recipeId: string, stageId: string, paramId: string) => void;
  onUpdateProcessConditions?: (recipeId: string, conditions: EditableProcessConditions) => void;
  onAddStage?: (recipeId: string, stageName: string) => void;
  onDeleteStage?: (recipeId: string, stageId: string) => void;
  onUpdateStageName?: (recipeId: string, stageId: string, name: string) => void;
}) {
  const [editingParamId, setEditingParamId] = useState<string | null>(null);
  const [addingToStageId, setAddingToStageId] = useState<string | null>(null);
  const [newParam, setNewParam] = useState({ name: "", value: "", unit: "" });

  const [editingStageId, setEditingStageId] = useState<string | null>(null);
  const [tempStageName, setTempStageName] = useState("");
  const [showAddStage, setShowAddStage] = useState(false);
  const [newStageName, setNewStageName] = useState("");

  // Process conditions local state
  const proc = recipe.process_conditions;
  const [rxnTimeVal, setRxnTimeVal] = useState(proc?.reaction_time?.value || "");
  const [rxnTimeUnit, setRxnTimeUnit] = useState(proc?.reaction_time?.unit || "h");
  const [feedMono, setFeedMono] = useState(proc?.feeding_hours?.monomer || "");
  const [feedEmul, setFeedEmul] = useState(proc?.feeding_hours?.emulsifier || "");
  const [feedCat, setFeedCat] = useState(proc?.feeding_hours?.catalyst || "");
  const [tempProfile, setTempProfile] = useState<{ stage: string; value: string; unit: string }[]>(
    proc?.temperature_profile || []
  );
  const [newTempStep, setNewTempStep] = useState({ stage: "", value: "", unit: "°C" });
  const [showAddTemp, setShowAddTemp] = useState(false);

  // Sync process conditions to parent
  const handleProcessChange = (updates: Partial<EditableProcessConditions>) => {
    if (!onUpdateProcessConditions) return;
    const updated: EditableProcessConditions = {
      reaction_time: updates.reaction_time ?? { value: rxnTimeVal, unit: rxnTimeUnit || "h" },
      feeding_hours: updates.feeding_hours ?? { monomer: feedMono, emulsifier: feedEmul, catalyst: feedCat },
      temperature_profile: updates.temperature_profile ?? tempProfile,
    };
    onUpdateProcessConditions(recipe.id, updated);
  };

  const hasStages = Array.isArray(recipe.stages) && recipe.stages.length > 0;

  return (
    <div style={{ marginTop: 16 }}>
      {/* Recipe Name Editor */}
      <div style={{ marginBottom: 16, background: "rgba(31,95,168,0.03)", padding: 12, borderRadius: 6, border: `1px solid ${BORDER}` }}>
        <label style={{ fontSize: "0.8125rem", fontWeight: 700, color: BLUE, display: "block", marginBottom: 6 }}>
          Recipe Name
        </label>
        <input
          type="text"
          value={recipe.name}
          onChange={(e) => onUpdateRecipeName?.(recipe.id, e.target.value)}
          placeholder="Recipe Name"
          style={{
            width: "100%",
            border: `1px solid ${BORDER}`,
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: "0.875rem",
            fontWeight: 600,
            color: TEXT,
            background: "white",
          }}
        />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: "0.875rem", color: "#6B7280", lineHeight: 1.5 }}>
          <strong style={{ color: BLUE }}>Patent Support:</strong> {recipe.patentSupport || "Inferred from chemical literature & target profile"}
        </div>
        <button
          onClick={() => {
            if (confirm("Are you sure you want to reset this recipe to its AI recommendation?")) {
              onResetRecipe(recipe.id);
            }
          }}
          style={{
            background: "white",
            color: RED,
            border: `1px solid ${BORDER}`,
            borderRadius: 6,
            padding: "6px 12px",
            fontSize: "0.75rem",
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Reset to AI Recommendation
        </button>
      </div>

      {hasStages ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Structured Synthesis Stages */}
          {recipe.stages.map((stage, sIdx) => (
            <div key={stage.id} style={{ ...card, overflow: "hidden" }}>
              <div
                style={{
                  padding: "10px 16px",
                  borderBottom: `1px solid ${BORDER}`,
                  background: "rgba(31,95,168,0.06)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                {editingStageId === stage.id ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, marginRight: 12 }}>
                    <input
                      type="text"
                      value={tempStageName}
                      onChange={(e) => setTempStageName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && tempStageName.trim()) {
                          onUpdateStageName?.(recipe.id, stage.id, tempStageName.trim());
                          setEditingStageId(null);
                        }
                      }}
                      autoFocus
                      style={{
                        padding: "4px 8px",
                        fontSize: "0.875rem",
                        fontWeight: 700,
                        border: "1px solid #CBD5E1",
                        borderRadius: 4,
                        color: BLUE,
                        flex: 1,
                        maxWidth: 320,
                      }}
                    />
                    <button
                      onClick={() => {
                        if (tempStageName.trim()) {
                          onUpdateStageName?.(recipe.id, stage.id, tempStageName.trim());
                        }
                        setEditingStageId(null);
                      }}
                      style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "4px 8px", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer" }}
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingStageId(null)}
                      style={{ background: "#E5E7EB", color: "#374151", border: "none", borderRadius: 4, padding: "4px 8px", fontSize: "0.75rem", cursor: "pointer" }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                      {sIdx + 1}. {stage.stage_name}
                    </span>
                    <button
                      onClick={() => {
                        setEditingStageId(stage.id);
                        setTempStageName(stage.stage_name);
                      }}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#9CA3AF", padding: 2 }}
                      title="Rename stage"
                    >
                      <Edit2 size={13} />
                    </button>
                  </div>
                )}
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: "0.75rem", color: "#6B7280" }}>
                    {stage.parameters.length} parameter{stage.parameters.length === 1 ? "" : "s"}
                  </span>
                  <button
                    onClick={() => {
                      if (confirm(`Are you sure you want to delete stage "${stage.stage_name}" and all its parameters?`)) {
                        onDeleteStage?.(recipe.id, stage.id);
                      }
                    }}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "#EF4444",
                      padding: "2px 4px",
                      display: "inline-flex",
                      alignItems: "center",
                    }}
                    title="Delete this stage"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr style={{ background: BG }}>
                      {["Ingredient / Parameter", "Value", "Unit", "Source", "Actions"].map((h, i) => (
                        <th
                          key={h}
                          style={{
                            padding: "8px 12px",
                            textAlign: i === 0 ? "left" : "center",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                            color: BLUE,
                            borderBottom: `1px solid ${BORDER}`,
                            borderRight: i < 4 ? `1px solid ${BORDER}` : "none",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {stage.parameters.length === 0 ? (
                      <tr>
                        <td
                          colSpan={5}
                          style={{
                            padding: "12px 16px",
                            color: "#9CA3AF",
                            fontStyle: "italic",
                            fontSize: "0.8125rem",
                            textAlign: "center",
                          }}
                        >
                          Not applicable / omitted for this target chemistry
                        </td>
                      </tr>
                    ) : (
                      stage.parameters.map((p, pIdx) => (
                        <tr
                          key={p.id}
                          style={{
                            borderTop: `1px solid ${BORDER}`,
                            background: pIdx % 2 === 0 ? "white" : "rgba(247,250,252,0.5)",
                          }}
                        >
                          <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}`, fontSize: "0.8125rem", color: TEXT, fontWeight: 500 }}>
                            {editingParamId === p.id ? (
                              <input
                                type="text"
                                value={p.name}
                                onChange={(e) =>
                                  onUpdateStageParameter?.(recipe.id, stage.id, p.id, { name: e.target.value })
                                }
                                onBlur={() => setEditingParamId(null)}
                                onKeyDown={(e) => e.key === "Enter" && setEditingParamId(null)}
                                autoFocus
                                style={{
                                  width: "100%",
                                  border: "1px solid #E5E7EB",
                                  borderRadius: 4,
                                  padding: "4px 8px",
                                  fontSize: "0.8125rem",
                                }}
                              />
                            ) : (
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ flex: 1 }}>{p.name}</span>
                                <button
                                  onClick={() => setEditingParamId(p.id)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: "#9CA3AF", padding: 2 }}
                                  title="Edit name"
                                >
                                  <Edit2 size={13} />
                                </button>
                              </div>
                            )}
                          </td>
                          <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}`, width: 120 }}>
                            <input
                              type="text"
                              value={p.value}
                              onChange={(e) =>
                                onUpdateStageParameter?.(recipe.id, stage.id, p.id, { value: e.target.value })
                              }
                              style={{
                                width: "100%",
                                border: "1px solid #E5E7EB",
                                borderRadius: 4,
                                padding: "4px 6px",
                                fontSize: "0.8125rem",
                                textAlign: "center",
                                color: TEXT,
                              }}
                            />
                          </td>
                          <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}`, width: 90 }}>
                            <input
                              type="text"
                              value={p.unit || ""}
                              onChange={(e) =>
                                onUpdateStageParameter?.(recipe.id, stage.id, p.id, { unit: e.target.value })
                              }
                              style={{
                                width: "100%",
                                border: "1px solid #E5E7EB",
                                borderRadius: 4,
                                padding: "4px 6px",
                                fontSize: "0.8125rem",
                                textAlign: "center",
                                color: TEXT,
                              }}
                            />
                          </td>
                          <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}`, textAlign: "center", fontSize: "0.75rem", color: "#6B7280" }}>
                            {p.source === "patent" ? (
                              <span style={{ color: BLUE, fontWeight: 600 }}>{p.patentRef || "Patent"}</span>
                            ) : (
                              <span style={{ color: "#9CA3AF" }}>Inferred</span>
                            )}
                          </td>
                          <td style={{ padding: "8px 12px", textAlign: "center", width: 60 }}>
                            <button
                              onClick={() => {
                                onDeleteStageParameter?.(recipe.id, stage.id, p.id);
                              }}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", padding: 2 }}
                              title="Delete parameter"
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                      ))
                    )}

                    {addingToStageId === stage.id && (
                      <tr style={{ borderTop: `1px solid ${BORDER}`, background: "rgba(31,183,181,0.04)" }}>
                        <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}` }}>
                          <input
                            type="text"
                            placeholder="Ingredient Name"
                            value={newParam.name}
                            onChange={(e) => setNewParam((prev) => ({ ...prev, name: e.target.value }))}
                            style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "4px 8px", fontSize: "0.8125rem" }}
                          />
                        </td>
                        <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}` }}>
                          <input
                            type="text"
                            placeholder="Value"
                            value={newParam.value}
                            onChange={(e) => setNewParam((prev) => ({ ...prev, value: e.target.value }))}
                            style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "4px 6px", fontSize: "0.8125rem", textAlign: "center" }}
                          />
                        </td>
                        <td style={{ padding: "8px 12px", borderRight: `1px solid ${BORDER}` }}>
                          <input
                            type="text"
                            placeholder="Unit"
                            value={newParam.unit}
                            onChange={(e) => setNewParam((prev) => ({ ...prev, unit: e.target.value }))}
                            style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "4px 6px", fontSize: "0.8125rem", textAlign: "center" }}
                          />
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "center", fontSize: "0.75rem", color: "#6B7280" }}>
                          Custom
                        </td>
                        <td style={{ padding: "8px 12px", textAlign: "center" }}>
                          <div style={{ display: "flex", gap: 6, justifyContent: "center" }}>
                            <button
                              onClick={() => {
                                if (newParam.name.trim()) {
                                  onAddStageParameter?.(recipe.id, stage.id, {
                                    id: `custom-p-${Date.now()}`,
                                    name: newParam.name,
                                    value: newParam.value,
                                    unit: newParam.unit,
                                    source: "inferred",
                                  });
                                  setNewParam({ name: "", value: "", unit: "" });
                                  setAddingToStageId(null);
                                }
                              }}
                              style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "4px 8px", fontSize: "0.75rem", cursor: "pointer", fontWeight: 600 }}
                            >
                              Save
                            </button>
                            <button
                              onClick={() => {
                                setAddingToStageId(null);
                                setNewParam({ name: "", value: "", unit: "" });
                              }}
                              style={{ background: "#E5E7EB", color: "#374151", border: "none", borderRadius: 4, padding: "4px 8px", fontSize: "0.75rem", cursor: "pointer" }}
                            >
                              Cancel
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                  {addingToStageId !== stage.id && (
                    <tfoot>
                      <tr>
                        <td colSpan={5} style={{ padding: "6px 12px", background: "white", textAlign: "right" }}>
                          <button
                            onClick={() => {
                              setAddingToStageId(stage.id);
                              setNewParam({ name: "", value: "", unit: "" });
                            }}
                            style={{
                              background: "none",
                              color: TEAL,
                              border: "none",
                              cursor: "pointer",
                              fontSize: "0.75rem",
                              fontWeight: 600,
                              display: "inline-flex",
                              alignItems: "center",
                              gap: 4,
                            }}
                          >
                            <Plus size={13} /> Add Parameter to {stage.stage_name}
                          </button>
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </div>
          ))}

          {/* Add New Synthesis Stage */}
          {!showAddStage ? (
            <div style={{ display: "flex", justifyContent: "center", margin: "4px 0" }}>
              <button
                onClick={() => setShowAddStage(true)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  background: "white",
                  color: BLUE,
                  border: `1.5px dashed ${BLUE}`,
                  borderRadius: 6,
                  padding: "8px 18px",
                  fontSize: "0.8125rem",
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                <Plus size={15} /> Add Synthesis Stage
              </button>
            </div>
          ) : (
            <div style={{ ...card, padding: 14, background: "rgba(31,95,168,0.03)", border: `1.5px dashed ${BLUE}` }}>
              <div style={{ fontSize: "0.8125rem", fontWeight: 700, color: BLUE, marginBottom: 8 }}>
                Add New Synthesis Stage
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <input
                  type="text"
                  placeholder="Stage Name (e.g. Pre-emulsion Charge, Post Neutralization, Finishing...)"
                  value={newStageName}
                  onChange={(e) => setNewStageName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newStageName.trim()) {
                      onAddStage?.(recipe.id, newStageName.trim());
                      setNewStageName("");
                      setShowAddStage(false);
                    }
                  }}
                  autoFocus
                  style={{ flex: 1, padding: "8px 12px", border: `1px solid ${BORDER}`, borderRadius: 6, fontSize: "0.8125rem" }}
                />
                <button
                  onClick={() => {
                    if (newStageName.trim()) {
                      onAddStage?.(recipe.id, newStageName.trim());
                      setNewStageName("");
                      setShowAddStage(false);
                    }
                  }}
                  style={{ background: TEAL, color: "white", border: "none", borderRadius: 6, padding: "8px 16px", fontSize: "0.8125rem", fontWeight: 700, cursor: "pointer" }}
                >
                  Add Stage
                </button>
                <button
                  onClick={() => {
                    setShowAddStage(false);
                    setNewStageName("");
                  }}
                  style={{ background: "white", color: "#6B7280", border: `1px solid ${BORDER}`, borderRadius: 6, padding: "8px 12px", fontSize: "0.8125rem", cursor: "pointer" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Process Conditions Editor */}
          <div style={{ ...card, overflow: "hidden" }}>
            <div
              style={{
                padding: "10px 16px",
                borderBottom: `1px solid ${BORDER}`,
                background: "rgba(31,183,181,0.08)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                Process Conditions
              </span>
              <span style={{ fontSize: "0.75rem", color: "#6B7280" }}>
                Reaction Time, Feeding Duration & Temperature Profile
              </span>
            </div>

            <div style={{ padding: "16px", display: "flex", flexDirection: "column", gap: 14 }}>
              {/* Row 1: Reaction Time & Feeding Hours */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                <div>
                  <label style={{ fontSize: "0.75rem", fontWeight: 600, color: "#4B5563", display: "block", marginBottom: 4 }}>
                    Total Reaction Time ({rxnTimeUnit || "h"})
                  </label>
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      type="text"
                      value={rxnTimeVal}
                      placeholder="e.g. 8"
                      onChange={(e) => {
                        setRxnTimeVal(e.target.value);
                        handleProcessChange({ reaction_time: { value: e.target.value, unit: rxnTimeUnit || "h" } });
                      }}
                      style={{ flex: 1, border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 8px", fontSize: "0.8125rem" }}
                    />
                    <input
                      type="text"
                      value={rxnTimeUnit}
                      placeholder="unit"
                      onChange={(e) => {
                        setRxnTimeUnit(e.target.value);
                        handleProcessChange({ reaction_time: { value: rxnTimeVal, unit: e.target.value } });
                      }}
                      style={{ width: 50, border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 4px", fontSize: "0.8125rem", textAlign: "center" }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ fontSize: "0.75rem", fontWeight: 600, color: "#4B5563", display: "block", marginBottom: 4 }}>
                    Monomer Feed Duration
                  </label>
                  <input
                    type="text"
                    value={feedMono}
                    placeholder="e.g. 4 h or N/A"
                    onChange={(e) => {
                      setFeedMono(e.target.value);
                      handleProcessChange({ feeding_hours: { monomer: e.target.value, emulsifier: feedEmul, catalyst: feedCat } });
                    }}
                    style={{ width: "100%", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 8px", fontSize: "0.8125rem" }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: "0.75rem", fontWeight: 600, color: "#4B5563", display: "block", marginBottom: 4 }}>
                    Emulsifier Feed Duration
                  </label>
                  <input
                    type="text"
                    value={feedEmul}
                    placeholder="e.g. 4 h or N/A"
                    onChange={(e) => {
                      setFeedEmul(e.target.value);
                      handleProcessChange({ feeding_hours: { monomer: feedMono, emulsifier: e.target.value, catalyst: feedCat } });
                    }}
                    style={{ width: "100%", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 8px", fontSize: "0.8125rem" }}
                  />
                </div>

                <div>
                  <label style={{ fontSize: "0.75rem", fontWeight: 600, color: "#4B5563", display: "block", marginBottom: 4 }}>
                    Catalyst / Initiator Feed Duration
                  </label>
                  <input
                    type="text"
                    value={feedCat}
                    placeholder="e.g. Continuous 6 h or N/A"
                    onChange={(e) => {
                      setFeedCat(e.target.value);
                      handleProcessChange({ feeding_hours: { monomer: feedMono, emulsifier: feedEmul, catalyst: e.target.value } });
                    }}
                    style={{ width: "100%", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 8px", fontSize: "0.8125rem" }}
                  />
                </div>
              </div>

              {/* Row 2: Temperature Profile */}
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <label style={{ fontSize: "0.75rem", fontWeight: 700, color: BLUE }}>
                    Temperature Profile
                  </label>
                  {!showAddTemp && (
                    <button
                      onClick={() => setShowAddTemp(true)}
                      style={{ background: "none", color: TEAL, border: "none", cursor: "pointer", fontSize: "0.75rem", fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}
                    >
                      <Plus size={13} /> Add Temperature Step
                    </button>
                  )}
                </div>

                <table style={{ borderCollapse: "collapse", width: "100%", border: `1px solid ${BORDER}`, borderRadius: 4 }}>
                  <thead>
                    <tr style={{ background: BG }}>
                      <th style={{ padding: "6px 10px", textAlign: "left", fontSize: "0.75rem", color: BLUE, borderBottom: `1px solid ${BORDER}` }}>Stage / Phase</th>
                      <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", color: BLUE, borderBottom: `1px solid ${BORDER}`, width: 100 }}>Temperature</th>
                      <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", color: BLUE, borderBottom: `1px solid ${BORDER}`, width: 60 }}>Unit</th>
                      <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", color: BLUE, borderBottom: `1px solid ${BORDER}`, width: 50 }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tempProfile.length === 0 ? (
                      <tr>
                        <td colSpan={4} style={{ padding: "10px", textAlign: "center", color: "#9CA3AF", fontStyle: "italic", fontSize: "0.75rem" }}>
                          No explicit temperature ramp defined
                        </td>
                      </tr>
                    ) : (
                      tempProfile.map((t, tIdx) => (
                        <tr key={tIdx} style={{ borderTop: `1px solid ${BORDER}` }}>
                          <td style={{ padding: "6px 10px", fontSize: "0.8125rem", color: TEXT }}>
                            <input
                              type="text"
                              value={t.stage}
                              onChange={(e) => {
                                const next = [...tempProfile];
                                next[tIdx] = { ...next[tIdx], stage: e.target.value };
                                setTempProfile(next);
                                handleProcessChange({ temperature_profile: next });
                              }}
                              style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem" }}
                            />
                          </td>
                          <td style={{ padding: "6px 10px", textAlign: "center" }}>
                            <input
                              type="text"
                              value={t.value}
                              onChange={(e) => {
                                const next = [...tempProfile];
                                next[tIdx] = { ...next[tIdx], value: e.target.value };
                                setTempProfile(next);
                                handleProcessChange({ temperature_profile: next });
                              }}
                              style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem", textAlign: "center" }}
                            />
                          </td>
                          <td style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", color: TEXT }}>
                            {t.unit || "°C"}
                          </td>
                          <td style={{ padding: "6px 10px", textAlign: "center" }}>
                            <button
                              onClick={() => {
                                const next = tempProfile.filter((_, i) => i !== tIdx);
                                setTempProfile(next);
                                handleProcessChange({ temperature_profile: next });
                              }}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", padding: 2 }}
                              title="Delete step"
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                    {showAddTemp && (
                      <tr style={{ borderTop: `1px solid ${BORDER}`, background: "rgba(31,183,181,0.04)" }}>
                        <td style={{ padding: "6px 10px" }}>
                          <input
                            type="text"
                            placeholder="Phase (e.g. Feeding)"
                            value={newTempStep.stage}
                            onChange={(e) => setNewTempStep((prev) => ({ ...prev, stage: e.target.value }))}
                            style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem" }}
                          />
                        </td>
                        <td style={{ padding: "6px 10px" }}>
                          <input
                            type="text"
                            placeholder="Temp"
                            value={newTempStep.value}
                            onChange={(e) => setNewTempStep((prev) => ({ ...prev, value: e.target.value }))}
                            style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem", textAlign: "center" }}
                          />
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem" }}>
                          °C
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "center" }}>
                          <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>
                            <button
                              onClick={() => {
                                if (newTempStep.stage.trim() || newTempStep.value.trim()) {
                                  const next = [...tempProfile, newTempStep];
                                  setTempProfile(next);
                                  handleProcessChange({ temperature_profile: next });
                                  setNewTempStep({ stage: "", value: "", unit: "°C" });
                                  setShowAddTemp(false);
                                }
                              }}
                              style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "2px 6px", fontSize: "0.75rem", cursor: "pointer" }}
                            >
                              Add
                            </button>
                            <button
                              onClick={() => {
                                setShowAddTemp(false);
                                setNewTempStep({ stage: "", value: "", unit: "°C" });
                              }}
                              style={{ background: "#E5E7EB", color: "#374151", border: "none", borderRadius: 4, padding: "2px 6px", fontSize: "0.75rem", cursor: "pointer" }}
                            >
                              X
                            </button>
                          </div>
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Legacy fallback: flat property table */
        <div style={{ ...card, overflow: "hidden" }}>
          <div
            style={{
              padding: "12px 16px",
              borderBottom: `1px solid ${BORDER}`,
              background: "rgba(31,95,168,0.07)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span style={{ fontSize: "0.875rem", fontWeight: 600, color: TEXT }}>
              Editable Formulation Properties
            </span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", minWidth: 600, width: "100%" }}>
              <thead>
                <tr style={{ background: BG }}>
                  {["Property Name", "Value", "Unit", "Actions"].map((h, i) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 14px",
                        textAlign: i === 0 ? "left" : "center",
                        fontSize: "0.75rem",
                        fontWeight: 700,
                        color: BLUE,
                        borderBottom: `1.5px solid ${BORDER}`,
                        borderRight: i < 3 ? `1px solid ${BORDER}` : "none",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recipe.properties.map((row, i) => (
                  <tr
                    key={row.id}
                    style={{
                      borderTop: `1px solid ${BORDER}`,
                      background: i % 2 === 0 ? "white" : "rgba(247,250,252,0.5)",
                    }}
                  >
                    <td style={{ padding: "10px 14px", fontSize: "0.8125rem", color: TEXT, fontWeight: 500, borderRight: `1px solid ${BORDER}` }}>
                      {editingParamId === row.id ? (
                        <input
                          type="text"
                          value={row.name}
                          onChange={(e) => onUpdateProperty(recipe.id, row.id, { name: e.target.value })}
                          onBlur={() => setEditingParamId(null)}
                          onKeyDown={(e) => e.key === "Enter" && setEditingParamId(null)}
                          autoFocus
                          style={{ width: "100%", border: "1px solid #E5E7EB", borderRadius: 4, padding: "4px 8px", fontSize: "0.8125rem" }}
                        />
                      ) : (
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ flex: 1 }}>{row.name}</span>
                          <button
                            onClick={() => setEditingParamId(row.id)}
                            style={{ background: "none", border: "none", cursor: "pointer", color: "#9CA3AF", padding: 2 }}
                          >
                            <Edit2 size={14} />
                          </button>
                        </div>
                      )}
                    </td>
                    <td style={{ padding: "10px 14px", borderRight: `1px solid ${BORDER}` }}>
                      <input
                        type="text"
                        value={row.value}
                        onChange={(e) => onUpdateProperty(recipe.id, row.id, { value: e.target.value })}
                        style={{ width: "100%", border: "1px solid #E5E7EB", background: "white", fontSize: "0.8125rem", color: TEXT, textAlign: "center", padding: "4px 6px", borderRadius: "4px" }}
                      />
                    </td>
                    <td style={{ padding: "10px 14px", borderRight: `1px solid ${BORDER}` }}>
                      <input
                        type="text"
                        value={row.unit || ""}
                        onChange={(e) => onUpdateProperty(recipe.id, row.id, { unit: e.target.value })}
                        style={{ width: "100%", border: "1px solid #E5E7EB", background: "white", fontSize: "0.8125rem", color: TEXT, textAlign: "center", padding: "4px 6px", borderRadius: "4px" }}
                      />
                    </td>
                    <td style={{ padding: "10px 14px", textAlign: "center" }}>
                      <button
                        onClick={() => {
                          if (confirm(`Are you sure you want to delete "${row.name}"?`)) {
                            onDeleteProperty(recipe.id, row.id);
                          }
                        }}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", padding: 2 }}
                        title="Delete property"
                      >
                        <Trash2 size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function PolymerizationRecipeCard({
  recipe,
  selected,
  onSelect,
  onSave,
  onUpdateProperty,
  onAddProperty,
  onDeleteProperty,
  onResetRecipe,
  onUpdateStageParameter,
  onAddStageParameter,
  onDeleteStageParameter,
  onUpdateProcessConditions,
  onUpdateRecipeName,
  onAddStage,
  onDeleteStage,
  onUpdateStageName,
  onSaveEdits,
}: {
  recipe: EditableRecipe;
  selected?: boolean;
  onSelect?: () => void;
  onSave?: (recipe: EditableRecipe) => void;
  onUpdateProperty: (recipeId: string, propertyId: string, updates: Partial<RecipeProperty>) => void;
  onAddProperty: (recipeId: string, property: Omit<RecipeProperty, "id">) => void;
  onDeleteProperty: (recipeId: string, propertyId: string) => void;
  onResetRecipe: (recipeId: string) => void;
  onUpdateStageParameter?: (recipeId: string, stageId: string, paramId: string, updates: Partial<RecipeProperty>) => void;
  onAddStageParameter?: (recipeId: string, stageId: string, param: RecipeProperty) => void;
  onDeleteStageParameter?: (recipeId: string, stageId: string, paramId: string) => void;
  onUpdateProcessConditions?: (recipeId: string, conditions: EditableProcessConditions) => void;
  onUpdateRecipeName?: (recipeId: string, name: string) => void;
  onAddStage?: (recipeId: string, stageName: string) => void;
  onDeleteStage?: (recipeId: string, stageId: string) => void;
  onUpdateStageName?: (recipeId: string, stageId: string, name: string) => void;
  onSaveEdits?: (recipeId: string) => Promise<void>;
}) {
  const [modalMode, setModalMode] = useState<"view" | "edit" | null>(null);
  const [showPredictions, setShowPredictions] = useState(false);
  const hasStages = Array.isArray(recipe.stages) && recipe.stages.length > 0;

  const targetFit = recipe.targetFit ?? recipe.targetAnalysis?.target_fit_score;
  const targetsMet = recipe.targetsMet ?? recipe.targetAnalysis?.targets_met;
  const targetsTotal = recipe.targetsTotal ?? recipe.targetAnalysis?.targets_total;
  const hasTargets = targetsTotal !== null && targetsTotal !== undefined && targetsTotal > 0;
  const allTargetsMet = hasTargets && targetsMet === targetsTotal;
  const hasViolations = hasTargets && targetsMet !== null && targetsMet < targetsTotal;
  const targetProps = recipe.targetAnalysis?.properties || recipe.raw_data?.predicted_properties || [];

  return (
    <div
      style={{
        ...card,
        border: selected ? `2px solid ${TEAL}` : (hasViolations ? "1.5px solid #FCA5A5" : `1px solid ${BORDER}`),
        boxShadow: selected ? "0 4px 14px rgba(31,183,181,0.18)" : "0 1px 3px rgba(0,0,0,0.05)",
        position: "relative",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        borderRadius: 8,
        background: "white",
        marginBottom: 16,
      }}
    >
      {/* Header with Title, Target Fit, Targets Met, and Confidence Score */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "16px 20px",
          borderBottom: `1px solid ${BORDER}`,
          background: selected ? "rgba(31,183,181,0.05)" : (hasViolations ? "rgba(254,242,242,0.6)" : "rgba(31,95,168,0.02)"),
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: "1.0625rem", fontWeight: 700, color: BLUE }}>
            {recipe.name}
          </span>
          {selected && (
            <span
              style={{
                background: "rgba(31,183,181,0.15)",
                color: TEAL,
                fontWeight: 700,
                fontSize: "0.75rem",
                padding: "2px 10px",
                borderRadius: 12,
                border: `1px solid ${TEAL}`,
              }}
            >
              Selected
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Target Fit Badge */}
          <span
            style={{
              background: hasTargets ? (allTargetsMet ? "rgba(16,185,129,0.12)" : "rgba(245,158,11,0.12)") : "rgba(100,116,139,0.1)",
              color: hasTargets ? (allTargetsMet ? "#059669" : "#D97706") : "#475569",
              fontWeight: 700,
              fontSize: "0.8125rem",
              padding: "4px 12px",
              borderRadius: 20,
              border: `1px solid ${hasTargets ? (allTargetsMet ? "rgba(16,185,129,0.3)" : "rgba(245,158,11,0.3)") : "rgba(100,116,139,0.2)"}`,
            }}
            title={hasTargets ? "Target Fit Score: Mathematically evaluated against target polymer properties" : "No explicit targets supplied"}
          >
            Target Fit: {targetFit !== null && targetFit !== undefined ? `${targetFit}%` : "N/A"}
          </span>

          {/* Targets Met Badge */}
          {hasTargets && (
            <span
              style={{
                background: allTargetsMet ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                color: allTargetsMet ? "#059669" : "#DC2626",
                fontWeight: 700,
                fontSize: "0.8125rem",
                padding: "4px 12px",
                borderRadius: 20,
                border: `1px solid ${allTargetsMet ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)"}`,
              }}
              title={`${targetsMet} of ${targetsTotal} target properties satisfied`}
            >
              Targets Met: {targetsMet}/{targetsTotal}
            </span>
          )}

          {/* Real Backend Confidence Badge */}
          <span
            style={{
              background: "rgba(31,183,181,0.12)",
              color: TEAL,
              fontWeight: 700,
              fontSize: "0.8125rem",
              padding: "4px 12px",
              borderRadius: 20,
              border: `1px solid rgba(31,183,181,0.3)`,
            }}
            title="Backend calculated confidence score based on target compliance, patent evidence, recipe completeness, and process feasibility"
          >
            Confidence: {recipe.confidence}%
          </span>
        </div>
      </div>

      {/* Target Violation Warning Banner */}
      {hasViolations && (
        <div
          style={{
            background: "#FEF2F2",
            borderBottom: "1px solid #FCA5A5",
            padding: "8px 20px",
            color: "#B91C1C",
            fontSize: "0.8125rem",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <AlertCircle size={15} color="#DC2626" />
          <span>
            <strong>Target Warning:</strong> {targetsTotal - (targetsMet || 0)} target propert{(targetsTotal - (targetsMet || 0)) === 1 ? "y" : "ies"} not satisfied by model prediction.
          </span>
        </div>
      )}

      <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
        {/* 6 Canonical Stages displayed cleanly across a responsive grid */}
        {hasStages ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: 12,
            }}
          >
            {recipe.stages.map((stage, idx) => (
              <div
                key={stage.id}
                style={{
                  background: BG,
                  borderRadius: 6,
                  padding: "10px 14px",
                  border: `1px solid ${BORDER}`,
                  fontSize: "0.75rem",
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div
                  style={{
                    fontWeight: 700,
                    color: BLUE,
                    fontSize: "0.8125rem",
                    borderBottom: "1px solid #E5E7EB",
                    paddingBottom: 4,
                    marginBottom: 6,
                  }}
                >
                  {idx + 1}. {stage.stage_name}
                </div>
                {stage.parameters && stage.parameters.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {stage.parameters.map((p) => (
                      <div key={p.id} style={{ color: "#374151" }}>
                        <span style={{ fontWeight: 600 }}>{p.name}:</span> {p.value} {p.unit}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div>
                    <div style={{ color: "#6B7280", fontStyle: "italic", fontSize: "0.75rem", marginBottom: 2 }}>
                      Not applicable
                    </div>
                    <div style={{ color: "#4B5563", fontSize: "0.7rem", lineHeight: 1.35 }}>
                      <strong style={{ color: BLUE }}>AI:</strong> {stage.omission_reason || "No separate stage required for this synthesis route."}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 8, background: BG, padding: 12, borderRadius: 6 }}>
            {recipe.properties.map((prop) => (
              <div key={prop.id} style={{ fontSize: "0.8125rem", color: TEXT }}>
                <strong>{prop.name}:</strong> {prop.value} {prop.unit}
              </div>
            ))}
          </div>
        )}

        {/* Process Conditions summary */}
        {recipe.process_conditions && (
          <div
            style={{
              background: "rgba(31,183,181,0.05)",
              border: "1px solid rgba(31,183,181,0.2)",
              borderRadius: 6,
              padding: "10px 14px",
              fontSize: "0.75rem",
              color: "#1E293B",
            }}
          >
            <div style={{ fontWeight: 700, color: TEAL, fontSize: "0.8125rem", marginBottom: 4 }}>
              Process Conditions
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
              {recipe.process_conditions.reaction_time && (
                <div>
                  <strong>Reaction Time:</strong> {recipe.process_conditions.reaction_time.value} {recipe.process_conditions.reaction_time.unit}
                </div>
              )}
              {recipe.process_conditions.feeding_hours && (
                <div>
                  <strong>Feeding Hours:</strong> Monomer: {recipe.process_conditions.feeding_hours.monomer || "N/A"} · Emulsifier: {recipe.process_conditions.feeding_hours.emulsifier || "N/A"} · Catalyst: {recipe.process_conditions.feeding_hours.catalyst || "N/A"}
                </div>
              )}
              {recipe.process_conditions.temperature_profile && recipe.process_conditions.temperature_profile.length > 0 && (
                <div>
                  <strong>Temperature Profile:</strong> {recipe.process_conditions.temperature_profile.map((t) => `${t.stage}: ${t.value} ${t.unit}`).join("; ")}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Target Properties & Prediction Analysis Section */}
        {targetProps && targetProps.length > 0 && (
          <div
            style={{
              background: "#F8FAFC",
              border: `1px solid ${hasViolations ? "#FCA5A5" : BORDER}`,
              borderRadius: 6,
              padding: "12px 14px",
              fontSize: "0.75rem",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 6 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontWeight: 700, color: BLUE, fontSize: "0.8125rem" }}>
                  Target Polymer Properties & Model Predictions
                </span>
                <span
                  style={{
                    background: allTargetsMet ? "rgba(16,185,129,0.12)" : "rgba(245,158,11,0.12)",
                    color: allTargetsMet ? "#059669" : "#D97706",
                    padding: "2px 8px",
                    borderRadius: 10,
                    fontWeight: 700,
                    fontSize: "0.7rem",
                  }}
                >
                  {allTargetsMet ? "✓ All Hard Targets Satisfied" : `${targetsMet ?? 0}/${targetsTotal ?? 0} Targets Satisfied`}
                </span>
              </div>
              <button
                onClick={() => setShowPredictions((prev) => !prev)}
                style={{
                  background: "none",
                  border: "none",
                  color: TEAL,
                  fontWeight: 600,
                  fontSize: "0.75rem",
                  cursor: "pointer",
                  textDecoration: "underline",
                }}
              >
                {showPredictions ? "Hide Property Predictions" : "View Property Predictions & Rationale"}
              </button>
            </div>

            {showPredictions && (
              <div style={{ overflowX: "auto", marginTop: 8 }}>
                <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.75rem" }}>
                  <thead>
                    <tr style={{ background: "rgba(31,95,168,0.06)", color: BLUE }}>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>Property</th>
                      <th style={{ padding: "6px 8px", textAlign: "center" }}>Target Objective</th>
                      <th style={{ padding: "6px 8px", textAlign: "center" }}>Model Prediction</th>
                      <th style={{ padding: "6px 8px", textAlign: "center" }}>Status</th>
                      <th style={{ padding: "6px 8px", textAlign: "left" }}>Chemical Levers & Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {targetProps.map((p: any, pIdx: number) => {
                      const propName = p.name || p.property || `Property ${pIdx + 1}`;
                      const unitStr = p.unit ? ` ${p.unit}` : "";
                      const meets = p.status === "MEETS_TARGET" || p.meets_target === true;

                      let targetStr = "Objective";
                      if (p.target_min !== undefined && p.target_max !== undefined && p.target_min !== null && p.target_max !== null) {
                        targetStr = `${p.target_min}–${p.target_max}${unitStr}`;
                      } else if (p.target_min !== undefined && p.target_min !== null) {
                        targetStr = `≥ ${p.target_min}${unitStr}`;
                      } else if (p.target_max !== undefined && p.target_max !== null) {
                        targetStr = `≤ ${p.target_max}${unitStr}`;
                      } else if (p.target_value !== undefined && p.target_value !== null) {
                        targetStr = `${p.target_value}${unitStr}`;
                      } else if (p.target !== undefined && p.target !== null) {
                        targetStr = `${p.target}${unitStr}`;
                      }

                      let predStr = "N/A";
                      if (p.predicted_min !== undefined && p.predicted_max !== undefined && p.predicted_min !== null && p.predicted_max !== null) {
                        predStr = `${p.predicted_min}–${p.predicted_max}${unitStr}`;
                      } else if (p.predicted_value !== undefined && p.predicted_value !== null) {
                        predStr = `${p.predicted_value}${unitStr}`;
                      }

                      return (
                        <tr key={pIdx} style={{ borderTop: `1px solid ${BORDER}` }}>
                          <td style={{ padding: "6px 8px", fontWeight: 600, color: TEXT }}>{propName}</td>
                          <td style={{ padding: "6px 8px", textAlign: "center", color: BLUE, fontWeight: 600 }}>{targetStr}</td>
                          <td style={{ padding: "6px 8px", textAlign: "center", fontWeight: 700, color: meets ? "#059669" : "#DC2626" }}>{predStr}</td>
                          <td style={{ padding: "6px 8px", textAlign: "center" }}>
                            <span
                              style={{
                                background: meets ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)",
                                color: meets ? "#059669" : "#DC2626",
                                padding: "2px 8px",
                                borderRadius: 10,
                                fontWeight: 700,
                                fontSize: "0.7rem",
                              }}
                            >
                              {meets ? "PASS" : "NOT MET"}
                            </span>
                          </td>
                          <td style={{ padding: "6px 8px", color: "#4B5563" }}>{p.reasoning || "Tuned via stoichiometric recipe levers."}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Patent Support */}
        <div
          style={{
            fontSize: "0.8125rem",
            color: "#4B5563",
            padding: "8px 12px",
            background: "#F8FAFC",
            borderRadius: 6,
            border: `1px solid ${BORDER}`,
          }}
        >
          <strong style={{ color: BLUE }}>Patent Support:</strong>{" "}
          {recipe.patentSupport}
        </div>

        {/* Action Buttons: [ View ] [ Edit ] [ Select ] [ Save ] */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", justifyContent: "flex-end", paddingTop: 4 }}>
          <button
            onClick={() => setModalMode("view")}
            style={{
              background: "white",
              color: BLUE,
              border: `1.5px solid ${BORDER}`,
              borderRadius: 6,
              padding: "8px 18px",
              fontSize: "0.8125rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            View
          </button>
          <button
            onClick={() => setModalMode("edit")}
            style={{
              background: BLUE,
              color: "white",
              border: "none",
              borderRadius: 6,
              padding: "8px 18px",
              fontSize: "0.8125rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Edit
          </button>
          <button
            onClick={onSelect}
            style={{
              border: `1.5px solid ${selected ? TEAL : BORDER}`,
              color: selected ? TEAL : BLUE,
              background: selected ? "rgba(31,183,181,0.12)" : "white",
              borderRadius: 6,
              padding: "8px 18px",
              fontSize: "0.8125rem",
              fontWeight: 700,
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {selected && <CheckCircle2 size={14} color={TEAL} />}
            {selected ? "Selected" : "Select"}
          </button>
          <button
            onClick={() => onSave?.(recipe)}
            style={{
              background: TEAL,
              color: "white",
              border: "none",
              borderRadius: 6,
              padding: "8px 18px",
              fontSize: "0.8125rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Save
          </button>
        </div>
      </div>

      {modalMode && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
          <div style={{ backgroundColor: 'white', borderRadius: 8, padding: '24px', maxWidth: '850px', width: '100%', maxHeight: '90vh', overflowY: 'auto', position: 'relative' }}>
            <button onClick={() => setModalMode(null)} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.5rem', lineHeight: 1 }}>&times;</button>
            <h3 style={{ margin: "0 0 16px 0", color: BLUE, fontSize: "1.125rem", fontWeight: 700 }}>
              {recipe.name} — {modalMode === "edit" ? "Edit Recipe" : "Full Recipe Details"}
            </h3>

            {modalMode === "edit" ? (
              <EditableRecipeDetailTable
                recipe={recipe}
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
            ) : (
              /* Structured Procedural View Modal (No Source or Patent Citation column) */
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {hasStages ? (
                  <>
                    {recipe.stages.map((stage, sIdx) => (
                      <div
                        key={stage.id}
                        style={{
                          background: "#FFFFFF",
                          border: `1px solid ${BORDER}`,
                          borderRadius: 8,
                          padding: "14px 18px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginBottom: 10,
                            paddingBottom: 6,
                            borderBottom: "1.5px solid #F1F5F9",
                          }}
                        >
                          <span style={{ fontSize: "0.9375rem", fontWeight: 700, color: BLUE }}>
                            {sIdx + 1}. {stage.stage_name}
                          </span>
                          {stage.parameters && stage.parameters.length > 0 && (
                            <span style={{ fontSize: "0.75rem", color: "#64748B", background: "#F1F5F9", padding: "2px 8px", borderRadius: 12 }}>
                              {stage.parameters.length} parameter{stage.parameters.length === 1 ? "" : "s"}
                            </span>
                          )}
                        </div>

                        {stage.parameters.length === 0 ? (
                          <div style={{ padding: "6px 0" }}>
                            <div style={{ fontSize: "0.8125rem", color: "#64748B", fontWeight: 600, marginBottom: 6 }}>
                              Not applicable
                            </div>
                            <div
                              style={{
                                background: "rgba(241, 245, 249, 0.7)",
                                borderLeft: `3px solid ${TEAL}`,
                                padding: "8px 12px",
                                borderRadius: "0 6px 6px 0",
                                fontSize: "0.8125rem",
                                color: "#334155",
                                lineHeight: 1.5,
                              }}
                            >
                              <strong style={{ color: BLUE }}>AI Reason:</strong>{" "}
                              {stage.omission_reason || "This stage was omitted based on the modeled synthesis pathway for this target compound."}
                            </div>
                          </div>
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                            {stage.parameters.map((p) => (
                              <div
                                key={p.id}
                                style={{
                                  display: "flex",
                                  justifyContent: "space-between",
                                  alignItems: "baseline",
                                  padding: "8px 12px",
                                  background: "#F8FAFC",
                                  borderRadius: 6,
                                  border: "1px solid #EDF2F7",
                                }}
                              >
                                <span style={{ fontSize: "0.875rem", fontWeight: 600, color: "#1E293B" }}>
                                  {p.name}
                                </span>
                                <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
                                  Value: {p.value} {p.unit}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}

                    {/* Process Conditions in View Modal */}
                    {recipe.process_conditions && (
                      <div
                        style={{
                          background: "#FFFFFF",
                          border: `1px solid ${BORDER}`,
                          borderRadius: 8,
                          padding: "14px 18px",
                        }}
                      >
                        <div
                          style={{
                            marginBottom: 10,
                            paddingBottom: 6,
                            borderBottom: "1.5px solid #F1F5F9",
                          }}
                        >
                          <span style={{ fontSize: "0.9375rem", fontWeight: 700, color: BLUE }}>
                            Process Conditions
                          </span>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                          {recipe.process_conditions.reaction_time && (
                            <div style={{ padding: "8px 12px", background: "#F8FAFC", borderRadius: 6 }}>
                              <span style={{ fontWeight: 600, color: "#1E293B", fontSize: "0.8125rem" }}>
                                Reaction Time:
                              </span>{" "}
                              <span style={{ fontWeight: 700, color: BLUE, fontSize: "0.875rem" }}>
                                {recipe.process_conditions.reaction_time.value} {recipe.process_conditions.reaction_time.unit}
                              </span>
                            </div>
                          )}
                          {recipe.process_conditions.feeding_hours && (
                            <div style={{ padding: "8px 12px", background: "#F8FAFC", borderRadius: 6 }}>
                              <div style={{ fontWeight: 600, color: "#1E293B", fontSize: "0.8125rem", marginBottom: 4 }}>
                                Feeding Hours:
                              </div>
                              <div style={{ paddingLeft: 8, fontSize: "0.8125rem", color: "#334155", display: "flex", flexDirection: "column", gap: 3 }}>
                                <div><strong>Monomer:</strong> {recipe.process_conditions.feeding_hours.monomer || "N/A"}</div>
                                <div><strong>Emulsifier:</strong> {recipe.process_conditions.feeding_hours.emulsifier || "N/A"}</div>
                                <div><strong>Catalyst:</strong> {recipe.process_conditions.feeding_hours.catalyst || "N/A"}</div>
                              </div>
                            </div>
                          )}
                          {recipe.process_conditions.temperature_profile && recipe.process_conditions.temperature_profile.length > 0 && (
                            <div style={{ padding: "8px 12px", background: "#F8FAFC", borderRadius: 6 }}>
                              <div style={{ fontWeight: 600, color: "#1E293B", fontSize: "0.8125rem", marginBottom: 4 }}>
                                Temperature Profile:
                              </div>
                              <div style={{ paddingLeft: 8, fontSize: "0.8125rem", color: "#334155", display: "flex", flexDirection: "column", gap: 3 }}>
                                {recipe.process_conditions.temperature_profile.map((t, idx) => (
                                  <div key={idx}>
                                    <strong>{t.stage}:</strong> {t.value} {t.unit}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ ...card, padding: 16 }}>
                    {recipe.properties.map((prop) => (
                      <div key={prop.id} style={{ fontSize: "0.875rem", marginBottom: 8, color: TEXT }}>
                        <strong>{prop.name}:</strong> {prop.value} {prop.unit}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                onClick={() => setModalMode(null)}
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
                {modalMode === "edit" ? "Cancel" : "Close"}
              </button>
              {modalMode === "edit" && (
                <button
                  onClick={async () => {
                    await onSaveEdits?.(recipe.id);
                    setModalMode(null);
                  }}
                  style={{
                    background: TEAL,
                    color: "white",
                    border: "none",
                    borderRadius: 6,
                    padding: "8px 20px",
                    fontWeight: 700,
                    cursor: "pointer",
                  }}
                >
                  Save Changes
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Step1TargetSpec({
  onBack,
  onContinue,
}: {
  onBack: () => void;
  onContinue: () => void;
}) {
  const { state: researchState } = usePatentResearch();
  const {
    createCycle,
    generateRecipes,
    cycle,
    candidates,
    resetContext,
    generationState,
    step1Inputs,
    setStep1Inputs,
    setGenerationSnapshot,
    markInputsChanged,
  } = useRecipe();
  const patentResearchReport = researchState.recipeData;
  const { properties, addProperty, updateProperty, deleteProperty } = useProperties();
  const [showPatentReport, setShowPatentReport] = useState(false);
  const [showSelectReport, setShowSelectReport] = useState(false);
  const hasAssociatedReport = Boolean(
    researchState.researchRunId &&
      (researchState.structuredReport ||
        researchState.reportHtml ||
        researchState.recipeData)
  );
  const patentColumns = getPatentColumns(patentResearchReport);

  const desired = step1Inputs.desired;
  const setDesired = (valOrFn: any) => {
    const next = typeof valOrFn === 'function' ? valOrFn(step1Inputs.desired) : valOrFn;
    setStep1Inputs({ desired: next });
  };

  const competitors = step1Inputs.competitors;
  const setCompetitors = (valOrFn: any) => {
    const next = typeof valOrFn === 'function' ? valOrFn(step1Inputs.competitors) : valOrFn;
    setStep1Inputs({ competitors: next });
  };

  const competitorValues = step1Inputs.competitorValues;
  const setCompetitorValues = (valOrFn: any) => {
    const next = typeof valOrFn === 'function' ? valOrFn(step1Inputs.competitorValues) : valOrFn;
    setStep1Inputs({ competitorValues: next });
  };

  const targetProduct = step1Inputs.targetProduct || researchState.compoundName || '';
  const setTargetProduct = (val: string) => {
    setStep1Inputs({ targetProduct: val });
  };

  const patentValues = useMemo(() => {
    return buildPatentColumnValues(patentResearchReport, properties);
  }, [patentResearchReport, properties]);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [showPatentRecipes, setShowPatentRecipes] = useState<
    Record<string, boolean>
  >({});
  const [showAddProperty, setShowAddProperty] = useState(false);
  const [editingProperty, setEditingProperty] = useState<string | null>(null);
  const [newProperty, setNewProperty] = useState({
    feature: '',
    unit: '',
    category: '',
    dataType: 'number' as 'number' | 'text' | 'boolean',
  });

  const lastRunIdRef = useRef<string | null>(researchState.researchRunId);
  const lastCompoundRef = useRef<string | null>(researchState.compoundName);

  // Sync initial compound name from patent research if targetProduct is not yet populated
  useEffect(() => {
    if (researchState.compoundName && !step1Inputs.targetProduct) {
      setStep1Inputs({ targetProduct: researchState.compoundName });
    }
  }, [researchState.compoundName, step1Inputs.targetProduct]);

  // Re-hydrate state whenever a patent research report is selected or switched
  useEffect(() => {
    const isNewReport = researchState.researchRunId !== lastRunIdRef.current;
    const isNewCompound = researchState.compoundName !== lastCompoundRef.current;

    if (isNewReport || (researchState.compoundName && isNewCompound)) {
      lastRunIdRef.current = researchState.researchRunId;
      lastCompoundRef.current = researchState.compoundName;

      // Update targetProduct to match the newly selected report's compound
      if (researchState.compoundName) {
        setStep1Inputs({ targetProduct: researchState.compoundName });
      }

      // If switching from an existing report, invalidate old generated recipes
      // to avoid showing/mixing recipes from Report A when Report B is active
      if (isNewReport && (cycle || (candidates?.length || 0) > 0)) {
        resetContext();
      }

      // Mark generation as stale since the report input has changed
      if (isNewReport) {
        markInputsChanged();
      }
    }
  }, [researchState.researchRunId, researchState.compoundName, cycle, candidates?.length, resetContext, markInputsChanged, setStep1Inputs]);

  const hasExistingCandidates = (candidates?.length || 0) > 0 || (cycle?.candidates?.length || 0) > 0;
  const snap = generationState.generationContextSnapshot;
  const isInputsUnchanged = Boolean(
    hasExistingCandidates &&
    !generationState.inputsChangedSinceGeneration &&
    snap !== null &&
    snap.reportId === researchState.researchRunId &&
    snap.targetProduct === (targetProduct.trim() || researchState.compoundName || '').trim() &&
    snap.desiredJson === JSON.stringify(desired) &&
    snap.competitorValuesJson === JSON.stringify(competitorValues)
  );

  const handleRun = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const formattedCompetitorData = competitors
        .map(c => {
          const vals: Record<string, string> = {};
          properties.forEach(p => {
            if (competitorValues[p.feature]?.[c.id]) {
              vals[p.feature] = competitorValues[p.feature][c.id];
            }
          });
          return {
            name: c.name?.trim() || "Unknown Competitor",
            values: vals
          };
        })
        .filter(c => Object.keys(c.values).length > 0 || c.name.trim() !== "Unknown Competitor");

      // Convert desired (Record<feature, {min,max}>) + properties list into target_properties
      const targetProperties = properties.map(p => ({
        id: p.id,
        feature: p.feature,
        unit: p.unit || '',
        min: desired[p.feature]?.min ?? '',
        max: desired[p.feature]?.max ?? '',
        category: (p as any).category || '',
        dataType: (p as any).dataType || 'number',
      })).filter(p => p.feature);

      const activeTargetProduct = targetProduct.trim() || researchState.compoundName || 'Unknown Product';

      // Pass created cycle id directly to generateRecipes to avoid stale closures
      const newCycleId = await createCycle({
        research_run_id: researchState.researchRunId || null,
        target_product: activeTargetProduct,
        target_properties: targetProperties,
        competitor_data: formattedCompetitorData,
      });
      await generateRecipes(newCycleId);

      // Record snapshot of inputs used for this generation
      setGenerationSnapshot({
        targetProduct: activeTargetProduct,
        desiredJson: JSON.stringify(desired),
        competitorValuesJson: JSON.stringify(competitorValues),
        reportId: researchState.researchRunId,
      });

      onContinue();
    } catch (e: any) {
      console.error(e);
      setRunError(e?.message || "Failed to generate recipes");
    } finally {
      setRunning(false);
    }
  };

  const readOnlyCell = {
    padding: "8px 12px",
    fontSize: "0.8125rem",
    color: "#374151",
    background: "#F9FAFB",
    textAlign: "right" as const,
    fontVariantNumeric: "tabular-nums" as const,
    borderRight: `1px solid ${BORDER}`,
  };

  const patentCell = {
    ...readOnlyCell,
    background: "#F3F4F6",
    color: "#4B5563",
  };

  const editableInputStyle = {
    width: "100%",
    border: "1px solid #E5E7EB",
    background: "white",
    fontSize: "0.8125rem",
    color: TEXT,
    outline: "none",
    fontFamily: "inherit",
    textAlign: "right" as const,
    fontVariantNumeric: "tabular-nums" as const,
    padding: "4px 6px",
    borderRadius: "4px",
    boxSizing: "border-box" as const,
  };

  const headerCell = {
    padding: "9px 12px",
    fontSize: "0.75rem",
    fontWeight: 700,
    color: BLUE,
    background: BG,
    textAlign: "right" as const,
    whiteSpace: "nowrap" as const,
    borderRight: `1px solid ${BORDER}`,
    borderBottom: `1px solid ${BORDER}`,
  };

  return (
    <div>
      {/* Target Product input — compound name sent to the LLM context */}
      <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <label
          htmlFor="target-product-input"
          style={{ fontSize: '0.875rem', fontWeight: 600, color: TEXT, whiteSpace: 'nowrap' }}
        >
          Target Product:
        </label>
        <input
          id="target-product-input"
          type="text"
          value={targetProduct}
          onChange={e => setTargetProduct(e.target.value)}
          placeholder={researchState.compoundName || 'e.g. Low ACN NBR, SBR, XSBR…'}
          style={{
            flex: 1,
            maxWidth: 360,
            border: `1px solid ${BORDER}`,
            borderRadius: 6,
            padding: '6px 10px',
            fontSize: '0.875rem',
            color: TEXT,
            outline: 'none',
            fontFamily: 'inherit',
          }}
        />
        {hasAssociatedReport && researchState.compoundName && (
          <span style={{ fontSize: '0.75rem', color: '#6B7280' }}>
            Report: <strong style={{ color: BLUE }}>{researchState.compoundName}</strong>
          </span>
        )}
      </div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ ...card, overflow: "hidden", minWidth: "fit-content" }}>
          <table
            style={{
              width: "100%",
              minWidth: "1000px",
              borderCollapse: "collapse",
              tableLayout: "fixed",
            }}
          >
            <colgroup>
              <col style={{ width: "28%", minWidth: "300px" }} />
              {competitors.map((c) => (
                <col key={c.id} style={{ width: `${28 / Math.max(1, competitors.length)}%`, minWidth: "120px" }} />
              ))}
              <col style={{ width: "24%", minWidth: "280px" }} />
              <col style={{ width: "20%", minWidth: "220px" }} />
            </colgroup>
            <thead>
              <tr>
                <th
                  style={{
                    ...headerCell,
                    textAlign: "left",
                    background: "white",
                  }}
                />
                <th
                  colSpan={competitors.length}
                  style={{
                    padding: "9px 12px",
                    fontSize: "0.75rem",
                    fontWeight: 800,
                    color: BLUE,
                    background: "rgba(31,95,168,0.07)",
                    textAlign: "center",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `1px solid ${BORDER}`,
                    textTransform: "uppercase",
                  }}
                >
                  Competitor Product Properties
                </th>
                <th
                  rowSpan={2}
                  style={{
                    padding: "9px 12px",
                    fontSize: "0.75rem",
                    fontWeight: 800,
                    color: "#6B7280",
                    background: "#F3F4F6",
                    textAlign: "center",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `1px solid ${BORDER}`,
                    textTransform: "uppercase",
                    width: 320,
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: '0 16px' }}>
                    <div style={{ marginBottom: 4 }}>Patent Research Data</div>
                    <div style={{ fontSize: '0.7rem', fontWeight: 500, color: '#9CA3AF', textTransform: 'none', marginBottom: 8, lineHeight: 1.4, textAlign: 'center' }}>
                      {hasAssociatedReport
                        ? `Using: ${researchState.compoundName || "Selected report"}`
                        : "Select or view a Patent Research Report for this simulator."}
                    </div>
                    <button
                      onClick={() => setShowSelectReport(true)}
                      style={{
                        background: "white",
                        color: BLUE,
                        border: `1px solid ${BLUE}`,
                        borderRadius: 6,
                        padding: "8px 18px",
                        fontSize: "0.8125rem",
                        fontWeight: 600,
                        cursor: "pointer",
                        textTransform: "none",
                        marginBottom: 8,
                        width: "100%",
                        maxWidth: 200,
                      }}
                    >
                      Select Patent Report
                    </button>
                    <button
                      onClick={() => setShowPatentReport(true)}
                      disabled={!hasAssociatedReport}
                      title={
                        hasAssociatedReport
                          ? "View associated patent report"
                          : "Select a patent report first"
                      }
                      style={{
                        background: hasAssociatedReport ? TEAL : "#9CA3AF",
                        color: "white",
                        border: "none",
                        borderRadius: 6,
                        padding: "8px 18px",
                        fontSize: "0.8125rem",
                        fontWeight: 600,
                        cursor: hasAssociatedReport ? "pointer" : "not-allowed",
                        textTransform: "none",
                        width: "100%",
                        maxWidth: 200,
                      }}
                    >
                      View Patent Report
                    </button>
                  </div>
                </th>
                <th
                  style={{
                    padding: "9px 12px",
                    fontSize: "0.75rem",
                    fontWeight: 800,
                    color: TEAL,
                    background: "rgba(31,183,181,0.10)",
                    textAlign: "center",
                    borderBottom: `1px solid ${BORDER}`,
                    borderLeft: `2px solid ${TEAL}`,
                    textTransform: "uppercase",
                  }}
                >
                  Target Polymer Properties
                </th>
              </tr>
              <tr>
                <th style={{ ...headerCell, textAlign: "left" }}>
                  Property
                </th>
                {competitors.map((c, idx) => (
                  <th key={c.id} style={{ ...headerCell, padding: "4px 8px" }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input
                        type="text"
                        value={c.name}
                        onChange={(e) => setCompetitors(prev => prev.map((p, i) => i === idx ? { ...p, name: e.target.value } : p))}
                        placeholder="Company Name"
                        style={{
                          width: '100%',
                          border: '1px solid transparent',
                          background: 'transparent',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          color: BLUE,
                          textAlign: 'center',
                          outline: 'none',
                        }}
                        onFocus={(e) => { e.target.style.background = 'white'; e.target.style.border = `1px solid ${BORDER}`; }}
                        onBlur={(e) => { e.target.style.background = 'transparent'; e.target.style.border = '1px solid transparent'; }}
                      />
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {competitors.length > 1 && (
                          <button
                            onClick={() => {
                              if (confirm("Are you sure you want to remove this company?")) {
                                setCompetitors(prev => prev.filter((_, i) => i !== idx));
                                // Cleanup values
                                setCompetitorValues(prev => {
                                  const next = { ...prev };
                                  Object.keys(next).forEach(prop => {
                                    if (next[prop]?.[c.id]) {
                                      const newPropVals = { ...next[prop] };
                                      delete newPropVals[c.id];
                                      next[prop] = newPropVals;
                                    }
                                  });
                                  return next;
                                });
                              }
                            }}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: '#EF4444',
                              cursor: 'pointer',
                              padding: '2px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              opacity: 0.7,
                            }}
                            onMouseOver={(e) => e.currentTarget.style.opacity = '1'}
                            onMouseOut={(e) => e.currentTarget.style.opacity = '0.7'}
                            title="Remove Company"
                          >
                            <X size={12} strokeWidth={3} />
                          </button>
                        )}
                        {idx === competitors.length - 1 && (
                          <button
                            onClick={() => setCompetitors(prev => [...prev, { id: `c${Date.now()}`, name: '' }])}
                            style={{
                              background: 'none',
                              border: 'none',
                              color: TEAL,
                              cursor: 'pointer',
                              padding: '2px',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center'
                            }}
                            title="Add Company"
                          >
                            <Plus size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                  </th>
                ))}
                {/* patentColumns removed */}
                <th
                  style={{
                    ...headerCell,
                    background: "rgba(31,183,181,0.08)",
                    borderLeft: `2px solid ${TEAL}`,
                    color: TEAL,
                  }}
                >
                  Min / Max
                </th>
              </tr>
            </thead>
            <tbody>
              {properties.map((row) => (
                <tr key={row.id} style={{ borderTop: `1px solid ${BORDER}` }}>
                  <td
                    style={{
                      padding: "8px 12px",
                      fontSize: "0.8125rem",
                      color: TEXT,
                      fontWeight: 500,
                      borderRight: `1px solid ${BORDER}`,
                      position: 'relative',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {editingProperty === row.id ? (
                        <input
                          type="text"
                          value={row.feature}
                          onChange={(e) => updateProperty(row.id, { feature: e.target.value })}
                          onBlur={() => setEditingProperty(null)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') setEditingProperty(null);
                            if (e.key === 'Escape') setEditingProperty(null);
                          }}
                          autoFocus
                          style={{
                            width: '100%',
                            border: '1px solid #E5E7EB',
                            borderRadius: 4,
                            padding: '4px 8px',
                            fontSize: '0.8125rem',
                            fontFamily: 'inherit',
                          }}
                        />
                      ) : (
                        <>
                          <span onClick={() => setEditingProperty(row.id)} style={{ cursor: 'pointer', flex: 1 }}>
                            {row.feature}
                          </span>
                          {row.unit && (
                            <span style={{ color: "#9CA3AF", marginLeft: 4 }}>
                              ({row.unit})
                            </span>
                          )}
                          <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
                            <button
                              onClick={() => setEditingProperty(row.id)}
                              style={{
                                background: 'none',
                                border: 'none',
                                cursor: 'pointer',
                                color: '#9CA3AF',
                                padding: 2,
                              }}
                              title="Edit property name"
                            >
                              <Edit2 size={14} />
                            </button>
                            <button
                              onClick={() => {
                                if (confirm(`Are you sure you want to delete "${row.feature}"?`)) {
                                  deleteProperty(row.id);
                                }
                              }}
                              style={{
                                background: 'none',
                                border: 'none',
                                cursor: 'pointer',
                                color: '#EF4444',
                                padding: 2,
                              }}
                              title="Delete property"
                            >
                              <Trash2 size={14} />
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </td>
                  {competitors.map((comp) => (
                    <td key={comp.id} style={readOnlyCell}>
                      <input
                        type="text"
                        value={competitorValues[row.feature]?.[comp.id] || ""}
                        onChange={(e) =>
                          setCompetitorValues((prev) => ({
                            ...prev,
                            [row.feature]: {
                              ...(prev[row.feature] || {}),
                              [comp.id]: e.target.value,
                            },
                          }))
                        }
                        style={editableInputStyle}
                      />
                    </td>
                  ))}
                  <td style={{ ...patentCell, borderRight: `1px solid ${BORDER}` }} />
                  <td
                    style={{
                      padding: "4px 8px",
                      background: "rgba(31,183,181,0.05)",
                      borderLeft: `2px solid ${TEAL}`,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <input
                        type="text"
                        value={desired[row.feature]?.min || ""}
                        onChange={(e) =>
                          setDesired((prev) => ({
                            ...prev,
                            [row.feature]: {
                              ...prev[row.feature],
                              min: e.target.value,
                            },
                          }))
                        }
                        placeholder="Min"
                        style={{
                          width: 100,
                          border: "1px solid #E5E7EB",
                          borderRadius: 4,
                          padding: "6px 8px",
                          fontSize: "0.75rem",
                          textAlign: "center",
                        }}
                      />
                      <span style={{ color: "#9CA3AF", fontSize: "0.75rem" }}>
                        –
                      </span>
                      <input
                        type="text"
                        value={desired[row.feature]?.max || ""}
                        onChange={(e) =>
                          setDesired((prev) => ({
                            ...prev,
                            [row.feature]: {
                              ...prev[row.feature],
                              max: e.target.value,
                            },
                          }))
                        }
                        placeholder="Max"
                        style={{
                          width: 100,
                          border: "1px solid #E5E7EB",
                          borderRadius: 4,
                          padding: "6px 8px",
                          fontSize: "0.75rem",
                          textAlign: "center",
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
              {showAddProperty && (
                <tr style={{ borderTop: `1px solid ${BORDER}`, background: "rgba(31,183,181,0.03)" }}>
                  <td
                    style={{
                      padding: "8px 12px",
                      borderRight: `1px solid ${BORDER}`,
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <input
                        type="text"
                        placeholder="Property Name"
                        value={newProperty.feature}
                        onChange={(e) => setNewProperty(prev => ({ ...prev, feature: e.target.value }))}
                        style={{
                          width: '100%',
                          border: '1px solid #E5E7EB',
                          borderRadius: 4,
                          padding: '6px 8px',
                          fontSize: '0.8125rem',
                          fontFamily: 'inherit',
                        }}
                      />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input
                          type="text"
                          placeholder="Unit"
                          value={newProperty.unit}
                          onChange={(e) => setNewProperty(prev => ({ ...prev, unit: e.target.value }))}
                          style={{
                            flex: 1,
                            border: '1px solid #E5E7EB',
                            borderRadius: 4,
                            padding: '6px 8px',
                            fontSize: '0.8125rem',
                            fontFamily: 'inherit',
                          }}
                        />
                        <select
                          value={newProperty.dataType}
                          onChange={(e) => setNewProperty(prev => ({ ...prev, dataType: e.target.value as 'number' | 'text' | 'boolean' }))}
                          style={{
                            flex: 1,
                            border: '1px solid #E5E7EB',
                            borderRadius: 4,
                            padding: '6px 8px',
                            fontSize: '0.8125rem',
                            fontFamily: 'inherit',
                          }}
                        >
                          <option value="number">Number</option>
                          <option value="text">Text</option>
                          <option value="boolean">Boolean</option>
                        </select>
                      </div>
                    </div>
                  </td>
                  {competitors.map((comp) => (
                    <td key={comp.id} style={readOnlyCell}>
                      <input
                        type="text"
                        placeholder=""
                        disabled
                        style={{
                          ...editableInputStyle,
                          background: '#F9FAFB',
                          cursor: 'not-allowed',
                        }}
                      />
                    </td>
                  ))}
                  <td style={{ ...patentCell, borderRight: `1px solid ${BORDER}` }} />
                  <td
                    style={{
                      padding: "4px 8px",
                      background: "rgba(31,183,181,0.05)",
                      borderLeft: `2px solid ${TEAL}`,
                    }}
                  >
                    <div
                      style={{
                        display: "flex",
                        gap: 8,
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <button
                        onClick={() => {
                          if (newProperty.feature.trim()) {
                            addProperty({
                              feature: newProperty.feature,
                              unit: newProperty.unit,
                              category: newProperty.category,
                              dataType: newProperty.dataType,
                              basf: '',
                              syn: '',
                              tri: '',
                            });
                            setNewProperty({ feature: '', unit: '', category: '', dataType: 'number' });
                            setShowAddProperty(false);
                          }
                        }}
                        style={{
                          background: TEAL,
                          color: 'white',
                          border: 'none',
                          borderRadius: 4,
                          padding: '6px 12px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Save
                      </button>
                      <button
                        onClick={() => {
                          setShowAddProperty(false);
                          setNewProperty({ feature: '', unit: '', category: '', dataType: 'number' });
                        }}
                        style={{
                          background: '#E5E7EB',
                          color: '#374151',
                          border: 'none',
                          borderRadius: 4,
                          padding: '6px 12px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot>
              {!showAddProperty && (
                <tr>
                  <td
                    colSpan={competitors.length + 3}
                    style={{
                      borderTop: `1px solid ${BORDER}`,
                      padding: '12px',
                      textAlign: 'center',
                    }}
                  >
                    <button
                      onClick={() => setShowAddProperty(true)}
                      style={{
                        background: 'rgba(31,183,181,0.1)',
                        color: TEAL,
                        border: `1px dashed ${TEAL}`,
                        borderRadius: 6,
                        padding: '8px 16px',
                        fontSize: '0.8125rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        margin: '0 auto',
                      }}
                    >
                      <Plus size={16} />
                      Add Property
                    </button>
                  </td>
                </tr>
              )}

            </tfoot>
          </table>
        </div>
      </div>

      {/* showPatentRecipes removed */}

      {runError && (
        <div
          style={{
            background: "#FEE2E2",
            border: "1px solid #FCA5A5",
            color: "#991B1B",
            padding: "10px 14px",
            borderRadius: 6,
            marginTop: 16,
            fontSize: "0.875rem",
          }}
        >
          {runError}
        </div>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 20,
        }}
      >
        <button
          onClick={onBack}
          style={{
            border: `1px solid ${BORDER}`,
            color: "#6B7280",
            background: "white",
            borderRadius: 7,
            padding: "9px 18px",
            fontSize: "0.875rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <ChevronLeft size={15} /> Back
        </button>
        {isInputsUnchanged ? (
          <button
            onClick={onContinue}
            style={{
              background: TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "11px 24px",
              fontSize: "0.875rem",
              fontWeight: 700,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
              boxShadow: "0 1px 3px rgba(31,183,181,0.25)",
            }}
            title="Go to existing generated recipes without regenerating"
          >
            Next <ChevronRight size={16} />
          </button>
        ) : (
          <button
            onClick={handleRun}
            disabled={running}
            style={{
              background: running ? "#9CA3AF" : TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "11px 22px",
              fontSize: "0.875rem",
              fontWeight: 700,
              cursor: running ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {running ? (
              <>
                <Loader
                  size={16}
                  style={{ animation: "spin 1s linear infinite" }}
                />
                Generating recipes…
              </>
            ) : (
              <>
                <Sparkles size={16} /> Generate Polymerization Recipes
              </>
            )}
          </button>
        )}
      </div>

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>

      {showPatentReport && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 9999, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
          <div style={{ backgroundColor: '#F7FAFC', borderRadius: 8, padding: '24px', maxWidth: '900px', width: '100%', maxHeight: '90vh', overflowY: 'auto', position: 'relative' }}>
            <button onClick={() => setShowPatentReport(false)} style={{ position: 'absolute', top: 16, right: 16, background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.5rem', lineHeight: 1 }}>&times;</button>
            <PatentReportViewer />
          </div>
        </div>
      )}

      <SelectPatentReportModal
        open={showSelectReport}
        onClose={() => setShowSelectReport(false)}
      />
    </div>
  );
}

export function Step2PolymerizationRecommendations({
  onBack,
}: {
  onBack: () => void;
  onContinue?: () => void;
}) {
  const {
    candidates,
    selectCandidate,
    selectedCandidate,
    cycle,
    cycleId,
    saveSavedRecipe,
    updateCandidateRecipeData,
    updateCandidateLocally,
  } = useRecipe();
  const navigate = useNavigate();
  const [editingRecipes, setEditingRecipes] = useState<EditableRecipe[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [downloadingExcel, setDownloadingExcel] = useState(false);

  const handleDownloadExcelAll = async () => {
    if (editingRecipes.length === 0) return;
    setDownloadingExcel(true);
    try {
      const model = buildRecipeComparisonModel(editingRecipes, cycle);
      const compound =
        cycle?.target_compound ||
        (editingRecipes[0] as any)?.raw_data?.compound ||
        "Polymer_Formulation";
      await exportRecipeComparisonToExcel(model, compound);
    } catch (err) {
      console.error("Failed to export Excel comparison:", err);
      alert("Failed to export Excel comparison. Please try again.");
    } finally {
      setDownloadingExcel(false);
    }
  };

  // Multi-select state
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<Set<string>>(new Set());
  const [showBatchSaveModal, setShowBatchSaveModal] = useState(false);
  const [batchNames, setBatchNames] = useState<Record<string, string>>({});
  const [batchSaving, setBatchSaving] = useState(false);

  useEffect(() => {
    const source =
      candidates?.length > 0
        ? candidates
        : cycle?.candidates?.length > 0
          ? cycle.candidates
          : [];
    if (source.length > 0) {
      setEditingRecipes(source.map(convertToEditableRecipe));
    }
  }, [candidates, cycle?.candidates]);

  useEffect(() => {
    if (selectedCandidate) {
      const edited = editingRecipes.find((r) => r.id === selectedCandidate.id);
      setSaveName(edited?.name || selectedCandidate.name || "");
      setSaveMessage(null);
    }
  }, [selectedCandidate?.id]);

  const handleSelect = async (id: string) => {
    setSubmitting(true);
    try {
      await selectCandidate(id);
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
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
    selectCandidate(recipeId);
  };

  const onUpdateRecipeName = (recipeId: string, name: string) => {
    setEditingRecipes((prev) =>
      prev.map((r) => (r.id === recipeId ? { ...r, name } : r))
    );
  };

  const onAddStage = (recipeId: string, stageName: string) => {
    if (!stageName.trim()) return;
    setEditingRecipes((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStage: EditableRecipeStage = {
          id: `custom-stage-${Date.now()}`,
          stage_name: stageName.trim(),
          parameters: [],
          is_applicable: true,
        };
        return {
          ...r,
          stages: [...(r.stages || []), newStage],
        };
      })
    );
  };

  const onDeleteStage = (recipeId: string, stageId: string) => {
    setEditingRecipes((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).filter((s) => s.id !== stageId);
        const newProps = newStages.flatMap((s) => s.parameters);
        return {
          ...r,
          stages: newStages,
          properties: newProps,
        };
      })
    );
  };

  const onUpdateStageName = (recipeId: string, stageId: string, name: string) => {
    setEditingRecipes((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        return {
          ...r,
          stages: (r.stages || []).map((s) =>
            s.id === stageId ? { ...s, stage_name: name.trim() } : s
          ),
        };
      })
    );
  };

  const handleSaveRecipeEdits = async (recipeId: string) => {
    const edited = editingRecipes.find((r) => r.id === recipeId);
    if (!edited) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const recipeData = editableRecipeToRecipeData(edited);
      await updateCandidateRecipeData(recipeId, {
        recipe_data: recipeData,
        name: edited.name,
      });
      updateCandidateLocally(recipeId, recipeData, edited.name);
      setSaveMessage(`Edits to "${edited.name}" saved successfully.`);
    } catch (err: any) {
      console.error(err);
      setSaveMessage(err?.message || "Failed to save edits");
    } finally {
      setSaving(false);
    }
  };

  const onUpdateProperty = (recipeId: string, propertyId: string, updates: Partial<RecipeProperty>) => {
    setEditingRecipes((prev) =>
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
    setEditingRecipes((prev) =>
      prev.map((r) =>
        r.id === recipeId
          ? { ...r, properties: [...r.properties, property] }
          : r
      )
    );
  };

  const onDeleteProperty = (recipeId: string, propertyId: string) => {
    setEditingRecipes((prev) =>
      prev.map((r) =>
        r.id === recipeId
          ? {
              ...r,
              properties: r.properties.filter((p) => p.id !== propertyId),
            }
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
    setEditingRecipes((prev) =>
      prev.map((r) => {
        if (r.id !== recipeId) return r;
        const newStages = (r.stages || []).map((stg) => {
          if (stg.id !== stageId) return stg;
          return {
            ...stg,
            parameters: stg.parameters.map((p) => (p.id === paramId ? { ...p, ...updates } : p)),
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

  const onAddStageParameter = (recipeId: string, stageId: string, param: RecipeProperty) => {
    setEditingRecipes((prev) =>
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

  const onDeleteStageParameter = (recipeId: string, stageId: string, paramId: string) => {
    setEditingRecipes((prev) =>
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

  const onUpdateProcessConditions = (recipeId: string, conditions: EditableProcessConditions) => {
    setEditingRecipes((prev) =>
      prev.map((r) => (r.id === recipeId ? { ...r, process_conditions: conditions } : r))
    );
  };

  const onResetRecipe = (recipeId: string) => {
    const original = candidates.find(c => c.id === recipeId);
    if (original) {
      setEditingRecipes((prev) =>
        prev.map((r) =>
          r.id === recipeId ? convertToEditableRecipe(original) : r
        )
      );
    }
  };

  const handleSaveRecipe = async () => {
    if (!selectedCandidate || !cycleId) return;
    const edited = editingRecipes.find((r) => r.id === selectedCandidate.id);
    if (!edited) return;

    setSaving(true);
    setSaveMessage(null);
    try {
      const recipeData = editableRecipeToRecipeData(edited);
      const name = saveName.trim() || edited.name;

      // Persist local edits onto the candidate first
      await updateCandidateRecipeData(selectedCandidate.id, {
        recipe_data: recipeData,
        name,
      });
      updateCandidateLocally(selectedCandidate.id, recipeData, name);

      await saveSavedRecipe({
        recipe_name: name,
        recipe_data: recipeData,
        target_properties: cycle?.target_properties || cycle?.target_specs || [],
        competitor_properties: cycle?.competitor_data || [],
        source_cycle_id: cycleId,
        source_candidate_id: selectedCandidate.id,
      });

      setSaveMessage("Recipe saved successfully. You can open it from Trial Feedback → Previous Recipes.");
    } catch (e: any) {
      console.error(e);
      setSaveMessage(e?.message || "Failed to save recipe");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSingleRecipe = async (targetRecipe: EditableRecipe) => {
    if (!cycleId) return;
    setSaving(true);
    setSaveMessage(null);
    try {
      const recipeData = editableRecipeToRecipeData(targetRecipe);
      const name = targetRecipe.name;

      // Persist local edits onto candidate first
      await updateCandidateRecipeData(targetRecipe.id, {
        recipe_data: recipeData,
        name,
      });
      updateCandidateLocally(targetRecipe.id, recipeData, name);

      await saveSavedRecipe({
        recipe_name: name,
        recipe_data: recipeData,
        target_properties: cycle?.target_properties || cycle?.target_specs || [],
        competitor_properties: cycle?.competitor_data || [],
        source_cycle_id: cycleId,
        source_candidate_id: targetRecipe.id,
      });

      setSaveMessage(`"${name}" saved successfully. You can open it from Trial Feedback → Previous Recipes.`);
    } catch (e: any) {
      console.error(e);
      setSaveMessage(e?.message || "Failed to save recipe");
    } finally {
      setSaving(false);
    }
  };

  const openBatchSave = () => {
    const names: Record<string, string> = {};
    editingRecipes.forEach((r) => {
      if (selectedCandidateIds.has(r.id)) {
        names[r.id] = r.name;
      }
    });
    setBatchNames(names);
    setShowBatchSaveModal(true);
  };

  const handleSaveBatch = async () => {
    if (!cycleId || selectedCandidateIds.size === 0) return;
    setBatchSaving(true);
    setSaveMessage(null);
    try {
      const selectedRecipes = editingRecipes.filter((r) => selectedCandidateIds.has(r.id));

      // Persist candidate edits in parallel
      await Promise.all(
        selectedRecipes.map((r) => {
          const customName = (batchNames[r.id] || r.name).trim() || r.name;
          const recipeData = editableRecipeToRecipeData(r);
          updateCandidateLocally(r.id, recipeData, customName);
          return updateCandidateRecipeData(r.id, {
            recipe_data: recipeData,
            name: customName,
          });
        })
      );

      const batchItems = selectedRecipes.map((r) => {
        const customName = (batchNames[r.id] || r.name).trim() || r.name;
        const recipeData = editableRecipeToRecipeData(r);
        return {
          recipe_name: customName,
          recipe_data: recipeData,
          target_properties: cycle?.target_properties || cycle?.target_specs || [],
          competitor_properties: cycle?.competitor_data || [],
          source_cycle_id: cycleId,
          source_candidate_id: r.id,
          recipe_kind: "NORMAL" as const,
        };
      });

      const res = await createSavedRecipesBatch(batchItems);
      const savedCount = res?.saved_count ?? batchItems.length;

      setShowBatchSaveModal(false);
      setSelectedCandidateIds(new Set());
      setSaveMessage(
        `Successfully saved ${savedCount} recipe${savedCount === 1 ? "" : "s"} independently. You can open them from Trial Feedback → Previous Recipes.`
      );
    } catch (e: any) {
      console.error(e);
      setSaveMessage(e?.message || "Failed to save selected recipes in batch");
    } finally {
      setBatchSaving(false);
    }
  };

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <button
          onClick={onBack}
          style={{
            display: "flex",
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
            flexShrink: 0,
          }}
          title="Return to input properties while preserving generated recipes"
        >
          <ChevronLeft size={16} /> Back
        </button>
        <div
          style={{
            flex: 1,
            background: "linear-gradient(135deg, #1F5FA8 0%, #1FB7B5 100%)",
            padding: "18px 24px",
            borderRadius: 8,
          }}
        >
          <h2
            style={{
              color: "white",
              fontSize: "1.125rem",
              fontWeight: 700,
              margin: "0 0 4px",
            }}
          >
            Polymerization Recipe Recommendations
          </h2>
          <p
            style={{
              color: "rgba(255,255,255,0.8)",
              fontSize: "0.8125rem",
              margin: 0,
            }}
          >
            5 candidate polymerization recipes generated from patent research and
            target polymer specifications
          </p>
        </div>
      </div>

      {/* TARGET MODE vs GENERAL RECIPE MODE Summary Banner (Section 22) */}
      <div
        style={{
          background: ((cycle?.target_properties || []).filter((tp: any) => (tp.min !== undefined && tp.min !== null && String(tp.min).trim() !== '') || (tp.max !== undefined && tp.max !== null && String(tp.max).trim() !== '') || (tp.target !== undefined && tp.target !== null && String(tp.target).trim() !== '') || (tp.value !== undefined && tp.value !== null && String(tp.value).trim() !== '')).length > 0 || (editingRecipes[0]?.targetsTotal ?? editingRecipes[0]?.targetAnalysis?.targets_total ?? 0) > 0) ? "rgba(31,183,181,0.08)" : "#F8FAFC",
          border: `1.5px solid ${((cycle?.target_properties || []).filter((tp: any) => (tp.min !== undefined && tp.min !== null && String(tp.min).trim() !== '') || (tp.max !== undefined && tp.max !== null && String(tp.max).trim() !== '') || (tp.target !== undefined && tp.target !== null && String(tp.target).trim() !== '') || (tp.value !== undefined && tp.value !== null && String(tp.value).trim() !== '')).length > 0 || (editingRecipes[0]?.targetsTotal ?? editingRecipes[0]?.targetAnalysis?.targets_total ?? 0) > 0) ? TEAL : "#CBD5E1"}`,
          borderRadius: 8,
          padding: "12px 18px",
          marginBottom: 20,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {(() => {
          const count = (cycle?.target_properties || []).filter((tp: any) => (tp.min !== undefined && tp.min !== null && String(tp.min).trim() !== '') || (tp.max !== undefined && tp.max !== null && String(tp.max).trim() !== '') || (tp.target !== undefined && tp.target !== null && String(tp.target).trim() !== '') || (tp.value !== undefined && tp.value !== null && String(tp.value).trim() !== '')).length || (editingRecipes[0]?.targetsTotal ?? editingRecipes[0]?.targetAnalysis?.targets_total ?? 0);
          const isTarget = count > 0;
          return (
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <span
                style={{
                  background: isTarget ? TEAL : "#64748B",
                  color: "white",
                  padding: "4px 10px",
                  borderRadius: 5,
                  fontSize: "0.75rem",
                  fontWeight: 800,
                  letterSpacing: "0.5px",
                }}
              >
                {isTarget ? "TARGET MODE" : "GENERAL RECIPE MODE"}
              </span>
              <span style={{ fontSize: "0.875rem", color: BLUE, fontWeight: 600 }}>
                {isTarget
                  ? `${count} target polymer propert${count === 1 ? 'y' : 'ies'} provided. Candidates evaluated against hard optimization objectives.`
                  : "No explicit target properties provided. Recipe generated from product requirements and patent evidence."}
              </span>
            </div>
          );
        })()}
      </div>

      {saveMessage && (
        <div
          style={{
            padding: "12px 18px",
            marginBottom: 20,
            borderRadius: 8,
            background: saveMessage.includes("Failed") ? "#FEE2E2" : "rgba(31,183,181,0.12)",
            border: `1.5px solid ${saveMessage.includes("Failed") ? "#EF4444" : TEAL}`,
            color: saveMessage.includes("Failed") ? "#991B1B" : BLUE,
            fontWeight: 600,
            fontSize: "0.875rem",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>{saveMessage}</span>
          <button
            onClick={() => setSaveMessage(null)}
            style={{
              background: "none",
              border: "none",
              color: "#6B7280",
              cursor: "pointer",
              fontWeight: 700,
              fontSize: "1rem",
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Multi-Select Action Banner */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: 12,
          padding: "12px 18px",
          marginBottom: 18,
          borderRadius: 8,
          background: selectedCandidateIds.size > 0 ? "rgba(31,183,181,0.08)" : "#F9FAFB",
          border: `1.5px solid ${selectedCandidateIds.size > 0 ? TEAL : BORDER}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: "0.875rem", fontWeight: 700, color: BLUE }}>
            {selectedCandidateIds.size > 0
              ? `${selectedCandidateIds.size} of ${editingRecipes.length} recipes selected`
              : "Select multiple recipes to save together"}
          </span>
          {editingRecipes.length > 0 && (
            <button
              onClick={() => {
                if (selectedCandidateIds.size === editingRecipes.length) {
                  setSelectedCandidateIds(new Set());
                } else {
                  setSelectedCandidateIds(new Set(editingRecipes.map((r) => r.id)));
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
              {selectedCandidateIds.size === editingRecipes.length ? "Deselect All" : "Select All (5)"}
            </button>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button
            onClick={handleDownloadExcelAll}
            disabled={editingRecipes.length === 0 || downloadingExcel}
            style={{
              background: "white",
              color: BLUE,
              border: `1.5px solid ${BLUE}`,
              borderRadius: 7,
              padding: "9px 16px",
              fontSize: "0.8125rem",
              fontWeight: 700,
              cursor: editingRecipes.length === 0 || downloadingExcel ? "not-allowed" : "pointer",
              opacity: editingRecipes.length === 0 ? 0.5 : 1,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
            }}
            title="Download Excel side-by-side comparison of all 5 recipes"
          >
            <Download size={15} /> Download Excel
          </button>

          <button
            onClick={() => navigate("/recipe-simulator/compare")}
            disabled={editingRecipes.length < 2}
            style={{
              background: editingRecipes.length < 2 ? "#94A3B8" : BLUE,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "9px 18px",
              fontSize: "0.8125rem",
              fontWeight: 700,
              cursor: editingRecipes.length < 2 ? "not-allowed" : "pointer",
              opacity: editingRecipes.length < 2 ? 0.6 : 1,
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              boxShadow: editingRecipes.length >= 2 ? "0 2px 4px rgba(31,95,168,0.25)" : "none",
            }}
            title="Compare currently generated recipes side-by-side on dedicated comparison page"
          >
            <Columns3 size={15} /> Compare Recipes
          </button>

          <button
            onClick={openBatchSave}
            disabled={selectedCandidateIds.size === 0}
            style={{
              background: TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "9px 20px",
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
            Save Selected ({selectedCandidateIds.size})
          </button>
        </div>
      </div>

      {/* 5 Recipe Cards Stacked Vertically */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 20,
          width: "100%",
          marginBottom: 24,
        }}
      >
        {editingRecipes.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', width: '100%', color: '#6B7280' }}>
            No recipes generated yet.
          </div>
        ) : (
          editingRecipes.map((recipe) => (
            <PolymerizationRecipeCard
              key={recipe.id}
              recipe={recipe}
              selected={selectedCandidateIds.has(recipe.id)}
              onSelect={() => handleToggleSelect(recipe.id)}
              onSave={() => handleSaveSingleRecipe(recipe)}
              onUpdateProperty={onUpdateProperty}
              onAddProperty={onAddProperty}
              onDeleteProperty={onDeleteProperty}
              onResetRecipe={onResetRecipe}
              onUpdateStageParameter={onUpdateStageParameter}
              onAddStageParameter={onAddStageParameter}
              onDeleteStageParameter={onDeleteStageParameter}
              onUpdateProcessConditions={onUpdateProcessConditions}
              onUpdateRecipeName={onUpdateRecipeName}
              onAddStage={onAddStage}
              onDeleteStage={onDeleteStage}
              onUpdateStageName={onUpdateStageName}
              onSaveEdits={handleSaveRecipeEdits}
            />
          ))
        )}
      </div>

      {/* Multi-Select Batch Save Dialog */}
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
                Save Selected Recipes ({selectedCandidateIds.size})
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
              Specify an independent custom name for each selected recipe before saving to Previous Recipes:
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 20 }}>
              {editingRecipes
                .filter((r) => selectedCandidateIds.has(r.id))
                .map((r, idx) => (
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
                        Recipe #{idx + 1} ({r.stages?.length || 0} stages)
                      </span>
                      <span style={{ fontSize: "0.75rem", color: TEAL, fontWeight: 600 }}>
                        Confidence: {r.confidence}%
                      </span>
                    </div>
                    <input
                      type="text"
                      value={batchNames[r.id] ?? r.name}
                      onChange={(e) => setBatchNames((prev) => ({ ...prev, [r.id]: e.target.value }))}
                      placeholder={`Custom name for Recipe ${idx + 1}`}
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
                ))}
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
                {batchSaving ? <Loader size={14} className="animate-spin" /> : null}
                {batchSaving ? "Saving Batch…" : `Save All Selected (${selectedCandidateIds.size})`}
              </button>
            </div>
          </div>
        </div>
      )}

      {selectedCandidate && (
        <div
          style={{
            ...card,
            padding: 20,
            marginBottom: 24,
            border: `1px solid ${TEAL}`,
            background: "rgba(31,183,181,0.04)",
          }}
        >
          <h3 style={{ margin: "0 0 12px", color: BLUE, fontSize: "0.95rem", fontWeight: 700 }}>
            Save Individual Recipe
          </h3>
          <p style={{ margin: "0 0 12px", color: "#6B7280", fontSize: "0.8125rem" }}>
            Save the currently selected (and any locally edited) recipe for later trial feedback.
          </p>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
            <label style={{ flex: 1, minWidth: 220, fontSize: "0.8125rem", fontWeight: 600, color: BLUE }}>
              Recipe Name
              <input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: 6,
                  border: `1px solid ${BORDER}`,
                  borderRadius: 6,
                  padding: "9px 12px",
                  fontSize: "0.875rem",
                }}
              />
            </label>
            <button
              onClick={handleSaveRecipe}
              disabled={saving || submitting}
              style={{
                background: TEAL,
                color: "white",
                border: "none",
                borderRadius: 7,
                padding: "11px 22px",
                fontSize: "0.875rem",
                fontWeight: 700,
                cursor: saving ? "not-allowed" : "pointer",
                opacity: saving ? 0.7 : 1,
              }}
            >
              {saving ? "Saving…" : "Save This Recipe"}
            </button>
          </div>
          {saveMessage && (
            <p style={{ margin: "12px 0 0", fontSize: "0.8125rem", color: saveMessage.includes("Failed") ? "#991B1B" : TEAL }}>
              {saveMessage}
            </p>
          )}
        </div>
      )}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <button
          onClick={onBack}
          style={{
            border: `1px solid ${BORDER}`,
            color: "#6B7280",
            background: "white",
            borderRadius: 7,
            padding: "9px 18px",
            fontSize: "0.875rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <ChevronLeft size={15} /> Back
        </button>
      </div>
    </div>
  );
}

export function Step3CustomerTrialFeedback({
  onBack,
  onNext,
  onOptimize,
  onSubmitFeedback,
  selectedRecipeName: selectedRecipeNameProp,
  submitLabel,
  nextLabel,
  hideBack,
}: {
  onBack?: () => void;
  onNext?: () => void;
  onOptimize?: () => void;
  onSubmitFeedback?: (payload: {
    feedback_text: string;
    actual_values: Record<string, string>;
    target_values: Record<string, string>;
  }) => Promise<void>;
  selectedRecipeName?: string;
  submitLabel?: string;
  nextLabel?: string;
  hideBack?: boolean;
}) {
  return (
    <CustomerFeedbackProvider initialProperties={CUSTOMER_FEEDBACK_PROPERTIES}>
      <Step3CustomerTrialFeedbackContent
        onBack={onBack}
        onNext={onNext}
        onOptimize={onOptimize}
        onSubmitFeedback={onSubmitFeedback}
        selectedRecipeName={selectedRecipeNameProp}
        submitLabel={submitLabel}
        nextLabel={nextLabel}
        hideBack={hideBack}
      />
    </CustomerFeedbackProvider>
  );
}

function Step3CustomerTrialFeedbackContent({
  onBack,
  onNext,
  onOptimize,
  onSubmitFeedback,
  selectedRecipeName: selectedRecipeNameProp,
  submitLabel,
  nextLabel,
  hideBack,
}: {
  onBack?: () => void;
  onNext?: () => void;
  onOptimize?: () => void;
  onSubmitFeedback?: (payload: {
    feedback_text: string;
    actual_values: Record<string, string>;
    target_values: Record<string, string>;
  }) => Promise<void>;
  selectedRecipeName?: string;
  submitLabel?: string;
  nextLabel?: string;
  hideBack?: boolean;
}) {
  const { customerFeedbackProperties, addCustomerFeedbackProperty, updateCustomerFeedbackProperty, deleteCustomerFeedbackProperty } = useCustomerFeedbackProperties();
  const { createTrial, selectedCandidate } = useRecipe();
  
  const selectedRecipeName = selectedRecipeNameProp || selectedCandidate?.name || "Selected Recipe";
  const [targetValues, setTargetValues] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState("");
  const [showAddProperty, setShowAddProperty] = useState(false);
  const [editingProperty, setEditingProperty] = useState<string | null>(null);
  const [newProperty, setNewProperty] = useState({
    feature: '',
    unit: '',
    category: '',
    dataType: 'number' as 'number' | 'text' | 'boolean',
  });
  const [running, setRunning] = useState(false);

  const handleOptimize = async () => {
    setRunning(true);
    try {
      const payload = {
        feedback_text: notes,
        // Actual column removed from this workflow; column remains in stored schema.
        actual_values: {},
        target_values: targetValues,
      };
      if (onSubmitFeedback) {
        await onSubmitFeedback(payload);
      } else {
        await createTrial(payload);
        onOptimize?.();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div>
      <div style={{ ...card, padding: "20px", marginBottom: 20 }}>
        <h3
          style={{
            margin: "0 0 16px",
            color: TEXT,
            fontSize: "0.95rem",
            fontWeight: 700,
          }}
        >
          Trial Feedback
        </h3>

        <div style={{ marginBottom: 20 }}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 700,
              color: BLUE,
              marginBottom: 8,
              textTransform: "uppercase",
            }}
          >
            Selected Recipe
          </div>
          <div
            style={{
              padding: "10px 12px",
              background: BG,
              border: `1px solid ${BORDER}`,
              borderRadius: 6,
              fontSize: "0.875rem",
              fontWeight: 600,
              color: TEXT,
            }}
          >
            {selectedRecipeName}
          </div>
        </div>

        <div style={{ marginBottom: 20 }}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 700,
              color: BLUE,
              marginBottom: 10,
              textTransform: "uppercase",
            }}
          >
            Trial Feedback
          </div>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{
              width: "100%",
              padding: "12px",
              background: BG,
              border: `1px solid ${BORDER}`,
              borderRadius: 6,
              fontSize: "0.8125rem",
              color: TEXT,
              lineHeight: 1.7,
              fontFamily: "inherit",
              resize: "vertical",
              minHeight: "80px",
              outline: "none",
            }}
            placeholder="Enter trial feedback..."
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 700,
              color: BLUE,
              marginBottom: 10,
              textTransform: "uppercase",
            }}
          >
            Target Properties
          </div>
          <div style={{ overflowX: "hidden" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                tableLayout: "fixed",
              }}
            >
              <thead>
                <tr style={{ background: BG }}>
                  {["Property", "Target"].map((col) => (
                    <th
                      key={col}
                      style={{
                        padding: "9px 12px",
                        textAlign: "left",
                        fontSize: "0.75rem",
                        fontWeight: 700,
                        color: BLUE,
                        border: `1px solid ${BORDER}`,
                      }}
                    >
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {customerFeedbackProperties.map((row) => {
                  return (
                    <tr key={row.id}>
                      <td
                        style={{
                          padding: "9px 12px",
                          fontSize: "0.8125rem",
                          border: `1px solid ${BORDER}`,
                          position: 'relative',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          {editingProperty === row.id ? (
                            <input
                              type="text"
                              value={row.feature}
                              onChange={(e) => updateCustomerFeedbackProperty(row.id, { feature: e.target.value })}
                              onBlur={() => setEditingProperty(null)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') setEditingProperty(null);
                                if (e.key === 'Escape') setEditingProperty(null);
                              }}
                              autoFocus
                              style={{
                                width: '100%',
                                border: '1px solid #E5E7EB',
                                borderRadius: 4,
                                padding: '4px 8px',
                                fontSize: '0.8125rem',
                                fontFamily: 'inherit',
                              }}
                            />
                          ) : (
                            <>
                              <span onClick={() => setEditingProperty(row.id)} style={{ cursor: 'pointer', flex: 1 }}>
                                {row.feature}
                              </span>
                              {row.unit && (
                                <span style={{ color: "#9CA3AF", marginLeft: 4 }}>
                                  ({row.unit})
                                </span>
                              )}
                              <div style={{ display: 'flex', gap: 4, marginLeft: 8 }}>
                                <button
                                  onClick={() => setEditingProperty(row.id)}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: '#9CA3AF',
                                    padding: 2,
                                  }}
                                  title="Edit property name"
                                >
                                  <Edit2 size={14} />
                                </button>
                                <button
                                  onClick={() => {
                                    if (confirm(`Are you sure you want to delete "${row.feature}"?`)) {
                                      deleteCustomerFeedbackProperty(row.id);
                                    }
                                  }}
                                  style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: '#EF4444',
                                    padding: 2,
                                  }}
                                  title="Delete property"
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      </td>
                      <td
                        style={{
                          padding: "9px 12px",
                          fontSize: "0.8125rem",
                          border: `1px solid ${BORDER}`,
                        }}
                      >
                        {row.dataType === 'boolean' ? (
                          <input
                            type="checkbox"
                            checked={targetValues[row.feature] === 'true'}
                            onChange={(e) =>
                              setTargetValues((prev) => ({
                                ...prev,
                                [row.feature]: e.target.checked ? 'true' : 'false',
                              }))
                            }
                            style={{ accentColor: BLUE }}
                          />
                        ) : (
                          <input
                            type={row.dataType === 'number' ? 'number' : 'text'}
                            value={targetValues[row.feature] || ""}
                            onChange={(e) =>
                              setTargetValues((prev) => ({
                                ...prev,
                                [row.feature]: e.target.value,
                              }))
                            }
                            placeholder={`Target ${row.unit ? `(${row.unit})` : ''}`}
                            style={{
                              width: '100%',
                              border: '1px solid #E5E7EB',
                              borderRadius: 4,
                              padding: '6px 8px',
                              fontSize: '0.8125rem',
                              fontFamily: 'inherit',
                              textAlign: 'right',
                            }}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
                {showAddProperty && (
                  <tr style={{ background: "rgba(31,183,181,0.03)" }}>
                    <td
                      style={{
                        padding: "8px 12px",
                        border: `1px solid ${BORDER}`,
                      }}
                    >
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <input
                          type="text"
                          placeholder="Property Name"
                          value={newProperty.feature}
                          onChange={(e) => setNewProperty(prev => ({ ...prev, feature: e.target.value }))}
                          style={{
                            width: '100%',
                            border: '1px solid #E5E7EB',
                            borderRadius: 4,
                            padding: '6px 8px',
                            fontSize: '0.8125rem',
                            fontFamily: 'inherit',
                          }}
                        />
                        <div style={{ display: 'flex', gap: 8 }}>
                          <input
                            type="text"
                            placeholder="Unit"
                            value={newProperty.unit}
                            onChange={(e) => setNewProperty(prev => ({ ...prev, unit: e.target.value }))}
                            style={{
                              flex: 1,
                              border: '1px solid #E5E7EB',
                              borderRadius: 4,
                              padding: '6px 8px',
                              fontSize: '0.8125rem',
                              fontFamily: 'inherit',
                            }}
                          />
                          <select
                            value={newProperty.dataType}
                            onChange={(e) => setNewProperty(prev => ({ ...prev, dataType: e.target.value as 'number' | 'text' | 'boolean' }))}
                            style={{
                              flex: 1,
                              border: '1px solid #E5E7EB',
                              borderRadius: 4,
                              padding: '6px 8px',
                              fontSize: '0.8125rem',
                              fontFamily: 'inherit',
                            }}
                          >
                            <option value="number">Number</option>
                            <option value="text">Text</option>
                            <option value="boolean">Boolean</option>
                          </select>
                        </div>
                      </div>
                    </td>
                    <td
                      style={{
                        padding: "9px 12px",
                        border: `1px solid ${BORDER}`,
                        background: '#F9FAFB',
                      }}
                    >
                      -
                    </td>
                    <td
                      style={{
                        padding: "9px 12px",
                        border: `1px solid ${BORDER}`,
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <button
                          onClick={() => {
                            if (newProperty.feature.trim()) {
                              addCustomerFeedbackProperty({
                                feature: newProperty.feature,
                                unit: newProperty.unit,
                                category: newProperty.category,
                                dataType: newProperty.dataType,
                                basf: '',
                                syn: '',
                                tri: '',
                              });
                              setNewProperty({ feature: '', unit: '', category: '', dataType: 'number' });
                              setShowAddProperty(false);
                            }
                          }}
                          style={{
                            background: TEAL,
                            color: 'white',
                            border: 'none',
                            borderRadius: 4,
                            padding: '6px 12px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Save
                        </button>
                        <button
                          onClick={() => {
                            setShowAddProperty(false);
                            setNewProperty({ feature: '', unit: '', category: '', dataType: 'number' });
                          }}
                          style={{
                            background: '#E5E7EB',
                            color: '#374151',
                            border: 'none',
                            borderRadius: 4,
                            padding: '6px 12px',
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
              <tfoot>
                {!showAddProperty && (
                  <tr>
                    <td
                      colSpan={2}
                      style={{
                        borderTop: `1px solid ${BORDER}`,
                        padding: '12px',
                        textAlign: 'center',
                      }}
                    >
                      <button
                        onClick={() => setShowAddProperty(true)}
                        style={{
                          background: 'rgba(31,183,181,0.1)',
                          color: TEAL,
                          border: `1px dashed ${TEAL}`,
                          borderRadius: 6,
                          padding: '8px 16px',
                          fontSize: '0.8125rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          margin: '0 auto',
                        }}
                      >
                        <Plus size={16} />
                        Add Property
                      </button>
                    </td>
                  </tr>
                )}
              </tfoot>
            </table>
          </div>
        </div>


      </div>

      <div
        style={{
          display: "flex",
          justifyContent: hideBack || !onBack ? "flex-end" : "space-between",
          alignItems: "center",
        }}
      >
        {!hideBack && onBack && (
          <button
            onClick={onBack}
            style={{
              border: `1px solid ${BORDER}`,
              color: "#6B7280",
              background: "white",
              borderRadius: 7,
              padding: "9px 18px",
              fontSize: "0.875rem",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <ChevronLeft size={15} /> Back
          </button>
        )}
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <button
            onClick={handleOptimize}
            disabled={running}
            style={{
              background: running ? "#9CA3AF" : TEAL,
              color: "white",
              border: "none",
              borderRadius: 7,
              padding: "11px 22px",
              fontSize: "0.875rem",
              fontWeight: 700,
              cursor: running ? "not-allowed" : "pointer",
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            {running ? (
              <>
                <Loader
                  size={16}
                  style={{ animation: "spin 1s linear infinite" }}
                />
                Submitting…
              </>
            ) : (
              <>
                <Sparkles size={16} /> {submitLabel || "Submit Trial Feedback"}
              </>
            )}
          </button>
          {onNext && (
            <button
              type="button"
              onClick={onNext}
              style={{
                border: `1.5px solid ${BLUE}`,
                color: BLUE,
                background: "white",
                borderRadius: 7,
                padding: "11px 22px",
                fontSize: "0.875rem",
                fontWeight: 700,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: 6,
                boxShadow: "0 1px 3px rgba(31,95,168,0.12)",
              }}
              title="Return to existing generated optimized recipes without regenerating"
            >
              {nextLabel || "Next"} <ChevronRight size={16} />
            </button>
          )}
        </div>
      </div>

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function OptimizedRecipeCard({ recipe, selected, onSelect }: { recipe: any; selected: boolean; onSelect: () => void }) {
  const [showRecipe, setShowRecipe] = useState(false);
  const { selectedCandidate } = useRecipe();
  const baseRecipe = selectedCandidate?.recipe_data;

  return (
    <div style={{ ...card, padding: "18px", marginBottom: 16, border: selected ? `2px solid ${TEAL}` : `1px solid ${BORDER}` }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <h4 style={{ margin: 0, color: BLUE, fontSize: "0.9375rem", display: 'flex', alignItems: 'center', gap: 8 }}>
          {recipe.name}
          {selected && <CheckCircle2 size={16} color={TEAL} />}
        </h4>
        <div style={{ display: 'flex', gap: 8 }}>
          <span
            style={{
              background: "rgba(31,183,181,0.12)",
              color: TEAL,
              fontWeight: 700,
              fontSize: "0.8125rem",
              padding: "3px 10px",
              borderRadius: 20,
            }}
          >
            Confidence: {recipe.confidence_score ?? recipe.evidence_coverage_score}%
          </span>
          <button
            onClick={onSelect}
            style={{
              background: selected ? 'white' : TEAL,
              color: selected ? TEAL : 'white',
              border: selected ? `1px solid ${TEAL}` : 'none',
              borderRadius: 20,
              padding: '3px 12px',
              fontSize: '0.8125rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {selected ? 'Selected' : 'Select'}
          </button>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div
          style={{
            fontSize: "0.75rem",
            fontWeight: 700,
            color: BLUE,
            marginBottom: 8,
          }}
        >
          Modified Parameters
        </div>
        <table
          style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}
        >
          <thead>
            <tr style={{ background: BG }}>
              {["Parameter", "Previous", "Revised"].map((col) => (
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
            {(recipe.optimization_details?.changes || []).map((change: any) => (
              <tr key={change.parameter}>
                <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}` }}>
                  {change.parameter}
                </td>
                <td style={{ padding: "8px 10px", border: `1px solid ${BORDER}` }}>
                  {change.previous}
                </td>
                <td
                  style={{
                    padding: "8px 10px",
                    border: `1px solid ${BORDER}`,
                    color: TEAL,
                    fontWeight: 600,
                  }}
                >
                  {change.revised}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ marginBottom: 14 }}>
        <div
          style={{
            fontSize: "0.75rem",
            fontWeight: 700,
            color: BLUE,
            marginBottom: 8,
          }}
        >
          Predicted Impact
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 8,
          }}
        >
          {(recipe.optimization_details?.impacts || []).map((impact: any) => (
            <div
              key={impact.property}
              style={{
                padding: "8px 10px",
                background: BG,
                border: `1px solid ${BORDER}`,
                borderRadius: 6,
                fontSize: "0.8125rem",
              }}
            >
              <strong>{impact.property}:</strong> {impact.expected_change}
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={() => setShowRecipe((v) => !v)}
        style={{
          background: BLUE,
          color: "white",
          border: "none",
          borderRadius: 6,
          padding: "8px 16px",
          fontSize: "0.8125rem",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        {showRecipe ? "Hide Recipe" : "View Recipe"}
      </button>

      {showRecipe && baseRecipe && (
          <RecipeDetailTable
            title={`${recipe.name} - Optimized Polymerization Recipe`}
            steps={getPolymerizationRecipeSteps(recipe.recipe_data)}
          />
        )}
    </div>
  );
}

export function Step4OptimizedRecipes({ onBack }: { onBack: () => void }) {
  const { optimizedCandidates, selectOptimized, selectedOptimized, trial } = useRecipe();
  
  return (
    <div>
      <div
        style={{
          background: "linear-gradient(135deg, #1F5FA8 0%, #1FB7B5 100%)",
          padding: "20px 28px",
          marginBottom: 24,
          borderRadius: 8,
        }}
      >
        <h2
          style={{
            color: "white",
            fontSize: "1.125rem",
            fontWeight: 700,
            margin: "0 0 4px",
          }}
        >
          Optimized Polymerization Recipes
        </h2>
        <p
          style={{
            color: "rgba(255,255,255,0.75)",
            fontSize: "0.8125rem",
            margin: 0,
          }}
        >
          Revised recipes generated from trial feedback for the selected recipe.
        </p>
      </div>

      {optimizedCandidates.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', width: '100%', color: '#6B7280' }}>
          No optimized recipes generated yet.
        </div>
      ) : (
        optimizedCandidates.map((recipe) => (
          <OptimizedRecipeCard 
            key={recipe.id} 
            recipe={recipe} 
            selected={selectedOptimized?.id === recipe.id}
            onSelect={() => selectOptimized(recipe.id)}
          />
        ))
      )}

      <div style={{ display: "flex", justifyContent: "flex-start" }}>
        <button
          onClick={onBack}
          style={{
            border: `1px solid ${BORDER}`,
            color: "#6B7280",
            background: "white",
            borderRadius: 7,
            padding: "9px 18px",
            fontSize: "0.875rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <ChevronLeft size={15} /> Back
        </button>
      </div>
    </div>
  );
}

export type { TransferredSpecData };
