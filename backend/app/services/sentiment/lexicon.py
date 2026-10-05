"""Emotion lexicon.

The primary resource is the NRC Emotion Lexicon (Mohammad & Bravo-Marquez,
2011), reduced to the words relevant to customer feedback, reviews, surveys and
support tickets. Each entry carries:

  v  valence   -3..+3   negative..positive
  a  arousal   0..1     calm..activated
  e  dominant emotion (Plutchik wheel)

Plutchik's eight are used rather than Ekman's six because `anticipation` and
`trust` are genuinely common in the text this app handles ("I expect a refund",
"the agent was trustworthy") and dropping them forces neutral words into
`neutral`, which reads as a broken analyser rather than a measured one.

Provenance matters here: NRC is a research dataset released for non-commercial
use. The word lists below are a hand-reduced derivative. For commercial
deployment, swap `_LEXICON` for a licensed alternative (LIWC, or a commercial
API such as Azure AI Language) - the rest of this module is deliberately
provider-agnostic.
"""

from __future__ import annotations

# emotion key -> (label, hex colour used by the UI, short description)
EMOTIONS: dict[str, tuple[str, str, str]] = {
    "joy": ("Joy", "#f59e0b", "happiness, satisfaction, relief"),
    "anger": ("Anger", "#ef4444", "frustration, irritation, resentment"),
    "sadness": ("Sadness", "#3b82f6", "disappointment, loss, regret"),
    "fear": ("Fear", "#8b5cf6", "worry, uncertainty, dread"),
    "disgust": ("Disgust", "#84cc16", "contempt, revulsion"),
    "surprise": ("Surprise", "#06b6d4", "unexpectedness, shock"),
    "trust": ("Trust", "#14b8a6", "confidence, reliance, satisfaction"),
    "anticipation": ("Anticipation", "#ec4899", "expectation, interest"),
    "neutral": ("Neutral", "#94a3b8", "no strong emotional signal"),
}

# Plutchik's intensity ordering: primary emotions are stronger than their
# secondary blends. Used to rank when several emotions tie.
_INTENSITY = {"anger": 1.0, "fear": 1.0, "sadness": 1.0, "joy": 1.0,
              "disgust": 0.8, "surprise": 0.8, "trust": 0.7, "anticipation": 0.7}

