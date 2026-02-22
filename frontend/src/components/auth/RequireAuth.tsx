import { Navigate, Outlet, useLocation } from "react-router-dom";

const STORAGE_KEY = "forge_session_api_key";

export function RequireAuth() {
  const location = useLocation();
  const hasKey = Boolean(localStorage.getItem(STORAGE_KEY));

  if (!hasKey) {
    const returnTo = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?returnTo=${returnTo}`} replace />;
  }

  return <Outlet />;
}
