/**
 * frontend/src/app/components/apcotex/RecipeComparison/RecipeComparisonTable.tsx
 *
 * Professional side-by-side comparison table component for polymerization recipes.
 * Restricted horizontal scrolling, sticky header and parameter columns,
 * clear visual badges for Target Fit, Targets Met, and PASS / NOT MET target evaluations.
 */
import React from "react";
import { CheckCircle2, AlertTriangle, FileText } from "lucide-react";
import type { RecipeComparisonModel } from "./recipeComparisonModel";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const BORDER = "#E5E7EB";

export function RecipeComparisonTable({ model }: { model: RecipeComparisonModel }) {
  const numRecipes = model.recipes.length;
  const colSpanTotal = 2 + numRecipes;

  return (
    <div
      style={{
        background: "white",
        borderRadius: 10,
        border: `1px solid ${BORDER}`,
        boxShadow: "0 2px 8px rgba(0,0,0,0.04)",
        overflow: "hidden",
      }}
    >
      {/* Scrollable table container — restricts horizontal scrolling to table area */}
      <div
        style={{
          overflowX: "auto",
          overflowY: "auto",
          maxHeight: "calc(100vh - 240px)",
          position: "relative",
        }}
      >
        <table
          style={{
            width: "100%",
            minWidth: 800 + numRecipes * 180,
            borderCollapse: "separate",
            borderSpacing: 0,
            fontSize: "0.85rem",
          }}
        >
          {/* ── Table Header ── */}
          <thead>
            <tr>
              <th
                style={{
                  position: "sticky",
                  top: 0,
                  left: 0,
                  zIndex: 4,
                  background: BLUE,
                  color: "white",
                  padding: "14px 18px",
                  textAlign: "left",
                  fontWeight: 700,
                  fontSize: "0.875rem",
                  width: 260,
                  minWidth: 260,
                  borderBottom: `2px solid rgba(255,255,255,0.2)`,
                  borderRight: `1px solid rgba(255,255,255,0.15)`,
                }}
              >
                Parameter / Component
              </th>
              <th
                style={{
                  position: "sticky",
                  top: 0,
                  left: 260,
                  zIndex: 4,
                  background: BLUE,
                  color: "white",
                  padding: "14px 16px",
                  textAlign: "left",
                  fontWeight: 700,
                  fontSize: "0.875rem",
                  width: 140,
                  minWidth: 140,
                  borderBottom: `2px solid rgba(255,255,255,0.2)`,
                  borderRight: `2px solid rgba(255,255,255,0.3)`,
                }}
              >
                Target / Unit
              </th>
              {model.recipes.map((r, i) => (
                <th
                  key={r.id}
                  style={{
                    position: "sticky",
                    top: 0,
                    zIndex: 3,
                    background: i === 0 ? "#1B4F8A" : BLUE,
                    color: "white",
                    padding: "14px 16px",
                    textAlign: "center",
                    fontWeight: 700,
                    fontSize: "0.875rem",
                    width: 200,
                    minWidth: 190,
                    borderBottom: `2px solid rgba(255,255,255,0.2)`,
                    borderRight: `1px solid rgba(255,255,255,0.15)`,
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                    <span style={{ fontSize: "0.75rem", opacity: 0.85, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                      Recipe {i + 1}
                    </span>
                    <span style={{ fontWeight: 800, fontSize: "0.9rem" }}>{r.name}</span>
                    {r.isCompliant && (
                      <span
                        style={{
                          background: "#22C55E",
                          color: "white",
                          fontSize: "0.65rem",
                          fontWeight: 700,
                          padding: "2px 6px",
                          borderRadius: 4,
                          marginTop: 2,
                        }}
                      >
                        ALL TARGETS MET
                      </span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {/* ── SECTION 1: RECIPE OVERVIEW ── */}
            <tr>
              <td
                colSpan={colSpanTotal}
                style={{
                  background: TEAL,
                  color: "white",
                  padding: "8px 18px",
                  fontWeight: 800,
                  fontSize: "0.8125rem",
                  letterSpacing: "0.5px",
                  textTransform: "uppercase",
                }}
              >
                Recipe Overview & Scoring Summary
              </td>
            </tr>
            {model.overviewRows.map((row, rIdx) => (
              <tr
                key={row.label}
                style={{
                  background: rIdx % 2 === 1 ? "#F8FAFC" : "white",
                }}
              >
                <td
                  style={{
                    position: "sticky",
                    left: 0,
                    zIndex: 2,
                    background: rIdx % 2 === 1 ? "#F8FAFC" : "white",
                    padding: "10px 18px",
                    fontWeight: 700,
                    color: BLUE,
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `1px solid ${BORDER}`,
                  }}
                >
                  {row.label}
                </td>
                <td
                  style={{
                    position: "sticky",
                    left: 260,
                    zIndex: 2,
                    background: rIdx % 2 === 1 ? "#F8FAFC" : "white",
                    padding: "10px 16px",
                    color: "#6B7280",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `2px solid #CBD5E1`,
                  }}
                >
                  —
                </td>
                {row.values.map((val, vIdx) => {
                  let badge = null;
                  if (row.label === "Target Fit") {
                    const strVal = String(val);
                    const is100 = strVal === "100%";
                    const isNA = strVal === "N/A";
                    badge = (
                      <span
                        style={{
                          background: is100 ? "#DCFCE7" : isNA ? "#F1F5F9" : "#FEF3C7",
                          color: is100 ? "#15803D" : isNA ? "#64748B" : "#B45309",
                          fontWeight: 800,
                          fontSize: "0.85rem",
                          padding: "3px 10px",
                          borderRadius: 6,
                        }}
                      >
                        {strVal}
                      </span>
                    );
                  } else if (row.label === "Targets Met") {
                    const strVal = String(val);
                    const [met, tot] = strVal.split("/").map(Number);
                    const isPerfect = met !== undefined && tot !== undefined && met === tot && tot > 0;
                    badge = (
                      <span
                        style={{
                          background: isPerfect ? "#DCFCE7" : strVal === "N/A" ? "#F1F5F9" : "#FEE2E2",
                          color: isPerfect ? "#15803D" : strVal === "N/A" ? "#64748B" : "#B91C1C",
                          fontWeight: 700,
                          fontSize: "0.8rem",
                          padding: "3px 8px",
                          borderRadius: 6,
                        }}
                      >
                        {strVal}
                      </span>
                    );
                  } else if (row.label === "Confidence Score") {
                    badge = (
                      <span
                        style={{
                          background: "rgba(31,183,181,0.15)",
                          color: BLUE,
                          fontWeight: 800,
                          fontSize: "0.85rem",
                          padding: "3px 10px",
                          borderRadius: 6,
                        }}
                      >
                        {val}
                      </span>
                    );
                  }

                  return (
                    <td
                      key={vIdx}
                      style={{
                        padding: "10px 16px",
                        textAlign: "center",
                        borderBottom: `1px solid ${BORDER}`,
                        borderRight: `1px solid ${BORDER}`,
                        fontWeight: row.label === "Recipe Name" ? 700 : 500,
                        color: "#1E293B",
                      }}
                    >
                      {badge || val}
                    </td>
                  );
                })}
              </tr>
            ))}

            {/* ── SECTION 2: TARGET PROPERTIES & MODEL PREDICTIONS ── */}
            <tr>
              <td
                colSpan={colSpanTotal}
                style={{
                  background: TEAL,
                  color: "white",
                  padding: "8px 18px",
                  fontWeight: 800,
                  fontSize: "0.8125rem",
                  letterSpacing: "0.5px",
                  textTransform: "uppercase",
                }}
              >
                Target Polymer Properties & Model Predictions
              </td>
            </tr>

            {model.targetRows.length === 0 ? (
              <tr>
                <td
                  colSpan={colSpanTotal}
                  style={{
                    padding: "16px 20px",
                    textAlign: "center",
                    background: "#F8FAFC",
                    color: "#64748B",
                    fontStyle: "italic",
                    borderBottom: `1px solid ${BORDER}`,
                  }}
                >
                  GENERAL RECIPE MODE — No explicit target properties were provided. Formulations generated from baseline product requirements and patent evidence.
                </td>
              </tr>
            ) : (
              model.targetRows.map((tRow, trIdx) => (
                <React.Fragment key={tRow.property}>
                  <tr style={{ background: trIdx % 2 === 1 ? "#F8FAFC" : "white" }}>
                    <td
                      style={{
                        position: "sticky",
                        left: 0,
                        zIndex: 2,
                        background: trIdx % 2 === 1 ? "#F8FAFC" : "white",
                        padding: "10px 18px",
                        fontWeight: 700,
                        color: "#1E293B",
                        borderBottom: `1px solid ${BORDER}`,
                        borderRight: `1px solid ${BORDER}`,
                      }}
                    >
                      {tRow.property}
                    </td>
                    <td
                      style={{
                        position: "sticky",
                        left: 260,
                        zIndex: 2,
                        background: trIdx % 2 === 1 ? "#F8FAFC" : "white",
                        padding: "10px 16px",
                        fontWeight: 700,
                        color: BLUE,
                        borderBottom: `1px solid ${BORDER}`,
                        borderRight: `2px solid #CBD5E1`,
                      }}
                    >
                      {tRow.target}
                    </td>
                    {tRow.predictions.map((predVal, pIdx) => {
                      const st = tRow.statuses[pIdx];
                      const isPass = st === "PASS";
                      const isFail = st === "NOT MET";

                      return (
                        <td
                          key={pIdx}
                          style={{
                            padding: "8px 12px",
                            textAlign: "center",
                            borderBottom: `1px solid ${BORDER}`,
                            borderRight: `1px solid ${BORDER}`,
                          }}
                        >
                          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                            <span style={{ fontWeight: 600, color: "#0F172A" }}>
                              {predVal}
                            </span>
                            {st !== "—" && (
                              <span
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: 4,
                                  fontSize: "0.72rem",
                                  fontWeight: 800,
                                  padding: "2px 8px",
                                  borderRadius: 4,
                                  background: isPass ? "#DCFCE7" : isFail ? "#FEE2E2" : "#F1F5F9",
                                  color: isPass ? "#15803D" : isFail ? "#B91C1C" : "#64748B",
                                }}
                              >
                                {isPass && <CheckCircle2 size={12} />}
                                {isFail && <AlertTriangle size={12} />}
                                {st}
                              </span>
                            )}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                </React.Fragment>
              ))
            )}

            {/* ── SECTION 3: SYNTHESIS FORMULATION BY STAGES ── */}
            <tr>
              <td
                colSpan={colSpanTotal}
                style={{
                  background: TEAL,
                  color: "white",
                  padding: "8px 18px",
                  fontWeight: 800,
                  fontSize: "0.8125rem",
                  letterSpacing: "0.5px",
                  textTransform: "uppercase",
                }}
              >
                Synthesis Formulation by Stages (Phr / Wt%)
              </td>
            </tr>

            {model.stages.map((stg, sIdx) => (
              <React.Fragment key={stg.stageName}>
                {/* Stage Sub-Banner */}
                <tr>
                  <td
                    colSpan={colSpanTotal}
                    style={{
                      background: "#E0F2FE",
                      color: "#0369A1",
                      padding: "8px 18px",
                      fontWeight: 800,
                      fontSize: "0.8125rem",
                      letterSpacing: "0.3px",
                      borderTop: `1px solid #BAE6FD`,
                      borderBottom: `1px solid #BAE6FD`,
                    }}
                  >
                    Stage {sIdx + 1}: {stg.stageName}
                  </td>
                </tr>

                {stg.parameters.map((param, pIdx) => (
                  <tr
                    key={param.name}
                    style={{
                      background: pIdx % 2 === 1 ? "#F8FAFC" : "white",
                    }}
                  >
                    <td
                      style={{
                        position: "sticky",
                        left: 0,
                        zIndex: 2,
                        background: pIdx % 2 === 1 ? "#F8FAFC" : "white",
                        padding: "8px 18px",
                        fontWeight: 600,
                        color: "#334155",
                        borderBottom: `1px solid ${BORDER}`,
                        borderRight: `1px solid ${BORDER}`,
                      }}
                    >
                      {param.name}
                    </td>
                    <td
                      style={{
                        position: "sticky",
                        left: 260,
                        zIndex: 2,
                        background: pIdx % 2 === 1 ? "#F8FAFC" : "white",
                        padding: "8px 16px",
                        color: "#64748B",
                        fontSize: "0.78rem",
                        borderBottom: `1px solid ${BORDER}`,
                        borderRight: `2px solid #CBD5E1`,
                      }}
                    >
                      {param.unit}
                    </td>
                    {param.values.map((v, vIdx) => {
                      const isMissing = v === "—";
                      return (
                        <td
                          key={vIdx}
                          style={{
                            padding: "8px 16px",
                            textAlign: "center",
                            borderBottom: `1px solid ${BORDER}`,
                            borderRight: `1px solid ${BORDER}`,
                            fontWeight: isMissing ? 400 : 600,
                            color: isMissing ? "#94A3B8" : "#0F172A",
                          }}
                        >
                          {v}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </React.Fragment>
            ))}

            {/* ── SECTION 4: PROCESS CONDITIONS ── */}
            <tr>
              <td
                colSpan={colSpanTotal}
                style={{
                  background: TEAL,
                  color: "white",
                  padding: "8px 18px",
                  fontWeight: 800,
                  fontSize: "0.8125rem",
                  letterSpacing: "0.5px",
                  textTransform: "uppercase",
                }}
              >
                Process Conditions
              </td>
            </tr>
            {model.processConditions.map((pc, idx) => (
              <tr
                key={pc.name}
                style={{
                  background: idx % 2 === 1 ? "#F8FAFC" : "white",
                }}
              >
                <td
                  style={{
                    position: "sticky",
                    left: 0,
                    zIndex: 2,
                    background: idx % 2 === 1 ? "#F8FAFC" : "white",
                    padding: "9px 18px",
                    fontWeight: 700,
                    color: "#1E293B",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `1px solid ${BORDER}`,
                  }}
                >
                  {pc.name}
                </td>
                <td
                  style={{
                    position: "sticky",
                    left: 260,
                    zIndex: 2,
                    background: idx % 2 === 1 ? "#F8FAFC" : "white",
                    padding: "9px 16px",
                    color: "#64748B",
                    fontSize: "0.78rem",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `2px solid #CBD5E1`,
                  }}
                >
                  {pc.unit}
                </td>
                {pc.values.map((v, vIdx) => (
                  <td
                    key={vIdx}
                    style={{
                      padding: "9px 16px",
                      textAlign: "center",
                      borderBottom: `1px solid ${BORDER}`,
                      borderRight: `1px solid ${BORDER}`,
                      color: v === "—" ? "#94A3B8" : "#0F172A",
                      fontWeight: 600,
                    }}
                  >
                    {v}
                  </td>
                ))}
              </tr>
            ))}

            {/* ── SECTION 5: PATENT SUPPORT ── */}
            <tr>
              <td
                colSpan={colSpanTotal}
                style={{
                  background: TEAL,
                  color: "white",
                  padding: "8px 18px",
                  fontWeight: 800,
                  fontSize: "0.8125rem",
                  letterSpacing: "0.5px",
                  textTransform: "uppercase",
                }}
              >
                Patent Research Support
              </td>
            </tr>
            <tr>
              <td
                style={{
                  position: "sticky",
                  left: 0,
                  zIndex: 2,
                  background: "white",
                  padding: "12px 18px",
                  fontWeight: 700,
                  color: BLUE,
                  borderBottom: `1px solid ${BORDER}`,
                  borderRight: `1px solid ${BORDER}`,
                }}
              >
                Patent Citations
              </td>
              <td
                style={{
                  position: "sticky",
                  left: 260,
                  zIndex: 2,
                  background: "white",
                  padding: "12px 16px",
                  color: "#64748B",
                  fontSize: "0.78rem",
                  borderBottom: `1px solid ${BORDER}`,
                  borderRight: `2px solid #CBD5E1`,
                }}
              >
                References
              </td>
              {model.patentSupport.citations.map((cit, cIdx) => (
                <td
                  key={cIdx}
                  style={{
                    padding: "12px 16px",
                    textAlign: "center",
                    borderBottom: `1px solid ${BORDER}`,
                    borderRight: `1px solid ${BORDER}`,
                    fontSize: "0.78rem",
                    color: "#334155",
                    fontWeight: 600,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                    <FileText size={14} color={BLUE} />
                    <span>{cit}</span>
                  </div>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
