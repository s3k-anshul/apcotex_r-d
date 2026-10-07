import { useNavigate } from "react-router";
import type { KeyboardEvent } from "react";
import {
  BookOpen,
  FlaskConical,
  FileText,
  Activity,
  MessageSquare,
  type LucideIcon,
} from "lucide-react";
import { Card } from "../ui/card";
import { useLayoutContext } from "./Layout";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const TEXT = "#1F2937";
const BORDER = "#E5E7EB";

interface ModuleCardConfig {
  title: string;
  description: string;
  buttonText: string;
  icon: LucideIcon;
  path: string;
}

const MODULES: ModuleCardConfig[] = [
  {
    title: "Research Assistant",
    description:
      "Scan scientific publications, patents, technical papers, and databases to gather formulation insights.",
    buttonText: "Start Research",
    icon: BookOpen,
    path: "/literature-review",
  },
  {
    title: "Recipe Generator",
    description:
      "Generate and optimize formulations using AI-powered recommendations and target specifications.",
    buttonText: "Generate Recipe",
    icon: FlaskConical,
    path: "/recipe-simulator",
  },
  {
    title: "Trial Feedback",
    description:
      "Submit trial feedback on saved recipes and generate revised formulations.",
    buttonText: "Open Feedback",
    icon: MessageSquare,
    path: "/customer-trial-feedback",
  },
  {
    title: "Audit Trail",
    description:
      "View activity logs, system actions, project history, and change tracking.",
    buttonText: "View Audit Trail",
    icon: FileText,
    path: "/audit-trail",
  },
  {
    title: "Token Usage",
    description:
      "Admin dashboard to monitor LLM token consumption, Serper search API usage, and estimated costs.",
    buttonText: "View Token Usage",
    icon: Activity,
    path: "/token-dashboard",
  },
];

export function Dashboard() {
  const navigate = useNavigate();
  const { userName, userRole } = useLayoutContext();

  const visibleModules = MODULES.filter(
    (m) => {
      if (m.path === "/audit-trail" || m.path === "/token-dashboard") {
        return userRole === "ADMIN";
      }
      return true;
    }
  );

  return (
    <div className="flex flex-col">
      <div
        style={{
          background: "linear-gradient(135deg, #1F5FA8 0%, #1FB7B5 100%)",
          padding: "36px 40px",
        }}
      >
        <div style={{ maxWidth: 600 }}>
          <p
            style={{
              color: "rgba(255,255,255,0.65)",
              fontSize: "0.75rem",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontWeight: 600,
              marginBottom: 8,
            }}
          >
            APCOTEX R&amp;D - RECIPE SIMULATOR
          </p>

          <h1
            style={{
              color: "white",
              fontSize: "1.5rem",
              fontWeight: 700,
              lineHeight: 1.3,
              marginBottom: 8,
            }}
          >
            Welcome back, {userName || "Dr. Subhra"}
          </h1>

          <p
            style={{
              color: "rgba(255,255,255,0.85)",
              fontSize: "0.9375rem",
              fontWeight: 400,
              lineHeight: 1.5,
              margin: 0,
            }}
          >
            What would you like to work on today?
          </p>
        </div>
      </div>

      <div
        className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 items-start"
        style={{ padding: 24, marginTop: 32, marginBottom: 32 }}
      >
        {visibleModules.map((module) => (
          <ModuleActionCard
            key={module.path}
            {...module}
            onNavigate={() => navigate(module.path)}
          />
        ))}
      </div>
    </div>
  );
}

function ModuleActionCard({
  title,
  description,
  buttonText,
  icon: Icon,
  onNavigate,
}: ModuleCardConfig & { onNavigate: () => void }) {
  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onNavigate();
    }
  };

  return (
    <Card
      role="button"
      tabIndex={0}
      onClick={onNavigate}
      onKeyDown={handleKeyDown}
      className="cursor-pointer transition-all duration-200 hover:-translate-y-1 hover:shadow-lg gap-0 rounded-2xl shadow-sm flex flex-col w-full"
      style={{
        background: "white",
        border: `1px solid ${BORDER}`,
        padding: 24,
      }}
    >
      <div
        style={{
          width: 48,
          height: 48,
          borderRadius: 12,
          background: "rgba(31,95,168,0.07)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 16,
          flexShrink: 0,
        }}
      >
        <Icon size={24} color={BLUE} strokeWidth={1.5} />
      </div>

      <h3
        style={{
          color: TEXT,
          fontSize: "1rem",
          fontWeight: 600,
          marginBottom: 10,
        }}
      >
        {title}
      </h3>

      <p
        style={{
          color: "#6B7280",
          fontSize: "0.875rem",
          lineHeight: 1.6,
          marginBottom: 16,
        }}
      >
        {description}
      </p>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onNavigate();
        }}
        style={{
          background: TEAL,
          color: "white",
          border: "none",
          borderRadius: 6,
          padding: "9px 18px",
          fontSize: "0.8125rem",
          fontWeight: 600,
          cursor: "pointer",
          alignSelf: "flex-start",
          transition: "opacity 0.15s ease",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.opacity = "0.9";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.opacity = "1";
        }}
      >
        {buttonText}
      </button>
    </Card>
  );
}
