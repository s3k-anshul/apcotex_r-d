import { createBrowserRouter, Navigate, Outlet } from 'react-router';
import { Layout } from './components/apcotex/Layout';
import { Dashboard } from './components/apcotex/Dashboard';
import { LiteratureReview } from './components/apcotex/LiteratureReview';
import { RecipeSimulator } from './components/apcotex/RecipeSimulator';
import { RecipeHistory } from './components/apcotex/RecipeHistory';
import { RecipeDetail } from './components/apcotex/RecipeDetail';
import { PlaceholderPage } from './components/apcotex/PlaceholderPage';
import { SettingsPage } from './components/apcotex/Settings';
import { AuditTrail } from './components/apcotex/AuditTrail';
import { TokenDashboard } from './components/apcotex/TokenDashboard';
import { Login } from './components/apcotex/Login';
import { ProtectedRoute } from './components/apcotex/ProtectedRoute';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/AuthContext';
import { PatentResearchProvider } from './contexts/PatentResearchContext';
import { RecipeProvider } from './contexts/RecipeContext';
import { PropertyProvider } from './contexts/PropertyContext';
import { SPEC_ROWS } from './components/apcotex/recipeSimulatorDemoData';

function AuthWrapper() {
  return (
    <AuthProvider>
      <PatentResearchProvider>
        <RecipeProvider>
          <PropertyProvider initialProperties={SPEC_ROWS}>
            <Outlet />
          </PropertyProvider>
        </RecipeProvider>
      </PatentResearchProvider>
    </AuthProvider>
  );
}

function LayoutWrapper() {
  const { user, logout } = useAuth();
  
  return (
    <Layout
      userRole={user?.role || null}
      userName={user?.name || ''}
      userTitle={user?.title || ''}
      onLogout={logout}
    />
  );
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== 'ADMIN') {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
}

export const router = createBrowserRouter([
  {
    element: <AuthWrapper />,
    children: [
      {
        path: '/login',
        Component: Login,
      },
      {
        path: '/',
        element: (
          <ProtectedRoute>
            <LayoutWrapper />
          </ProtectedRoute>
        ),
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: 'dashboard', Component: Dashboard },
          { path: 'compound-finder', Component: PlaceholderPage },
          { path: 'literature-review', Component: LiteratureReview },
          { path: 'recipe-simulator', Component: RecipeSimulator },
          { path: 'recipe-history', Component: RecipeHistory },
          { 
            path: 'audit-trail', 
            element: (
              <AdminRoute>
                <AuditTrail />
              </AdminRoute>
            )
          },
          { 
            path: 'token-dashboard', 
            element: (
              <AdminRoute>
                <TokenDashboard />
              </AdminRoute>
            )
          },
          { path: 'recipe/:recipeId', Component: RecipeDetail },
          { path: 'experiments', Component: PlaceholderPage },
          { path: 'products', Component: PlaceholderPage },
          { path: 'settings', Component: SettingsPage },
        ],
      },
    ],
  },
]);
