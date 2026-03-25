import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "forge-user-skills-v1";

export interface UserSkill {
  id: string;
  /** Short label / slash-style name (for display). */
  name: string;
  description?: string;
  /** Sent to the agent when the skill is run. */
  content: string;
  updatedAt: number;
}

function loadSkills(): UserSkill[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (x): x is UserSkill =>
        typeof x === "object" &&
        x !== null &&
        typeof (x as UserSkill).id === "string" &&
        typeof (x as UserSkill).name === "string" &&
        typeof (x as UserSkill).content === "string",
    );
  } catch {
    return [];
  }
}

function saveSkills(skills: UserSkill[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(skills));
  } catch {
    /* ignore quota */
  }
}

export function useUserSkills() {
  const [skills, setSkills] = useState<UserSkill[]>(loadSkills);

  useEffect(() => {
    saveSkills(skills);
  }, [skills]);

  const addSkill = useCallback((draft: Omit<UserSkill, "id" | "updatedAt">) => {
    const row: UserSkill = {
      ...draft,
      id: crypto.randomUUID(),
      updatedAt: Date.now(),
    };
    setSkills((prev) => [...prev, row]);
    return row;
  }, []);

  const updateSkill = useCallback((id: string, draft: Omit<UserSkill, "id" | "updatedAt">) => {
    setSkills((prev) =>
      prev.map((s) =>
        s.id === id ? { ...s, ...draft, updatedAt: Date.now() } : s,
      ),
    );
  }, []);

  const removeSkill = useCallback((id: string) => {
    setSkills((prev) => prev.filter((s) => s.id !== id));
  }, []);

  return { skills, addSkill, updateSkill, removeSkill };
}
