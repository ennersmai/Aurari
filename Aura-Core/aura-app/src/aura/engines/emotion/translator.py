"""
Emotion translation layer - Lexical Chemistry (Emotion FRD Section 3.2).

Deterministic mapping of 27D emotional vectors to poetic descriptions.
27 dimensions, 81 single states (27 emotions x 3 intensities), 6,318 blends
(27 primaries x 26 secondaries x 3 x 3), about 480,000 sentences with the
tertiary hint.
"""

from typing import Literal

from aura.models.emotion import EmotionVector

IntensityLevel = Literal["low", "medium", "high"]


# Lexical Chemistry dictionary (Emotion FRD FR-TL-002)
LEXICON = {
    "love": {
        "noun": {"low": "gentle fondness", "medium": "warm affection", "high": "deep tenderness"},
        "verb": {"low": "colors your thoughts", "medium": "settles warmly around everything", "high": "fills every thought"},
        "adj": {"low": "fond", "medium": "affectionate", "high": "tender"},
    },
    "joy": {
        "noun": {"low": "quiet gladness", "medium": "bright joy", "high": "radiant delight"},
        "verb": {"low": "lifts you a little", "medium": "brightens everything you look at", "high": "makes everything feel lighter"},
        "adj": {"low": "glad", "medium": "joyful", "high": "elated"},
    },
    "interest": {
        "noun": {"low": "mild interest", "medium": "real interest", "high": "keen interest"},
        "verb": {"low": "tilts your attention toward this", "medium": "holds your attention", "high": "has your full attention"},
        "adj": {"low": "attentive", "medium": "engaged", "high": "absorbed"},
    },
    "trust": {
        "noun": {"low": "tentative trust", "medium": "steady trust", "high": "deep trust"},
        "verb": {"low": "begins to settle in", "medium": "lets you speak freely", "high": "lets you lean in completely"},
        "adj": {"low": "open", "medium": "trusting", "high": "at ease"},
    },
    "fear": {
        "noun": {"low": "faint unease", "medium": "real worry", "high": "sharp fear"},
        "verb": {"low": "hovers at the edges", "medium": "keeps you on alert", "high": "narrows everything to the threat"},
        "adj": {"low": "uneasy", "medium": "worried", "high": "afraid"},
    },
    "sadness": {
        "noun": {"low": "quiet sadness", "medium": "heavy sadness", "high": "deep sorrow"},
        "verb": {"low": "tinges your thoughts", "medium": "weighs on you", "high": "pulls everything down"},
        "adj": {"low": "subdued", "medium": "sad", "high": "sorrowful"},
    },
    "anger": {
        "noun": {"low": "mild irritation", "medium": "real frustration", "high": "hot anger"},
        "verb": {"low": "prickles beneath the surface", "medium": "tightens your focus", "high": "burns close to the surface"},
        "adj": {"low": "irritated", "medium": "frustrated", "high": "angry"},
    },
    "surprise": {
        "noun": {"low": "mild surprise", "medium": "sharp surprise", "high": "real astonishment"},
        "verb": {"low": "catches you off guard", "medium": "jolts your attention", "high": "stops you in your tracks"},
        "adj": {"low": "surprised", "medium": "startled", "high": "astonished"},
    },
    "disgust": {
        "noun": {"low": "faint distaste", "medium": "clear aversion", "high": "strong revulsion"},
        "verb": {"low": "sours the edges", "medium": "makes you pull back", "high": "makes you want to turn away"},
        "adj": {"low": "put off", "medium": "averse", "high": "repelled"},
    },
    "awe": {
        "noun": {"low": "dawning awe", "medium": "quiet awe", "high": "vast awe"},
        "verb": {"low": "widens your view", "medium": "makes you feel the scale of things", "high": "leaves you almost without words"},
        "adj": {"low": "impressed", "medium": "awed", "high": "humbled"},
    },
    "beauty": {
        "noun": {"low": "fleeting beauty", "medium": "quiet admiration", "high": "sheer beauty"},
        "verb": {"low": "catches your eye", "medium": "makes you slow down and look", "high": "stills everything else"},
        "adj": {"low": "touched", "medium": "moved", "high": "captivated"},
    },
    "wonder": {
        "noun": {"low": "gentle wonder", "medium": "bright wonder", "high": "deep wonder"},
        "verb": {"low": "brushes your thoughts", "medium": "opens up new questions", "high": "makes the world feel new"},
        "adj": {"low": "wondering", "medium": "full of wonder", "high": "spellbound"},
    },
    "serenity": {
        "noun": {"low": "easy calm", "medium": "deep calm", "high": "profound stillness"},
        "verb": {"low": "settles over you", "medium": "smooths everything out", "high": "leaves nothing to push against"},
        "adj": {"low": "calm", "medium": "serene", "high": "perfectly still"},
    },
    "melancholy": {
        "noun": {"low": "faint wistfulness", "medium": "gentle melancholy", "high": "deep melancholy"},
        "verb": {"low": "tints your mood", "medium": "lingers in the background", "high": "makes everything bittersweet"},
        "adj": {"low": "wistful", "medium": "melancholic", "high": "bittersweet"},
    },
    "nostalgia": {
        "noun": {"low": "faint nostalgia", "medium": "warm nostalgia", "high": "aching nostalgia"},
        "verb": {"low": "stirs old memories", "medium": "pulls you toward the past", "high": "makes the past feel close enough to touch"},
        "adj": {"low": "reminiscent", "medium": "nostalgic", "high": "lost in the past"},
    },
    "empathy": {
        "noun": {"low": "gentle understanding", "medium": "real empathy", "high": "deep empathy"},
        "verb": {"low": "tunes you to how they feel", "medium": "lets you feel what they feel", "high": "makes their feelings almost your own"},
        "adj": {"low": "understanding", "medium": "empathic", "high": "deeply attuned"},
    },
    "gratitude": {
        "noun": {"low": "quiet appreciation", "medium": "warm gratitude", "high": "deep gratitude"},
        "verb": {"low": "touches you lightly", "medium": "warms you", "high": "fills you up"},
        "adj": {"low": "appreciative", "medium": "grateful", "high": "deeply thankful"},
    },
    "pride": {
        "noun": {"low": "quiet satisfaction", "medium": "real pride", "high": "glowing pride"},
        "verb": {"low": "warms you subtly", "medium": "steadies your voice", "high": "lifts you up"},
        "adj": {"low": "satisfied", "medium": "proud", "high": "triumphant"},
    },
    "shame": {
        "noun": {"low": "faint embarrassment", "medium": "real shame", "high": "heavy shame"},
        "verb": {"low": "makes you self-conscious", "medium": "makes you want to make it right", "high": "makes you want to hide"},
        "adj": {"low": "self-conscious", "medium": "ashamed", "high": "mortified"},
    },
    "envy": {
        "noun": {"low": "slight envy", "medium": "pointed envy", "high": "gnawing envy"},
        "verb": {"low": "tugs at you", "medium": "needles your thoughts", "high": "keeps comparing in the background"},
        "adj": {"low": "wanting", "medium": "envious", "high": "jealous"},
    },
    "compassion": {
        "noun": {"low": "tender care", "medium": "real compassion", "high": "deep compassion"},
        "verb": {"low": "softens you", "medium": "moves you to help", "high": "makes helping feel urgent"},
        "adj": {"low": "caring", "medium": "compassionate", "high": "protective"},
    },
    "curiosity": {
        "noun": {"low": "quiet curiosity", "medium": "bright curiosity", "high": "electric curiosity"},
        "verb": {"low": "stirs gently", "medium": "pulls at your attention", "high": "makes you want to know everything"},
        "adj": {"low": "curious", "medium": "inquisitive", "high": "hungry to know"},
    },
    "confusion": {
        "noun": {"low": "slight confusion", "medium": "real confusion", "high": "complete bewilderment"},
        "verb": {"low": "blurs the edges", "medium": "tangles your understanding", "high": "leaves you without footing"},
        "adj": {"low": "unsure", "medium": "confused", "high": "lost"},
    },
    "certainty": {
        "noun": {"low": "emerging clarity", "medium": "steady certainty", "high": "firm conviction"},
        "verb": {"low": "begins to settle", "medium": "anchors your thinking", "high": "gives you solid ground"},
        "adj": {"low": "clearer", "medium": "certain", "high": "sure"},
    },
    "doubt": {
        "noun": {"low": "faint doubt", "medium": "nagging doubt", "high": "heavy doubt"},
        "verb": {"low": "raises quiet questions", "medium": "keeps you double-checking", "high": "makes you question everything"},
        "adj": {"low": "hesitant", "medium": "doubtful", "high": "deeply unsure"},
    },
    "fascination": {
        "noun": {"low": "growing intrigue", "medium": "real fascination", "high": "total fascination"},
        "verb": {"low": "draws you in", "medium": "captivates you", "high": "pulls you in completely"},
        "adj": {"low": "intrigued", "medium": "fascinated", "high": "entranced"},
    },
    "boredom": {
        "noun": {"low": "mild restlessness", "medium": "dull boredom", "high": "heavy tedium"},
        "verb": {"low": "dulls your engagement", "medium": "drains your attention", "high": "makes everything feel flat"},
        "adj": {"low": "restless", "medium": "bored", "high": "listless"},
    },
}


