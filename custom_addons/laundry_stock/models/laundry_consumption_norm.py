# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LaundryConsumptionNorm(models.Model):
    """How much of a supply one piece — or one order — is expected to use.

    Norms are matched from the least specific to the most specific: a norm
    without a service, a category or a branch applies everywhere, and any
    norm that names one of them wins over it for the same product.
    """
    _name = 'laundry.consumption.norm'
    _description = 'Material Consumption Norm'
    _order = 'sequence, id'

    name = fields.Char(compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    service_type_id = fields.Many2one(
        'laundry.service.type',
        string='Service',
        ondelete='cascade',
        index=True,
        help='Leave empty to apply to every service.',
    )
    item_category_id = fields.Many2one(
        'laundry.item.category',
        string='Item Category',
        ondelete='cascade',
        index=True,
        help='Leave empty to apply to every item category.',
    )
    branch_id = fields.Many2one(
        'laundry.branch',
        string='Branch',
        ondelete='cascade',
        index=True,
        help='Leave empty to apply to every branch.',
    )

    # The counter sells a garment with a service variant; the back office
    # writes orders with a service type. Norms speak both languages.
    service_value_id = fields.Many2one(
        'product.attribute.value',
        string='POS Service',
        ondelete='cascade',
        index=True,
        domain="[('attribute_id.is_laundry_service', '=', True)]",
        help='Service the garment was sold with at the counter. Leave empty '
             'to apply to every service.',
    )
    product_categ_id = fields.Many2one(
        'product.category',
        string='Sales Category',
        ondelete='cascade',
        index=True,
        help='Category of the item sold — clothes, linen, hotel. It covers '
             'its sub-categories too. Leave empty to apply to all of them.',
    )
    garment_product_id = fields.Many2one(
        'product.product',
        string='Sold Item',
        ondelete='cascade',
        index=True,
        help='One specific item sold at the counter. Leave empty to apply to '
             'every item of the category.',
    )

    product_id = fields.Many2one(
        'product.product',
        string='Supply',
        required=True,
        index=True,
        domain=[('is_laundry_supply', '=', True)],
        ondelete='cascade',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit',
        required=True,
        compute='_compute_product_uom_id',
        store=True,
        readonly=False,
        precompute=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        # A dose is a rate, not a stock quantity: 12 grams of detergent per
        # kilogram is 0.012, which the two decimals of a stock quantity would
        # flatten to nothing.
        digits=(16, 6),
    )
    basis = fields.Selection([
        ('piece', 'Per Piece'),
        ('kg', 'Per Kg'),
        ('order', 'Per Order'),
    ], string='Basis', required=True, default='piece')

    is_excluded = fields.Boolean(
        string='Not Used',
        help='The supply is not used in this scope at all — a blanket takes '
             'no hanger. It cancels a more general norm for the same supply.',
    )
    note = fields.Char(string='Note')
    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for norm in self:
            norm.product_uom_id = norm.product_id.uom_id

    @api.depends('product_id', 'service_type_id', 'item_category_id',
                 'branch_id', 'basis', 'service_value_id', 'product_categ_id',
                 'garment_product_id')
    def _compute_name(self):
        basis_labels = dict(self._fields['basis'].selection)
        for norm in self:
            scope = ' / '.join(filter(None, [
                norm.service_value_id.display_name,
                norm.garment_product_id.display_name,
                norm.product_categ_id.display_name,
                norm.service_type_id.display_name,
                norm.item_category_id.display_name,
                norm.branch_id.display_name,
            ])) or _('All services')
            norm.name = '%s — %s (%s)' % (
                norm.product_id.display_name or '',
                scope,
                basis_labels.get(norm.basis, ''),
            )

    @api.constrains('qty', 'is_excluded')
    def _check_qty(self):
        for norm in self:
            if norm.qty <= 0 and not norm.is_excluded:
                raise ValidationError(_('The norm quantity must be above zero.'))

    # ── MATCHING ────────────────────────────────────────────

    def _specificity(self):
        """The more a norm names, the more it wins."""
        self.ensure_one()
        return (
            (8 if self.branch_id else 0)
            + (4 if self.garment_product_id else 0)
            + (2 if self.service_type_id or self.service_value_id else 0)
            + (1 if self.item_category_id or self.product_categ_id else 0)
        )

    @api.model
    def _match(self, service_type=None, item_category=None, branch=None):
        """Applicable norms, keeping only the most specific one per supply."""
        domain = [
            ('service_value_id', '=', False),
            ('garment_product_id', '=', False),
            ('product_categ_id', '=', False),
            '|', ('service_type_id', '=', False),
            ('service_type_id', '=', service_type.id if service_type else False),
            '|', ('item_category_id', '=', False),
            ('item_category_id', '=', item_category.id if item_category else False),
            '|', ('branch_id', '=', False),
            ('branch_id', '=', branch.id if branch else False),
        ]
        best = {}
        for norm in self.search(domain):
            current = best.get(norm.product_id)
            if not current or norm._specificity() > current._specificity():
                best[norm.product_id] = norm
        return self.browse([norm.id for norm in best.values()])

    @api.model
    def _quantities_for_order(self, order):
        """{product: (qty, uom)} a laundry order is expected to consume."""
        needs = {}

        def add(product, qty, uom):
            if qty <= 0:
                return
            if product in needs:
                previous_qty, previous_uom = needs[product]
                qty = previous_qty + uom._compute_quantity(qty, previous_uom)
                uom = previous_uom
            needs[product] = (qty, uom)

        once_per_order = self.browse()
        for line in order.order_line_ids:
            norms = self._match(
                service_type=line.service_type_id,
                item_category=line.item_category_id,
                branch=order.branch_id,
            )
            for norm in norms:
                if norm.is_excluded:
                    continue
                if norm.basis == 'piece':
                    add(norm.product_id, norm.qty * line.qty, norm.product_uom_id)
                elif norm.basis == 'kg':
                    weight = line.qty * (line.item_category_id.avg_weight_kg or 0.0)
                    add(norm.product_id, norm.qty * weight, norm.product_uom_id)
                else:
                    once_per_order |= norm

        once_per_order |= self._match(branch=order.branch_id).filtered(
            lambda n: n.basis == 'order' and not n.is_excluded
        )
        for norm in once_per_order:
            add(norm.product_id, norm.qty, norm.product_uom_id)
        return needs

    # ── MATCHING AGAINST WHAT THE COUNTER SOLD ──────────────

    @api.model
    def _match_pos(self, product=None, service_value=None, branch=None):
        """Applicable norms for one item sold with one service."""
        categories = self.env['product.category']
        if product:
            categories = categories.search([('id', 'parent_of', product.categ_id.id)])
        domain = [
            ('service_type_id', '=', False),
            ('item_category_id', '=', False),
            '|', ('garment_product_id', '=', False),
            ('garment_product_id', '=', product.id if product else False),
            '|', ('product_categ_id', '=', False),
            ('product_categ_id', 'in', categories.ids or [0]),
            '|', ('service_value_id', '=', False),
            ('service_value_id', '=', service_value.id if service_value else False),
            '|', ('branch_id', '=', False),
            ('branch_id', '=', branch.id if branch else False),
        ]
        best = {}
        for norm in self.search(domain):
            current = best.get(norm.product_id)
            if not current or norm._specificity() > current._specificity():
                best[norm.product_id] = norm
        return self.browse([norm.id for norm in best.values()])

    @api.model
    def _quantities_for_pos_lines(self, lines, branch=None):
        """{product: (qty, uom)} the sold lines are expected to have consumed.

        Returns the needs and the items skipped because a per-kilogram norm
        matched an item with no weight on its product record.
        """
        needs, missing_weight = {}, set()

        def add(product, qty, uom):
            if qty <= 0:
                return
            if product in needs:
                previous_qty, previous_uom = needs[product]
                qty = previous_qty + uom._compute_quantity(qty, previous_uom)
                uom = previous_uom
            needs[product] = (qty, uom)

        service_attribute = self.env['product.attribute']._laundry_service_attribute()
        once_per_order = self.browse()
        for line in lines:
            values = line.product_id.product_template_attribute_value_ids
            service_value = values.filtered(
                lambda v: v.attribute_id == service_attribute
            ).product_attribute_value_id[:1]
            norms = self._match_pos(
                product=line.product_id,
                service_value=service_value,
                branch=branch,
            )
            for norm in norms:
                if norm.is_excluded:
                    continue
                if norm.basis == 'piece':
                    add(norm.product_id, norm.qty * line.qty, norm.product_uom_id)
                elif norm.basis == 'kg':
                    weight = line.product_id.weight
                    if not weight:
                        missing_weight.add(line.product_id.display_name)
                        continue
                    add(norm.product_id, norm.qty * line.qty * weight,
                        norm.product_uom_id)
                else:
                    once_per_order |= norm

        for norm in once_per_order:
            add(norm.product_id, norm.qty * len(lines.mapped('order_id')),
                norm.product_uom_id)
        return needs, sorted(missing_weight)

    # ── STARTER NORMS ───────────────────────────────────────

    # Per piece, for one garment sold with one service. Every figure is a
    # starting point the laundry is expected to correct from its own usage.
    STARTER_NORMS = [
        # service keyword, supply xml id, qty
        ('iron', 'supply_hanger_wire', 1.0),
        ('iron', 'supply_shirt_bag', 1.0),
        ('wash', 'supply_detergent_powder', 0.02),
        ('wash', 'supply_softener', 0.01),
        ('wash', 'supply_hanger_wire', 1.0),
        ('wash', 'supply_shirt_bag', 1.0),
        ('deep', 'supply_detergent_powder', 0.03),
        ('deep', 'supply_spotting_chemical', 0.005),
        ('deep', 'supply_hanger_wire', 1.0),
        ('deep', 'supply_shirt_bag', 1.0),
    ]
    # Bedding goes through a machine and comes back in a bag, not on a hanger.
    STARTER_BEDDING = [
        # service keywords, supply xml id, qty, excluded
        (('wash', 'deep'), 'supply_detergent_powder', 0.15, False),
        (('wash', 'deep'), 'supply_softener', 0.05, False),
        (('iron', 'wash', 'deep'), 'supply_carry_bag', 1.0, False),
        (('iron', 'wash', 'deep'), 'supply_hanger_wire', 0.0, True),
        (('iron', 'wash', 'deep'), 'supply_shirt_bag', 0.0, True),
    ]
    BEDDING_CATEGORY_NAMES = ('المفروشات', 'Bedding', 'Linen')

    @api.model
    def _service_keyword(self, value_name):
        """Read a service value name in either language."""
        name = (value_name or '').lower()
        if 'تنظيف' in name or 'deep' in name or 'dry' in name:
            return 'deep'
        if 'غسيل' in name or 'wash' in name:
            return 'wash'
        if 'كوي' in name or 'iron' in name or 'press' in name:
            return 'iron'
        return None

    def action_seed_starter_norms(self):
        """Create a first set of norms from the services the counter sells.

        Nothing is overwritten: a service that already has norms is left alone.
        """
        attribute = self.env['product.attribute']._laundry_service_attribute()
        if not attribute:
            raise UserError(_(
                'No service attribute was found. Tick "Laundry Service '
                'Attribute" on the product attribute that carries the service.'
            ))
        bedding = self.env['product.category'].search(
            [('name', 'in', list(self.BEDDING_CATEGORY_NAMES))], limit=1
        )
        created = self.browse()
        for value in attribute.value_ids:
            if self.search_count([('service_value_id', '=', value.id)]):
                continue
            keyword = self._service_keyword(value.name)
            if not keyword:
                continue
            for service_keyword, supply, qty in self.STARTER_NORMS:
                if service_keyword != keyword:
                    continue
                product = self.env.ref(
                    'laundry_stock.%s' % supply, raise_if_not_found=False)
                if not product:
                    continue
                created |= self.create({
                    'service_value_id': value.id,
                    'product_id': product.product_variant_id.id,
                    'qty': qty,
                    'basis': 'piece',
                    'note': _('Starting point — correct it from your own usage.'),
                })
            if bedding:
                for keywords, supply, qty, excluded in self.STARTER_BEDDING:
                    if keyword not in keywords:
                        continue
                    product = self.env.ref(
                        'laundry_stock.%s' % supply, raise_if_not_found=False)
                    if not product:
                        continue
                    created |= self.create({
                        'service_value_id': value.id,
                        'product_categ_id': bedding.id,
                        'product_id': product.product_variant_id.id,
                        'qty': qty,
                        'basis': 'piece',
                        'is_excluded': excluded,
                        'note': _('Starting point — correct it from your own usage.'),
                    })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Starter norms loaded'),
                'message': _('%s norm(s) created. Review the quantities '
                             'against what your branches really use.',
                             len(created)),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
