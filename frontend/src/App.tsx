import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { RequireAuth } from './auth/RequireAuth';
import { landingPathForRole } from './auth/roles';
import { Layout } from './components/layout/Layout';

import { LoginPage } from './pages/LoginPage';
import { UnauthorizedPage } from './pages/UnauthorizedPage';
import { NoAccessPage } from './pages/NoAccessPage';

import { AdminDashboard } from './pages/admin/AdminDashboard';
import { TenantsPage } from './pages/admin/TenantsPage';
import { TenantDetailPage } from './pages/admin/TenantDetailPage';

import { TenantDashboard } from './pages/tenant/TenantDashboard';
import { TenantSettingsPage } from './pages/tenant/TenantSettingsPage';

import { DataScientistDashboard } from './pages/workspace/DataScientistDashboard';
import { ExperimentsPage } from './pages/workspace/ExperimentsPage';
import { ExperimentDetailPage } from './pages/workspace/ExperimentDetailPage';
import { JobsPage } from './pages/workspace/JobsPage';
import { SubmitJobPage } from './pages/workspace/SubmitJobPage';
import { ModelsPage } from './pages/workspace/ModelsPage';
import { NotebookPage } from './pages/workspace/NotebookPage';

import { GovernanceDashboard } from './pages/governance/GovernanceDashboard';
import { ReviewQueuePage } from './pages/governance/ReviewQueuePage';
import { ReviewDetailPage } from './pages/governance/ReviewDetailPage';

import { SnowflakePage } from './pages/snowflake/SnowflakePage';
import { AuditLogPage } from './pages/audit/AuditLogPage';
import { FeatureStorePage } from './pages/features/FeatureStorePage';

function RootRedirect() {
  const { user, status } = useAuth();
  if (status === 'no-access') return <Navigate to="/no-access" replace />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={landingPathForRole(user.role)} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />
      <Route path="/no-access" element={<NoAccessPage />} />
      <Route path="/" element={<RootRedirect />} />

      {/* ── Platform Admin ─────────────────────────────────────────────── */}
      <Route
        path="/admin"
        element={
          <RequireAuth roles={['PlatformAdmin']}>
            <Layout title="Platform Admin">
              <AdminDashboard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/tenants"
        element={
          <RequireAuth roles={['PlatformAdmin']}>
            <Layout title="Tenants">
              <TenantsPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/admin/tenants/:tenantId"
        element={
          <RequireAuth roles={['PlatformAdmin']}>
            <Layout title="Tenant Detail">
              <TenantDetailPage />
            </Layout>
          </RequireAuth>
        }
      />
      {/* ── Tenant Admin ───────────────────────────────────────────────── */}
      <Route
        path="/tenant"
        element={
          <RequireAuth roles={['TenantAdmin']}>
            <Layout title="Tenant Dashboard">
              <TenantDashboard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/tenant/settings"
        element={
          <RequireAuth roles={['TenantAdmin']}>
            <Layout title="Tenant Settings">
              <TenantSettingsPage />
            </Layout>
          </RequireAuth>
        }
      />

      {/* ── Shared workspace ───────────────────────────────────────────── */}
      <Route
        path="/workspace"
        element={
          <RequireAuth roles={['DataScientist']}>
            <Layout title="Dashboard">
              <DataScientistDashboard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/experiments"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist', 'MRM']}>
            <Layout title="Experiments">
              <ExperimentsPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/experiments/:experimentId"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist', 'MRM']}>
            <Layout title="Experiment Detail">
              <ExperimentDetailPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/jobs"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist']}>
            <Layout title="Training Jobs">
              <JobsPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/submit"
        element={
          <RequireAuth roles={['DataScientist']}>
            <Layout title="Submit Training Job">
              <SubmitJobPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/models"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist', 'MRM']}>
            <Layout title="Model Registry">
              <ModelsPage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/feature-store"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist', 'MRM']}>
            <Layout title="Feature Store">
              <FeatureStorePage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/notebook"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist']}>
            <Layout title="Notebooks">
              <NotebookPage />
            </Layout>
          </RequireAuth>
        }
      />

      {/* ── Governance / MRM ───────────────────────────────────────────── */}
      <Route
        path="/governance"
        element={
          <RequireAuth roles={['MRM', 'PlatformAdmin']}>
            <Layout title="Governance">
              <GovernanceDashboard />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/governance/reviews"
        element={
          <RequireAuth roles={['MRM', 'PlatformAdmin']}>
            <Layout title="Review Queue">
              <ReviewQueuePage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/governance/reviews/:reviewId"
        element={
          <RequireAuth roles={['MRM', 'PlatformAdmin']}>
            <Layout title="Review Detail">
              <ReviewDetailPage />
            </Layout>
          </RequireAuth>
        }
      />

      {/* ── Snowflake / Audit ──────────────────────────────────────────── */}
      <Route
        path="/snowflake"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist']}>
            <Layout title="Snowflake">
              <SnowflakePage />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/audit"
        element={
          <RequireAuth roles={['PlatformAdmin', 'TenantAdmin', 'DataScientist']}>
            <Layout title="Audit Log">
              <AuditLogPage />
            </Layout>
          </RequireAuth>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
