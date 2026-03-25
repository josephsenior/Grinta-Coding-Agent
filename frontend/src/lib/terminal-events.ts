import { ActionType, ObservationType } from "@/types/agent";
import type { ForgeEvent } from "@/types/events";

function splitNonEmptyLines(text: string): string[] {
	return text
		.replace(/\r\n/g, "\n")
		.split("\n")
		.map((line) => line.trimEnd())
		.filter((line) => line.length > 0);
}

/** Maps terminal-related events to one or more terminal panel lines. */
export function extractTerminalLinesFromEvent(event: ForgeEvent): string[] {
	if ("action" in event) {
		if (event.action === ActionType.TERMINAL_RUN) {
			const command = typeof event.args?.command === "string" ? event.args.command : "";
			const cwd = typeof event.args?.cwd === "string" ? event.args.cwd : "";
			if (!command) return [];
			return [cwd ? `[run @ ${cwd}] $ ${command}` : `$ ${command}`];
		}

		if (event.action === ActionType.TERMINAL_INPUT) {
			const input = typeof event.args?.input === "string" ? event.args.input : "";
			if (!input) return [];
			const compact = input.replace(/\r?\n/g, "\\n");
			return [`> ${compact}`];
		}

		return [];
	}

	if ("observation" in event && event.observation === ObservationType.TERMINAL) {
		if (!event.content || typeof event.content !== "string") return [];
		return splitNonEmptyLines(event.content);
	}

	return [];
}

