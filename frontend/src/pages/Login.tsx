import { useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Hammer, Eye, EyeOff, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import apiClient from "@/api/client";

const STORAGE_KEY = "forge_session_api_key";

export default function Login() {
  const [key, setKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const returnTo = params.get("returnTo") || "/";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) {
      inputRef.current?.focus();
      return;
    }

    setLoading(true);
    try {
      // Verify the key with a lightweight authenticated request
      await apiClient.get("/conversations?limit=1", {
        headers: { "X-Session-API-Key": trimmed },
      });
      localStorage.setItem(STORAGE_KEY, trimmed);
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        toast.error("Invalid API key — check your config and try again");
      } else {
        // Network error or server down — save anyway so the UI can show the error naturally
        localStorage.setItem(STORAGE_KEY, trimmed);
        navigate(returnTo, { replace: true });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <Hammer className="h-6 w-6 text-primary" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Forge</h1>
          <p className="text-center text-sm text-muted-foreground">
            Enter your session API key to continue
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="api-key" className="text-sm font-medium">
              Session API Key
            </label>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="api-key"
                ref={inputRef}
                type={showKey ? "text" : "password"}
                placeholder="forge_..."
                value={key}
                onChange={(e) => setKey(e.target.value)}
                className="pl-9 pr-10 font-mono"
                autoFocus
                autoComplete="current-password"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                tabIndex={-1}
                aria-label={showKey ? "Hide key" : "Show key"}
              >
                {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          <Button type="submit" className="w-full" disabled={loading || !key.trim()}>
            {loading ? "Verifying..." : "Sign in"}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Find your key in{" "}
          <code className="rounded bg-muted px-1 font-mono">
            backend/.env.local
          </code>{" "}
          under <code className="rounded bg-muted px-1 font-mono">SESSION_API_KEY</code>
        </p>
      </div>
    </div>
  );
}
