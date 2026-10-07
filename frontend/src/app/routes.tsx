import { createBrowserRouter, Navigate, Outlet, useRouteError, isRouteErrorResponse } from 'react-router';
import { Layout } from './components/apcotex/Layout';
import { Dashboard } from './components/apcotex/Dashboard';
import { LiteratureReview } from './components/apcotex/LiteratureReview';
import { RecipeSimulator } from './components/apcotex/RecipeSimulator';
import { RecipeComparisonPage } from './components/apcotex/RecipeComparison/RecipeComparisonPage';
import { RecipeHistory } from './components/apcotex/RecipeHistory';
import { CustomerTrialFeedbackPage } from './components/apcotex/CustomerTrialFeedbackPage';
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

function RouteErrorBoundary() {
  const error: any = useRouteError();
  const errorMessage = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error?.message || 'An unexpected error occurred';

  return (
    <div style={{
      padding: '40px 24px',
      maxWidth: 600,
      margin: '60px auto',
      background: 'white',
      borderRadius: 12,
      border: '1px solid #E5E7EB',
      boxShadow: '0 4px 20px rgba(0,0,0,0.06)',
      textAlign: 'center',
      fontFamily: 'inherit'
    }}>
      <h2 style={{ color: '#1F5FA8', fontSize: '1.25rem', fontWeight: 700, marginBottom: 8 }}>
        Something went wrong
      </h2>
      <p style={{ color: '#6B7280', fontSize: '0.875rem', marginBottom: 16 }}>
        {errorMessage}
      </p>
      <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
        <button
          onClick={() => window.location.reload()}
          style={{
            background: '#1FB7B5',
            color: 'white',
            border: 'none',
            borderRadius: 6,
            padding: '8px 18px',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: 'pointer'
          }}
        >
          Reload Page
        </button>
        <button
          onClick={() => window.location.href = '/dashboard'}
          style={{
            background: 'white',
            color: '#1F5FA8',
            border: '1px solid #1F5FA8',
            borderRadius: 6,
            padding: '8px 18px',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: 'pointer'
          }}
        >
          Return to Dashboard
        </button>
      </div>
    </div>
  );
}

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
    errorElement: <RouteErrorBoundary />,
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
          { path: 'recipe-simulator/compare', Component: RecipeComparisonPage },
          { path: 'recipe-history', Component: RecipeHistory },
          { path: 'customer-trial-feedback', Component: CustomerTrialFeedbackPage },
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
