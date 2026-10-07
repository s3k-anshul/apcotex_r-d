import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router";
import {
  Search,
  CheckCircle2,
  Circle,
  Loader,
  Download,
  FlaskConical,
  AlertTriangle,
  FileText
} from "lucide-react";
import { usePatentResearch } from "../../contexts/PatentResearchContext";
import { PatentReportViewer } from "./PatentReportViewer";
import { PreviousReports } from "./PreviousReports";
import { 
  createResearchRun, 
  pollResearchStatus, 
  getReportContent, 
  downloadFile,
  suggestAssignees,
} from "../../services/researchApi";
import { addAssigneeNames, removeAssigneeName } from "../../config/assigneeSelection";

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

type PublicationDateFilterMode = "any" | "last3years" | "last5years" | "last10years" | "custom";

const PUBLICATION_DATE_OPTIONS: {
  value: PublicationDateFilterMode;
  label: string;
}[] = [
  { value: "any", label: "Any Time" },
  { value: "last3years", label: "Last 3 Years" },
  { value: "last5years", label: "Last 5 Years" },
  { value: "last10years", label: "Last 10 Years" },
  { value: "custom", label: "Custom Range" },
];

const PATENT_SOURCES = ["Google Patents", "Espacenet", "USPTO"];
const JURISDICTIONS = ["US", "EU", "IN", "CN", "JP", "KR", "WO", "Other"];
const STATUS_ORDER = ["PENDING", "SEARCHING", "FILTERING", "EXTRACTING", "GENERATING", "COMPLETED", "COMPLETED_PARTIAL"];

