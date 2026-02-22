import { Activity } from "lucide-react";

export default function Monitoring() {
  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col px-6 py-8">
      <div className="mb-6 flex items-center gap-2">
        <Activity className="h-6 w-6" />
        <h1 className="text-2xl font-bold">Monitoring</h1>
      </div>
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        Monitoring dashboard — Phase 7
      </div>
    </div>
  );
}
