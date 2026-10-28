"""Explicit research scope and stable recommendation cache identity.

Rules live in the private profile, rather than hard-coding a user's interests.
"""
import hashlib
import json
import re


def phrase_matches(text, phrase):
    tokens = re.findall(r"[^\W_]+", str(phrase).casefold())
    if not tokens:
        return False
    pattern = r"[\W_]+".join(re.escape(t) for t in tokens)
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", text.casefold()))


def scope_match(paper, profile):
    """Return (allowed, matched focus labels, strongest priority).

    Explicit exclusions override prestige, must-read rules and fallback ranking.
    A profile without focus groups retains the original broad semantic search.
    """
    text = " ".join(str(paper.get(k) or "") for k in ("title", "abstract"))
    rules = profile.get("recommendation_scope") or {}
    if any(phrase_matches(text, term) for term in rules.get("exclude_terms", [])):
        return False, [], 0.0
    groups = rules.get("focus_groups") or []
    matches = [g for g in groups if (
        any(phrase_matches(text, t) for t in g.get("terms", []))
        or any(terms and all(phrase_matches(text, t) for t in terms)
               for terms in g.get("all_terms", []))
    )]
    if groups and not matches:
        return False, [], 0.0
    return True, [g["label"] for g in matches], max((float(g.get("weight", 1)) for g in matches), default=0.0)


def profile_fingerprint(profile):
    fields = {key: profile.get(key) for key in (
        "core_directions", "topic_weights", "recommendation_scope", "editorial_preferences", "must_read",
        "interest_embedding_model", "interest_vector", "methodology_preferences",
        "taste_profile", "research_summary",
    )}
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(("recommendations-v2:" + payload).encode()).hexdigest()