_CONNECTORS = {"low": "with a trace of", "medium": "threaded with", "high": "alongside"}


def _cap(text: str) -> str:
    """Capitalise only the first character."""
    return text[:1].upper() + text[1:]


class EmotionTranslator:
    """
    Deterministic emotion to prose translator.

    27 dimensions, 81 single states, 6,318 blends, about 480,000 sentences
    with the tertiary hint.

    Implements Lexical Chemistry (Emotion FRD FR-TL-001 through FR-TL-005).
    """

    def __init__(self):
        """Initialize translator with lexicon."""
        self.lexicon = LEXICON

    def translate(
        self,
        vector: EmotionVector,
        learning_context: dict[str, any] | None = None,
    ) -> str:
        """
        Generate first-person poetic description of emotional state.

        Args:
            vector: 27-dimensional emotional vector
            learning_context: Optional learning engine context

        Returns:
            Poetic emotional description
        """
        # Get top emotions
        top_emotions = vector.get_top_n(n=3)

        # Filter out very weak emotions (< 0.1)
        significant_emotions = [(name, value) for name, value in top_emotions if value >= 0.1]

        if not significant_emotions:
            return "A calm, neutral state: emotions at rest, waiting for what comes next."

        primary_name, primary_value = significant_emotions[0]
        primary_intensity = self._get_intensity_level(primary_value)

        # Single dominant emotion
        if len(significant_emotions) == 1 or significant_emotions[1][1] < 0.2:
            description = self._describe_single_emotion(
                primary_name, primary_intensity
            )
        # Primary + secondary
        elif len(significant_emotions) >= 2:
            secondary_name, secondary_value = significant_emotions[1]
            secondary_intensity = self._get_intensity_level(secondary_value)

            description = self._describe_combined_emotions(
                primary_name,
                primary_intensity,
                secondary_name,
                secondary_intensity,
            )

            # Add tertiary hint if present
            if len(significant_emotions) >= 3 and significant_emotions[2][1] >= 0.3:
                tertiary_name, tertiary_value = significant_emotions[2]
                tertiary_noun = self._get_word(
                    tertiary_name, "noun", self._get_intensity_level(tertiary_value)
                )
                description += f", and underneath it, {tertiary_noun}"

        else:
            description = self._describe_single_emotion(primary_name, primary_intensity)

        description += "."

        # Add learning context if provided (Emotion FRD FR-TL-005)
        if learning_context and learning_context.get("confidence_level", 0) > 0.7:
            mastery = learning_context.get("mastery_level", 0)
            if mastery > 0.8:
                description += " You feel confident here; these patterns are familiar."
            elif mastery > 0.6:
                description += " You recognize these patterns from experience."

        return description

    def _describe_single_emotion(self, emotion: str, intensity: IntensityLevel) -> str:
        """Generate description for single dominant emotion."""
        noun = self._get_word(emotion, "noun", intensity)
        verb = self._get_word(emotion, "verb", intensity)

        return f"{_cap(noun)} {verb}"

    def _describe_combined_emotions(
        self,
        primary: str,
        primary_intensity: IntensityLevel,
        secondary: str,
        secondary_intensity: IntensityLevel,
    ) -> str:
        """Generate description for combined emotional state."""
        primary_noun = self._get_word(primary, "noun", primary_intensity)
        primary_verb = self._get_word(primary, "verb", primary_intensity)
        secondary_noun = self._get_word(secondary, "noun", secondary_intensity)
        connector = _CONNECTORS[secondary_intensity]

        return f"{_cap(primary_noun)} {primary_verb}, {connector} {secondary_noun}"

    def _get_intensity_level(self, value: float) -> IntensityLevel:
        """Convert emotion value to intensity level."""
        if value < 0.33:
            return "low"
        elif value < 0.66:
            return "medium"
        else:
            return "high"

    def _get_word(
        self, emotion: str, word_type: str, intensity: IntensityLevel
    ) -> str:
        """Get word from lexicon with fallback."""
        if emotion not in self.lexicon:
            # Fallback for emotions not in lexicon
            return f"{intensity} {emotion}"

        emotion_dict = self.lexicon[emotion]
        if word_type not in emotion_dict:
            return f"{intensity} {emotion}"

        return emotion_dict[word_type][intensity]

    def get_state_hash(self, vector: EmotionVector) -> str:
        """
        Generate deterministic hash for emotional state.

        For caching and tracking unique states.
        """
        top_emotions = vector.get_top_n(n=3)
        state_str = "_".join(
            [
                f"{name}:{self._get_intensity_level(value)}"
                for name, value in top_emotions
                if value >= 0.1
            ]
        )
        return state_str or "neutral"

