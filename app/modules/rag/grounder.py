"""Grounding decision: strong | soft | refused. See spec §10."""


def decide(hits: list, cfg: dict) -> dict:
    """Return {"grounded": "strong"|"soft"|"refused",
                "citation_keys": [...],
                "included_hits": [Hit...],
                "suggestions": [{"citation_key", "score", "content", "page_number"}, ...]}.
    """
    high = cfg["include_threshold"]
    soft = cfg["soft_include_threshold"]
    low = cfg["suggest_threshold"]
    cap = cfg["max_chunks"]

    above_high = [h for h in hits if h.score >= high][:cap]
    above_soft = [h for h in hits if h.score >= soft]
    above_low = [h for h in hits if h.score >= low]

    if above_high:
        for h in above_high:
            h.included = True
        return {
            "grounded": "strong",
            "citation_keys": [k for h in above_high for k in h.citation_keys],
            "included_hits": above_high,
            "suggestions": [],
        }
    if above_soft:
        rescue = above_soft[0]
        rescue.included = True
        return {
            "grounded": "soft",
            "citation_keys": list(rescue.citation_keys),
            "included_hits": [rescue],
            "suggestions": [],
        }
    return {
        "grounded": "refused",
        "citation_keys": [],
        "included_hits": [],
        "suggestions": [
            {
                "citation_key": h.citation_keys[0] if h.citation_keys else "",
                "score": h.score,
                "content": h.content,
                "page_number": h.page_number,
            }
            for h in above_low[:3]
        ],
    }
