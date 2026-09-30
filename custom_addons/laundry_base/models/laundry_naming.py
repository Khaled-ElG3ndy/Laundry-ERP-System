# -*- coding: utf-8 -*-
"""One place that decides which of the two stored names a user reads.

These records keep the English name in `name` and the Arabic one in `name_ar`.
Whoever reads them should see their own language, so every `name_get` on such a
model goes through here instead of always preferring Arabic.
"""


def display_name_for(record):
    """The name of `record` in the language of whoever is reading it."""
    language = record.env.context.get('lang') or record.env.user.lang or 'en_US'
    if language.startswith('ar'):
        return record.name_ar or record.name
    return record.name or record.name_ar
