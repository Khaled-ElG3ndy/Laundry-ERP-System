# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Give the branches that already exist a warehouse laid out for them."""
    branches = env['laundry.branch'].with_context(active_test=False).search([])
    for branch in branches:
        try:
            with env.cr.savepoint():
                branch.action_setup_warehouse()
                _logger.info(
                    'laundry_stock: branch %s set up on warehouse %s',
                    branch.code, branch.warehouse_id.code,
                )
        except Exception as error:  # noqa: BLE001 - installation must not fail
            _logger.warning(
                'laundry_stock: could not set up the warehouse of branch %s: %s',
                branch.code, error,
            )
