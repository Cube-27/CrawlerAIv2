import { createContext, use, useCallback, useMemo, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { createApiClient, type ApiClient } from "../api/client";
import { readProblem, type ProblemSummary } from "../api/problem";

interface AuthState {
  apiKey: string | null;
  /** Why the last key was dropped: the API's 401 problem. Null after a connect or a disconnect. */
  rejection: ProblemSummary | null;
}

interface AuthContextValue extends AuthState {
  connect: (apiKey: string) => void;
  disconnect: () => void;
  /** Drops `apiKey` after the API answered 401 for it. A key connected since then is kept. */
  reject: (apiKey: string, problem: ProblemSummary | null) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const KEY_REJECTED: ProblemSummary = { title: "The API rejected the key.", detail: null };

/** Holds the API key in React state only: never in storage or cookies, so a reload returns to /connect (§18). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ apiKey: null, rejection: null });

  const connect = useCallback((apiKey: string) => {
    setState({ apiKey, rejection: null });
  }, []);
  const disconnect = useCallback(() => {
    setState({ apiKey: null, rejection: null });
  }, []);
  const reject = useCallback((apiKey: string, problem: ProblemSummary | null) => {
    setState((current) =>
      current.apiKey === apiKey ? { apiKey: null, rejection: problem ?? KEY_REJECTED } : current,
    );
  }, []);

  const value = useMemo(
    () => ({ ...state, connect, disconnect, reject }),
    [state, connect, disconnect, reject],
  );
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthContextValue {
  const auth = use(AuthContext);
  if (auth === null) throw new Error("useAuth is used outside AuthProvider");
  return auth;
}

function authenticatedClient(apiKey: string, reject: AuthContextValue["reject"]): ApiClient {
  const client = createApiClient({ baseUrl: window.location.origin, apiKey });
  client.use({
    async onResponse({ response }) {
      // RFC 9110 §15.5.2: 401 means the request's credentials were not accepted (SPEC-07 §4.2: unknown or revoked).
      if (response.status === 401) reject(apiKey, await readProblem(response.clone()));
    },
  });
  return client;
}

/** The API client for the connected key. A 401 answer drops the key, and RequireKey then shows /connect. */
export function useApiClient(): ApiClient {
  const { apiKey, reject } = useAuth();
  const client = useMemo(
    () => (apiKey === null ? null : authenticatedClient(apiKey, reject)),
    [apiKey, reject],
  );
  if (client === null) throw new Error("useApiClient is used on a route outside RequireKey");
  return client;
}

/** Route element for screens that call the API: without a key, sends the viewer to /connect and back afterwards. */
export function RequireKey() {
  const { apiKey } = useAuth();
  const location = useLocation();
  if (apiKey === null) {
    return <Navigate to="/connect" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
