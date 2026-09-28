"""The cache key a stored summary is filed under.

A summary is a pure function of its input, so there is no reason to spend GPU
time twice on the same one. Storage belongs to the backend -- a
``technology_summary`` row, not Redis: a cache that empties on restart means
regenerating a person's twelve technologies the moment they open the screen,
which on a laptop GPU is tens of seconds of blank card.
"""

import hashlib

from llm.contracts import FactPack, canonical_fact_pack_json


def summary_cache_key(
    user_id: str,
    fact_pack: FactPack,
    *,
    prompt_version: str,
    model: str,
) -> str:
    """Hash everything the summary depends on.

    ``user_id`` is an argument rather than a Fact Pack field: the key has to
    separate two people looking at the same technology, but the model is never
    given a value that points at a person.

    ``prompt_version`` and ``model`` belong in the key. Without them, editing
    the prompt leaves every summary written by the old one in place, and the
    screen shows text no current prompt would produce.
    """

    technology = fact_pack.technology
    parts = (
        f"user_id={user_id}",
        f"tech_id={technology.tech_id}",
        f"registry_version={technology.registry_version}",
        f"personal_level={technology.personal_level.value}",
        f"repository_level={technology.repository_level.value}",
        f"authorship={fact_pack.authorship.value}",
        f"prompt_version={prompt_version}",
        f"model={model}",
        f"fact_pack={canonical_fact_pack_json(fact_pack)}",
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
