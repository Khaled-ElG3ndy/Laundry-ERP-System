# -*- coding: utf-8 -*-
"""Put the laundry app away: its screens now live in Odoo's own Inventory app.

Only the menu is switched off — every model, record and report stays exactly
where it is, because `laundry_stock` is built on them. Turning the app back on
is one tick in Settings > Technical > User Interface > Menu Items.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    root = env.ref('laundry_base.menu_laundry_root', raise_if_not_found=False)
    if root and root.active:
        root.active = False
        _logger.info('laundry_stock: the laundry app menu is now hidden; '
                     'its screens live under Inventory')
