const META_PATTERNS: RegExp[] = [
  /^the user is\b/i,
  /^from the system context\b/i,
  /^i should\b/i,
  /^i can see i have\b/i,
  /^this is a general knowledge question\b/i,
];

export interface AssistantTextSegments {
  thought: string;
  response: string;
  hasSplit: boolean;
}

function normalizeLines(input: string): string[] {
  return input
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trimEnd());
}

function isMetaLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return META_PATTERNS.some((pattern) => pattern.test(trimmed));
}

export function splitAssistantThoughtAndResponse(input: string): AssistantTextSegments {
  const lines = normalizeLines(input);
  if (lines.length === 0) {
    return { thought: "", response: input, hasSplit: false };
  }

  // Only split when it clearly looks like leaked internal planning text.
  const firstWindow = lines.slice(0, 14);
  const metaHits = firstWindow.filter(isMetaLine).length;
  if (metaHits < 2) {
    return { thought: "", response: input, hasSplit: false };
  }

  let cutIndex = 0;
  while (cutIndex < lines.length) {
    const line = lines[cutIndex] ?? "";
    if (!line.trim()) {
      // Skip one blank separator after the meta preamble.
      cutIndex += 1;
      break;
    }
    cutIndex += 1;
  }

  const thought = lines.slice(0, cutIndex).join("\n").trim();
  const response = lines.slice(cutIndex).join("\n").trimStart();

  if (!thought) {
    return { thought: "", response: input, hasSplit: false };
  }

  return {
    thought,
    response,
    hasSplit: true,
  };
}
