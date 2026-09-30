# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .product_category import SUPPLY_ZONES

# Labels of the records this module creates at runtime. Odoo translates those
# fields, but a record created from Python is not module data, so no .po file
# can reach it — we write both languages ourselves instead.
CONSUMPTION_PARENT = ('Laundry Consumption', 'استهلاك المغسلة')
ISSUE_PICKING_TYPE = ('Material Issue', 'صرف مواد')

ARABIC_LANGS = ('ar_001', 'ar')


def set_bilingual(record, field, english, arabic):
    """Write `english` and `arabic` into a translated field, whatever the
    language of the user who triggered the creation."""
    record.with_context(lang='en_US').write({field: english})
    installed = record.env['res.lang'].search([]).mapped('code')
    for lang in ARABIC_LANGS:
        if lang in installed:
            record.with_context(lang=lang).write({field: arabic})


class LaundryBranch(models.Model):
    _inherit = 'laundry.branch'

    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        copy=False,
        ondelete='restrict',
        help='Warehouse holding the supplies of this branch.',
    )
    store_location_id = fields.Many2one(
        'stock.location',
        string='Main Store',
        related='warehouse_id.lot_stock_id',
        store=True,
        readonly=True,
    )
    consumption_location_id = fields.Many2one(
        'stock.location',
        string='Consumption Location',
        copy=False,
        ondelete='restrict',
        help='Virtual location the materials consumed by this branch are '
             'moved to. What lands here is what the branch has used up.',
    )
    issue_picking_type_id = fields.Many2one(
        'stock.picking.type',
        string='Material Issue Operation',
        copy=False,
        ondelete='set null',
    )
    zone_location_ids = fields.One2many(
        'stock.location',
        'laundry_branch_id',
        string='Storage Zones',
        domain=[('laundry_zone_code', '!=', False)],
    )
    is_warehouse_ready = fields.Boolean(
        string='Warehouse Ready',
        compute='_compute_is_warehouse_ready',
    )

    auto_consume = fields.Boolean(
        string='Auto-issue Materials',
        help='Issue the materials of an order automatically, from the '
             'consumption norms, when the order reaches the stage below. '
             'Leave it off to issue materials by hand.',
    )
    auto_consume_state = fields.Selection([
        ('washing', 'Washing'),
        ('packing', 'Packing'),
        ('ready', 'Ready'),
        ('delivered', 'Delivered'),
    ], string='Issue Materials At', default='ready')

    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    supply_on_hand_value = fields.Monetary(
        string='Stock Value',
        compute='_compute_stock_figures',
        currency_field='currency_id',
    )
    supply_product_count = fields.Integer(
        string='Supplies in Stock',
        compute='_compute_stock_figures',
    )
    low_stock_count = fields.Integer(
        string='To Reorder',
        compute='_compute_stock_figures',
    )

    _sql_constraints = [
        ('warehouse_uniq', 'unique(warehouse_id)',
         'This warehouse is already used by another branch.'),
    ]

    # ── COMPUTES ────────────────────────────────────────────

    @api.depends('warehouse_id', 'consumption_location_id',
                 'issue_picking_type_id', 'zone_location_ids')
    def _compute_is_warehouse_ready(self):
        for branch in self:
            branch.is_warehouse_ready = bool(
                branch.warehouse_id
                and branch.consumption_location_id
                and branch.issue_picking_type_id
                and branch.zone_location_ids
            )

    def _compute_stock_figures(self):
        # Read through sudo: a branch manager reads these figures on the
        # branch form without being an inventory user.
        quant = self.env['stock.quant'].sudo()
        orderpoint = self.env['stock.warehouse.orderpoint'].sudo()
        for branch in self:
            branch.supply_on_hand_value = 0.0
            branch.supply_product_count = 0
            branch.low_stock_count = 0
            if not branch.warehouse_id:
                continue
            groups = quant._read_group(
                [('location_id', 'child_of',
                  branch.warehouse_id.view_location_id.id),
                 ('product_id.is_laundry_supply', '=', True)],
                groupby=['product_id'],
                aggregates=['quantity:sum'],
            )
            value = 0.0
            for product, quantity in groups:
                value += quantity * product.standard_price
            branch.supply_product_count = len(groups)
            branch.supply_on_hand_value = value
            branch.low_stock_count = orderpoint.search_count([
                ('warehouse_id', '=', branch.warehouse_id.id),
                ('qty_to_order', '>', 0),
            ])

    # ── WAREHOUSE PROVISIONING ──────────────────────────────

    def action_setup_warehouse(self):
        """Give the branch a warehouse laid out for a laundry, or top up the
        pieces that are missing. Safe to run again at any time."""
        for branch in self:
            branch._ensure_warehouse()
            branch._ensure_zones()
            branch._ensure_putaway_rules()
            branch._ensure_consumption_location()
            branch._ensure_issue_picking_type()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Warehouse ready'),
                'message': _('Storage zones, put-away rules and the material '
                             'issue operation are in place.'),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _branch_company(self):
        return self.warehouse_id.company_id or self.env.company

    def _ensure_warehouse(self):
        self.ensure_one()
        if self.warehouse_id:
            return self.warehouse_id
        Warehouse = self.env['stock.warehouse']
        company = self.env.company
        code = (self.code or 'WH').upper()[:5]
        warehouse = Warehouse.search([
            ('code', '=', code), ('company_id', '=', company.id),
        ], limit=1)
        if not warehouse:
            # A single-branch laundry keeps working in the warehouse Odoo
            # created with the company instead of getting a second, empty one.
            company_warehouses = Warehouse.search(
                [('company_id', '=', company.id)]
            )
            free = company_warehouses.filtered(lambda w: not w.laundry_branch_ids)
            if len(company_warehouses) == 1 and free:
                warehouse = free
                # Odoo names the first warehouse after the company. If nobody
                # ever changed it, it now belongs to a branch and says so.
                if warehouse.name in (company.name, 'My Company'):
                    warehouse.name = self._unique_warehouse_name(company)
        if not warehouse:
            warehouse = Warehouse.create({
                'name': self._unique_warehouse_name(company),
                'code': self._unique_warehouse_code(code, company),
                'company_id': company.id,
            })
        self.warehouse_id = warehouse
        warehouse.view_location_id.laundry_branch_id = self.id
        warehouse.lot_stock_id.laundry_branch_id = self.id
        return warehouse

    def _unique_warehouse_name(self, company):
        base_name = self.name or self.name_ar or self.code
        Warehouse = self.env['stock.warehouse']
        name, suffix = base_name, 1
        while Warehouse.search_count([
            ('name', '=', name), ('company_id', '=', company.id),
        ]):
            suffix += 1
            name = '%s %s' % (base_name, suffix)
        return name

    def _unique_warehouse_code(self, code, company):
        Warehouse = self.env['stock.warehouse']
        candidate, suffix = code, 1
        while Warehouse.search_count([
            ('code', '=', candidate), ('company_id', '=', company.id),
        ]):
            suffix += 1
            candidate = '%s%s' % (code[:4], suffix)
        return candidate

    def _ensure_zones(self):
        """Split the branch store into the zones a laundry actually uses."""
        self.ensure_one()
        Location = self.env['stock.location']
        parent = self.warehouse_id.lot_stock_id
        company = self._branch_company()
        for zone_code, _label, location_name in SUPPLY_ZONES:
            zone = Location.search([
                ('location_id', '=', parent.id),
                ('laundry_zone_code', '=', zone_code),
            ], limit=1)
            if not zone:
                # Adopt a location somebody already created by hand.
                zone = Location.search([
                    ('location_id', '=', parent.id),
                    ('name', '=', location_name),
                ], limit=1)
            values = {
                'laundry_zone_code': zone_code,
                'laundry_branch_id': self.id,
            }
            if zone:
                zone.write(values)
            else:
                Location.create(dict(
                    values,
                    name=location_name,
                    location_id=parent.id,
                    usage='internal',
                    company_id=company.id,
                ))

    def _ensure_putaway_rules(self):
        """Received goods walk themselves to the right zone."""
        self.ensure_one()
        Putaway = self.env['stock.putaway.rule']
        parent = self.warehouse_id.lot_stock_id
        company = self._branch_company()
        zones = {z.laundry_zone_code: z for z in self.zone_location_ids}
        categories = self.env['product.category'].search(
            [('laundry_zone_code', '!=', False)]
        )
        for category in categories:
            zone = zones.get(category.laundry_zone_code)
            if not zone:
                continue
            existing = Putaway.search([
                ('location_in_id', '=', parent.id),
                ('category_id', '=', category.id),
            ], limit=1)
            if existing:
                existing.location_out_id = zone.id
            else:
                Putaway.create({
                    'location_in_id': parent.id,
                    'location_out_id': zone.id,
                    'category_id': category.id,
                    'company_id': company.id,
                })

    def _ensure_consumption_location(self):
        self.ensure_one()
        if self.consumption_location_id:
            return self.consumption_location_id
        Location = self.env['stock.location']
        parent = self.env.ref(
            'laundry_stock.stock_location_laundry_consumption',
            raise_if_not_found=False,
        )
        if not parent:
            raise UserError(_(
                'The parent consumption location is missing. Upgrade the '
                'Laundry Inventory & Purchasing module and try again.'
            ))
        location = Location.search([
            ('location_id', '=', parent.id),
            ('laundry_branch_id', '=', self.id),
        ], limit=1)
        if not location:
            location = Location.create({
                'name': self._consumption_location_name(),
                'location_id': parent.id,
                'usage': 'production',
                'laundry_branch_id': self.id,
                'company_id': self._branch_company().id,
            })
        self.consumption_location_id = location
        return location

    def _consumption_location_name(self):
        """A location name Odoo never translates, so it carries both languages
        the way the storage zones do."""
        self.ensure_one()
        titles = list(dict.fromkeys(
            [t for t in (self.name, self.name_ar) if t]
        ))
        return '%s — %s' % (self.code, ' / '.join(titles) or self.code)

    def _ensure_issue_picking_type(self):
        self.ensure_one()
        if self.issue_picking_type_id:
            return self.issue_picking_type_id
        picking_type = self.env['stock.picking.type'].create({
            'name': ISSUE_PICKING_TYPE[0],
            'code': 'internal',
            'sequence_code': 'MI',
            'warehouse_id': self.warehouse_id.id,
            'company_id': self._branch_company().id,
            'default_location_src_id': self.warehouse_id.lot_stock_id.id,
            'default_location_dest_id': self.consumption_location_id.id,
            'create_backorder': 'never',
        })
        set_bilingual(picking_type, 'name', *ISSUE_PICKING_TYPE)
        self.issue_picking_type_id = picking_type
        return picking_type

    # ── ACTIONS ─────────────────────────────────────────────

    def _require_warehouse(self):
        self.ensure_one()
        if not self.warehouse_id:
            raise UserError(_(
                'Branch "%s" has no warehouse yet. Use "Set Up Warehouse" on '
                'the branch first.', self.display_name
            ))

    def action_view_stock(self):
        self._require_warehouse()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_quant'
        )
        action['domain'] = [
            ('location_id', 'child_of', self.warehouse_id.view_location_id.id),
            ('product_id.is_laundry_supply', '=', True),
        ]
        action['context'] = {'search_default_locationgroup': 1}
        return action

    def action_view_low_stock(self):
        self._require_warehouse()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_reordering'
        )
        action['domain'] = [('warehouse_id', '=', self.warehouse_id.id)]
        action['context'] = {'default_warehouse_id': self.warehouse_id.id}
        return action

    def action_view_issues(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_stock_issue'
        )
        action['domain'] = [('branch_id', '=', self.id)]
        action['context'] = {'default_branch_id': self.id}
        return action

    def action_view_purchase_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'laundry_stock.action_laundry_purchase_request'
        )
        action['domain'] = [('branch_id', '=', self.id)]
        action['context'] = {'default_branch_id': self.id}
        return action
