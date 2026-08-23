# -*- coding: utf-8 -*-
"""Explicit, opt-in import of the agreed price sheet.

Importing is a decision somebody makes, not a side effect of upgrading the
module. Once prices are in the database they are ordinary pricelist rules that
staff edit in the backend; this wizard only writes over them when told to, and
by default leaves anything hand-edited alone.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..data import price_book
from ..models.hotel_setup import CONTRACT_TIERS

_logger = logging.getLogger(__name__)


class HotelPriceImport(models.TransientModel):
    _name = 'hotel.price.import'
    _description = 'Import Hotel Contract Prices'

    mode = fields.Selection(
        selection=[
            ('skip_manual', 'Add missing prices, update untouched ones (recommended)'),
            ('create_only', 'Only add prices that are missing'),
            ('update_all', 'Overwrite every price from the sheet'),
        ],
        default='skip_manual',
        required=True,
        string='What should the import do?',
        help="'Add missing, update untouched' leaves alone any price that has "
             "been edited in the backend since it was last imported.\n"
             "'Only add missing' never changes an existing price.\n"
             "'Overwrite everything' discards manual edits and restores the "
             "sheet's prices.",
    )

    dry_run = fields.Boolean(
        string='Preview only',
        default=True,
        help="Work out exactly what would change and report it, without "
             "writing anything.",
    )

    rename_customers = fields.Boolean(
        string='Apply price-sheet customer names',
        default=False,
        help="Rename each matched customer to the name used in the price "
             "sheet. The original sheet name is always kept in the "
             "traceability field either way.",
    )

    state = fields.Selection(
        [('setup', 'Setup'), ('done', 'Done')], default='setup')
    summary = fields.Text(readonly=True)

    # -- engine --------------------------------------------------------------

    @api.model
    def run_import(self, mode='skip_manual', dry_run=False,
                   assign_pricelists=True, rename_customers=False):
        """Import the price book. Returns a summary dict.

        Idempotent by construction: products key on ``default_code``,
        pricelists on ``hotel_tier``, rules on (pricelist, product, min_qty)
        and partners on reviewed ids, so nothing is ever created twice.
        """
        setup = self.env['hotel.pricing.setup'].with_context(lang='en_US')
        counters = {'created': 0, 'updated': 0, 'skipped': 0, 'unchanged': 0,
                    'ambiguous': 0, 'failed': 0}
        notes = []

        pos_categories = setup._sync_pos_category()
        product_category = setup._sync_product_category()
        pricelists = setup._sync_pricelists()
        products = setup._sync_products(pos_categories, product_category)
        if not dry_run:
            setup._assign_product_categories(pos_categories, products)

        Item = self.env['product.pricelist.item']
        currency = self.env.company.currency_id

        for code, arabic, _english, prices in price_book.PRODUCTS:
            template = products.get(code)
            if not template:
                counters['failed'] += 1
                notes.append('%s %s: no product' % (code, arabic))
                continue

            for tier, price in prices.items():
                if tier not in CONTRACT_TIERS:
                    continue
                pricelist = pricelists.get(tier)
                if not pricelist:
                    counters['failed'] += 1
                    notes.append('%s: tier %s missing' % (code, tier))
                    continue
                try:
                    outcome, note = self._sync_one_rule(
                        Item, currency, pricelist, template, price, code,
                        arabic, tier, mode, dry_run)
                except Exception as error:              # pragma: no cover
                    counters['failed'] += 1
                    notes.append('%s/%s: %s' % (code, tier, error))
                    _logger.exception('Hotel price import failed for %s/%s',
                                      code, tier)
                    continue
                counters[outcome] += 1
                if note:
                    notes.append(note)

        customer_stats, customer_notes = setup._sync_customers(
            pricelists, assign_pricelists=assign_pricelists,
            rename=rename_customers, dry_run=dry_run)
        notes.extend(customer_notes)
        counters['ambiguous'] += customer_stats['ambiguous']
        counters['failed'] += customer_stats['failed']

        if not dry_run:
            setup._sync_pos_configs(pricelists, pos_categories)

        summary = dict(counters, customers=customer_stats, notes=notes)
        _logger.info('Hotel price import (mode=%s dry_run=%s): %s',
                     mode, dry_run, counters)
        return summary

    def _sync_one_rule(self, Item, currency, pricelist, template, price, code,
                       arabic, tier, mode, dry_run):
        """Create or update one fixed-price rule. Returns (outcome, note).

        The rule is written at template level. A ``fixed`` rule replaces the
        price outright rather than adding to it, so every variant of a hotel
        product resolves to the same contract price -- which is exactly what a
        sheet carrying one price per item means.
        """
        item = Item.search([
            ('pricelist_id', '=', pricelist.id),
            ('applied_on', '=', '1_product'),
            ('product_tmpl_id', '=', template.id),
            ('min_quantity', '=', 0),
        ], limit=1)

        if not item:
            if not dry_run:
                Item.create({
                    'pricelist_id': pricelist.id,
                    'applied_on': '1_product',
                    'product_tmpl_id': template.id,
                    'compute_price': 'fixed',
                    'fixed_price': price,
                    'min_quantity': 0,
                    'hotel_import_tracked': True,
                    'hotel_imported_price': price,
                })
            return 'created', None

        if mode == 'create_only':
            return 'skipped', None

        if mode == 'skip_manual' and item.hotel_price_edited:
            return 'skipped', _(
                '%(code)s %(name)s / %(tier)s: kept the edited price '
                '%(current).2f (sheet says %(sheet).2f)',
                code=code, name=arabic, tier=tier,
                current=item.fixed_price, sheet=price)

        same_price = currency.compare_amounts(item.fixed_price, price) == 0
        if same_price and item.compute_price == 'fixed' and item.hotel_import_tracked:
            return 'unchanged', None

        if not dry_run:
            item.write({
                'compute_price': 'fixed',
                'fixed_price': price,
                'hotel_import_tracked': True,
                'hotel_imported_price': price,
            })
        if same_price:
            # Only the tracking metadata was missing; the price itself stands.
            return 'unchanged', None
        return 'updated', _(
            '%(code)s %(name)s / %(tier)s: %(old).2f -> %(new).2f',
            code=code, name=arabic, tier=tier,
            old=item.fixed_price, new=price)

    # -- wizard --------------------------------------------------------------

    def action_run(self):
        self.ensure_one()
        if not self.env.user.has_group(
                'hosny_hotel_pos.group_hotel_contract_manager'):
            raise UserError(_(
                "Only a Hotel Contract Manager may import contract prices."))

        summary = self.run_import(
            mode=self.mode, dry_run=self.dry_run,
            assign_pricelists=True, rename_customers=self.rename_customers)

        headline = _(
            "%(what)s\n\n"
            "Prices  created %(created)d | updated %(updated)d | "
            "skipped %(skipped)d | unchanged %(unchanged)d | "
            "ambiguous %(ambiguous)d | failed %(failed)d\n"
            "Customers  created %(c_created)d | linked %(c_linked)d | "
            "renamed %(c_renamed)d | unchanged %(c_unchanged)d | "
            "ambiguous %(c_ambiguous)d | failed %(c_failed)d",
            what=(_("PREVIEW - nothing was written.") if self.dry_run
                  else _("Import applied.")),
            created=summary['created'], updated=summary['updated'],
            skipped=summary['skipped'], unchanged=summary['unchanged'],
            ambiguous=summary['ambiguous'], failed=summary['failed'],
            c_created=summary['customers']['created'],
            c_linked=summary['customers']['linked'],
            c_renamed=summary['customers']['renamed'],
            c_unchanged=summary['customers']['unchanged'],
            c_ambiguous=summary['customers']['ambiguous'],
            c_failed=summary['customers']['failed'],
        )
        detail = '\n'.join('  - %s' % note for note in summary['notes'][:200])
        if len(summary['notes']) > 200:
            detail += _('\n  ... and %d more', len(summary['notes']) - 200)

        self.write({
            'state': 'done',
            'summary': headline + (('\n\n' + detail) if detail else ''),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
