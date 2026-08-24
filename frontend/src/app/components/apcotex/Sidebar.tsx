import { useNavigate, useLocation } from "react-router";
import {
  LayoutDashboard,
  BookOpen,
  FlaskConical,
  Settings,
  MessageSquare,
  BarChart3,
  Search,
  Eye,
  History,
  Activity,
} from "lucide-react";
import { useAuth } from "../../contexts/AuthContext";

const BLUE = "#1F5FA8";
const TEAL = "#1FB7B5";
const RED = "#D93A2F";
const BORDER = "#E5E7EB";

// ✅ Logo embedded as Base64 — no external file path needed
const LOGO =
  "data:image/png;base64,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";

const mainNavItems = [
  {
    path: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    exact: true,
  },
  {
    path: "/literature-review",
    label: "Patent Research",
    icon: BookOpen,
  },
  {
    path: "/recipe-simulator",
    label: "Recipe Simulator",
    icon: FlaskConical,
  },
  {
    path: "/recipe-history",
    label: "Recipe History",
    icon: History,
  },
];

interface SidebarProps {
  userName: string;
  userTitle: string;
  userRole: "admin" | "user" | null;
  onLogout: () => void;
}

export function Sidebar({
  userName,
  userTitle,
  userRole,
  onLogout,
}: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAdmin } = useAuth();

  const isActive = (item: {
    path: string;
    exact?: boolean;
  }) => {
    if (item.exact) return location.pathname === item.path;
    return (
      location.pathname === item.path ||
      location.pathname.startsWith(item.path + "/")
    );
  };

  return (
    <div
      style={{
        width: 240,
        minWidth: 240,
        background: "white",
        borderRight: `1px solid ${BORDER}`,
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          padding: "10px 20px",
          borderBottom: `1px solid ${BORDER}`,
          flexShrink: 0,
        }}
      >
        <img
          src={LOGO}
          alt="Apcotex"
          style={{ height: 60, width: "auto" }}
        />
      </div>

      <div style={{ padding: "16px 20px 6px", flexShrink: 0 }}>
        <span
          style={{
            fontSize: "0.6875rem",
            color: "#9CA3AF",
            letterSpacing: "0.07em",
            textTransform: "uppercase",
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Workspace
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: RED,
            }}
          />
        </span>
      </div>

      <nav style={{ flex: 1, overflowY: "auto" }}>
        {mainNavItems.map((item) => {
          const active = isActive(item);
          const Icon = item.icon;

          return (
            <button
              key={item.path}
              onClick={() => navigate(item.path)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "8px 20px",
                background: active
                  ? "rgba(31,95,168,0.06)"
                  : "transparent",
                border: "none",
                borderLeft: active
                  ? `3px solid ${TEAL}`
                  : "3px solid transparent",
                color: active ? BLUE : "#6B7280",
                cursor: "pointer",
                textAlign: "left",
                fontSize: "0.875rem",
                fontWeight: active ? 600 : 400,
                transition: "background 0.12s, color 0.12s",
              }}
              onMouseEnter={(e) => {
                if (!active) {
                  e.currentTarget.style.background = "#F9FAFB";
                  e.currentTarget.style.color = "#374151";
                }
              }}
              onMouseLeave={(e) => {
                if (!active) {
                  e.currentTarget.style.background =
                    "transparent";
                  e.currentTarget.style.color = "#6B7280";
                }
              }}
            >
              <Icon
                size={17}
                strokeWidth={active ? 2 : 1.5}
                style={{ flexShrink: 0 }}
              />
              <span>{item.label}</span>

              {item.label === "Recipe Simulator" && (
                <span
                  style={{
                    marginLeft: "auto",
                    background: "rgba(31,183,181,0.12)",
                    color: TEAL,
                    fontSize: "0.6875rem",
                    padding: "1px 7px",
                    borderRadius: 20,
                    fontWeight: 600,
                  }}
                >
                  AI
                </span>
              )}
            </button>
          );
        })}

        {userRole === "ADMIN" && (
          <>
            <button
              key="/audit-trail"
              onClick={() => navigate("/audit-trail")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "8px 20px",
                background: isActive({ path: "/audit-trail" })
                  ? "rgba(31,95,168,0.06)"
                  : "transparent",
                border: "none",
                borderLeft: isActive({ path: "/audit-trail" })
                  ? `3px solid ${TEAL}`
                  : "3px solid transparent",
                color: isActive({ path: "/audit-trail" })
                  ? BLUE
                  : "#6B7280",
                cursor: "pointer",
                textAlign: "left",
                fontSize: "0.875rem",
                fontWeight: isActive({ path: "/audit-trail" })
                  ? 600
                  : 400,
                transition: "background 0.12s, color 0.12s",
              }}
              onMouseEnter={(e) => {
                if (!isActive({ path: "/audit-trail" })) {
                  e.currentTarget.style.background = "#F9FAFB";
                  e.currentTarget.style.color = "#374151";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive({ path: "/audit-trail" })) {
                  e.currentTarget.style.background =
                    "transparent";
                  e.currentTarget.style.color = "#6B7280";
                }
              }}
            >
              <History
                size={17}
                strokeWidth={
                  isActive({ path: "/audit-trail" }) ? 2 : 1.5
                }
                style={{ flexShrink: 0 }}
              />
              <span>Audit Trail</span>
            </button>
            
            <button
              key="/token-dashboard"
              onClick={() => navigate("/token-dashboard")}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                padding: "8px 20px",
                background: isActive({ path: "/token-dashboard" })
                  ? "rgba(31,95,168,0.06)"
                  : "transparent",
                border: "none",
                borderLeft: isActive({ path: "/token-dashboard" })
                  ? `3px solid ${TEAL}`
                  : "3px solid transparent",
                color: isActive({ path: "/token-dashboard" })
                  ? BLUE
                  : "#6B7280",
                cursor: "pointer",
                textAlign: "left",
                fontSize: "0.875rem",
                fontWeight: isActive({ path: "/token-dashboard" })
                  ? 600
                  : 400,
                transition: "background 0.12s, color 0.12s",
              }}
              onMouseEnter={(e) => {
                if (!isActive({ path: "/token-dashboard" })) {
                  e.currentTarget.style.background = "#F9FAFB";
                  e.currentTarget.style.color = "#374151";
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive({ path: "/token-dashboard" })) {
                  e.currentTarget.style.background =
                    "transparent";
                  e.currentTarget.style.color = "#6B7280";
                }
              }}
            >
              <Activity
                size={17}
                strokeWidth={
                  isActive({ path: "/token-dashboard" }) ? 2 : 1.5
                }
                style={{ flexShrink: 0 }}
              />
              <span>Token Usage</span>
            </button>
          </>
        )}
      </nav>

      <div
        style={{
          borderTop: `1px solid ${BORDER}`,
          flexShrink: 0,
        }}
      >
        {isAdmin && (
          <button
            onClick={() => navigate("/settings")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              width: "100%",
              padding: "8px 20px",
              background: "transparent",
              border: "none",
              borderLeft: "3px solid transparent",
              color: "#6B7280",
              cursor: "pointer",
              fontSize: "0.875rem",
            }}
          >
            <Settings size={17} strokeWidth={1.5} />
            Settings
            <span
              style={{
                marginLeft: "auto",
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "rgba(217,58,47,0.7)",
              }}
            />
          </button>
        )}

        <button
          onClick={onLogout}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "12px 20px",
            borderTop: `1px solid ${BORDER}`,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            width: "100%",
          }}
        >
          <div
            style={{
              width: 30,
              height: 30,
              borderRadius: "50%",
              background: BLUE,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <span
              style={{
                color: "white",
                fontSize: "0.6875rem",
                fontWeight: 700,
              }}
            >
              {userName.charAt(0).toUpperCase()}
            </span>
          </div>

          <div style={{ minWidth: 0 }}>
            <div
              style={{
                color: "#1F2937",
                fontSize: "0.8125rem",
                fontWeight: 600,
                lineHeight: 1.3,
              }}
            >
              {userName}
            </div>
            <div
              style={{
                color: "#9CA3AF",
                fontSize: "0.6875rem",
                lineHeight: 1.3,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {userTitle}
            </div>
          </div>
        </button>
      </div>
    </div>
  );
}