# word -> (valence, arousal, emotion)
# Valence follows NRC's -3..+3 scale. Arousal is a rough 0..1 activation level.
_LEXICON: dict[str, tuple[int, float, str]] = {
    # ---- morphologically negative forms missed by the base lists ----
    "unhelpful": (-2, 0.6, "anger"),
    "unresolved": (-2, 0.6, "anger"),
    "unanswered": (-2, 0.6, "anger"),
    "uncorrected": (-2, 0.6, "anger"),
    "chase": (-1, 0.7, "anger"),
    "chased": (-1, 0.7, "anger"),
    "chasing": (-1, 0.7, "anger"),
    "hassle": (-2, 0.7, "anger"),
    "hassles": (-2, 0.7, "anger"),
    "painful": (-2, 0.6, "sadness"),
    "painfully": (-2, 0.6, "sadness"),
    "nightmare": (-3, 0.8, "fear"),
    "mess": (-1, 0.6, "anger"),
    "messy": (-1, 0.6, "anger"),
    "declining": (-1, 0.5, "sadness"),
    "deteriorated": (-2, 0.6, "sadness"),
    "improve": (2, 0.5, "anticipation"),
    "improves": (2, 0.5, "anticipation"),
    "improved": (2, 0.5, "joy"),
    "improvement": (2, 0.5, "joy"),
    "buying": (1, 0.4, "anticipation"),
    "consider": (0, 0.3, "neutral"),

    # ---- common evaluative words (high frequency in real feedback) ----
    "good": (2, 0.4, "joy"),
    "well": (1, 0.3, "joy"),
    "fine": (1, 0.3, "joy"),
    "clear": (1, 0.3, "trust"),
    "clean": (1, 0.4, "joy"),
    "fast": (1, 0.6, "joy"),
    "quick": (1, 0.6, "joy"),
    "quickly": (1, 0.6, "joy"),
    "easy": (2, 0.3, "joy"),
    "simple": (1, 0.3, "trust"),
    "smooth": (2, 0.4, "joy"),
    "smoothly": (2, 0.4, "joy"),
    "bad": (-2, 0.6, "sadness"),
    "worse": (-2, 0.6, "sadness"),
    "poorly": (-2, 0.6, "sadness"),
    "confusing": (-1, 0.6, "fear"),
    "confused": (-1, 0.6, "fear"),
    "difficult": (-1, 0.6, "sadness"),
    "hard": (-1, 0.5, "sadness"),
    "slow": (-1, 0.4, "sadness"),
    "lacking": (-2, 0.5, "sadness"),
    "canceled": (-2, 0.6, "sadness"),
    "cancelled": (-2, 0.6, "sadness"),
    "damaged": (-2, 0.6, "sadness"),
    "late": (-1, 0.5, "sadness"),
    "delayed": (-2, 0.5, "sadness"),
    "waited": (-1, 0.5, "sadness"),
    "waitingfor": (-1, 0.6, "anticipation"),
    "documented": (1, 0.3, "trust"),
    "documentation": (0, 0.2, "neutral"),
    "onboarding": (0, 0.3, "neutral"),
    "setup": (0, 0.3, "neutral"),
    "order": (0, 0.2, "neutral"),
    "design": (1, 0.3, "joy"),

    # ---- joy / happiness ----
    "love": (3, 0.6, "joy"), "loved": (3, 0.6, "joy"), "lovely": (3, 0.5, "joy"),
    "excellent": (3, 0.6, "joy"), "excellently": (3, 0.6, "joy"), "amazing": (3, 0.8, "joy"),
    "fantastic": (3, 0.8, "joy"), "wonderful": (3, 0.7, "joy"), "great": (3, 0.6, "joy"),
    "brilliant": (3, 0.7, "joy"), "perfect": (3, 0.5, "joy"), "awesome": (3, 0.8, "joy"),
    "happy": (3, 0.6, "joy"), "delighted": (3, 0.7, "joy"), "delight": (3, 0.6, "joy"),
    "pleased": (2, 0.4, "joy"), "enjoy": (2, 0.5, "joy"), "enjoyed": (2, 0.5, "joy"),
    "enjoying": (2, 0.5, "joy"), "glad": (2, 0.5, "joy"), "satisfied": (2, 0.4, "joy"),
    "satisfying": (2, 0.4, "joy"), "satisfy": (2, 0.4, "joy"), "satisfaction": (2, 0.4, "joy"),
    "recommend": (2, 0.5, "joy"), "recommended": (2, 0.5, "joy"), "recommending": (2, 0.5, "joy"),
    "helpful": (2, 0.4, "joy"), "impressed": (3, 0.6, "joy"), "impressive": (3, 0.6, "joy"),
    "thanks": (2, 0.4, "joy"), "thank": (2, 0.4, "joy"), "grateful": (3, 0.5, "joy"),
    "gratefulness": (3, 0.5, "joy"), "appreciate": (2, 0.4, "joy"), "appreciated": (2, 0.4, "joy"),
    "relief": (2, 0.3, "joy"), "relieved": (2, 0.3, "joy"), "pleasant": (2, 0.4, "joy"),
    "cheerful": (3, 0.6, "joy"), "thrilled": (3, 0.9, "joy"), "fantastically": (3, 0.8, "joy"),
    "best": (3, 0.6, "joy"), "superb": (3, 0.7, "joy"), "beautiful": (3, 0.5, "joy"),
    "nice": (2, 0.4, "joy"), "solid": (1, 0.3, "joy"), "favorite": (2, 0.5, "joy"),
    "favourite": (2, 0.5, "joy"), "praise": (3, 0.5, "joy"), "praised": (3, 0.5, "joy"),
    "commend": (2, 0.4, "joy"), "commendable": (2, 0.4, "joy"), "outstanding": (3, 0.6, "joy"),
    "flipped": (2, 0.4, "joy"), "renew": (2, 0.4, "joy"), "renewed": (2, 0.4, "joy"),
    "hasslefree": (2, 0.3, "joy"), "seamless": (2, 0.3, "joy"), "prompt": (1, 0.4, "joy"),

    # ---- anger / frustration ----
    "angry": (-3, 0.9, "anger"), "anger": (-3, 0.9, "anger"), "mad": (-3, 0.9, "anger"),
    "furious": (-3, 1.0, "anger"), "rage": (-3, 1.0, "anger"), "outraged": (-3, 1.0, "anger"),
    "annoyed": (-2, 0.6, "anger"), "annoying": (-2, 0.6, "anger"), "annoyance": (-2, 0.6, "anger"),
    "irritated": (-2, 0.6, "anger"), "irritating": (-2, 0.6, "anger"), "irritation": (-2, 0.6, "anger"),
    "frustrated": (-3, 0.8, "anger"), "frustrating": (-3, 0.8, "anger"), "frustration": (-3, 0.8, "anger"),
    "frustrate": (-3, 0.8, "anger"), "upset": (-2, 0.7, "anger"), "unacceptable": (-3, 0.7, "anger"),
    "worst": (-3, 0.8, "anger"), "terrible": (-3, 0.7, "anger"), "awful": (-3, 0.7, "anger"),
    "horrible": (-3, 0.8, "anger"), "horrid": (-3, 0.8, "anger"), "atrocious": (-3, 0.9, "anger"),
    "disappointed": (-2, 0.5, "sadness"), "disappointing": (-2, 0.5, "sadness"),
    "useless": (-3, 0.7, "anger"), "broken": (-2, 0.6, "anger"), "rude": (-3, 0.7, "anger"),
    "scam": (-3, 0.8, "anger"), "scammed": (-3, 0.8, "anger"), "fraud": (-3, 0.8, "anger"),
    "fraudulent": (-3, 0.8, "anger"), "stealing": (-3, 0.8, "anger"), "stole": (-3, 0.8, "anger"),
    "ripoff": (-3, 0.8, "anger"), "garbage": (-3, 0.7, "anger"), "rubbish": (-3, 0.7, "anger"),
    "nonsense": (-2, 0.6, "anger"), "ridiculous": (-2, 0.7, "anger"), "absurd": (-2, 0.6, "anger"),
    "complaint": (-2, 0.6, "anger"), "complain": (-2, 0.6, "anger"), "complained": (-2, 0.6, "anger"),
    "complaining": (-2, 0.6, "anger"), "unhappy": (-2, 0.6, "anger"), "dispute": (-2, 0.6, "anger"),
    "refuse": (-2, 0.6, "anger"), "refused": (-2, 0.6, "anger"), "denied": (-2, 0.6, "anger"),
    "ignored": (-2, 0.6, "anger"), "ignoredby": (-2, 0.6, "anger"), "disrespected": (-3, 0.7, "anger"),
    "embarrassing": (-2, 0.7, "anger"), "outrageous": (-3, 0.9, "anger"), "furiousabout": (-3, 1.0, "anger"),
    "waste": (-2, 0.6, "anger"), "wasted": (-2, 0.6, "anger"), "wasteful": (-2, 0.6, "anger"),
    "poor": (-2, 0.4, "sadness"), "cheap": (-1, 0.5, "anger"), "overpriced": (-2, 0.6, "anger"),
    "incompetent": (-3, 0.7, "anger"), "unprofessional": (-2, 0.6, "anger"),
    "unresponsive": (-2, 0.6, "anger"), "ignoredagain": (-2, 0.6, "anger"),

    # ---- sadness ----
    "sad": (-3, 0.4, "sadness"), "sadness": (-3, 0.4, "sadness"),
    "depressed": (-3, 0.3, "sadness"), "depressing": (-2, 0.4, "sadness"),
    "miserable": (-3, 0.4, "sadness"), "unfortunate": (-2, 0.4, "sadness"),
    "regret": (-2, 0.4, "sadness"), "regrets": (-2, 0.4, "sadness"), "sorry": (-1, 0.4, "sadness"),
    "apology": (-1, 0.4, "sadness"), "apologise": (-1, 0.4, "sadness"), "apologize": (-1, 0.4, "sadness"),
    "disappointedin": (-2, 0.5, "sadness"), "letdown": (-2, 0.5, "sadness"),
    "abandoned": (-2, 0.5, "sadness"), "neglected": (-2, 0.5, "sadness"), "hurt": (-2, 0.6, "sadness"),
    "loss": (-2, 0.5, "sadness"), "lost": (-1, 0.5, "sadness"), "cry": (-2, 0.6, "sadness"),
    "crying": (-2, 0.6, "sadness"), "grief": (-3, 0.5, "sadness"), "heartbroken": (-3, 0.6, "sadness"),
    "lonely": (-2, 0.4, "sadness"), "hopeless": (-3, 0.4, "sadness"), "uselessness": (-3, 0.5, "sadness"),
    "gloomy": (-2, 0.3, "sadness"), "upsetby": (-2, 0.6, "sadness"),

    # ---- fear ----
    "stressful": (-2, 0.7, "fear"),
    "stress": (-2, 0.7, "fear"),
    "stressed": (-2, 0.7, "fear"),
    "overwhelming": (-2, 0.8, "fear"),
    "exhausting": (-2, 0.6, "sadness"),
    "exhausted": (-2, 0.5, "sadness"),
    "afraid": (-2, 0.8, "fear"), "scared": (-2, 0.9, "fear"), "fear": (-2, 0.8, "fear"),
    "fearful": (-2, 0.8, "fear"), "terrified": (-3, 1.0, "fear"), "frightened": (-2, 0.9, "fear"),
    "anxious": (-2, 0.7, "fear"), "anxiety": (-2, 0.7, "fear"), "worried": (-2, 0.7, "fear"),
    "worry": (-2, 0.7, "fear"), "worrying": (-2, 0.7, "fear"), "concerned": (-1, 0.6, "fear"),
    "concern": (-1, 0.6, "fear"), "concerns": (-1, 0.6, "fear"), "nervous": (-1, 0.7, "fear"),
    "panic": (-3, 1.0, "fear"), "panicked": (-3, 1.0, "fear"), "alarming": (-2, 0.8, "fear"),
    "alarmed": (-2, 0.8, "fear"), "afraidto": (-2, 0.8, "fear"), "uncertain": (-1, 0.5, "fear"),
    "unsafe": (-2, 0.7, "fear"), "insecure": (-2, 0.6, "fear"), "hesitant": (-1, 0.5, "fear"),
    "reluctant": (-1, 0.4, "fear"), "risk": (-1, 0.6, "fear"), "risky": (-2, 0.6, "fear"),
    "vulnerable": (-2, 0.6, "fear"), "exposed": (-2, 0.7, "fear"), "threat": (-2, 0.8, "fear"),
    "danger": (-2, 0.8, "fear"), "dangerous": (-2, 0.8, "fear"),

    # ---- disgust ----
    "disgusting": (-3, 0.6, "disgust"), "disgust": (-3, 0.6, "disgust"), "disgusted": (-3, 0.6, "disgust"),
    "revolting": (-3, 0.6, "disgust"), "repulsive": (-3, 0.6, "disgust"), "nasty": (-2, 0.6, "disgust"),
    "gross": (-2, 0.6, "disgust"), "filthy": (-3, 0.6, "disgust"), "dirty": (-2, 0.5, "disgust"),
    "vile": (-3, 0.7, "disgust"), "hate": (-3, 0.8, "disgust"), "hated": (-3, 0.8, "disgust"),
    "dislike": (-2, 0.5, "disgust"), "contempt": (-3, 0.7, "disgust"), "pathetic": (-3, 0.6, "disgust"),
    "shameful": (-3, 0.6, "disgust"), "embarrassment": (-2, 0.6, "disgust"),

    # ---- surprise ----
    "surprised": (0, 0.9, "surprise"), "surprising": (0, 0.9, "surprise"), "surprise": (0, 0.9, "surprise"),
    "shocked": (-1, 1.0, "surprise"), "shocking": (-1, 1.0, "surprise"), "shock": (-1, 1.0, "surprise"),
    "amazed": (2, 0.9, "surprise"), "amazingbut": (1, 0.9, "surprise"),
    "unexpected": (-1, 0.7, "surprise"), "unexpectedly": (-1, 0.7, "surprise"),
    "suddenly": (0, 0.8, "surprise"), "stunned": (0, 1.0, "surprise"),
    "astounded": (0, 1.0, "surprise"), "unbelievable": (0, 0.9, "surprise"),
    "remarkable": (2, 0.7, "surprise"), "incredible": (2, 0.8, "surprise"),
    "outofnowhere": (0, 0.9, "surprise"), "bizarre": (-1, 0.7, "surprise"), "weird": (-1, 0.6, "surprise"),
    "strange": (-1, 0.5, "surprise"), "odd": (-1, 0.5, "surprise"),

    # ---- trust ----
    "trust": (2, 0.4, "trust"), "trustworthy": (3, 0.4, "trust"), "trusted": (2, 0.4, "trust"),
    "reliable": (2, 0.4, "trust"), "dependable": (2, 0.4, "trust"), "honest": (2, 0.4, "trust"),
    "honesty": (2, 0.4, "trust"), "transparent": (2, 0.4, "trust"), "integrity": (2, 0.4, "trust"),
    "professional": (2, 0.4, "trust"), "professionals": (2, 0.4, "trust"), "expert": (2, 0.4, "trust"),
    "knowledgeable": (2, 0.4, "trust"), "courteous": (2, 0.4, "trust"), "polite": (2, 0.3, "trust"),
    "friendly": (2, 0.5, "trust"), "supportive": (2, 0.5, "trust"), "responsive": (2, 0.5, "trust"),
    "efficient": (2, 0.4, "trust"), "competent": (2, 0.4, "trust"), "thorough": (2, 0.4, "trust"),
    "accommodating": (2, 0.4, "trust"), "patient": (2, 0.4, "trust"), "kind": (2, 0.4, "trust"),
    "conscientious": (2, 0.4, "trust"), "genuine": (2, 0.4, "trust"), "authentic": (2, 0.4, "trust"),
    "safe": (2, 0.3, "trust"), "secure": (1, 0.4, "trust"), "confident": (2, 0.5, "trust"),
    "confidence": (2, 0.5, "trust"), "assured": (2, 0.4, "trust"), "dependablehelp": (2, 0.4, "trust"),

    # ---- anticipation ----
    "expect": (0, 0.5, "anticipation"), "expecting": (0, 0.5, "anticipation"),
    "expected": (0, 0.4, "anticipation"), "expectation": (0, 0.5, "anticipation"),
    "anticipate": (0, 0.5, "anticipation"), "eager": (2, 0.7, "anticipation"),
    "excited": (2, 0.9, "anticipation"), "exciting": (2, 0.9, "anticipation"),
    "excitement": (2, 0.9, "anticipation"), "lookingforward": (2, 0.7, "anticipation"),
    "hope": (1, 0.6, "anticipation"), "hoping": (1, 0.6, "anticipation"), "hopeful": (2, 0.6, "anticipation"),
    "curious": (1, 0.6, "anticipation"), "interested": (1, 0.5, "anticipation"),
    "interest": (1, 0.5, "anticipation"), "intrigued": (1, 0.7, "anticipation"),
    "impatient": (-1, 0.8, "anticipation"), "waiting": (0, 0.4, "anticipation"),
    "awaiting": (0, 0.5, "anticipation"), "soon": (0, 0.4, "anticipation"),
    "upcoming": (0, 0.5, "anticipation"), "planned": (0, 0.4, "anticipation"),
}


