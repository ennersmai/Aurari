"""Identity and venue helpers for memory v2 (W3-10).

A turn happens in a venue (the app, a DM, or a guild channel) and is spoken
by a speaker (the owner, or a Discord user id). These helpers turn the
transport's raw ids into the keys memory v2 stores on a fact or episode.
"""


def speaker_key(user_id: str, requester_role: str) -> str:
    """Return the speaker key: ``"owner"`` for the owner, else ``user_id``.

    Discord user ids already look like ``discord_<id>``.
    """
    if requester_role == "owner":
        return "owner"
    return user_id


def venue_for_discord(guild_id: str, channel_id: str, user_id: str) -> str:
    """Return the venue for a Discord message.

    A DM is ``dm:<user_id>``; a guild message names both the guild and the
    channel it was sent in.
    """
    if guild_id == "dm":
        return f"dm:{user_id}"
    return f"guild:{guild_id}/channel:{channel_id}"


def visibility_for_venue(venue: str, speaker: str) -> str:
    """Return the visibility a fact spoken in ``venue`` is stored with.

    App turns are owner-only, a DM is private to its speaker, and a guild
    channel's facts are shared with that guild.
    """
    if venue == "app":
        return "owner"
    if venue.startswith("dm:"):
        return f"private:{speaker}"
    if venue.startswith("guild:"):
        guild_id = venue[len("guild:"):].split("/", 1)[0]
        return f"guild:{guild_id}"
    raise ValueError(f"Unknown venue: {venue}")


def visible_in_venue(venue: str) -> list[str]:
    """Return the visibilities that may be recalled in ``venue``.

    ``"app"`` sees owner facts. A DM sees its private facts, and the owner's
    DM also sees owner facts. A guild channel sees its guild's facts.
    """
    if venue == "app":
        return ["owner"]
    if venue.startswith("dm:"):
        user_id = venue[len("dm:"):]
        visibilities = [f"private:{user_id}"]
        if venue == "dm:owner":
            visibilities.append("owner")
        return visibilities
    if venue.startswith("guild:"):
        guild_id = venue[len("guild:"):].split("/", 1)[0]
        return [f"guild:{guild_id}"]
    raise ValueError(f"Unknown venue: {venue}")