export function LiteratureReview() {
  const navigate = useNavigate();
  const { state, setState, clearState } = usePatentResearch();
  
  const [compound, setCompound] = useState("Low Acrylonitrile NBR");
  const [selectedAssignees, setSelectedAssignees] = useState<string[]>([]);
  const [assigneeQuery, setAssigneeQuery] = useState("");
  const [assigneeSuggestions, setAssigneeSuggestions] = useState<string[]>([]);
  const [assigneeLoading, setAssigneeLoading] = useState(false);
  const [assigneeMenuOpen, setAssigneeMenuOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(0);
  const [mentionedWebsites, setMentionedWebsites] = useState("");
  const [publicationDateMode, setPublicationDateMode] = useState<PublicationDateFilterMode>("any");
  const [customDateFrom, setCustomDateFrom] = useState("");
  const [customDateTo, setCustomDateTo] = useState("");
  const [publicationDateError, setPublicationDateError] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([...PATENT_SOURCES]);
  const [selectedJurisdictions, setSelectedJurisdictions] = useState<string[]>(["US", "EU", "IN"]);
  const [jurisdictionsError, setJurisdictionsError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showPreviousReports, setShowPreviousReports] = useState(false);
  
  // Polling ref
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Stop polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  useEffect(() => {
    const query = assigneeQuery.trim();
    if (query.length < 2) {
      setAssigneeSuggestions([]);
      setAssigneeLoading(false);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      setAssigneeLoading(true);
      try {
        const names = await suggestAssignees(query);
        if (!cancelled) {
          setAssigneeSuggestions(names.filter((name) => (
            !selectedAssignees.some((item) => item.toLowerCase() === name.toLowerCase())
          )).slice(0, 10));
          setActiveSuggestion(0);
          setAssigneeMenuOpen(true);
        }
      } catch {
        if (!cancelled) setAssigneeSuggestions([]);
      } finally {
        if (!cancelled) setAssigneeLoading(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [assigneeQuery, selectedAssignees]);

  // Polling logic
  useEffect(() => {
    // Determine if we should poll
    const isTerminal = (status: string) => {
      return ["COMPLETED", "COMPLETED_PARTIAL", "FAILED", "CANCELLED", "LLM_PROVIDER_EXHAUSTED"].includes(status);
    };

    if (state.researchRunId && !isTerminal(state.status)) {
      if (pollingRef.current) clearInterval(pollingRef.current);
      
      const MAX_POLLS = 600; // 30 minutes at 3s intervals
      let pollCount = 0;

      pollingRef.current = setInterval(async () => {
        pollCount++;
        if (pollCount > MAX_POLLS) {
          console.warn(`[RESEARCH POLL] Run: ${state.researchRunId} Status: TIMEOUT. Polling stopped.`);
          if (pollingRef.current) clearInterval(pollingRef.current);
          setState({ error: "Research status could not be confirmed. Check Audit Trail / Research History." });
          return;
        }

        console.log(`[RESEARCH POLL] Run: ${state.researchRunId} Status: ${state.status} Next poll: 3s`);
        
        try {
          const run = await pollResearchStatus(state.researchRunId!);
          setState({ status: run.status, progressNote: run.progress || null });
          
          if (isTerminal(run.status)) {
            console.log(`[RESEARCH POLL] Run: ${state.researchRunId} Status: ${run.status}`);
            if (run.status === "LLM_PROVIDER_EXHAUSTED") {
              console.log(`[RESEARCH POLL] Reason: Provider quota exhausted.`);
            } else if (run.status === "FAILED") {
              console.log(`[RESEARCH POLL] Polling stopped. Run failed.`);
            } else if (run.status === "COMPLETED" || run.status === "COMPLETED_PARTIAL") {
              console.log(`[RESEARCH POLL] Polling stopped. Run completed.`);
            }

            if (pollingRef.current) clearInterval(pollingRef.current);
            
            if (run.status === "COMPLETED" || run.status === "COMPLETED_PARTIAL") {
              // Fetch the final HTML report
              try {
                const content = await getReportContent(state.researchRunId!);
                setState({ 
                  reportHtml: content.html, 
                  reportMarkdown: content.markdown,
                  recipeData: content.extractions,
                  extractions: content.extractions,
                  structuredReport: content.structuredReport
                });
              } catch (err) {
                setState({ error: "Failed to load report content." });
              }
            } else if (run.status === "FAILED" || run.status === "CANCELLED") {
              setState({ error: "Patent research failed or was cancelled by the server." });
            } else if (run.status === "LLM_PROVIDER_EXHAUSTED") {
              setState({ error: "LLM Provider quota exhausted. Research stopped." });
            }
          }
        } catch (error) {
          console.error("Polling error:", error);
          if (pollingRef.current) clearInterval(pollingRef.current);
          setState({ error: "Lost connection to server during polling." });
        }
      }, 3000);
    }
  }, [state.researchRunId, state.status, setState]);

  const toggleSource = (src: string) => {
    setSelectedSources((prev) =>
      prev.includes(src) ? prev.filter((s) => s !== src) : [...prev, src],
    );
  };

  const toggleJurisdiction = (jur: string) => {
    setSelectedJurisdictions((prev) => {
      const newSelections = prev.includes(jur) ? prev.filter((j) => j !== jur) : [...prev, jur];
      if (newSelections.length > 0) setJurisdictionsError("");
      return newSelections;
    });
  };

  const validatePublicationDate = () => {
    if (publicationDateMode !== "custom") {
      setPublicationDateError("");
      return true;
    }
    if (!customDateFrom || !customDateTo) {
      setPublicationDateError("Both From and To dates are required.");
      return false;
    }
    if (customDateFrom > customDateTo) {
      setPublicationDateError("From date cannot be after To date.");
      return false;
    }
    setPublicationDateError("");
    return true;
  };

  const isCustomPublicationRangeInvalid =
    publicationDateMode === "custom" &&
    (!customDateFrom || !customDateTo || customDateFrom > customDateTo);

  const startResearch = async () => {
    if (selectedJurisdictions.length === 0) {
      setJurisdictionsError("Please select at least one jurisdiction.");
      return;
    }
    if (!validatePublicationDate()) return;
    if (!compound.trim() || selectedSources.length === 0 || isCustomPublicationRangeInvalid) return;
    
    setIsSubmitting(true);
    setState({ error: null });
    
    console.log("RESEARCH REQUEST");
    console.log("----------------");
    console.log("URL: /api/v1/research-runs");
    console.log("METHOD: POST");
    
    try {
      const competitors = addAssigneeNames(selectedAssignees, assigneeQuery);
        
      const websites = mentionedWebsites
        .split(",")
        .map(s => s.trim())
        .filter(s => s.length > 0);
        
      const publicationFilter = publicationDateMode === "any" ? undefined : {
        mode: publicationDateMode,
        customFrom: customDateFrom,
        customTo: customDateTo
      };
      
      const mappedJurisdictions = selectedJurisdictions.map(j => j === "EU" ? "EP" : j);
      
      console.log("PAYLOAD:", {
        compound_name: compound.trim(),
        competitors,
        patent_sources: selectedSources,
        mentioned_websites: websites,
        publication_filter: publicationFilter,
        jurisdictions: mappedJurisdictions
      });
      console.log("REQUEST STARTED: ", new Date().toISOString());
        
      const run = await createResearchRun({
        compound_name: compound.trim(),
        competitors,
        patent_sources: selectedSources,
        mentioned_websites: websites,
        publication_filter: publicationFilter,
        jurisdictions: mappedJurisdictions
      });
      
      console.log("RESEARCH RESPONSE");
      console.log("-----------------");
      console.log("STATUS: SUCCESS");
      console.log("BODY:", run);
      
      setState({ 
        researchRunId: run.id, 
        status: run.status,
        compoundName: run.compound_name,
        createdDate: run.created_at
      });

      // If the run is already COMPLETED (e.g. cache hit), we must immediately fetch the report
      // Otherwise, the polling hook won't trigger and the UI will be stuck in a blank state.
      if (run.status === "COMPLETED" || run.status === "COMPLETED_PARTIAL") {
        try {
          const content = await getReportContent(run.id);
          setState({ 
            reportHtml: content.html, 
            reportMarkdown: content.markdown,
            recipeData: content.extractions,
            extractions: content.extractions,
            structuredReport: content.structuredReport
          });
        } catch (err) {
          setState({ error: "Failed to load cached report content." });
        }
      }
    } catch (err: any) {
      console.error("RESEARCH REQUEST FAILED");
      console.error("-----------------------");
      console.error("ERROR:", err);
      console.error("MESSAGE:", err.message);
      setState({ error: err.message || "Failed to start research" });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleProceedWithRecipe = () => {
    if (!state.recipeData) return;
    navigate("/recipe-simulator");
  };

  const handleStartNewResearch = () => {
    clearState();
    setCompound("Low Acrylonitrile NBR");
    setSelectedAssignees([]);
    setAssigneeQuery("");
    setAssigneeSuggestions([]);
    setMentionedWebsites("");
    setPublicationDateMode("any");
    setCustomDateFrom("");
    setCustomDateTo("");
    setPublicationDateError("");
  };
  
  const renderProgressItem = (stepStatus: string, label: string) => {
    const currentIndex = STATUS_ORDER.indexOf(state.status || "PENDING");
    const stepIndex = STATUS_ORDER.indexOf(stepStatus);
    
    const isPast = stepIndex < currentIndex;
    const isCurrent = stepIndex === currentIndex;
    const isCompleted = state.status === "COMPLETED" || state.status === "COMPLETED_PARTIAL" || isPast;
    
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {isCompleted ? (
          <CheckCircle2 size={18} color={TEAL} />
        ) : isCurrent ? (
          <Loader size={18} color={BLUE} style={{ animation: "spin 1s linear infinite" }} />
        ) : (
          <Circle size={18} color="#D1D5DB" />
        )}
        <span style={{ fontSize: "0.875rem", color: isCompleted || isCurrent ? TEXT : "#9CA3AF", flex: 1, fontWeight: isCurrent ? 600 : 400 }}>
          {label}
        </span>
      </div>
    );
  };

  // Determine which page state to show
  const isForm = !state.researchRunId && !state.error;
  const isProgress = state.researchRunId && state.status !== "COMPLETED" && state.status !== "COMPLETED_PARTIAL" && !state.error;
  const isResults = (state.status === "COMPLETED" || state.status === "COMPLETED_PARTIAL") && state.reportHtml;
  const isError = !!state.error;

  return (
    <div style={{ padding: "28px 32px 48px", background: BG, minHeight: "100vh" }}>
      <div style={{ marginBottom: 24, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 style={{ color: BLUE, fontSize: "1.25rem", fontWeight: 700, marginBottom: 4 }}>
            Patent Research
          </h1>
          <p style={{ color: "#6B7280", fontSize: "0.875rem" }}>
            AI-powered patent research across global patent databases to identify competitor patents, technology trends, and formulation intelligence.
          </p>
        </div>
        <button
          onClick={() => setShowPreviousReports(true)}
          style={{
            background: "transparent", color: BLUE, border: `1.5px solid ${BLUE}`,
            borderRadius: 7, padding: "8px 16px", fontSize: "0.875rem", fontWeight: 600,
            cursor: "pointer", display: "flex", alignItems: "center", gap: 6
          }}
        >
          <FileText size={16} /> View Previous Reports
        </button>
      </div>

      {showPreviousReports && (
        <PreviousReports onClose={() => setShowPreviousReports(false)} />
      )}

      {isForm && (
        <div style={{ maxWidth: 680 }}>
          <div style={{ ...card, padding: "24px" }}>
            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 8 }}>
              Compound / Product Name
            </label>
            <div style={{ position: "relative", marginBottom: 20 }}>
              <Search size={16} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF" }} />
              <input
                type="text"
                value={compound}
                onChange={(e) => setCompound(e.target.value)}
                placeholder="e.g. Low Acrylonitrile NBR"
                style={{ width: "100%", height: 42, paddingLeft: 38, paddingRight: 14, border: `1.5px solid ${BORDER}`, borderRadius: 7, fontSize: "0.875rem", color: TEXT, outline: "none" }}
              />
            </div>

            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 8 }}>
              Competitor Name(s) <span style={{ color: "#9CA3AF", fontWeight: 500 }}>(Optional)</span>
            </label>
            <div style={{ position: "relative", marginBottom: 20 }}>
              {selectedAssignees.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
                  {selectedAssignees.map((name) => (
                    <button
                      key={name}
                      type="button"
                      onClick={() => setSelectedAssignees((current) => removeAssigneeName(current, name))}
                      style={{ border: `1px solid ${BORDER}`, background: BG, color: TEXT, borderRadius: 7, padding: "4px 8px", fontSize: "0.8125rem", cursor: "pointer" }}
                    >
                      {name} ×
                    </button>
                  ))}
                </div>
              )}
              <input
                type="text"
                value={assigneeQuery}
                onChange={(e) => {
                  setAssigneeQuery(e.target.value);
                  setAssigneeMenuOpen(true);
                }}
                onFocus={() => setAssigneeMenuOpen(true)}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setActiveSuggestion((index) => Math.min(index + 1, Math.max(assigneeSuggestions.length - 1, 0)));
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setActiveSuggestion((index) => Math.max(index - 1, 0));
                  } else if (e.key === "Escape") {
                    setAssigneeMenuOpen(false);
                  } else if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    const highlighted = assigneeMenuOpen ? assigneeSuggestions[activeSuggestion] : "";
                    const nextValue = highlighted || assigneeQuery;
                    if (!nextValue.trim()) return;
                    setSelectedAssignees((current) => addAssigneeNames(current, nextValue));
                    setAssigneeQuery("");
                    setAssigneeMenuOpen(false);
                  }
                }}
                placeholder="e.g. LG Chem, Synthomer"
                style={{ width: "100%", height: 42, paddingLeft: 14, paddingRight: 14, border: `1.5px solid ${BORDER}`, borderRadius: 7, fontSize: "0.875rem", color: TEXT, outline: "none" }}
              />
              {assigneeMenuOpen && assigneeQuery.trim().length >= 2 && (
                <div style={{ position: "absolute", zIndex: 5, left: 0, right: 0, top: "100%", marginTop: 4, background: "white", border: `1px solid ${BORDER}`, borderRadius: 7, boxShadow: "0 4px 12px rgba(31,95,168,0.08)" }}>
                  {assigneeLoading && (
                    <div style={{ padding: "8px 12px", fontSize: "0.8125rem", color: "#6B7280" }}>Searching assignees...</div>
                  )}
                  {!assigneeLoading && assigneeSuggestions.length === 0 && (
                    <div style={{ padding: "8px 12px", fontSize: "0.8125rem", color: "#6B7280" }}>No suggestions. Press Enter to use this name.</div>
                  )}
                  {!assigneeLoading && assigneeSuggestions.map((name, index) => (
                    <button
                      key={name}
                      type="button"
                      onMouseDown={(event) => {
                        event.preventDefault();
                        setSelectedAssignees((current) => addAssigneeNames(current, name));
                        setAssigneeQuery("");
                        setAssigneeMenuOpen(false);
                      }}
                      style={{
                        display: "block", width: "100%", textAlign: "left", border: "none",
                        background: index === activeSuggestion ? BG : "white",
                        color: TEXT, padding: "8px 12px", fontSize: "0.875rem", cursor: "pointer",
                      }}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 8 }}>
              Mention Websites <span style={{ color: "#9CA3AF", fontWeight: 500 }}>(Optional)</span>
            </label>
            <textarea
              value={mentionedWebsites}
              onChange={(e) => setMentionedWebsites(e.target.value)}
              placeholder="e.g. sciencedirect.com, rubberworld.com, scholar.google.com"
              rows={3}
              style={{
                width: "100%", marginBottom: 20, padding: "10px 12px", border: `1.5px solid ${BORDER}`,
                borderRadius: 7, fontSize: "0.875rem", color: TEXT, background: "white", outline: "none",
                fontFamily: "inherit", boxSizing: "border-box", resize: "vertical", lineHeight: 1.5,
              }}
            />

            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 10 }}>
              Publication Date <span style={{ color: "#9CA3AF", fontWeight: 500 }}>(Optional)</span>
            </label>
            <select
              value={publicationDateMode}
              onChange={(e) => {
                setPublicationDateMode(e.target.value as PublicationDateFilterMode);
                setPublicationDateError("");
              }}
              style={{
                width: "100%", height: 42, marginBottom: publicationDateMode === "custom" ? 12 : 20,
                paddingLeft: 14, paddingRight: 14, border: `1.5px solid ${BORDER}`, borderRadius: 7,
                fontSize: "0.875rem", color: TEXT, background: "white", outline: "none",
                fontFamily: "inherit", boxSizing: "border-box", cursor: "pointer",
              }}
            >
              {PUBLICATION_DATE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>

            {publicationDateMode === "custom" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: publicationDateError ? 8 : 20 }}>
                <div>
                  <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: TEXT, marginBottom: 6 }}>From</label>
                  <input
                    type="date"
                    value={customDateFrom}
                    onChange={(e) => {
                      setCustomDateFrom(e.target.value);
                      setPublicationDateError("");
                    }}
                    style={{ width: "100%", height: 42, paddingLeft: 12, paddingRight: 12, border: `1.5px solid ${BORDER}`, borderRadius: 7, fontSize: "0.875rem", color: TEXT, outline: "none" }}
                  />
                </div>
                <div>
                  <label style={{ display: "block", fontSize: "0.8125rem", fontWeight: 600, color: TEXT, marginBottom: 6 }}>To</label>
                  <input
                    type="date"
                    value={customDateTo}
                    onChange={(e) => {
                      setCustomDateTo(e.target.value);
                      setPublicationDateError("");
                    }}
                    style={{ width: "100%", height: 42, paddingLeft: 12, paddingRight: 12, border: `1.5px solid ${BORDER}`, borderRadius: 7, fontSize: "0.875rem", color: TEXT, outline: "none" }}
                  />
                </div>
              </div>
            )}

            {publicationDateError && (
              <p style={{ margin: "0 0 20px", color: RED, fontSize: "0.8125rem" }}>
                {publicationDateError}
              </p>
            )}

            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 10 }}>
              Research Sources
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 24 }}>
              {PATENT_SOURCES.map((src) => {
                const active = selectedSources.includes(src);
                return (
                  <button
                    key={src}
                    onClick={() => toggleSource(src)}
                    style={{
                      padding: "5px 13px", borderRadius: 20, fontSize: "0.8125rem", fontWeight: 500, cursor: "pointer",
                      border: `1.5px solid ${active ? BLUE : BORDER}`, background: active ? "rgba(31,95,168,0.07)" : "white",
                      color: active ? BLUE : "#6B7280", transition: "all 0.12s", display: "flex", alignItems: "center", gap: 5,
                    }}
                  >
                    {active && <CheckCircle2 size={13} color={BLUE} />}
                    {src}
                  </button>
                );
              })}
            </div>

            <label style={{ display: "block", fontSize: "0.875rem", fontWeight: 600, color: TEXT, marginBottom: 10 }}>
              Jurisdictions
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: jurisdictionsError ? 8 : 24 }}>
              {JURISDICTIONS.map((jur) => {
                const active = selectedJurisdictions.includes(jur);
                return (
                  <button
                    key={jur}
                    onClick={() => toggleJurisdiction(jur)}
                    style={{
                      padding: "5px 13px", borderRadius: 20, fontSize: "0.8125rem", fontWeight: 500, cursor: "pointer",
                      border: `1.5px solid ${active ? BLUE : BORDER}`, background: active ? "rgba(31,95,168,0.07)" : "white",
                      color: active ? BLUE : "#6B7280", transition: "all 0.12s", display: "flex", alignItems: "center", gap: 5,
                    }}
                  >
                    {active && <CheckCircle2 size={13} color={BLUE} />}
                    {jur}
                  </button>
                );
              })}
            </div>
            
            {jurisdictionsError && (
              <p style={{ margin: "0 0 24px", color: RED, fontSize: "0.8125rem" }}>
                {jurisdictionsError}
              </p>
            )}

            <button
              onClick={startResearch}
              disabled={!compound.trim() || selectedSources.length === 0 || isSubmitting || isCustomPublicationRangeInvalid}
              style={{
                background: TEAL, color: "white", border: "none", borderRadius: 7, padding: "11px 24px",
                fontSize: "0.875rem", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
                opacity: (!compound.trim() || selectedSources.length === 0 || isSubmitting || isCustomPublicationRangeInvalid) ? 0.5 : 1
              }}
            >
              {isSubmitting ? <Loader size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Search size={16} />}
              Generate Patent Report
            </button>
          </div>
        </div>
      )}

      {isProgress && (
        <div style={{ maxWidth: 560 }}>
          <div style={{ ...card, padding: "28px 24px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
              <Loader size={20} color={TEAL} style={{ animation: "spin 1s linear infinite" }} />
              <span style={{ color: TEXT, fontWeight: 600, fontSize: "0.9375rem" }}>
                Generating Patent Research...
              </span>
              {state.progressNote && (
                <span style={{ marginLeft: "auto", color: "#6B7280", fontSize: "0.8125rem" }}>{state.progressNote}</span>
              )}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {renderProgressItem("SEARCHING", "AI Search Strategy & Serper Querying")}
              {renderProgressItem("FILTERING", "Patent Filtering & Relevance Classification")}
              {renderProgressItem("EXTRACTING", "Structured JSON Extraction (Gemini)")}
              {renderProgressItem("GENERATING", "Report Generation & Formatting")}
            </div>
          </div>
        </div>
      )}
      
      {isError && (
        <div style={{ maxWidth: 560 }}>
          <div style={{ ...card, padding: "28px 24px", borderLeft: `4px solid ${RED}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              <AlertTriangle size={20} color={RED} />
              <span style={{ color: RED, fontWeight: 600, fontSize: "0.9375rem" }}>
                Patent research failed.
              </span>
            </div>
            <p style={{ color: TEXT, fontSize: "0.875rem", marginBottom: 20 }}>
              <strong>Reason:</strong> {state.error}
            </p>
            <button
              onClick={handleStartNewResearch}
              style={{
                background: "white", color: RED, border: `1px solid ${RED}`, borderRadius: 7, padding: "8px 16px",
                fontSize: "0.875rem", fontWeight: 600, cursor: "pointer",
              }}
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {isResults && (
        <div>
          <PatentReportViewer />

          <div style={{ maxWidth: 816, margin: "24px auto 0", display: "flex", gap: 12, flexWrap: "wrap" }}>
            <button
              onClick={() => downloadFile(state.researchRunId!, 'pdf', `APCOTEX_Report_${state.compoundName}.pdf`)}
              style={{ border: `1.5px solid ${BLUE}`, color: BLUE, background: "white", borderRadius: 7, padding: "10px 20px", fontSize: "0.875rem", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}
            >
              <Download size={15} /> Download PDF
            </button>
            
            <button
              onClick={() => downloadFile(state.researchRunId!, 'docx', `APCOTEX_Report_${state.compoundName}.docx`)}
              style={{ border: `1.5px solid ${BLUE}`, color: BLUE, background: "white", borderRadius: 7, padding: "10px 20px", fontSize: "0.875rem", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}
            >
              <Download size={15} /> Download DOCX
            </button>

            <button
              onClick={handleProceedWithRecipe}
              style={{ border: "none", color: "white", background: TEAL, borderRadius: 7, padding: "10px 20px", fontSize: "0.875rem", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}
            >
              <FlaskConical size={15} /> Proceed to Recipe Simulator
            </button>

            <button
              onClick={handleStartNewResearch}
              style={{ border: `1.5px solid ${BORDER}`, color: TEXT, background: "white", borderRadius: 7, padding: "10px 20px", fontSize: "0.875rem", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 7 }}
            >
              <Search size={15} /> Start New Research
            </button>
          </div>
        </div>
      )}
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
