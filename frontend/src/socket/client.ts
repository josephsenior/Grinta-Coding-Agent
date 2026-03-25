import { io, type Socket } from "socket.io-client";
import { WS_URL } from "@/lib/constants";
import type { ForgeEvent, UserAction } from "@/types/events";

/** Normalize wire payloads so `id` is always a number for dedup / ordering. */
export function coerceForgeEvent(raw: ForgeEvent): ForgeEvent {
  const id =
    typeof raw.id === "number" && Number.isFinite(raw.id) ? raw.id : Number(raw.id);
  if (!Number.isFinite(id) || id < 0) {
    return { ...raw, id: -1 } as ForgeEvent;
  }
  return id === raw.id ? raw : ({ ...raw, id } as ForgeEvent);
}

let socket: Socket | null = null;

export interface ConnectOptions {
  conversationId: string;
  latestEventId?: number;
}

/** Establish a Socket.IO connection to a conversation. */
export function connectSocket(opts: ConnectOptions): Socket {
  if (socket?.connected) {
    socket.disconnect();
  }

  socket = io(WS_URL, {
    query: {
      conversation_id: opts.conversationId,
      latest_event_id: opts.latestEventId ?? -1,
    },
    transports: ["websocket", "polling"],
    reconnection: true,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    reconnectionAttempts: Infinity,
  });

  return socket;
}

/** Send a user action to the backend. Returns false if the socket is not connected. */
export function sendUserAction(action: UserAction): boolean {
  if (!socket?.connected) return false;
  socket.emit("forge_user_action", action);
  return true;
}

/** Get the current socket instance. */
export function getSocket(): Socket | null {
  return socket;
}

/** Disconnect the socket. */
export function disconnectSocket(): void {
  socket?.disconnect();
  socket = null;
}

/**
 * Register `forge_event` on this socket instance immediately (before connect resolves).
 * Coerces `event.id` to a number so dedup logic stays consistent with the REST API.
 */
export function registerForgeEventListener(
  sock: Socket,
  callback: (event: ForgeEvent) => void,
): () => void {
  const handler = (data: ForgeEvent) => {
    callback(coerceForgeEvent(data));
  };
  sock.on("forge_event", handler);
  return () => {
    sock.off("forge_event", handler);
  };
}