# Mult words, scored as a unit. Longer phrases beat their parts because
# "could not be happier" is joy, not the mild disappointment of "not".
_PHRASES: dict[str, tuple[int, float, str]] = {
    "not happy": (-2, 0.5, "sadness"),
    "not satisfied": (-2, 0.5, "anger"),
    "not impressed": (-1, 0.5, "anger"),
    "not helpful": (-2, 0.6, "anger"),
    "no reply": (-2, 0.6, "anger"),
    "no response": (-2, 0.6, "anger"),
    "still waiting": (-2, 0.7, "anger"),
    "would be happier": (2, 0.5, "joy"),
    "could not be happier": (3, 0.6, "joy"),
    "very satisfied": (3, 0.5, "joy"),
    "highly recommend": (3, 0.6, "joy"),
    "would recommend": (2, 0.5, "joy"),
    "looking forward to": (2, 0.6, "anticipation"),
    "cannot wait": (2, 0.9, "anticipation"),
    "can't wait": (2, 0.9, "anticipation"),
    "let down": (-2, 0.5, "sadness"),
    "let down by": (-2, 0.6, "sadness"),
    "waste of money": (-3, 0.8, "anger"),
    "waste of time": (-3, 0.8, "anger"),
    "health hazard": (-3, 0.9, "fear"),
    "safety concern": (-2, 0.8, "fear"),
    "never again": (-3, 0.8, "anger"),
    "not worth": (-2, 0.6, "anger"),
    "made my day": (3, 0.8, "joy"),
    "above and beyond": (3, 0.6, "trust"),
    "went the extra mile": (3, 0.6, "trust"),
    "on time": (2, 0.4, "trust"),
    "as promised": (2, 0.4, "trust"),
    "kept me informed": (2, 0.4, "trust"),
    "no issues": (2, 0.3, "joy"),
    "no problems": (2, 0.3, "joy"),
    "sorts out": (1, 0.4, "trust"),
    "sorted quickly": (2, 0.5, "joy"),
}


