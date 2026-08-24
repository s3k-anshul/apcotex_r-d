import { createContext, useContext, useState, ReactNode, useEffect } from "react";
import { getToken } from "../services/researchApi";

interface User {
  id: string;
  role: "ADMIN" | "SCIENTIST" | null;
  username: string;
  name: string;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: User;
  isAdmin: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState<User>({ id: "", role: null, username: "", name: "" });

  const BASE_URL = import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || '/api/v1';

  const fetchProfile = async (token: string) => {
    try {
      const res = await fetch(`${BASE_URL}/users/me`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (res.ok) {
        const data = await res.json();
        const userData = data.data;
        setUser({
          id: userData.id,
          role: userData.role,
          username: userData.username,
          name: userData.full_name
        });
        setIsAuthenticated(true);
      }
    } catch (e) {
      console.error("Failed to fetch user profile", e);
    }
  };

  const login = async (username: string, password: string) => {
    try {
      const res = await fetch(`${BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      
      if (!res.ok) return false;
      
      const data = await res.json();
      const token = data.data.access_token;
      // Also cache token in localStorage so we can persist session (optional depending on strict requirements)
      localStorage.setItem('access_token', token);
      
      await fetchProfile(token);
      return true;
    } catch (e) {
      console.error(e);
      return false;
    }
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setIsAuthenticated(false);
    setUser({ id: "", role: null, username: "", name: "" });
  };

  // Session restoration
  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      fetchProfile(token);
    }
  }, []);

  const isAdmin = user.role === "ADMIN";

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
