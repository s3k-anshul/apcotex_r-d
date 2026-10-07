import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Eye, Pencil, Check, X, Loader, Trash2, Plus, Edit2 } from "lucide-react";
import * as api from "../../services/researchApi";
import { useAuth } from "../../contexts/AuthContext";
import {
  convertToEditableRecipe,
  editableRecipeToRecipeData,
  type EditableRecipe,
  type EditableRecipeStage,
  type RecipeProperty,
} from "./recipeSimulatorDemoData";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const BORDER = "#E5E7EB";
const TEXT = "#1F2937";
const BG = "#F7FAFC";
const RED = "#DC2626";

export type SavedRecipe = {
  id: string;
  recipe_name: string;
  recipe_data: any;
  target_properties?: any[];
  competitor_properties?: any[];
  created_by?: string;
  created_by_name?: string | null;
  updated_by_name?: string | null;
  created_at: string;
  updated_at: string;
  expires_at: string;
  parent_recipe_id?: string | null;
  parent_recipe_name?: string | null;
  revision_number: number;
  status: string;
  is_revision?: boolean;
  notes?: string | null;
  source_cycle_id?: string | null;
  source_candidate_id?: string | null;
  source_trial_id?: string | null;
  source_optimized_id?: string | null;
  recipe_kind?: string;
  optimization_number?: number;
  source_feedback_text?: string | null;
};

/** Compact date for table cells (avoids wide timestamps). */
function fmtCompact(value?: string | null) {
  if (!value) return "—";
  try {
    const d = new Date(value);
    const date = d.toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
    const time = d.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
    return `${date}\n${time}`;
  } catch {
    return value;
  }
}

