import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles, Play, Loader2, Pencil, Trash2, Plus, MoreHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePlaybooks } from "@/hooks/use-playbooks";
import { useUserSkills, type UserSkill } from "@/hooks/use-user-skills";
import { sendUserAction } from "@/socket/client";
import { toast } from "sonner";
import {
  deletePlaybook,
  updatePlaybookContent,
  type Playbook,
} from "@/api/playbooks";

interface SkillsTabProps {
  conversationId: string;
}

function slugifyName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Path segments allowed by the playbook rename API (letters, digits, _, -). */
function normalizePlaybookKey(raw: string): string {
  const segments = raw
    .trim()
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .map((seg) =>
      seg
        .trim()
        .replace(/\s+/g, "-")
        .replace(/[^a-zA-Z0-9_-]/g, ""),
    )
    .filter(Boolean);
  return segments.join("/");
}

export function SkillsTab({ conversationId }: SkillsTabProps) {
  const queryClient = useQueryClient();
  const {
    data: serverPlaybooks = [],
    isLoading,
    isError: playbooksError,
    refetch: refetchPlaybooks,
  } = usePlaybooks(conversationId);
  const { skills: userSkills, addSkill, updateSkill, removeSkill } = useUserSkills();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formName, setFormName] = useState("");
  const [formContent, setFormContent] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<UserSkill | null>(null);

  const [serverEditorPb, setServerEditorPb] = useState<Playbook | null>(null);
  const [serverEditorName, setServerEditorName] = useState("");
  const [serverEditorContent, setServerEditorContent] = useState("");
  const [deleteServerPb, setDeleteServerPb] = useState<Playbook | null>(null);

  const updateServerPb = useMutation({
    mutationFn: ({
      name,
      content,
      newName,
    }: {
      name: string;
      content: string;
      newName?: string;
    }) => updatePlaybookContent(conversationId, name, content, { newName }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["playbooks", conversationId] });
      toast.success("Playbook saved");
      setServerEditorPb(null);
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "response" in err
          ? String(
              (err as { response?: { data?: { detail?: unknown; error?: unknown } } }).response?.data
                ?.detail ??
                (err as { response?: { data?: { error?: unknown } } }).response?.data?.error ??
                "Request failed",
            )
          : err instanceof Error
            ? err.message
            : "Could not save playbook";
      toast.error(msg);
    },
  });

  const deleteServerPbMut = useMutation({
    mutationFn: (name: string) => deletePlaybook(conversationId, name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["playbooks", conversationId] });
      toast.success("Playbook removed");
      setDeleteServerPb(null);
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "response" in err
          ? String(
              (err as { response?: { data?: { detail?: unknown; error?: unknown } } }).response?.data
                ?.detail ??
                (err as { response?: { data?: { error?: unknown } } }).response?.data?.error ??
                "Request failed",
            )
          : err instanceof Error
            ? err.message
            : "Could not delete playbook";
      toast.error(msg);
    },
  });

  const totalCount = serverPlaybooks.length + userSkills.length;

  const openCreate = () => {
    setEditingId(null);
    setFormName("");
    setFormContent("");
    setEditorOpen(true);
  };

  const openEdit = (s: UserSkill) => {
    setEditingId(s.id);
    setFormName(s.name);
    setFormContent(s.content);
    setEditorOpen(true);
  };

  const submitForm = () => {
    const name = slugifyName(formName) || "skill";
    const content = formContent.trim();
    if (!content) {
      toast.error("Skill content is required");
      return;
    }
    if (editingId) {
      updateSkill(editingId, { name, content });
      toast.success("Skill updated");
    } else {
      addSkill({ name, content });
      toast.success("Skill added");
    }
    setEditorOpen(false);
  };

  const handleRunServer = (pb: Playbook) => {
    const ok = sendUserAction({
      action: "message",
      args: { content: `/${pb.name}` },
    });
    if (ok) toast.success(`Running /${pb.name}`);
    else
      toast.error("Not connected", {
        description: "Open this chat and wait for the live link, then try again.",
      });
  };

  const openServerEditor = (pb: Playbook) => {
    setServerEditorPb(pb);
    setServerEditorName(pb.name);
    setServerEditorContent(pb.content ?? "");
  };

  const submitServerEditor = () => {
    if (!serverEditorPb) return;
    const content = serverEditorContent.trim();
    const newName = normalizePlaybookKey(serverEditorName);
    if (!content) {
      toast.error("Content is required");
      return;
    }
    if (!newName) {
      toast.error("Name is required");
      return;
    }
    updateServerPb.mutate({
      name: serverEditorPb.name,
      content,
      newName: newName !== serverEditorPb.name ? newName : undefined,
    });
  };

  const handleRunUser = (s: UserSkill) => {
    const ok = sendUserAction({
      action: "message",
      args: { content: s.content },
    });
    if (ok) toast.success(`Sent skill: ${s.name}`);
    else
      toast.error("Not connected", {
        description: "Open this chat and wait for the live link, then try again.",
      });
  };

  const sortedLocals = useMemo(
    () => [...userSkills].sort((a, b) => b.updatedAt - a.updatedAt),
    [userSkills],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 border-b px-3 py-2">
        <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Skills
        </span>
        {totalCount > 0 && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
            {totalCount}
          </Badge>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto h-7 gap-1 px-2 text-[11px]"
          onClick={openCreate}
          title="Add custom skill"
        >
          <Plus className="h-3 w-3" />
          Add
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-1 p-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : playbooksError ? (
            <div className="space-y-2 px-2 py-4">
              <p className="text-xs font-medium text-destructive">Couldn&apos;t load workspace skills</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Custom skills below still work. For repo playbooks, fix the API and retry.
              </p>
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void refetchPlaybooks()}>
                Try again
              </Button>
            </div>
          ) : totalCount === 0 ? (
            <div className="space-y-1.5 px-2 py-4">
              <p className="text-xs text-muted-foreground">No skills in this list yet.</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground/90">
                Add a <span className="font-medium text-foreground/80">custom skill</span> (saved in this
                browser), or open a workspace that loads repository playbooks — they show up in this list
                automatically.
              </p>
            </div>
          ) : null}

          {serverPlaybooks.map((pb) => (
            <div
              key={`srv-${pb.name}`}
              className="flex items-start gap-2 rounded-lg border p-2 transition-colors hover:bg-accent"
            >
              <div className="min-w-0 flex-1">
                <span className="font-mono text-xs font-medium">/{pb.name}</span>
                {(pb.description ?? "").trim().length > 0 && (
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                    {pb.description}
                  </p>
                )}
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    aria-label="Playbook actions"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem
                    className="gap-2 text-xs"
                    onSelect={() => openServerEditor(pb)}
                    disabled={updateServerPb.isPending}
                  >
                    <Pencil className="h-3 w-3" />
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2 text-xs"
                    onSelect={() => handleRunServer(pb)}
                  >
                    <Play className="h-3 w-3" />
                    Run
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2 text-xs text-destructive focus:text-destructive"
                    onSelect={() => setDeleteServerPb(pb)}
                    disabled={deleteServerPbMut.isPending}
                  >
                    <Trash2 className="h-3 w-3" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}

          {sortedLocals.map((s) => (
            <div
              key={s.id}
              className="flex items-start gap-2 rounded-lg border p-2 transition-colors hover:bg-accent"
            >
              <div className="min-w-0 flex-1">
                <span className="font-mono text-xs font-medium">{s.name}</span>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 shrink-0"
                    aria-label="Skill actions"
                  >
                    <MoreHorizontal className="h-3.5 w-3.5" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem className="gap-2 text-xs" onSelect={() => openEdit(s)}>
                    <Pencil className="h-3 w-3" />
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem className="gap-2 text-xs" onSelect={() => handleRunUser(s)}>
                    <Play className="h-3 w-3" />
                    Run
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="gap-2 text-xs text-destructive focus:text-destructive"
                    onSelect={() => setDeleteTarget(s)}
                  >
                    <Trash2 className="h-3 w-3" />
                    Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}
        </div>
      </ScrollArea>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-h-[min(90vh,640px)] gap-4 overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingId ? "Edit skill" : "New skill"}</DialogTitle>
            <DialogDescription>
              Custom skills send their content as a chat message. Workspace skills use{" "}
              <code className="text-xs">/name</code> and come from the repository.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <label htmlFor="skill-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="skill-name"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                placeholder="e.g. review-pr"
                autoComplete="off"
              />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor="skill-content" className="text-sm font-medium">
                Content
              </label>
              <Textarea
                id="skill-content"
                value={formContent}
                onChange={(e) => setFormContent(e.target.value)}
                placeholder="Full instructions sent to the agent when you run this skill…"
                className="min-h-[160px] resize-y font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditorOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submitForm}>{editingId ? "Save" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete skill?</DialogTitle>
            <DialogDescription>
              Remove &ldquo;{deleteTarget?.name}&rdquo; from your custom skills. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (deleteTarget) removeSkill(deleteTarget.id);
                setDeleteTarget(null);
                toast.success("Skill removed");
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={!!serverEditorPb}
        onOpenChange={(o) => {
          if (!o) setServerEditorPb(null);
        }}
      >
        <DialogContent className="max-h-[min(90vh,640px)] gap-4 overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Edit playbook</DialogTitle>
            <DialogDescription>
              Saves to the playbook file under this workspace. You can change the slash name for files in{" "}
              <span className="font-mono text-[10px]">.Forge/playbooks</span>.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <label htmlFor="pb-name" className="text-sm font-medium">
                Name
              </label>
              <Input
                id="pb-name"
                value={serverEditorName}
                onChange={(e) => setServerEditorName(e.target.value)}
                placeholder="e.g. my-task or folder/my-task"
                autoComplete="off"
                className="font-mono text-xs"
              />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor="pb-content" className="text-sm font-medium">
                Content
              </label>
              <Textarea
                id="pb-content"
                value={serverEditorContent}
                onChange={(e) => setServerEditorContent(e.target.value)}
                className="min-h-[220px] resize-y font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setServerEditorPb(null)}>
              Cancel
            </Button>
            <Button
              onClick={submitServerEditor}
              disabled={updateServerPb.isPending}
              className="gap-2"
            >
              {updateServerPb.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteServerPb} onOpenChange={(o) => !o && setDeleteServerPb(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete playbook?</DialogTitle>
            <DialogDescription>
              Remove <span className="font-mono">/{deleteServerPb?.name}</span> from the workspace and
              this session. The file on disk will be deleted if it lives under the workspace.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteServerPb(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteServerPbMut.isPending}
              className="gap-2"
              onClick={() => {
                if (deleteServerPb) deleteServerPbMut.mutate(deleteServerPb.name);
              }}
            >
              {deleteServerPbMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
