"""Tag normalisation (§4).

Tags are free text that has to behave like a controlled vocabulary, otherwise the same
idea arrives as "Tools", "tools " and "TOOLS" and autocomplete stops keeping them
together (§6.5). Normalising on the way in is what makes that work.

Trimming, lowercasing and deduplicating are corrections. Length and character set are
not: an over-long or illegal tag is rejected rather than mangled into something the
caller did not ask for.
"""

import re

MAX_TAGS = 20
MAX_LENGTH = 32
PATTERN = re.compile(r"^[a-z0-9-]+$")


def normalise(tags: list[str]) -> list[str]:
    """
    Trim, lowercase, drop blanks, deduplicate, sort.

    Search filters go through this too, not a lenient variant. Trimming and lowercasing
    are correctness rather than tidiness there, since stored tags are lowercase and
    `?tag=Tools` would otherwise match nothing. And a tag that could never have been
    stored cannot simply be dropped from a filter, because the filter is conjunctive:
    dropping it from ["tools", "hand tools"] would widen the search to everything
    tagged "tools" rather than correctly matching nothing. Rejecting says so out loud.

    Sorted because the storage layer keeps tags in a table with no ordering column, so
    reading them back has to impose one anyway. Doing it here means a tag list survives
    a round trip unchanged.

    Raises:
        ValueError: on a tag that is too long or contains anything outside [a-z0-9-],
            and on more than 20 tags. Pydantic turns this into a validation error,
            which the API reports as 422 (§6.0).
    """
    cleaned = sorted({tag.strip().lower() for tag in tags if tag.strip()})

    for tag in cleaned:
        if len(tag) > MAX_LENGTH:
            raise ValueError(f"tag longer than {MAX_LENGTH} characters: {tag!r}")
        if not PATTERN.match(tag):
            raise ValueError(f"tag may only contain [a-z0-9-]: {tag!r}")

    if len(cleaned) > MAX_TAGS:
        raise ValueError(f"more than {MAX_TAGS} tags: {len(cleaned)}")

    return cleaned
