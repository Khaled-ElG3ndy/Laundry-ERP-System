# -*- coding: utf-8 -*-
"""Rename the consumption locations to the bilingual form the zones use.

`stock.location.name` is not a translated field, so a name written in one
language only leaves the other language's reader guessing.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    branches = env['laundry.branch'].with_context(active_test=False).search(
        [('consumption_location_id', '!=', False)])
    for branch in branches:
        wanted = branch._consumption_location_name()
        if branch.consumption_location_id.name != wanted:
            branch.consumption_location_id.name = wanted
            _logger.info('laundry_stock: consumption location renamed to %s', wanted)
