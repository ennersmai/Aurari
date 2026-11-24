import { describe, it, expect } from 'vitest';
import { goalPursuitTagId } from './goalPursuitTag';

const reply = "I'd like to work on [GOAL_PURSUIT_REQUEST:goal:abc123] independently. May I?";

describe('goalPursuitTagId (B3-06)', () => {
  it('finds the tag when goals_v2 is off (legacy modal path)', () => {
    expect(goalPursuitTagId(reply, false)).toBe('goal:abc123');
    expect(goalPursuitTagId(reply, undefined)).toBe('goal:abc123');
  });
  it('ignores the tag when goals_v2 is on, so no modal opens', () => {
    expect(goalPursuitTagId(reply, true)).toBeNull();
  });
  it('returns null without a tag', () => {
    expect(goalPursuitTagId('hello', false)).toBeNull();
  });
});
