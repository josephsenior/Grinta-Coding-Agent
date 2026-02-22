import { BookOpen } from "lucide-react";

export default function KnowledgeBase() {
  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col px-6 py-8">
      <div className="mb-6 flex items-center gap-2">
        <BookOpen className="h-6 w-6" />
        <h1 className="text-2xl font-bold">Knowledge Base</h1>
      </div>
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        Knowledge Base page — Phase 6
      </div>
    </div>
  );
}
