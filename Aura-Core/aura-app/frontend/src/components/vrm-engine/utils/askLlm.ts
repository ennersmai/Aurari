import type { Message, Screenplay } from "../mockDependencies";

export async function askLLM(
  _systemPrompt: string,
  _userPrompt: string,
  _chat?: unknown,
): Promise<{ messages: Message[]; screenplay: Screenplay[] }> {
  return { messages: [], screenplay: [] };
}
