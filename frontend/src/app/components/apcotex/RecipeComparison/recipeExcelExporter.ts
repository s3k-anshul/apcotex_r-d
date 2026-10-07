/**
 * frontend/src/app/components/apcotex/RecipeComparison/recipeExcelExporter.ts
 *
 * Professional Excel Workbook Exporter for Apcotex R&D Recipe Comparison.
 * Utilizes ExcelJS to format side-by-side comparison tables with frozen headers,
 * custom corporate Apcotex palette, preserved numeric types, unit columns,
 * and deterministic PASS / NOT MET target evaluations.
 */
import ExcelJS from "exceljs";
import type { RecipeComparisonModel } from "./recipeComparisonModel";

const NAVY_BLUE = "1F5FA8";
const TEAL_ACCENT = "1FB7B5";
const LIGHT_ROW = "F8FAFC";
const BORDER_COLOR = "D1D5DB";
const STAGE_BG = "E0F2FE";
const STAGE_TEXT = "0369A1";
const PASS_COLOR = "15803D";
const NOT_MET_COLOR = "B91C1C";

export async function exportRecipeComparisonToExcel(
  model: RecipeComparisonModel,
  compoundName: string = "Polymer Formulation"
): Promise<void> {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Apcotex R&D Recipe Simulator";
  workbook.lastModifiedBy = "Apcotex R&D Platform";
  workbook.created = new Date();
  workbook.modified = new Date();

  const sheetName = "Recipe Comparison";
  const ws = workbook.addWorksheet(sheetName, {
    views: [{ state: "frozen", xSplit: 2, ySplit: 4 }],
    properties: { defaultRowHeight: 20 },
  });

  const numRecipes = model.recipes.length;
  const totalCols = 2 + numRecipes;

  // ── Column Definitions ─────────────────────────────────────────────────────
  ws.columns = [
    { header: "", key: "param", width: 34 },
    { header: "", key: "unit", width: 18 },
    ...model.recipes.map((_, i) => ({
      header: "",
      key: `r_${i}`,
      width: 24,
    })),
  ];

  // Helper border definition
  const thinBorder: Partial<ExcelJS.Borders> = {
    top: { style: "thin", color: { argb: BORDER_COLOR } },
    left: { style: "thin", color: { argb: BORDER_COLOR } },
    bottom: { style: "thin", color: { argb: BORDER_COLOR } },
    right: { style: "thin", color: { argb: BORDER_COLOR } },
  };

  // ── Row 1: Title Header ────────────────────────────────────────────────────
  const titleRow = ws.addRow([
    `APCOTEX R&D RECIPE SIMULATOR — RECIPE COMPARISON`,
  ]);
  titleRow.height = 28;
  ws.mergeCells(1, 1, 1, totalCols);
  const titleCell = ws.getCell(1, 1);
  titleCell.font = { name: "Segoe UI", size: 14, bold: true, color: { argb: "FFFFFF" } };
  titleCell.fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: NAVY_BLUE },
  };
  titleCell.alignment = { vertical: "middle", horizontal: "left", indent: 1 };

  // ── Row 2: Subtitle Metadata ───────────────────────────────────────────────
  const modeText =
    model.targetMode === "STRICT_TARGET"
      ? `TARGET MODE (${model.targetCount} Hard Targets)`
      : "GENERAL RECIPE MODE (Patent & Product Baseline)";
  const dateStr = new Date().toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const subRow = ws.addRow([
    `Target Compound: ${compoundName}   |   ${modeText}   |   Generated: ${dateStr}`,
  ]);
  subRow.height = 20;
  ws.mergeCells(2, 1, 2, totalCols);
  const subCell = ws.getCell(2, 1);
  subCell.font = { name: "Segoe UI", size: 9, italic: true, color: { argb: "475569" } };
  subCell.fill = {
    type: "pattern",
    pattern: "solid",
    fgColor: { argb: "F1F5F9" },
  };
  subCell.alignment = { vertical: "middle", horizontal: "left", indent: 1 };

  // ── Row 3: Blank separator ─────────────────────────────────────────────────
  const blankRow = ws.addRow([]);
  blankRow.height = 6;

  // ── Row 4: Main Column Headers ─────────────────────────────────────────────
  const headerVals = [
    "Parameter / Component",
    "Target / Unit",
    ...model.recipes.map((r, i) => `${r.name || `Recipe ${i + 1}`}`),
  ];
  const colHeaderRow = ws.addRow(headerVals);
  colHeaderRow.height = 24;
  colHeaderRow.eachCell((cell, colNum) => {
    cell.font = { name: "Segoe UI", size: 10, bold: true, color: { argb: "FFFFFF" } };
    cell.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: colNum <= 2 ? NAVY_BLUE : "1E293B" },
    };
    cell.alignment = {
      vertical: "middle",
      horizontal: colNum <= 2 ? "left" : "center",
      wrapText: true,
    };
    cell.border = thinBorder;
  });

  // Helper function to add major section banner
  function addSectionBanner(title: string) {
    const r = ws.addRow([title]);
    r.height = 22;
    ws.mergeCells(r.number, 1, r.number, totalCols);
    const c = ws.getCell(r.number, 1);
    c.font = { name: "Segoe UI", size: 10, bold: true, color: { argb: "FFFFFF" } };
    c.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: TEAL_ACCENT },
    };
    c.alignment = { vertical: "middle", horizontal: "left", indent: 1 };
  }

  // Helper function to add subsection / stage banner
  function addSubBanner(title: string) {
    const r = ws.addRow([title]);
    r.height = 20;
    ws.mergeCells(r.number, 1, r.number, totalCols);
    const c = ws.getCell(r.number, 1);
    c.font = { name: "Segoe UI", size: 9, bold: true, color: { argb: STAGE_TEXT } };
    c.fill = {
      type: "pattern",
      pattern: "solid",
      fgColor: { argb: STAGE_BG },
    };
    c.alignment = { vertical: "middle", horizontal: "left", indent: 1 };
  }

  // ── 1. RECIPE OVERVIEW ─────────────────────────────────────────────────────
  addSectionBanner("RECIPE OVERVIEW & SCORING SUMMARY");
  model.overviewRows.forEach((or, idx) => {
    const row = ws.addRow([or.label, "—", ...or.values]);
    row.height = 20;
    row.eachCell((cell, colNum) => {
      cell.font = {
        name: "Segoe UI",
        size: 9.5,
        bold: colNum <= 1 || or.label === "Recipe Name",
        color: { argb: "0F172A" },
      };
      if (idx % 2 === 1) {
        cell.fill = {
          type: "pattern",
          pattern: "solid",
          fgColor: { argb: LIGHT_ROW },
        };
      }
      cell.alignment = {
        vertical: "middle",
        horizontal: colNum <= 2 ? "left" : "center",
      };
      cell.border = thinBorder;
    });
  });

  // ── 2. TARGET PROPERTIES & PREDICTIONS ─────────────────────────────────────
  addSectionBanner("TARGET POLYMER PROPERTIES & MODEL PREDICTIONS");
  if (model.targetRows.length === 0) {
    const noTgtRow = ws.addRow([
      "GENERAL RECIPE MODE — No explicit target properties were provided. Formulations generated from product specifications and patent evidence.",
    ]);
    noTgtRow.height = 22;
    ws.mergeCells(noTgtRow.number, 1, noTgtRow.number, totalCols);
    const c = ws.getCell(noTgtRow.number, 1);
    c.font = { name: "Segoe UI", size: 9, italic: true, color: { argb: "64748B" } };
    c.alignment = { vertical: "middle", horizontal: "left", indent: 1 };
  } else {
    model.targetRows.forEach((tr, idx) => {
      // Row 1: Predicted values
      const predRow = ws.addRow([tr.property, tr.target, ...tr.predictions]);
      predRow.height = 20;
      predRow.eachCell((cell, colNum) => {
        cell.font = {
          name: "Segoe UI",
          size: 9.5,
          bold: colNum === 1,
          color: { argb: "0F172A" },
        };
        if (idx % 2 === 1) {
          cell.fill = {
            type: "pattern",
            pattern: "solid",
            fgColor: { argb: LIGHT_ROW },
          };
        }
        cell.alignment = {
          vertical: "middle",
          horizontal: colNum <= 2 ? "left" : "center",
        };
        cell.border = thinBorder;
      });

      // Row 2: Model Status (PASS / NOT MET)
      const statusRow = ws.addRow([
        `   ↳ Status (${tr.property})`,
        "Constraint Status",
        ...tr.statuses,
      ]);
      statusRow.height = 18;
      statusRow.eachCell((cell, colNum) => {
        const valStr = String(cell.value || "");
        const isPass = valStr === "PASS";
        const isFail = valStr === "NOT MET";

        cell.font = {
          name: "Segoe UI",
          size: 9,
          bold: true,
          color: {
            argb: isPass ? PASS_COLOR : isFail ? NOT_MET_COLOR : "64748B",
          },
        };
        cell.fill = {
          type: "pattern",
          pattern: "solid",
          fgColor: {
            argb: isPass ? "DCFCE7" : isFail ? "FEE2E2" : "F1F5F9",
          },
        };
        cell.alignment = {
          vertical: "middle",
          horizontal: colNum <= 2 ? "left" : "center",
        };
        cell.border = thinBorder;
      });
    });
  }

  // ── 3. RECIPE FORMULATION BY STAGES ────────────────────────────────────────
  addSectionBanner("SYNTHESIS FORMULATION BY STAGES (PHR / WT%)");
  model.stages.forEach((stg) => {
    addSubBanner(`STAGE: ${stg.stageName.toUpperCase()}`);
    stg.parameters.forEach((param, pIdx) => {
      // Write cells individually so numeric values are true Excel numbers
      const row = ws.addRow([param.name, param.unit]);
      row.height = 19;

      param.values.forEach((v, vIdx) => {
        const numVal = param.numericValues[vIdx];
        if (numVal !== null) {
          row.getCell(3 + vIdx).value = numVal;
          row.getCell(3 + vIdx).numFmt = "#,##0.00";
        } else {
          row.getCell(3 + vIdx).value = v;
        }
      });

      row.eachCell((cell, colNum) => {
        cell.font = {
          name: "Segoe UI",
          size: 9.5,
          color: { argb: "0F172A" },
        };
        if (pIdx % 2 === 1) {
          cell.fill = {
            type: "pattern",
            pattern: "solid",
            fgColor: { argb: LIGHT_ROW },
          };
        }
        cell.alignment = {
          vertical: "middle",
          horizontal: colNum === 1 ? "left" : colNum === 2 ? "center" : "right",
        };
        cell.border = thinBorder;
      });
    });
  });

  // ── 4. PROCESS CONDITIONS ──────────────────────────────────────────────────
  addSectionBanner("PROCESS CONDITIONS");
  model.processConditions.forEach((pc, idx) => {
    const row = ws.addRow([pc.name, pc.unit]);
    row.height = 19;

    pc.values.forEach((v, vIdx) => {
      const numVal = pc.numericValues[vIdx];
      if (numVal !== null) {
        row.getCell(3 + vIdx).value = numVal;
        row.getCell(3 + vIdx).numFmt = "#,##0.00";
      } else {
        row.getCell(3 + vIdx).value = v;
      }
    });

    row.eachCell((cell, colNum) => {
      cell.font = {
        name: "Segoe UI",
        size: 9.5,
        bold: colNum === 1,
        color: { argb: "0F172A" },
      };
      if (idx % 2 === 1) {
        cell.fill = {
          type: "pattern",
          pattern: "solid",
          fgColor: { argb: LIGHT_ROW },
        };
      }
      cell.alignment = {
        vertical: "middle",
        horizontal: colNum <= 2 ? "left" : "center",
      };
      cell.border = thinBorder;
    });
  });

  // ── 5. PATENT SUPPORT ──────────────────────────────────────────────────────
  addSectionBanner("PATENT RESEARCH SUPPORT");
  const patRow = ws.addRow([
    model.patentSupport.label,
    "Patent Citations",
    ...model.patentSupport.citations,
  ]);
  patRow.height = 24;
  patRow.eachCell((cell, colNum) => {
    cell.font = {
      name: "Segoe UI",
      size: 9,
      bold: colNum <= 2,
      color: { argb: "0F172A" },
    };
    cell.alignment = {
      vertical: "middle",
      horizontal: colNum <= 2 ? "left" : "center",
      wrapText: true,
    };
    cell.border = thinBorder;
  });

  // ── File Generation & Download ─────────────────────────────────────────────
  const buffer = await workbook.xlsx.writeBuffer();
  const blob = new Blob([buffer], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const safeName = compoundName.replace(/[^a-zA-Z0-9_-]/g, "_");
  const dateStamp = new Date().toISOString().slice(0, 10);
  a.href = url;
  a.download = `Apcotex_Recipe_Comparison_${safeName}_${dateStamp}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
