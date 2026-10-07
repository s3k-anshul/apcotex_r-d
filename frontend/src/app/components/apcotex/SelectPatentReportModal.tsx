/**
 * Modal to select an existing completed Patent Research report
 * and associate it with Recipe Simulator (same hydration as Proceed to Recipe).
 * Does NOT regenerate reports — only loads existing report content.
 */
import { useEffect, useState } from "react";
import { FileText, Loader, X } from "lucide-react";
import {
  getResearchRuns,
  getReportContent,
  pollResearchStatus,
} from "../../services/researchApi";
import { usePatentResearch, type RunStatus } from "../../contexts/PatentResearchContext";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const BORDER = "#E5E7EB";
const TEXT = "#1F2937";
const GREEN = "#10B981";
const GRAY = "#6B7280";

const SELECTABLE = new Set(["COMPLETED", "COMPLETED_PARTIAL"]);

type ReportRow = {
  id: string;
  compound_name: string;
  status: string;
  created_by?: string;
  created_by_name?: string | null;
  created_at: string;
  report_version?: number;
  jurisdictions?: string[];
};

function fmtDate(value?: string | null) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function SelectPatentReportModal({
  open,
  onClose,
  onSelected,
}: {
  open: boolean;
  onClose: () => void;
  onSelected?: () => void;
}) {
  const { setState } = usePatentResearch();
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectingId, setSelectingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getResearchRuns();
        const items = (data?.items || []).filter((r: ReportRow) =>
          SELECTABLE.has(r.status)
        );
        if (!cancelled) setReports(items);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Failed to load reports");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleSelect = async (row: ReportRow) => {
    setSelectingId(row.id);
    setError(null);
    try {
      // Load existing report content — no regeneration
      const [run, content] = await Promise.all([
        pollResearchStatus(row.id),
        getReportContent(row.id),
      ]);
      setState({
        researchRunId: row.id,
        status: (run?.status || row.status) as RunStatus,
        compoundName: run?.compound_name || row.compound_name,
        createdDate: run?.created_at || row.created_at,
        reportHtml: content.html,
        reportMarkdown: content.markdown,
        recipeData: content.extractions,
        extractions: content.extractions,
        structuredReport: content.structuredReport,
        error: null,
      });
      onSelected?.();
      onClose();
    } catch (e: any) {
      setError(e?.message || "Failed to load selected report");
    } finally {
      setSelectingId(null);
    }
  };

  if (!open) return null;

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
        padding: 24,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          borderRadius: 10,
          width: "100%",
          maxWidth: 640,
          maxHeight: "85vh",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 12px 40px rgba(0,0,0,0.18)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: `1px solid ${BORDER}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <h2
            style={{
              margin: 0,
              color: BLUE,
              fontSize: "1.05rem",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <FileText size={18} /> Select Patent Research Report
          </h2>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: GRAY }}
          >
            <X size={20} />
          </button>
        </div>

        <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
          {loading ? (
            <div style={{ textAlign: "center", padding: 40, color: BLUE }}>
              <Loader size={22} style={{ animation: "spin 1s linear infinite" }} /> Loading…
            </div>
          ) : error ? (
            <div
              style={{
                color: "#991B1B",
                background: "#FEE2E2",
                padding: 12,
                borderRadius: 6,
                marginBottom: 12,
                fontSize: "0.875rem",
              }}
            >
              {error}
            </div>
          ) : null}

          {!loading && reports.length === 0 && !error ? (
            <div style={{ textAlign: "center", padding: 40, color: GRAY, fontSize: "0.875rem" }}>
              No completed patent research reports are available.
              <br />
              Generate a report from Patent Research first.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {reports.map((r) => (
                <div
                  key={r.id}
                  style={{
                    border: `1px solid ${BORDER}`,
                    borderRadius: 8,
                    padding: "14px 16px",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: 16,
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        fontWeight: 700,
                        color: TEXT,
                        fontSize: "0.9375rem",
                        marginBottom: 6,
                      }}
                    >
                      {r.compound_name} Patent Research
                    </div>
                    <div
                      style={{
                        fontSize: "0.8125rem",
                        color: GRAY,
                        display: "flex",
                        flexDirection: "column",
                        gap: 2,
                      }}
                    >
                      <span>
                        Created by:{" "}
                        <strong style={{ color: TEXT }}>
                          {r.created_by_name || "—"}
                        </strong>
                      </span>
                      <span>Created: {fmtDate(r.created_at)}</span>
                      <span>
                        Status:{" "}
                        <span style={{ color: GREEN, fontWeight: 600 }}>{r.status}</span>
                      </span>
                      <span style={{ fontSize: "0.75rem", color: "#9CA3AF" }}>
                        Report ID: {r.id}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => handleSelect(r)}
                    disabled={selectingId === r.id}
                    style={{
                      flexShrink: 0,
                      background: selectingId === r.id ? "#9CA3AF" : TEAL,
                      color: "white",
                      border: "none",
                      borderRadius: 6,
                      padding: "8px 16px",
                      fontSize: "0.8125rem",
                      fontWeight: 700,
                      cursor: selectingId === r.id ? "wait" : "pointer",
                    }}
                  >
                    {selectingId === r.id ? "Loading…" : "Select"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      </div>
    </div>
  );
}
