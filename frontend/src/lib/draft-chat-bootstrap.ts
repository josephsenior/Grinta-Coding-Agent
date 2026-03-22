/**
 * First message on /chat/new may need: create conversation → connect socket → upload files → send.
 * Files are not JSON-serializable for router state; we queue them here until the real id is live.
 */
export type DraftChatBootstrap = {
  conversationId: string;
  text: string;
  workspaceFiles: File[];
  imageUrls: string[];
};

let pending: DraftChatBootstrap | null = null;

export function setDraftChatBootstrap(next: DraftChatBootstrap | null): void {
  pending = next;
}

export function takeDraftChatBootstrap(conversationId: string): DraftChatBootstrap | null {
  if (!pending || pending.conversationId !== conversationId) {
    return null;
  }
  const out = pending;
  pending = null;
  return out;
}
