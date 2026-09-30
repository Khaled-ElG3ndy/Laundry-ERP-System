# -*- coding: utf-8 -*-
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools.misc import format_date

from .product_category import SUPPLY_ZONES


class LaundryStockDashboard(models.AbstractModel):
    """Everything the inventory dashboard shows, in one round trip."""
    _name = 'laundry.stock.dashboard'
    _description = 'Laundry Inventory Dashboard'

    # ── ENTRY POINT ─────────────────────────────────────────

    @api.model
    def get_dashboard_data(self, branch_id=None, months=6):
        if not self.env.user.has_group('laundry_stock.group_laundry_storekeeper'):
            raise AccessError(_(
                'The inventory dashboard is for the store keepers and the '
                'branch managers.'
            ))
        branches = self.env['laundry.branch'].search(
            [('warehouse_id', '!=', False)]
        )
        selected = branches.filtered(lambda b: b.id == branch_id) or branches
        company = self.env.company

        return {
            'branches': [{'id': b.id, 'name': b.display_name} for b in branches],
            'branch_id': branch_id if branch_id in branches.ids else None,
            'currency': {
                'symbol': company.currency_id.symbol,
                'position': company.currency_id.position,
                'decimals': company.currency_id.decimal_places,
            },
            'kpis': self._kpis(selected),
            'monthly': self._monthly_consumption(selected, months),
            'zones': self._zone_breakdown(selected),
            'to_reorder': self._to_reorder(selected),
            'top_materials': self._top_materials(selected),
            'recent': self._recent_issues(selected),
            'ready': bool(selected.filtered('is_warehouse_ready')),
        }

    # ── HELPERS ─────────────────────────────────────────────

    def _locations(self, branches):
        return branches.mapped('warehouse_id.view_location_id')

    def _quants(self, branches):
        locations = self._locations(branches)
        if not locations:
            return self.env['stock.quant']
        return self.env['stock.quant'].sudo().search([
            ('location_id', 'child_of', locations.ids),
            ('location_id.usage', '=', 'internal'),
            ('product_id.is_laundry_supply', '=', True),
        ])

    def _on_hand_by_product(self, branches):
        totals = {}
        for quant in self._quants(branches):
            totals[quant.product_id] = totals.get(quant.product_id, 0.0) + quant.quantity
        return totals

    @staticmethod
    def _value(product, quantity):
        return quantity * (product.standard_price or 0.0)

    # ── KPIs ────────────────────────────────────────────────

    def _kpis(self, branches):
        on_hand = self._on_hand_by_product(branches)
        stock_value = sum(self._value(p, q) for p, q in on_hand.items())

        reorder = self._to_reorder(branches)
        out_of_stock = sum(
            1 for product, quantity in on_hand.items() if quantity <= 0
        )

        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        consumed = self.env['laundry.consumption.report'].sudo().search([
            ('date', '>=', fields.Datetime.to_datetime(month_start)),
            ('branch_id', 'in', branches.ids),
        ])

        to_approve = self.env['laundry.purchase.request'].sudo().search_count([
            ('state', '=', 'to_approve'),
            ('branch_id', 'in', branches.ids),
        ])
        incoming = self.env['stock.picking'].sudo().search_count([
            ('picking_type_id', 'in', branches.mapped('warehouse_id.in_type_id').ids),
            ('state', 'not in', ('done', 'cancel')),
        ])
        return {
            'stock_value': stock_value,
            'supply_count': len(on_hand),
            'to_reorder': len(reorder),
            'out_of_stock': out_of_stock,
            'month_cost': sum(consumed.mapped('cost')),
            'month_documents': len(set(consumed.mapped('issue_id.id'))),
            'to_approve': to_approve,
            'incoming': incoming,
        }

    # ── CONSUMPTION OVER TIME ───────────────────────────────

    def _monthly_consumption(self, branches, months):
        today = fields.Date.context_today(self)
        first = today.replace(day=1) - relativedelta(months=months - 1)
        rows = self.env['laundry.consumption.report'].sudo()._read_group(
            [('date', '>=', fields.Datetime.to_datetime(first)),
             ('branch_id', 'in', branches.ids)],
            groupby=['date:month'],
            aggregates=['cost:sum'],
        )
        found = {}
        for period, cost in rows:
            if period:
                found[date(period.year, period.month, 1)] = cost or 0.0

        series = []
        for offset in range(months):
            moment = first + relativedelta(months=offset)
            series.append({
                'label': format_date(self.env, moment, date_format='MMM'),
                'full_label': format_date(self.env, moment, date_format='MMMM yyyy'),
                'cost': found.get(moment, 0.0),
            })
        return series

    # ── ZONES ───────────────────────────────────────────────

    def _zone_breakdown(self, branches):
        selection = dict(self.env['product.category'].fields_get(
            ['laundry_zone_code'])['laundry_zone_code']['selection'])
        totals = {code: {'value': 0.0, 'qty': 0.0, 'items': set()}
                  for code, _label, _name in SUPPLY_ZONES}
        for quant in self._quants(branches):
            code = (quant.location_id.laundry_zone_code
                    or quant.product_id.categ_id.laundry_zone_code
                    or 'OTHER')
            entry = totals.setdefault(
                code, {'value': 0.0, 'qty': 0.0, 'items': set()})
            entry['value'] += self._value(quant.product_id, quant.quantity)
            entry['qty'] += quant.quantity
            entry['items'].add(quant.product_id.id)

        zones = []
        for code, entry in totals.items():
            zones.append({
                'code': code,
                'label': selection.get(code) or _('Unzoned'),
                'value': entry['value'],
                'items': len(entry['items']),
            })
        # Every zone stays on the board, even an empty one: the layout is the
        # layout of the store, not of today's stock.
        return sorted(zones, key=lambda zone: zone['value'], reverse=True)

    # ── WHAT TO BUY ─────────────────────────────────────────

    def _to_reorder(self, branches):
        """Supplies whose on-hand fell under the minimum set on the product."""
        on_hand = self._on_hand_by_product(branches)
        supplies = self.env['product.product'].sudo().search([
            ('is_laundry_supply', '=', True),
            ('type', '=', 'product'),
            ('laundry_min_qty', '>', 0),
        ])
        rows = []
        for product in supplies:
            quantity = on_hand.get(product, 0.0)
            if quantity >= product.laundry_min_qty:
                continue
            target = max(product.laundry_max_qty, product.laundry_min_qty)
            rows.append({
                'id': product.id,
                'name': product.display_name,
                'uom': product.uom_id.display_name,
                'on_hand': quantity,
                'minimum': product.laundry_min_qty,
                'suggested': max(target - quantity, 0.0),
                'share': min(quantity / product.laundry_min_qty, 1.0)
                         if product.laundry_min_qty else 0.0,
            })
        return sorted(rows, key=lambda row: row['share'])[:8]

    # ── WHAT WE USE MOST ────────────────────────────────────

    def _top_materials(self, branches, limit=5):
        today = fields.Date.context_today(self)
        start = today.replace(day=1) - relativedelta(months=2)
        rows = self.env['laundry.consumption.report'].sudo()._read_group(
            [('date', '>=', fields.Datetime.to_datetime(start)),
             ('branch_id', 'in', branches.ids)],
            groupby=['product_id'],
            aggregates=['cost:sum', 'qty:sum'],
        )
        materials = [{
            'id': product.id,
            'name': product.display_name,
            'uom': product.uom_id.display_name,
            'cost': cost or 0.0,
            'qty': qty or 0.0,
        } for product, cost, qty in rows if (cost or 0.0) > 0]
        return sorted(materials, key=lambda row: row['cost'], reverse=True)[:limit]

    # ── LAST MOVEMENTS ──────────────────────────────────────

    def _recent_issues(self, branches, limit=6):
        issues = self.env['laundry.stock.issue'].sudo().search(
            [('branch_id', 'in', branches.ids), ('state', '=', 'done')],
            limit=limit, order='date desc, id desc',
        )
        descriptions = self.env['laundry.stock.issue'].fields_get(
            ['purpose', 'operation_type'])
        purposes = dict(descriptions['purpose']['selection'])
        operations = dict(descriptions['operation_type']['selection'])
        return [{
            'id': issue.id,
            'name': issue.name,
            'branch': issue.branch_id.display_name,
            'date': format_date(self.env, issue.date),
            'purpose': purposes.get(issue.purpose, ''),
            'operation': operations.get(issue.operation_type, ''),
            'is_return': issue.operation_type == 'return',
            'cost': issue.total_cost,
            'lines': len(issue.line_ids),
        } for issue in issues]
