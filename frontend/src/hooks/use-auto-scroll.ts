import { useRef, useCallback, useEffect, useState } from "react";

const SCROLL_THRESHOLD = 100; // px from bottom to consider "at bottom"

/**
 * Manages auto-scroll behavior for the chat event stream.
 * Returns refs and state for scroll container, bottom anchor, and FAB visibility.
 */
export function useAutoScroll(deps: unknown[]) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showScrollFab, setShowScrollFab] = useState(false);
  const userScrolledUpRef = useRef(false);

  const isNearBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD;
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    bottomRef.current?.scrollIntoView({ behavior });
    userScrolledUpRef.current = false;
    setShowScrollFab(false);
  }, []);

  // Handle user scroll
  const handleScroll = useCallback(() => {
    const atBottom = isNearBottom();
    userScrolledUpRef.current = !atBottom;
    setShowScrollFab(!atBottom);
  }, [isNearBottom]);

  // Auto-scroll on new content — only if user hasn't scrolled up
  useEffect(() => {
    if (!userScrolledUpRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return {
    scrollContainerRef,
    bottomRef,
    showScrollFab,
    scrollToBottom,
    handleScroll,
  };
}