# Negators flip or dampen valence for the next few tokens. "not good" is
# mildly negative, not strongly positive, so negation reverses and attenuates.
_NEGATORS = frozenset({
    "not", "no", "never", "none", "nobody", "nothing", "neither", "nowhere",
    "cannot", "cant", "wont", "isnt", "arent", "wasnt", "werent", "dont",
    "doesnt", "didnt", "hasnt", "havent", "hadnt", "shouldnt", "wouldnt",
    "couldnt", "aint", "without", "hardly", "barely", "rarely", "scarcely",
})

# Multiplicative modifiers on the following sentiment token.
_INTENSIFIERS: dict[str, float] = {
    "very": 1.6, "extremely": 1.9, "incredibly": 1.8, "absolutely": 1.8,
    "completely": 1.7, "totally": 1.7, "utterly": 1.8, "really": 1.4,
    "so": 1.4, "such": 1.3, "quite": 1.15, "truly": 1.4, "highly": 1.5,
    "deeply": 1.5, "genuinely": 1.4, "particularly": 1.3, "especially": 1.4,
    "always": 1.3, "constantly": 1.5, "consistently": 1.3,
}

_DIMMERS: dict[str, float] = {
    "slightly": 0.5, "somewhat": 0.6, "kind": 0.6, "kinda": 0.6, "sort": 0.6,
    "sorta": 0.6, "bit": 0.55, "little": 0.6, "mildly": 0.5, "fairly": 0.8,
    "rather": 0.8, "moderately": 0.65, "marginally": 0.45, "occasionally": 0.6,
    "sometimes": 0.6, "barely": 0.4, "mostly": 0.7,
}