function fmtDate(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function Truncate({
  text,
  title,
  style,
}: {
  text: string;
  title?: string;
  style?: CSSProperties;
}) {
  return (
    <span
      title={title || text}
      style={{
        display: "block",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        maxWidth: "100%",
        ...style,
      }}
    >
      {text}
    </span>
  );
}

export function RecipePropertiesEditor({
  recipe,
  readOnly,
  onUpdateProperty,
  onAddParameter,
  onDeleteParameter,
  onAddStage,
  onDeleteStage,
  onUpdateStageName,
}: {
  recipe: EditableRecipe;
  readOnly?: boolean;
  onUpdateProperty?: (propertyId: string, updates: Partial<RecipeProperty>) => void;
  onAddParameter?: (stageId: string, param: RecipeProperty) => void;
  onDeleteParameter?: (stageId: string, paramId: string) => void;
  onAddStage?: (stageName: string) => void;
  onDeleteStage?: (stageId: string) => void;
  onUpdateStageName?: (stageId: string, name: string) => void;
}) {
  const [addingToStageId, setAddingToStageId] = useState<string | null>(null);
  const [newParam, setNewParam] = useState({ name: "", value: "", unit: "" });
  const [editingParamId, setEditingParamId] = useState<string | null>(null);
  const [editingStageId, setEditingStageId] = useState<string | null>(null);
  const [tempStageName, setTempStageName] = useState("");
  const [showAddStage, setShowAddStage] = useState(false);
  const [newStageName, setNewStageName] = useState("");

  const hasStages = Array.isArray(recipe.stages) && recipe.stages.length > 0;

  if (hasStages) {
    if (readOnly) {
      return (
        <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14 }}>
          {recipe.stages.map((stage, sIdx) => (
            <div
              key={stage.id || sIdx}
              style={{
                border: `1px solid ${BORDER}`,
                borderRadius: 8,
                background: "#FFFFFF",
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
                  {sIdx + 1}. {stage.stage_name}
                </span>
              </div>
              {stage.parameters && stage.parameters.length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {stage.parameters.map((p) => (
                    <div
                      key={p.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "8px 12px",
                        background: BG,
                        borderRadius: 6,
                        border: `1px solid ${BORDER}`,
                      }}
                    >
                      <span style={{ fontWeight: 600, color: "#1E293B", fontSize: "0.8125rem" }}>
                        {p.name}
                      </span>
                      <span style={{ fontWeight: 700, color: BLUE, fontSize: "0.875rem" }}>
                        Value: {p.value} {p.unit}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div
                  style={{
                    padding: "10px 14px",
                    background: "#F8FAFC",
                    borderRadius: 6,
                    border: "1px dashed #CBD5E1",
                  }}
                >
                  <div style={{ color: "#64748B", fontStyle: "italic", fontSize: "0.8125rem", marginBottom: 4 }}>
                    Not applicable
                  </div>
                  <div style={{ color: "#334155", fontSize: "0.75rem", lineHeight: 1.4 }}>
                    <strong style={{ color: BLUE }}>AI Reason:</strong>{" "}
                    {stage.omission_reason || "No separate stage required for this synthesis route."}
                  </div>
                </div>
              )}
            </div>
          ))}

          {recipe.process_conditions && (
            <div
              style={{
                border: `1px solid ${BORDER}`,
                borderRadius: 8,
                background: "#FFFFFF",
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
                  <div style={{ padding: "8px 12px", background: BG, borderRadius: 6 }}>
                    <span style={{ fontWeight: 600, color: "#1E293B", fontSize: "0.8125rem" }}>
                      Reaction Time:
                    </span>{" "}
                    <span style={{ fontWeight: 700, color: BLUE, fontSize: "0.875rem" }}>
                      {recipe.process_conditions.reaction_time.value} {recipe.process_conditions.reaction_time.unit}
                    </span>
                  </div>
                )}
                {recipe.process_conditions.feeding_hours && (
                  <div style={{ padding: "8px 12px", background: BG, borderRadius: 6 }}>
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
                  <div style={{ padding: "8px 12px", background: BG, borderRadius: 6 }}>
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
        </div>
      );
    }

    return (
      <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
        {recipe.stages.map((stage, sIdx) => (
          <div key={stage.id || sIdx} style={{ border: `1px solid ${BORDER}`, borderRadius: 6, overflow: "hidden" }}>
            <div
              style={{
                padding: "8px 12px",
                background: "rgba(31,95,168,0.06)",
                borderBottom: `1px solid ${BORDER}`,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              {editingStageId === stage.id ? (
                <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, marginRight: 10 }}>
                  <input
                    value={tempStageName}
                    onChange={(e) => setTempStageName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && tempStageName.trim()) {
                        onUpdateStageName?.(stage.id, tempStageName.trim());
                        setEditingStageId(null);
                      }
                    }}
                    autoFocus
                    style={{ padding: "3px 6px", fontSize: "0.8125rem", fontWeight: 700, color: BLUE, border: `1px solid ${BORDER}`, borderRadius: 4, flex: 1 }}
                  />
                  <button
                    onClick={() => {
                      if (tempStageName.trim()) onUpdateStageName?.(stage.id, tempStageName.trim());
                      setEditingStageId(null);
                    }}
                    style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem", cursor: "pointer", fontWeight: 600 }}
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditingStageId(null)}
                    style={{ background: "#E5E7EB", color: "#374151", border: "none", borderRadius: 4, padding: "3px 6px", fontSize: "0.75rem", cursor: "pointer" }}
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: "0.8125rem", fontWeight: 700, color: BLUE }}>
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
                    <Edit2 size={12} />
                  </button>
                </div>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: "0.75rem", color: "#6B7280" }}>
                  {stage.parameters.length} parameter{stage.parameters.length === 1 ? "" : "s"}
                </span>
                <button
                  onClick={() => {
                    if (confirm(`Delete stage "${stage.stage_name}"?`)) {
                      onDeleteStage?.(stage.id);
                    }
                  }}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", padding: 2 }}
                  title="Delete stage"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
              <thead>
                <tr style={{ background: BG }}>
                  <th style={{ padding: "6px 10px", textAlign: "left", fontSize: "0.75rem", fontWeight: 700, color: BLUE, borderBottom: `1px solid ${BORDER}`, width: "45%" }}>
                    Ingredient / Parameter
                  </th>
                  <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", fontWeight: 700, color: BLUE, borderBottom: `1px solid ${BORDER}`, width: "25%" }}>
                    Value
                  </th>
                  <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", fontWeight: 700, color: BLUE, borderBottom: `1px solid ${BORDER}`, width: "20%" }}>
                    Unit
                  </th>
                  <th style={{ padding: "6px 10px", textAlign: "center", fontSize: "0.75rem", fontWeight: 700, color: BLUE, borderBottom: `1px solid ${BORDER}`, width: "10%" }}>
                    ✕
                  </th>
                </tr>
              </thead>
              <tbody>
                {stage.parameters.length === 0 ? (
                  <tr>
                    <td colSpan={4} style={{ padding: "10px", textAlign: "center", color: "#9CA3AF", fontStyle: "italic", fontSize: "0.75rem" }}>
                      Not applicable / omitted for this chemistry
                    </td>
                  </tr>
                ) : (
                  stage.parameters.map((p) => (
                    <tr key={p.id} style={{ borderTop: `1px solid ${BORDER}` }}>
                      <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}`, fontSize: "0.8125rem", color: TEXT, fontWeight: 500 }}>
                        {editingParamId === p.id ? (
                          <input
                            value={p.name}
                            onChange={(e) => onUpdateProperty?.(p.id, { name: e.target.value })}
                            onBlur={() => setEditingParamId(null)}
                            onKeyDown={(e) => e.key === "Enter" && setEditingParamId(null)}
                            autoFocus
                            style={{ width: "100%", padding: "2px 4px", fontSize: "0.8125rem", border: "1px solid #CBD5E1", borderRadius: 4 }}
                          />
                        ) : (
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ flex: 1 }}>{p.name}</span>
                            <button
                              onClick={() => setEditingParamId(p.id)}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#9CA3AF", padding: 2 }}
                              title="Edit parameter name"
                            >
                              <Edit2 size={12} />
                            </button>
                          </div>
                        )}
                      </td>
                      <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}`, textAlign: "center" }}>
                        <input
                          value={p.value}
                          onChange={(e) => onUpdateProperty?.(p.id, { value: e.target.value })}
                          style={{
                            width: "100%",
                            border: `1px solid ${BORDER}`,
                            borderRadius: 4,
                            padding: "4px 6px",
                            fontSize: "0.8125rem",
                            textAlign: "center",
                          }}
                        />
                      </td>
                      <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}`, textAlign: "center" }}>
                        <input
                          value={p.unit}
                          onChange={(e) => onUpdateProperty?.(p.id, { unit: e.target.value })}
                          style={{
                            width: "100%",
                            border: `1px solid ${BORDER}`,
                            borderRadius: 4,
                            padding: "4px 6px",
                            fontSize: "0.8125rem",
                            textAlign: "center",
                          }}
                        />
                      </td>
                      <td style={{ padding: "6px 10px", textAlign: "center" }}>
                        <button
                          onClick={() => onDeleteParameter?.(stage.id, p.id)}
                          style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444", padding: 2 }}
                          title="Delete parameter"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
                {addingToStageId === stage.id && (
                  <tr style={{ borderTop: `1px solid ${BORDER}`, background: "rgba(31,183,181,0.04)" }}>
                    <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}` }}>
                      <input
                        placeholder="Parameter Name"
                        value={newParam.name}
                        onChange={(e) => setNewParam((prev) => ({ ...prev, name: e.target.value }))}
                        style={{ width: "100%", padding: "4px 6px", fontSize: "0.8125rem", border: "1px solid #CBD5E1", borderRadius: 4 }}
                      />
                    </td>
                    <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}`, textAlign: "center" }}>
                      <input
                        placeholder="Value"
                        value={newParam.value}
                        onChange={(e) => setNewParam((prev) => ({ ...prev, value: e.target.value }))}
                        style={{ width: "100%", padding: "4px 6px", fontSize: "0.8125rem", border: "1px solid #CBD5E1", borderRadius: 4, textAlign: "center" }}
                      />
                    </td>
                    <td style={{ padding: "6px 10px", borderRight: `1px solid ${BORDER}`, textAlign: "center" }}>
                      <input
                        placeholder="Unit"
                        value={newParam.unit}
                        onChange={(e) => setNewParam((prev) => ({ ...prev, unit: e.target.value }))}
                        style={{ width: "100%", padding: "4px 6px", fontSize: "0.8125rem", border: "1px solid #CBD5E1", borderRadius: 4, textAlign: "center" }}
                      />
                    </td>
                    <td style={{ padding: "6px 10px", textAlign: "center" }}>
                      <div style={{ display: "flex", gap: 4, justifyContent: "center" }}>
                        <button
                          onClick={() => {
                            if (newParam.name.trim()) {
                              onAddParameter?.(stage.id, {
                                id: `p-${Date.now()}`,
                                name: newParam.name.trim(),
                                value: newParam.value,
                                unit: newParam.unit,
                              });
                              setNewParam({ name: "", value: "", unit: "" });
                              setAddingToStageId(null);
                            }
                          }}
                          style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "2px 6px", fontSize: "0.75rem", cursor: "pointer", fontWeight: 600 }}
                        >
                          Add
                        </button>
                        <button
                          onClick={() => {
                            setAddingToStageId(null);
                            setNewParam({ name: "", value: "", unit: "" });
                          }}
                          style={{ background: "#E5E7EB", color: "#374151", border: "none", borderRadius: 4, padding: "2px 6px", fontSize: "0.75rem", cursor: "pointer" }}
                        >
                          ✕
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
              {addingToStageId !== stage.id && (
                <tfoot>
                  <tr>
                    <td colSpan={4} style={{ padding: "6px 10px", background: "white", textAlign: "right" }}>
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
                        <Plus size={12} /> Add Parameter
                      </button>
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        ))}

        {!showAddStage ? (
          <div style={{ display: "flex", justifyContent: "center" }}>
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
                padding: "6px 14px",
                fontSize: "0.78rem",
                fontWeight: 700,
                cursor: "pointer",
              }}
            >
              <Plus size={14} /> Add Synthesis Stage
            </button>
          </div>
        ) : (
          <div style={{ background: "rgba(31,95,168,0.03)", border: `1.5px dashed ${BLUE}`, borderRadius: 6, padding: 12, display: "flex", gap: 8 }}>
            <input
              placeholder="Stage Name (e.g. Pre-emulsion Charge, Neutralization...)"
              value={newStageName}
              onChange={(e) => setNewStageName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newStageName.trim()) {
                  onAddStage?.(newStageName.trim());
                  setNewStageName("");
                  setShowAddStage(false);
                }
              }}
              autoFocus
              style={{ flex: 1, padding: "6px 8px", border: `1px solid ${BORDER}`, borderRadius: 4, fontSize: "0.8125rem" }}
            />
            <button
              onClick={() => {
                if (newStageName.trim()) {
                  onAddStage?.(newStageName.trim());
                  setNewStageName("");
                  setShowAddStage(false);
                }
              }}
              style={{ background: TEAL, color: "white", border: "none", borderRadius: 4, padding: "6px 12px", fontSize: "0.78rem", fontWeight: 700, cursor: "pointer" }}
            >
              Add
            </button>
            <button
              onClick={() => {
                setShowAddStage(false);
                setNewStageName("");
              }}
              style={{ background: "white", color: "#6B7280", border: `1px solid ${BORDER}`, borderRadius: 4, padding: "6px 10px", fontSize: "0.78rem", cursor: "pointer" }}
            >
              Cancel
            </button>
          </div>
        )}

        {recipe.process_conditions && (
          <div style={{ border: `1px solid ${BORDER}`, borderRadius: 6, overflow: "hidden" }}>
            <div
              style={{
                padding: "8px 12px",
                background: "rgba(31,183,181,0.08)",
                borderBottom: `1px solid ${BORDER}`,
                fontWeight: 700,
                color: BLUE,
                fontSize: "0.8125rem",
              }}
            >
              Process Conditions
            </div>
            <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: 8, fontSize: "0.8125rem", color: TEXT }}>
              {recipe.process_conditions.reaction_time && (
                <div>
                  <strong>Total Reaction Time:</strong> {recipe.process_conditions.reaction_time.value} {recipe.process_conditions.reaction_time.unit}
                </div>
              )}
              {recipe.process_conditions.feeding_hours && (
                <div>
                  <strong>Feeding Hours:</strong> Monomer: {recipe.process_conditions.feeding_hours.monomer || "N/A"} · Emulsifier: {recipe.process_conditions.feeding_hours.emulsifier || "N/A"} · Catalyst: {recipe.process_conditions.feeding_hours.catalyst || "N/A"}
                </div>
              )}
              {recipe.process_conditions.temperature_profile && recipe.process_conditions.temperature_profile.length > 0 && (
                <div>
                  <strong>Temperature Profile:</strong>
                  <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                    {recipe.process_conditions.temperature_profile.map((t, idx) => (
                      <li key={idx}>
                        {t.stage}: {t.value} {t.unit}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  /* Legacy flat parameters fallback */
  return (
    <div style={{ width: "100%", overflowX: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
        <thead>
          <tr style={{ background: BG }}>
            {["Property", "Value", "Unit"].map((h) => (
              <th
                key={h}
                style={{
                  padding: "8px 12px",
                  textAlign: "left",
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  color: BLUE,
                  border: `1px solid ${BORDER}`,
                }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {recipe.properties.map((p) => (
            <tr key={p.id}>
              <td style={{ padding: "8px 12px", border: `1px solid ${BORDER}`, fontSize: "0.8125rem" }}>
                {p.name}
              </td>
              <td style={{ padding: "8px 12px", border: `1px solid ${BORDER}` }}>
                {readOnly ? (
                  <span style={{ fontSize: "0.8125rem" }}>{p.value}</span>
                ) : (
                  <input
                    value={p.value}
                    onChange={(e) => onUpdateProperty?.(p.id, { value: e.target.value })}
                    style={{
                      width: "100%",
                      border: `1px solid ${BORDER}`,
                      borderRadius: 4,
                      padding: "6px 8px",
                      fontSize: "0.8125rem",
                    }}
                  />
                )}
              </td>
              <td style={{ padding: "8px 12px", border: `1px solid ${BORDER}` }}>
                {readOnly ? (
                  <span style={{ fontSize: "0.8125rem" }}>{p.unit}</span>
                ) : (
                  <input
                    value={p.unit}
                    onChange={(e) => onUpdateProperty?.(p.id, { unit: e.target.value })}
                    style={{
                      width: "100%",
                      border: `1px solid ${BORDER}`,
                      borderRadius: 4,
                      padding: "6px 8px",
                      fontSize: "0.8125rem",
                    }}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SavedRecipesPanel({
  open,
  onClose,
  mode = "browse",
  kind = "NORMAL",
  title,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  mode?: "browse" | "select";
  kind?: "NORMAL" | "OPTIMIZED";
  title?: string;
  onSelect?: (recipe: SavedRecipe) => void;
}) {
  const { isAdmin } = useAuth();
  const [recipes, setRecipes] = useState<SavedRecipe[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewRecipe, setViewRecipe] = useState<SavedRecipe | null>(null);
  const [editRecipe, setEditRecipe] = useState<SavedRecipe | null>(null);
  const [editName, setEditName] = useState("");
  const [editEditable, setEditEditable] = useState<EditableRecipe | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SavedRecipe | null>(null);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listSavedRecipes({
        selectableOnly: mode === "select",
        kind,
      });
      setRecipes(data || []);
    } catch (err: any) {
      setError(err?.message || "Failed to load saved recipes");
    } finally {
      setLoading(false);
    }
  }, [mode, kind]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const openEdit = (recipe: SavedRecipe) => {
    setEditRecipe(recipe);
    setEditName(recipe.recipe_name);
    setEditEditable(
      convertToEditableRecipe({
        id: recipe.id,
        name: recipe.recipe_name,
        recipe_data: recipe.recipe_data,
        evidence_coverage_score: 0,
        patent_references: [],
        rank: 0,
      })
    );
  };

  const handleSaveEdit = async () => {
    if (!editRecipe || !editEditable) return;
    setSaving(true);
    try {
      const updated = await api.updateSavedRecipe(editRecipe.id, {
        recipe_name: editName.trim() || editRecipe.recipe_name,
        recipe_data: editableRecipeToRecipeData(editEditable),
      });
      setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      setEditRecipe(null);
      setEditEditable(null);
    } catch (err: any) {
      alert(err?.message || "Failed to update recipe");
    } finally {
      setSaving(false);
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget || !isAdmin) return;
    setDeleting(true);
    try {
      await api.deleteSavedRecipe(deleteTarget.id);
      setRecipes((prev) => prev.filter((r) => r.id !== deleteTarget.id));
      if (viewRecipe?.id === deleteTarget.id) setViewRecipe(null);
      if (editRecipe?.id === deleteTarget.id) {
        setEditRecipe(null);
        setEditEditable(null);
      }
      setDeleteTarget(null);
    } catch (err: any) {
      alert(err?.message || "Failed to delete recipe");
    } finally {
      setDeleting(false);
    }
  };

  if (!open) return null;

  const canEdit = (r: SavedRecipe) =>
    r.status === "ACTIVE" && new Date(r.expires_at).getTime() > Date.now();

  const th: CSSProperties = {
    padding: "8px 6px",
    textAlign: "left",
    fontSize: "0.65rem",
    fontWeight: 700,
    color: BLUE,
    borderBottom: `1.5px solid ${BORDER}`,
    whiteSpace: "nowrap",
  };

  const td: CSSProperties = {
    padding: "8px 6px",
    fontSize: "0.72rem",
    verticalAlign: "middle",
    borderBottom: `1px solid ${BORDER}`,
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 10000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
        overflow: "hidden",
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          borderRadius: 10,
          width: "100%",
          maxWidth: "min(1100px, 96vw)",
          maxHeight: "90vh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 12px 40px rgba(0,0,0,0.18)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            padding: "14px 16px",
            borderBottom: `1px solid ${BORDER}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "linear-gradient(135deg, rgba(31,95,168,0.06), rgba(31,183,181,0.06))",
            flexShrink: 0,
          }}
        >
          <div>
            <h2 style={{ margin: 0, color: BLUE, fontSize: "1.05rem", fontWeight: 700 }}>
              {title || (kind === "OPTIMIZED" ? "Previous Optimized Recipes" : "Previous Recipes")}
            </h2>
            <p style={{ margin: "4px 0 0", color: "#6B7280", fontSize: "0.8125rem" }}>
              {mode === "select"
                ? kind === "OPTIMIZED"
                  ? "Select a saved optimized recipe to optimize again"
                  : "Select an active saved recipe for trial feedback"
                : kind === "OPTIMIZED"
                  ? "Browse and manage saved optimized recipes"
                  : "Browse and manage your saved recipes"}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#6B7280" }}
          >
            <X size={20} />
          </button>
        </div>

        <div
          style={{
            padding: "12px 14px",
            overflowY: "auto",
            overflowX: "hidden",
            flex: 1,
            minHeight: 0,
          }}
        >
          {loading ? (
            <div style={{ textAlign: "center", padding: 40, color: "#6B7280" }}>
              <Loader size={20} style={{ animation: "spin 1s linear infinite" }} /> Loading…
            </div>
          ) : error ? (
            <div style={{ color: "#991B1B", background: "#FEE2E2", padding: 12, borderRadius: 6 }}>
              {error}
            </div>
          ) : recipes.length === 0 ? (
            <div style={{ textAlign: "center", padding: 40, color: "#6B7280" }}>
              No saved recipes found.
            </div>
          ) : (
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                tableLayout: "fixed",
              }}
            >
              <colgroup>
                <col style={{ width: "22%" }} />
                <col style={{ width: "8%" }} />
                <col style={{ width: "12%" }} />
                <col style={{ width: "10%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "9%" }} />
                <col style={{ width: "7%" }} />
                <col style={{ width: "4%" }} />
                <col style={{ width: "10%" }} />
              </colgroup>
              <thead>
                <tr style={{ background: BG }}>
                  {[
                    "Recipe Name",
                    "Type",
                    "Parent",
                    "Created By",
                    "Created",
                    "Updated",
                    "Expiry",
                    "Status",
                    "Rev",
                    "Actions",
                  ].map((h) => (
                    <th key={h} style={th}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recipes.map((r) => (
                  <tr key={r.id}>
                    <td style={{ ...td, fontWeight: 600, color: TEXT }}>
                      <Truncate text={r.recipe_name} />
                    </td>
                    <td style={td}>
                      <span
                        style={{
                          background:
                            kind === "OPTIMIZED" || r.is_revision
                              ? "rgba(31,183,181,0.12)"
                              : "rgba(31,95,168,0.1)",
                          color: kind === "OPTIMIZED" || r.is_revision ? TEAL : BLUE,
                          padding: "2px 6px",
                          borderRadius: 10,
                          fontWeight: 600,
                          fontSize: "0.65rem",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {kind === "OPTIMIZED" ? "Opt" : r.is_revision ? "Rev" : "Orig"}
                      </span>
                    </td>
                    <td style={{ ...td, color: "#6B7280" }}>
                      <Truncate text={r.parent_recipe_name || "—"} />
                    </td>
                    <td style={td}>
                      <Truncate text={r.created_by_name || "—"} />
                    </td>
                    <td
                      style={{ ...td, whiteSpace: "pre-line", lineHeight: 1.25 }}
                      title={fmtDate(r.created_at)}
                    >
                      {fmtCompact(r.created_at)}
                    </td>
                    <td
                      style={{ ...td, whiteSpace: "pre-line", lineHeight: 1.25 }}
                      title={fmtDate(r.updated_at)}
                    >
                      {fmtCompact(r.updated_at)}
                    </td>
                    <td
                      style={{ ...td, whiteSpace: "pre-line", lineHeight: 1.25 }}
                      title={fmtDate(r.expires_at)}
                    >
                      {fmtCompact(r.expires_at)}
                    </td>
                    <td style={{ ...td, fontWeight: 600 }}>{r.status}</td>
                    <td style={{ ...td, textAlign: "center" }}>
                      {kind === "OPTIMIZED"
                        ? (r.optimization_number ?? r.revision_number)
                        : r.revision_number}
                    </td>
                    <td style={td}>
                      <div style={{ display: "flex", gap: 4, flexWrap: "nowrap" }}>
                        <button
                          title="View Recipe"
                          onClick={() => setViewRecipe(r)}
                          style={iconBtn}
                        >
                          <Eye size={13} />
                        </button>
                        {canEdit(r) && (
                          <button
                            title="Edit Recipe"
                            onClick={() => openEdit(r)}
                            style={iconBtn}
                          >
                            <Pencil size={13} />
                          </button>
                        )}
                        {isAdmin && (
                          <button
                            title="Delete Recipe"
                            onClick={() => setDeleteTarget(r)}
                            style={{ ...iconBtn, color: RED, borderColor: "#FECACA" }}
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                        {mode === "select" && canEdit(r) && (
                          <button
                            title="Select"
                            onClick={() => {
                              onSelect?.(r);
                              onClose();
                            }}
                            style={{
                              ...iconBtn,
                              background: TEAL,
                              color: "white",
                              border: "none",
                            }}
                          >
                            <Check size={13} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {viewRecipe && (
        <DetailOverlay title={`View: ${viewRecipe.recipe_name}`} onClose={() => setViewRecipe(null)}>
          <MetaBlock recipe={viewRecipe} />
          <RecipePropertiesEditor
            recipe={convertToEditableRecipe({
              id: viewRecipe.id,
              name: viewRecipe.recipe_name,
              recipe_data: viewRecipe.recipe_data,
              evidence_coverage_score: 0,
              patent_references: [],
              rank: 0,
            })}
            readOnly
          />
        </DetailOverlay>
      )}

      {editRecipe && editEditable && (
        <DetailOverlay title={`Edit: ${editRecipe.recipe_name}`} onClose={() => setEditRecipe(null)}>
          <label
            style={{
              display: "block",
              marginBottom: 12,
              fontSize: "0.8125rem",
              fontWeight: 600,
              color: BLUE,
            }}
          >
            Recipe Name
            <input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              style={{
                display: "block",
                width: "100%",
                marginTop: 6,
                border: `1px solid ${BORDER}`,
                borderRadius: 6,
                padding: "8px 10px",
                fontSize: "0.875rem",
              }}
            />
          </label>
          <RecipePropertiesEditor
            recipe={editEditable}
            onUpdateProperty={(propertyId, updates) =>
              setEditEditable((prev) => {
                if (!prev) return prev;
                const newProps = prev.properties.map((p) =>
                  p.id === propertyId ? { ...p, ...updates } : p
                );
                const newStages = prev.stages
                  ? prev.stages.map((s) => ({
                      ...s,
                      parameters: s.parameters.map((p) =>
                        p.id === propertyId ? { ...p, ...updates } : p
                      ),
                    }))
                  : [];
                return {
                  ...prev,
                  properties: newProps,
                  stages: newStages,
                };
              })
            }
            onAddParameter={(stageId, param) =>
              setEditEditable((prev) => {
                if (!prev) return prev;
                const newStages = (prev.stages || []).map((s) =>
                  s.id === stageId
                    ? { ...s, parameters: [...s.parameters, param] }
                    : s
                );
                return {
                  ...prev,
                  stages: newStages,
                  properties: [...prev.properties, param],
                };
              })
            }
            onDeleteParameter={(stageId, paramId) =>
              setEditEditable((prev) => {
                if (!prev) return prev;
                const newStages = (prev.stages || []).map((s) =>
                  s.id === stageId
                    ? { ...s, parameters: s.parameters.filter((p) => p.id !== paramId) }
                    : s
                );
                return {
                  ...prev,
                  stages: newStages,
                  properties: prev.properties.filter((p) => p.id !== paramId),
                };
              })
            }
            onAddStage={(stageName) =>
              setEditEditable((prev) => {
                if (!prev || !stageName.trim()) return prev;
                const newStage: EditableRecipeStage = {
                  id: `stage-${Date.now()}`,
                  stage_name: stageName.trim(),
                  parameters: [],
                  is_applicable: true,
                };
                return {
                  ...prev,
                  stages: [...(prev.stages || []), newStage],
                };
              })
            }
            onDeleteStage={(stageId) =>
              setEditEditable((prev) => {
                if (!prev) return prev;
                const newStages = (prev.stages || []).filter((s) => s.id !== stageId);
                const newProps = newStages.flatMap((s) => s.parameters);
                return {
                  ...prev,
                  stages: newStages,
                  properties: newProps,
                };
              })
            }
            onUpdateStageName={(stageId, name) =>
              setEditEditable((prev) => {
                if (!prev || !name.trim()) return prev;
                const newStages = (prev.stages || []).map((s) =>
                  s.id === stageId ? { ...s, stage_name: name.trim() } : s
                );
                return {
                  ...prev,
                  stages: newStages,
                };
              })
            }
          />
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
            <button onClick={() => setEditRecipe(null)} style={secondaryBtn}>
              Cancel
            </button>
            <button onClick={handleSaveEdit} disabled={saving} style={primaryBtn}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </DetailOverlay>
      )}

      {deleteTarget && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 10002,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
          onClick={() => !deleting && setDeleteTarget(null)}
        >
          <div
            style={{
              background: "white",
              borderRadius: 10,
              maxWidth: 440,
              width: "100%",
              padding: 24,
              boxShadow: "0 12px 40px rgba(0,0,0,0.2)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 10px", color: TEXT, fontSize: "1.05rem", fontWeight: 700 }}>
              {kind === "OPTIMIZED" ? "Delete Optimized Recipe?" : "Delete Recipe?"}
            </h3>
            <p style={{ margin: "0 0 8px", color: "#4B5563", fontSize: "0.875rem", lineHeight: 1.5 }}>
              This action permanently deletes{" "}
              <strong>&ldquo;{deleteTarget.recipe_name}&rdquo;</strong>
              {kind === "OPTIMIZED"
                ? " from saved optimized recipes."
                : " and its associated recipe data from the database."}
            </p>
            <p style={{ margin: "0 0 20px", color: "#991B1B", fontSize: "0.8125rem", fontWeight: 600 }}>
              This action cannot be undone.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <button
                onClick={() => setDeleteTarget(null)}
                disabled={deleting}
                style={secondaryBtn}
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={deleting}
                style={{
                  ...primaryBtn,
                  background: RED,
                }}
              >
                {deleting ? "Deleting…" : "Delete Permanently"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export function MetaBlock({ recipe }: { recipe: SavedRecipe }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 10,
        marginBottom: 16,
        fontSize: "0.8125rem",
      }}
    >
      {[
        ["Type", recipe.is_revision ? "Revision" : "Original"],
        ["Parent", recipe.parent_recipe_name || "—"],
        ["Created By", recipe.created_by_name || "—"],
        ["Created At", fmtDate(recipe.created_at)],
        ["Updated At", fmtDate(recipe.updated_at)],
        ["Expires", fmtDate(recipe.expires_at)],
        ["Status", recipe.status],
        ["Revision #", String(recipe.revision_number)],
      ].map(([label, value]) => (
        <div
          key={label}
          style={{
            background: BG,
            border: `1px solid ${BORDER}`,
            borderRadius: 6,
            padding: "8px 10px",
          }}
        >
          <div
            style={{ color: "#9CA3AF", fontSize: "0.7rem", fontWeight: 700, marginBottom: 2 }}
          >
            {label}
          </div>
          <div style={{ color: TEXT, fontWeight: 600, wordBreak: "break-word" }}>{value}</div>
        </div>
      ))}
    </div>
  );
}

export function DetailOverlay({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        zIndex: 10001,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          borderRadius: 10,
          width: "100%",
          maxWidth: 720,
          maxHeight: "90vh",
          overflowY: "auto",
          overflowX: "hidden",
          padding: 20,
          boxShadow: "0 12px 40px rgba(0,0,0,0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <h3
            style={{
              margin: 0,
              color: BLUE,
              fontSize: "1rem",
              fontWeight: 700,
              paddingRight: 12,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={title}
          >
            {title}
          </h3>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: "#6B7280" }}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

const iconBtn: CSSProperties = {
  background: "white",
  border: `1px solid ${BORDER}`,
  borderRadius: 5,
  padding: 5,
  cursor: "pointer",
  color: "#374151",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};

const primaryBtn: CSSProperties = {
  background: TEAL,
  color: "white",
  border: "none",
  borderRadius: 6,
  padding: "8px 16px",
  fontSize: "0.8125rem",
  fontWeight: 700,
  cursor: "pointer",
};

const secondaryBtn: CSSProperties = {
  background: "white",
  color: "#374151",
  border: `1px solid ${BORDER}`,
  borderRadius: 6,
  padding: "8px 16px",
  fontSize: "0.8125rem",
  fontWeight: 600,
  cursor: "pointer",
};
