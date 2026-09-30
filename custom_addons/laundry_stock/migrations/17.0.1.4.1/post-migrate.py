# -*- coding: utf-8 -*-
"""Give the laundry roles the Odoo inventory rights their menus sit behind.

The groups belong to `laundry_base`, whose records are flagged `noupdate`, so a
data file in this module reaches them on a fresh install and never again. This
runs on the upgrade instead.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# group to extend -> groups it should imply
WIRING = {
    'laundry_base.group_laundry_manager': (
        'laundry_stock.group_laundry_storekeeper',
        'stock.group_stock_manager',
    ),
    'laundry_base.group_laundry_admin': (
        'laundry_stock.group_laundry_purchaser',
        'stock.group_stock_manager',
        'purchase.group_purchase_manager',
    ),
    'base.group_user': (
        'stock.group_stock_multi_locations',
    ),
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for target, implied in WIRING.items():
        group = env.ref(target, raise_if_not_found=False)
        if not group:
            continue
        missing = env['res.groups']
        for xmlid in implied:
            other = env.ref(xmlid, raise_if_not_found=False)
            if other and other not in group.implied_ids:
                missing |= other
        if missing:
            group.write({'implied_ids': [(4, g.id) for g in missing]})
            _logger.info('laundry_stock: %s now implies %s',
                         target, missing.mapped('name'))