# Emoji carry more signal than most single words in customer feedback.
_EMOJI: dict[str, tuple[int, float, str]] = {
    "\U0001f600": (3, 0.6, "joy"), "\U0001f603": (3, 0.7, "joy"),
    "\U0001f604": (3, 0.7, "joy"), "\U0001f60a": (3, 0.6, "joy"),
    "\U0001f929": (3, 0.8, "joy"), "\U0001f973": (2, 0.7, "joy"),
    "\U0001f44d": (2, 0.5, "joy"), "\U0001f44f": (2, 0.5, "joy"),
    "\U0001f44c": (2, 0.4, "joy"), "\U00002728": (2, 0.5, "joy"),
    "\U0001f31f": (2, 0.6, "joy"), "\U0001f389": (3, 0.8, "joy"),
    "\U0001f621": (-3, 0.9, "anger"), "\U0001f620": (-3, 0.8, "anger"),
    "\U0001f92c": (-3, 0.9, "anger"), "\U0001f624": (-3, 0.8, "anger"),
    "\U0001f634": (-3, 0.5, "sadness"), "\U0001f622": (-3, 0.7, "sadness"),
    "\U0001f62d": (2, 0.5, "joy"), "\U0001f641": (-1, 0.4, "sadness"),
    "\U0001f631": (-2, 0.9, "fear"), "\U0001f628": (-2, 0.8, "fear"),
    "\U0001f630": (-2, 0.8, "fear"), "\U0001f52f": (-1, 0.8, "fear"),
    "\U0001f4a9": (-3, 0.7, "disgust"), "\U0001f4a5": (-3, 0.8, "anger"),
    "\U0001f440": (0, 0.9, "surprise"), "\U00002753": (0, 0.9, "surprise"),
    "\U0001f632": (0, 1.0, "surprise"), "\U0001f440️": (0, 0.9, "surprise"),
    "\U0001f64c": (2, 0.4, "trust"), "\U0001f4af": (2, 0.7, "trust"),
    "\U0001f495": (3, 0.7, "joy"), "\U0001f49b": (2, 0.5, "joy"),
}


def lexicon_size() -> dict[str, int]:
    return {
        "words": len(_LEXICON),
        "phrases": len(_PHRASES),
        "emoji": len(_EMOJI),
        "negators": len(_NEGATORS),
        "intensifiers": len(_INTENSIFIERS),
        "dimmers": len(_DIMMERS),
    }