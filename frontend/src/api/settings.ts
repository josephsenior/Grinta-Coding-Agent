import apiClient from "./client";
import type { SettingsResponse } from "@/types/settings";

export async function getSettings(): Promise<SettingsResponse> {
  const { data } = await apiClient.get<SettingsResponse>("/settings");
  return data;
}

export async function saveSettings(
  settings: Partial<SettingsResponse>,
): Promise<void> {
  await apiClient.post("/settings", settings);
}
