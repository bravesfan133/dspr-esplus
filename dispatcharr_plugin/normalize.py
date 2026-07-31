import re


def normalize_title(title: str) -> str:
    if not title:
        return ""

    text = title.lower()

    text = re.sub(r"\bvs?\b", " vs ", text)
    text = re.sub(r"\bat\b", " vs ", text)
    text = text.replace("@", " vs ")

    text = re.sub(r"[^\w\s/]", " ", text)

    text = re.sub(r"\blive\b", " ", text)
    text = re.sub(r"\bhd\b", " ", text)
    text = re.sub(r"\buhd\b", " ", text)
    text = re.sub(r"\b4k\b", " ", text)
    text = re.sub(r"\bespn\+?\b", " ", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text
