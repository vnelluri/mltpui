import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import axios from 'axios';
import {
  PublicClientApplication,
  type AccountInfo,
  InteractionRequiredAuthError,
} from '@azure/msal-browser';
import { msalConfig, loginRequest, apiTokenRequest, DEMO_MODE } from './msalConfig';
import { setTokenProvider } from '../api/client';
import { authApi } from '../api/auth';
import type { CurrentUser, Role } from '../types/platform';
import { parseTenantRole } from './roles';

type AuthStatus =
  | 'initializing'
  | 'unauthenticated'
  | 'authenticating'
  | 'authenticated'
  | 'no-access'
  | 'error';

interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUser | null;
  /** Entra group OIDs decoded from the ID token — display/debug only. */
  groups: string[];
  /** Role derived from groups claim — display/debug only, NOT authoritative. */
  tokenRole: Role | null;
  /** The demo role-selector value (localStorage). Purely visual. */
  demoRole: Role;
  demoMode: boolean;
  error: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
  setDemoRole: (role: Role) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const DEMO_AUTH_KEY = 'mlplatform.demoAuthenticated';
const DEMO_ROLE_KEY = 'mlplatform.demoRole';

// MSAL app instance (only meaningfully used in prod mode).
const msalInstance = new PublicClientApplication(msalConfig);

function decodeGroupsFromIdToken(account: AccountInfo | null): string[] {
  const claims = account?.idTokenClaims as { groups?: unknown } | undefined;
  if (claims && Array.isArray(claims.groups)) {
    return claims.groups.filter((g): g is string => typeof g === 'string');
  }
  return [];
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [demoRole, setDemoRoleState] = useState<Role>(
    () => (localStorage.getItem(DEMO_ROLE_KEY) as Role) || 'PlatformAdmin',
  );
  const msalReady = useRef(false);

  const tokenRole = useMemo(() => parseTenantRole(groups), [groups]);

  // Register the Bearer-token provider used by api/client.ts (prod mode only).
  const registerTokenProvider = useCallback(() => {
    if (DEMO_MODE) {
      setTokenProvider(null);
      return;
    }
    setTokenProvider(async () => {
      const account = msalInstance.getActiveAccount() ?? msalInstance.getAllAccounts()[0];
      if (!account) return null;
      try {
        const result = await msalInstance.acquireTokenSilent({ ...apiTokenRequest, account });
        return result.accessToken;
      } catch (err) {
        if (err instanceof InteractionRequiredAuthError) {
          const result = await msalInstance.acquireTokenPopup(apiTokenRequest);
          return result.accessToken;
        }
        return null;
      }
    });
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUser(me);
      setError(null);
      setStatus('authenticated');
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 403) {
        setStatus('no-access');
        setUser(null);
        return;
      }
      setError('Unable to load your profile from the platform.');
      setStatus('error');
    }
  }, []);

  // Initial bootstrap.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (DEMO_MODE) {
        setTokenProvider(null);
        const wasAuthed = localStorage.getItem(DEMO_AUTH_KEY) === 'true';
        if (wasAuthed) {
          await refreshMe();
        } else if (!cancelled) {
          setStatus('unauthenticated');
        }
        return;
      }

      // Prod mode: initialize MSAL and check for an existing session.
      try {
        await msalInstance.initialize();
        msalReady.current = true;
        await msalInstance.handleRedirectPromise();
        const accounts = msalInstance.getAllAccounts();
        if (accounts.length > 0) {
          msalInstance.setActiveAccount(accounts[0]);
          setGroups(decodeGroupsFromIdToken(accounts[0]));
          registerTokenProvider();
          await refreshMe();
        } else if (!cancelled) {
          setStatus('unauthenticated');
        }
      } catch {
        if (!cancelled) {
          setError('Failed to initialize authentication.');
          setStatus('error');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async () => {
    setStatus('authenticating');
    setError(null);
    if (DEMO_MODE) {
      localStorage.setItem(DEMO_AUTH_KEY, 'true');
      await refreshMe();
      return;
    }
    try {
      if (!msalReady.current) {
        await msalInstance.initialize();
        msalReady.current = true;
      }
      const result = await msalInstance.loginPopup(loginRequest);
      msalInstance.setActiveAccount(result.account);
      setGroups(decodeGroupsFromIdToken(result.account));
      registerTokenProvider();
      await refreshMe();
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 403) {
        setStatus('no-access');
        return;
      }
      setError('Microsoft sign-in was cancelled or failed.');
      setStatus('unauthenticated');
    }
  }, [refreshMe, registerTokenProvider]);

  const logout = useCallback(async () => {
    localStorage.removeItem(DEMO_AUTH_KEY);
    setUser(null);
    setGroups([]);
    setStatus('unauthenticated');
    if (!DEMO_MODE && msalReady.current) {
      const account = msalInstance.getActiveAccount() ?? undefined;
      try {
        await msalInstance.logoutPopup({ account });
      } catch {
        // Ignore popup-close errors on logout.
      }
    }
  }, []);

  const setDemoRole = useCallback((role: Role) => {
    localStorage.setItem(DEMO_ROLE_KEY, role);
    setDemoRoleState(role);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      groups,
      tokenRole,
      demoRole,
      demoMode: DEMO_MODE,
      error,
      login,
      logout,
      refreshMe,
      setDemoRole,
    }),
    [status, user, groups, tokenRole, demoRole, error, login, logout, refreshMe, setDemoRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
