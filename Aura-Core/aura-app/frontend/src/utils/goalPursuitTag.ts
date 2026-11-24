/**
 * Legacy [GOAL_PURSUIT_REQUEST:goal_id] tag (B3-06).
 * With goals_v2 on, Aura uses the request_pursuit tool, so the tag is ignored.
 * Remove this path in a later cleanup card, after the flag defaults on.
 */
export function goalPursuitTagId(responseText: string, goalsV2Enabled: boolean | undefined): string | null {
  if (goalsV2Enabled) return null;
  const match = responseText.match(/\[GOAL_PURSUIT_REQUEST:([^\]]+)\]/);
  return match ? match[1] : null;
}
