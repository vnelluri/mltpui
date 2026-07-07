import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from './AuthContext';
import { hasRole } from './roles';
import type { Role } from '../types/platform';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';

interface RequireAuthProps {
  children: ReactNode;
  roles?: Role[];
}

export function RequireAuth({ children, roles }: RequireAuthProps) {
  const { status, user } = useAuth();
  const location = useLocation();

  if (status === 'initializing' || status === 'authenticating') {
    return (
      <div className="flex h-screen items-center justify-center bg-bg-dark">
        <LoadingSpinner label="Authenticating…" />
      </div>
    );
  }

  if (status === 'no-access') {
    return <Navigate to="/no-access" replace />;
  }

  if (status !== 'authenticated' || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (roles && roles.length > 0 && !hasRole(user.role, roles)) {
    return <Navigate to="/unauthorized" replace />;
  }

  return <>{children}</>;
}
