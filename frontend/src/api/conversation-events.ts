import apiClient from "./client";
import type { ForgeEvent } from "@/types/events";

const PAGE_LIMIT = 100;

export interface ConversationEventsPage {
  events: ForgeEvent[];
  has_more: boolean;
}

/** Single page (max 100 events per backend contract). */
export async function fetchConversationEventsPage(
  conversationId: string,
  startId: number,
): Promise<ConversationEventsPage> {
  const { data } = await apiClient.get<ConversationEventsPage>(
    `/conversations/${conversationId}/events`,
    { params: { start_id: startId, limit: PAGE_LIMIT } },
  );
  return data;
}

/** Load the full persisted stream for a conversation (paginated). */
export async function fetchAllConversationEvents(conversationId: string): Promise<ForgeEvent[]> {
  const all: ForgeEvent[] = [];
  let startId = 0;
  let hasMore = true;

  while (hasMore) {
    const { events, has_more: more } = await fetchConversationEventsPage(conversationId, startId);
    if (events.length === 0) break;
    all.push(...events);
    hasMore = more;
    const maxId = Math.max(...events.map((e) => Number(e.id)));
    startId = maxId + 1;
  }

  return all;
}

/** Events with id strictly greater than `afterId` (paginated). Use after reconnect to fill gaps. */
export async function fetchConversationEventsAfter(
  conversationId: string,
  afterId: number,
): Promise<ForgeEvent[]> {
  const all: ForgeEvent[] = [];
  let startId = afterId < 0 ? 0 : afterId + 1;
  let hasMore = true;

  while (hasMore) {
    const { events, has_more: more } = await fetchConversationEventsPage(conversationId, startId);
    if (events.length === 0) break;
    all.push(...events);
    hasMore = more;
    const maxId = Math.max(...events.map((e) => Number(e.id)));
    startId = maxId + 1;
  }

  return all;
}
