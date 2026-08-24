import React from 'react';
import { usePatentResearch } from "../../contexts/PatentResearchContext";

const TEXT = "#111827";
const BORDER = "#E5E7EB";
const LINK = "#2563EB";
const BG = "#F9FAFB";

const documentStyles = {
  maxWidth: 900,
  margin: "0 auto",
  background: "white",
  padding: "48px 64px",
  boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
  fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  fontSize: "11pt",
  lineHeight: 1.6,
  color: TEXT,
} as const;

export function PatentReportViewer() {
  const { state } = usePatentResearch();

  const report = state.structuredReport;

  // Fallback to legacy HTML report if no structured report
  if (!report) {
    if (state.reportHtml) {
      return (
        <div style={documentStyles}>
          <div 
            dangerouslySetInnerHTML={{ __html: state.reportHtml }} 
            className="patent-report-content"
          />
          <style>{`
            .patent-report-content h1 { text-align: center; font-size: 20pt; margin-bottom: 24px; border-bottom: 2px solid ${TEXT}; padding-bottom: 24px; text-transform: uppercase; font-weight: 800; }
            .patent-report-content h2 { font-size: 16pt; margin-top: 32px; margin-bottom: 16px; font-weight: 700; text-transform: uppercase; color: #1F2937; }
            .patent-report-content h3 { font-size: 13pt; margin-top: 24px; margin-bottom: 12px; font-weight: 600; color: #374151; }
            .patent-report-content table { width: 100%; border-collapse: collapse; margin-top: 16px; margin-bottom: 16px; font-size: 10.5pt; }
            .patent-report-content th { border: 1px solid ${BORDER}; padding: 10px 12px; background: #F3F4F6; text-align: left; font-weight: 600; }
            .patent-report-content td { border: 1px solid ${BORDER}; padding: 10px 12px; vertical-align: top; }
            .patent-report-content a { color: ${LINK}; text-decoration: none; }
            .patent-report-content a:hover { text-decoration: underline; }
            .patent-report-content p { text-align: justify; margin-bottom: 16px; color: #374151; }
            .patent-report-content ul { padding-left: 24px; margin-bottom: 16px; color: #374151; }
            .patent-report-content li { margin-bottom: 6px; }
          `}</style>
        </div>
      );
    }
    return null;
  }

  const allPatents = report.methodology_patents || report.primary_patents || [];
  const primaryPatents = allPatents.filter((p: any) => !p.patent_details || p.patent_details.relevance_tier !== 'SECONDARY');
  const secondaryPatents = report.secondary_patents || allPatents.filter((p: any) => p.patent_details && p.patent_details.relevance_tier === 'SECONDARY');
  const competitorPatents = report.competitor_patents || [];
  const websiteSources = report.website_sources || [];
  const comparisonDimensions = report.comparison_dimensions || [];

  return (
    <div style={documentStyles}>
      <header style={{ marginBottom: 40, textAlign: 'center' }}>
        <h1 style={{ fontSize: "22pt", fontWeight: 800, margin: "0 0 24px 0", borderBottom: `3px solid ${TEXT}`, paddingBottom: 24, textTransform: "uppercase", letterSpacing: "-0.025em" }}>
          {report.title || `${state.compoundName} - Patent Research Report`}
        </h1>
      </header>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 16px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
          1. Abstract
        </h2>
        <p style={{ margin: 0, textAlign: 'justify', color: '#374151' }}>{report.abstract}</p>
      </section>

      <section style={{ marginBottom: 40 }}>
        <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 24px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
          2. Methodology
        </h2>
        <h3 style={{ fontSize: "14pt", fontWeight: 600, margin: "0 0 20px 0", color: "#1F2937" }}>
          Primary Patent Evidence
        </h3>

        {primaryPatents.length === 0 && (
          <p style={{ color: '#6B7280', fontStyle: 'italic' }}>
            No qualifying primary patents were identified under the configured Low Acrylonitrile NBR relevance criteria.
          </p>
        )}

        {primaryPatents.map((patent: any, idx: number) => {
          const details = patent.patent_details || {};
          const method = patent.polymerization_method || { dynamic_parameters: [] };
          
          return (
            <div key={idx} style={{ marginBottom: 40 }}>
              <h4 style={{ fontSize: "14pt", fontWeight: 600, color: "#1F2937", margin: "0 0 16px 0", display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ background: '#E5E7EB', padding: '4px 12px', borderRadius: 4, fontSize: '11pt' }}>
                  {details.relevance_tier === 'SECONDARY' ? `Secondary Patent ${idx + 1}` : `Patent ${idx + 1}`}
                </span>
                {details.patent_title}
              </h4>

              {/* Details Grid */}
              <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 20, marginBottom: 20 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px 24px' }}>
                  <div><strong style={{ color: '#4B5563' }}>Number:</strong> {details.patent_number}</div>
                  <div><strong style={{ color: '#4B5563' }}>Jurisdiction:</strong> {details.jurisdiction}</div>
                  <div><strong style={{ color: '#4B5563' }}>Assignee:</strong> {details.assignee}</div>
                  <div><strong style={{ color: '#4B5563' }}>Year:</strong> {details.publication_year}</div>
                  {details.material_type && (
                    <div style={{ gridColumn: '1 / -1' }}><strong style={{ color: '#4B5563' }}>Material Type:</strong> {details.material_type}</div>
                  )}
                  <div style={{ gridColumn: '1 / -1' }}><strong style={{ color: '#4B5563' }}>Relevance:</strong> {details.relevance_to_target}</div>
                </div>
              </div>

              {/* Dynamic Technical Method Table */}
              <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>Polymerization Method</h5>
              
              {method.dynamic_parameters && method.dynamic_parameters.length > 0 ? (
                <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 24, fontSize: '10.5pt' }}>
                  <tbody>
                    {method.dynamic_parameters.map((paramStr: string, i: number) => {
                      const splitIdx = paramStr.indexOf(':');
                      if (splitIdx === -1) return null;
                      const name = paramStr.substring(0, splitIdx).trim();
                      const value = paramStr.substring(splitIdx + 1).trim();
                      if (!value || value === 'Not disclosed') return null;
                      return (
                        <tr key={i}>
                          <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px', background: '#F9FAFB', fontWeight: 600, width: '35%', color: '#4B5563' }}>
                            {name}
                          </td>
                          <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px', color: '#111827' }}>
                            {value}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              ) : (
                <p style={{ color: '#6B7280', fontStyle: 'italic', marginBottom: 24 }}>No polymerization parameters disclosed.</p>
              )}

              {/* Experimental Evidence */}
              {patent.experimental_evidence && patent.experimental_evidence.length > 0 && (
                <div style={{ marginBottom: 24 }}>
                  <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>Relevant Experimental Evidence</h5>
                  <ul style={{ margin: 0, paddingLeft: 24, color: '#374151' }}>
                    {patent.experimental_evidence.map((ev: string, i: number) => (
                      <li key={i} style={{ marginBottom: 6 }}>{ev}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Technical Relevance */}
              {patent.technical_relevance && (
                <div>
                  <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 8px 0", color: '#374151' }}>Technical Relevance</h5>
                  <p style={{ margin: 0, color: '#4B5563', fontStyle: 'italic' }}>{patent.technical_relevance}</p>
                </div>
              )}
            </div>
          );
        })}
      </section>

      {/* Secondary Patents — shown after primary with amber badge */}
      {secondaryPatents.length > 0 && (
        <section style={{ marginBottom: 40 }}>
          <h3 style={{ fontSize: "14pt", fontWeight: 600, margin: "0 0 16px 0", color: "#92400E", borderTop: `1px dashed #F59E0B`, paddingTop: 16 }}>
            Supporting / Related Patents
          </h3>
          <p style={{ color: '#6B7280', fontStyle: 'italic', marginBottom: 16, fontSize: '10.5pt' }}>
            These patents are related to NBR synthesis but Low-ACN relevance was not confirmed from available title and abstract data.
          </p>
          {secondaryPatents.map((patent: any, idx: number) => {
            const details = patent.patent_details || {};
            return (
              <div key={idx} style={{ marginBottom: 28 }}>
                <h4 style={{ fontSize: "13pt", fontWeight: 600, color: "#92400E", margin: "0 0 12px 0", display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ background: '#FEF3C7', border: '1px solid #F59E0B', padding: '3px 10px', borderRadius: 4, fontSize: '10.5pt', color: '#92400E' }}>Secondary</span>
                  {details.patent_title}
                </h4>
                <div style={{ background: '#FFFBEB', border: `1px solid #F59E0B`, borderRadius: 8, padding: 16 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px 24px' }}>
                    <div><strong style={{ color: '#92400E' }}>Number:</strong> {details.patent_number}</div>
                    <div><strong style={{ color: '#92400E' }}>Jurisdiction:</strong> {details.jurisdiction}</div>
                    <div><strong style={{ color: '#92400E' }}>Assignee:</strong> {details.assignee}</div>
                    <div><strong style={{ color: '#92400E' }}>Year:</strong> {details.publication_year}</div>
                  </div>
                  {patent.technical_relevance && (
                    <div style={{ marginTop: 12 }}><strong style={{ color: '#92400E' }}>Note:</strong> <span style={{ color: '#78350F' }}>{patent.technical_relevance}</span></div>
                  )}
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* Competitor Patents Section - Conditional */}
      {competitorPatents.length > 0 && (
        <section style={{ marginBottom: 40 }}>
          <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 24px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
            3. Competitor Patent Discovery
          </h2>

          {competitorPatents.map((patent: any, idx: number) => {
            const details = patent.patent_details || {};
            const method = patent.polymerization_method || { dynamic_parameters: [] };
            
            return (
              <div key={idx} style={{ marginBottom: 40 }}>
                <h4 style={{ fontSize: "14pt", fontWeight: 600, color: "#1F2937", margin: "0 0 16px 0", display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ background: '#FEF3C7', padding: '4px 12px', borderRadius: 4, fontSize: '11pt', color: '#92400E' }}>Competitor Patent {idx + 1}</span>
                  {details.patent_title}
                </h4>

                <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: 8, padding: 20, marginBottom: 20 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px 24px' }}>
                    <div><strong style={{ color: '#4B5563' }}>Number:</strong> {details.patent_number}</div>
                    <div><strong style={{ color: '#4B5563' }}>Jurisdiction:</strong> {details.jurisdiction}</div>
                    <div><strong style={{ color: '#4B5563' }}>Assignee:</strong> {details.assignee}</div>
                    {patent.competitor_name && (
                      <div><strong style={{ color: '#4B5563' }}>Competitor:</strong> {patent.competitor_name}</div>
                    )}
                  </div>
                </div>

                <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>Polymerization Method</h5>
                
                {method.dynamic_parameters && method.dynamic_parameters.length > 0 && (
                  <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 24, fontSize: '10.5pt' }}>
                    <tbody>
                      {method.dynamic_parameters.map((paramStr: string, i: number) => {
                        const splitIdx = paramStr.indexOf(':');
                        if (splitIdx === -1) return null;
                        const name = paramStr.substring(0, splitIdx).trim();
                        const value = paramStr.substring(splitIdx + 1).trim();
                        if (!value || value === 'Not disclosed') return null;
                        return (
                          <tr key={i}>
                            <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px', background: '#F9FAFB', fontWeight: 600, width: '35%', color: '#4B5563' }}>
                              {name}
                            </td>
                            <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px', color: '#111827' }}>
                              {value}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}

                <div>
                  <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 8px 0", color: '#374151' }}>Technical Relevance</h5>
                  <p style={{ margin: 0, color: '#4B5563', fontStyle: 'italic' }}>{patent.technical_relevance}</p>
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* Website Sources Section - Conditional */}
      {websiteSources.length > 0 && (
        <section style={{ marginBottom: 40 }}>
          <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 24px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
            {competitorPatents.length > 0 ? "4. External / Website Sources" : "3. External / Website Sources"}
          </h2>

          {websiteSources.map((source: any, idx: number) => (
            <div key={idx} style={{ marginBottom: 24, padding: 16, background: BG, borderRadius: 8 }}>
              <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>
                Source {idx + 1}: {source.website}
              </h5>
              <div style={{ marginBottom: 12 }}>
                <strong style={{ color: '#4B5563' }}>URL:</strong>{' '}
                <a href={source.url} target="_blank" rel="noopener noreferrer" style={{ color: LINK }}>
                  {source.url}
                </a>
              </div>
              <div style={{ marginBottom: 12 }}>
                <strong style={{ color: '#4B5563' }}>Title:</strong> {source.title}
              </div>
              <div>
                <strong style={{ color: '#4B5563' }}>Key Findings:</strong>
                <ul style={{ margin: '8px 0 0 24px', color: '#374151' }}>
                  {source.findings?.map((finding: string, i: number) => (
                    <li key={i} style={{ marginBottom: 4 }}>{finding}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Cross-Patent Comparison - only when >= 2 primary patents */}
      <section style={{ marginBottom: 40 }}>
        <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 16px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
          {competitorPatents.length > 0 ? (websiteSources.length > 0 ? "5. Cross-Patent Comparison & Trends" : "4. Cross-Patent Comparison & Trends") : (websiteSources.length > 0 ? "4. Cross-Patent Comparison & Trends" : "3. Cross-Patent Comparison & Trends")}
        </h2>

        {primaryPatents.length < 2 ? (
          <p style={{ color: '#6B7280', fontStyle: 'italic' }}>
            {primaryPatents.length === 0
              ? 'No qualifying primary patents were identified under the configured Low Acrylonitrile NBR relevance criteria. Cross-patent quantitative trends were therefore not generated.'
              : 'At least two primary patents are required for cross-patent trend analysis. Only one primary patent was identified.'}
          </p>
        ) : comparisonDimensions.length > 0 ? (
          <>
            <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>Comparison Table</h5>
            <div style={{ overflowX: 'auto', marginBottom: 24 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '10.5pt', minWidth: 600 }}>
                <thead>
                  <tr>
                    <th style={{ border: `1px solid ${BORDER}`, padding: '10px 12px', background: '#F3F4F6', fontWeight: 600 }}>Patent</th>
                    {comparisonDimensions.map((dim: any, i: number) => (
                      <th key={i} style={{ border: `1px solid ${BORDER}`, padding: '10px 12px', background: '#F3F4F6', fontWeight: 600 }}>
                        {dim.parameter_name}
                      </th>
                    ))}
                    <th style={{ border: `1px solid ${BORDER}`, padding: '10px 12px', background: '#F3F4F6', fontWeight: 600 }}>Key Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {primaryPatents.map((patent: any, idx: number) => {
                    const details = patent.patent_details || {};
                    return (
                      <tr key={idx}>
                        <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px', fontWeight: 500 }}>{details.patent_number}</td>
                        {comparisonDimensions.map((dim: any, i: number) => {
                          const value = dim.values?.[details.patent_number] || 'Not disclosed';
                          return (
                            <td key={i} style={{ border: `1px solid ${BORDER}`, padding: '8px 12px' }}>
                              {value}
                            </td>
                          );
                        })}
                        <td style={{ border: `1px solid ${BORDER}`, padding: '8px 12px' }}></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p style={{ color: '#6B7280', fontStyle: 'italic', marginBottom: 16 }}>Insufficient comparable evidence was available to identify a reliable cross-patent trend.</p>
        )}

        {primaryPatents.length >= 2 && (
          <>
            <h5 style={{ fontSize: "12pt", fontWeight: 600, margin: "0 0 12px 0", color: '#374151' }}>Trend Analysis</h5>
            <ul style={{ margin: 0, paddingLeft: 24, color: '#374151' }}>
              {report.cross_patent_comparison?.map((point: string, idx: number) => (
                <li key={idx} style={{ marginBottom: 8 }}>{point}</li>
              ))}
            </ul>
          </>
        )}
      </section>

      {/* Conclusion - Conditional */}
      {report.conclusion && (
        <section style={{ marginBottom: 40 }}>
          <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 16px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
            Conclusion
          </h2>
          <p style={{ margin: 0, textAlign: 'justify', color: '#374151' }}>{report.conclusion}</p>
        </section>
      )}

      {/* References */}
      <section>
        <h2 style={{ fontSize: "16pt", fontWeight: 700, margin: "0 0 16px 0", textTransform: "uppercase", color: "#111827", borderBottom: `2px solid ${BORDER}`, paddingBottom: 8 }}>
          References
        </h2>
        <ul style={{ margin: 0, paddingLeft: 24, color: '#374151' }}>
          {report.references?.map((ref: string, idx: number) => (
            <li key={idx} style={{ marginBottom: 8, wordBreak: 'break-word' }}>
              <span dangerouslySetInnerHTML={{ __html: ref }} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
