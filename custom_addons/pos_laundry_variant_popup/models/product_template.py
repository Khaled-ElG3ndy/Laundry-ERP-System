# -*- coding: utf-8 -*-

from collections import defaultdict

from odoo import Command, api, fields, models, _


SERVICE_ATTRIBUTE_NAME = 'Service Type'
LEGACY_SERVICE_ATTRIBUTES = ('NORMAL', 'URGENT')
STAIN_ATTRIBUTE_NONE_LABELS = {
    'Removing Stains': 'None',
    'ازاله البقع': 'بدون',
    'إزالة البقع': 'بدون',
}
LAUNDRY_ADDON_CODES = (
    'stain_removal',
    'mirzam_type',
    'starch_type',
)
# Add-ons seeded onto the headwear products the shop already sells. After the
# one-time seeding the assignment lives in ``laundry_addon_attribute_ids``, so
# renaming a product no longer silently drops its add-ons.
HEADWEAR_ADDON_CODES = ('mirzam_type', 'starch_type')
STAIN_REMOVAL_PRICES = {
    'pos_laundry_variant_popup.addon_stain_s': 1.0,
    'pos_laundry_variant_popup.addon_stain_m': 2.0,
    'pos_laundry_variant_popup.addon_stain_l': 3.0,
}
HEADWEAR_NAMES = {
    'ghutra',
    'shemagh',
    'شماغ',
    'غترة',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    has_legacy_laundry_service_attributes = fields.Boolean(
        compute='_compute_has_legacy_laundry_service_attributes',
    )
    laundry_addon_attribute_ids = fields.Many2many(
        'product.attribute',
        'product_template_laundry_addon_rel',
        'template_id',
        'attribute_id',
        string='Laundry Add-ons',
        domain="[('laundry_addon_code', '!=', False), ('laundry_addon_scope', '=', 'template')]",
        help='Optional laundry add-on groups offered for this product in the POS.',
    )
    laundry_addon_seeded = fields.Boolean(
        string='Laundry Add-ons Seeded',
        default=False,
        copy=False,
        help='Technical flag: the product already went through the one-time '
             'headwear add-on seeding, so manual changes are never overwritten.',
    )

    @api.depends('attribute_line_ids.attribute_id.name')
    def _compute_has_legacy_laundry_service_attributes(self):
        for template in self:
            attribute_names = set(template.attribute_line_ids.mapped('attribute_id.name'))
            template.has_legacy_laundry_service_attributes = all(
                name in attribute_names for name in LEGACY_SERVICE_ATTRIBUTES
            )

    def _get_sorted_ptavs(self, ptavs):
        return ptavs.sorted(
            key=lambda ptav: (
                ptav.product_attribute_value_id.sequence,
                ptav.product_attribute_value_id.id,
                ptav.id,
            )
        )

    def _get_or_create_service_attribute(self):
        service_attribute = self.env['product.attribute'].search(
            [('name', '=', SERVICE_ATTRIBUTE_NAME)],
            limit=1,
        )
        if not service_attribute:
            service_attribute = self.env['product.attribute'].create({
                'name': SERVICE_ATTRIBUTE_NAME,
                'display_type': 'radio',
                'create_variant': 'always',
            })
        else:
            updates = {}
            if service_attribute.display_type != 'radio':
                updates['display_type'] = 'radio'
            if service_attribute.create_variant != 'always':
                updates['create_variant'] = 'always'
            if updates:
                service_attribute.write(updates)
        return service_attribute

    def _get_or_create_attribute_value(self, attribute, name, sequence):
        value = self.env['product.attribute.value'].search([
            ('attribute_id', '=', attribute.id),
            ('name', '=', name),
        ], limit=1)
        if not value:
            value = self.env['product.attribute.value'].create({
                'attribute_id': attribute.id,
                'name': name,
                'sequence': sequence,
            })
        elif value.sequence != sequence:
            value.sequence = sequence
        return value

    def _get_or_create_optional_attribute_clone(self, attribute):
        optional_attribute = self.env['product.attribute'].search([
            ('name', '=', attribute.name),
            ('create_variant', '=', 'no_variant'),
        ], limit=1)
        if not optional_attribute:
            optional_attribute = self.env['product.attribute'].create({
                'name': attribute.name,
                'display_type': attribute.display_type,
                'create_variant': 'no_variant',
                'sequence': attribute.sequence,
            })
        else:
            updates = {}
            if optional_attribute.display_type != attribute.display_type:
                updates['display_type'] = attribute.display_type
            if optional_attribute.sequence != attribute.sequence:
                updates['sequence'] = attribute.sequence
            if updates:
                optional_attribute.write(updates)
        return optional_attribute

    def _ensure_none_value(self, line):
        none_label = STAIN_ATTRIBUTE_NONE_LABELS.get(line.attribute_id.name)
        if not none_label:
            return

        existing_none_ptav = line.product_template_value_ids.filtered(
            lambda ptav: ptav.name == none_label
        )[:1]
        if existing_none_ptav:
            if abs(existing_none_ptav.price_extra) >= 1e-9:
                existing_none_ptav.price_extra = 0.0
            return

        first_sequence = min(line.value_ids.mapped('sequence') or [0]) - 1
        none_value = self._get_or_create_attribute_value(
            line.attribute_id,
            none_label,
            first_sequence,
        )
        if none_value not in line.value_ids:
            line.write({'value_ids': [Command.link(none_value.id)]})

        none_ptav = line.product_template_value_ids.filtered(
            lambda ptav: ptav.product_attribute_value_id == none_value
        )[:1]
        if none_ptav and abs(none_ptav.price_extra) >= 1e-9:
            none_ptav.price_extra = 0.0

    def _convert_line_to_optional_attribute(self, template, line):
        if line.attribute_id.create_variant == 'no_variant':
            template._ensure_none_value(line)
            return

        optional_attribute = template._get_or_create_optional_attribute_clone(
            line.attribute_id
        )
        source_ptavs = template._get_sorted_ptavs(line.product_template_value_ids)
        optional_values = self.env['product.attribute.value']
        price_by_name = {}

        for ptav in source_ptavs:
            optional_values |= template._get_or_create_attribute_value(
                optional_attribute,
                ptav.name,
                ptav.product_attribute_value_id.sequence,
            )
            price_by_name[ptav.name] = ptav.price_extra

        optional_line = template.attribute_line_ids.filtered(
            lambda current_line: current_line.attribute_id == optional_attribute
        )[:1]
        if optional_line:
            optional_line.write({
                'sequence': line.sequence,
                'value_ids': [Command.set(optional_values.ids)],
            })
        else:
            template.write({
                'attribute_line_ids': [Command.create({
                    'attribute_id': optional_attribute.id,
                    'sequence': line.sequence,
                    'value_ids': [Command.set(optional_values.ids)],
                })]
            })
            optional_line = template.attribute_line_ids.filtered(
                lambda current_line: current_line.attribute_id == optional_attribute
            )[:1]

        for ptav in optional_line.product_template_value_ids:
            target_price = price_by_name.get(ptav.name, 0.0)
            if abs(ptav.price_extra - target_price) >= 1e-9:
                ptav.price_extra = target_price

        template.write({'attribute_line_ids': [Command.unlink(line.id)]})
        template._ensure_none_value(optional_line)

    def _normalize_laundry_attributes(self):
        self = self.with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
        )
        for template in self:
            attribute_by_name = {
                line.attribute_id.name: line
                for line in template.attribute_line_ids
            }
            normal_line = attribute_by_name.get('NORMAL')
            urgent_line = attribute_by_name.get('URGENT')
            if not (normal_line and urgent_line):
                continue

            optional_lines = template.attribute_line_ids.filtered(
                lambda line: line not in (normal_line, urgent_line)
            )
            for optional_line in optional_lines:
                template._convert_line_to_optional_attribute(template, optional_line)

            template.invalidate_recordset()
            attribute_by_name = {
                line.attribute_id.name: line
                for line in template.attribute_line_ids
            }
            normal_line = attribute_by_name.get('NORMAL')
            urgent_line = attribute_by_name.get('URGENT')
            if not (normal_line and urgent_line):
                continue

            service_attribute = template._get_or_create_service_attribute()
            service_specs = []
            for line in (normal_line, urgent_line):
                for index, ptav in enumerate(template._get_sorted_ptavs(line.product_template_value_ids)):
                    service_specs.append({
                        'name': ptav.name,
                        'price_extra': ptav.price_extra,
                        'sequence': len(service_specs) + index + 1,
                    })

            service_values = self.env['product.attribute.value']
            for sequence, spec in enumerate(service_specs, start=1):
                service_values |= template._get_or_create_attribute_value(
                    service_attribute,
                    spec['name'],
                    sequence,
                )

            service_line = template.attribute_line_ids.filtered(
                lambda line: line.attribute_id == service_attribute
            )[:1]
            line_sequence = min(normal_line.sequence, urgent_line.sequence)
            if service_line:
                service_line.write({
                    'sequence': line_sequence,
                    'value_ids': [Command.set(service_values.ids)],
                })
            else:
                template.write({
                    'attribute_line_ids': [Command.create({
                        'attribute_id': service_attribute.id,
                        'sequence': line_sequence,
                        'value_ids': [Command.set(service_values.ids)],
                    })]
                })
                service_line = template.attribute_line_ids.filtered(
                    lambda line: line.attribute_id == service_attribute
                )[:1]

            price_by_name = {
                spec['name']: spec['price_extra']
                for spec in service_specs
            }
            for ptav in service_line.product_template_value_ids:
                target_price = price_by_name.get(ptav.name, 0.0)
                if abs(ptav.price_extra - target_price) >= 1e-9:
                    ptav.price_extra = target_price

            template.write({
                'attribute_line_ids': [
                    Command.unlink(normal_line.id),
                    Command.unlink(urgent_line.id),
                ]
            })

            template._create_variant_ids()

    def _is_laundry_headwear_template(self):
        self.ensure_one()
        names = set()
        for language_code in ('en_US', 'ar_001', 'ar'):
            name = self.with_context(lang=language_code).name
            if name:
                names.add(str(name).strip().casefold())
        return bool(names & HEADWEAR_NAMES)

    def _get_variant_usage_by_id(self, variants):
        usage_by_id = defaultdict(int)
        if not variants or 'pos.order.line' not in self.env:
            return usage_by_id

        usage_rows = self.env['pos.order.line']._read_group(
            [
                ('product_id', 'in', variants.ids),
                ('order_id.state', '=', 'draft'),
            ],
            ['product_id'],
            ['__count'],
        )
        for product, count in usage_rows:
            usage_by_id[product.id] = count
        return usage_by_id

    def _collapse_variant_line_without_losing_draft_orders(self, line):
        """Collapse a legacy variant-generating line before making it optional.

        The active product with the most draft POS usage is retained for each
        remaining service combination. Draft backend lines using a duplicate
        are moved to the retained product so an already-open order keeps a
        resolvable product after the POS reloads.
        """
        self.ensure_one()
        legacy_ptavs = line.product_template_value_ids
        if not legacy_ptavs:
            return

        variants = self.with_context(active_test=False).product_variant_ids
        grouped_variants = defaultdict(lambda: self.env['product.product'])
        signature_by_key = {}
        for variant in variants:
            signature = variant.product_template_attribute_value_ids - legacy_ptavs
            signature_key = tuple(sorted(signature.ids))
            grouped_variants[signature_key] |= variant
            signature_by_key[signature_key] = signature

        usage_by_id = self._get_variant_usage_by_id(variants)
        for signature_key, duplicate_variants in grouped_variants.items():
            canonical = duplicate_variants.sorted(
                key=lambda product: (
                    not product.active,
                    -usage_by_id[product.id],
                    product.id,
                )
            )[:1]
            duplicates = duplicate_variants - canonical
            active_duplicates = duplicates.filtered('active')
            if active_duplicates:
                active_duplicates.write({'active': False})

            signature = signature_by_key[signature_key]
            if canonical.product_template_attribute_value_ids != signature:
                canonical.write({
                    'product_template_attribute_value_ids': [
                        Command.set(signature.ids)
                    ],
                })
            if not canonical.active:
                canonical.active = True

            draft_lines = self.env['pos.order.line'].search([
                ('product_id', 'in', duplicates.ids),
                ('order_id.state', '=', 'draft'),
            ])
            if draft_lines:
                draft_lines.write({'product_id': canonical.id})

    def _remove_legacy_starch_variant_lines(self, target_attribute):
        """Collapse a variant-creating attribute that duplicates an add-on.

        The shop used to model starch as a real variant axis, which doubled the
        number of Shemagh products. A line is treated as the legacy twin of
        ``target_attribute`` when it asks the same question - same English
        attribute name, or the known legacy starch value pair.
        """
        self.ensure_one()
        target_name = str(
            target_attribute.with_context(lang='en_US').name or ''
        ).strip().casefold()

        def _is_legacy_twin(line):
            if line.attribute_id == target_attribute:
                return False
            if line.attribute_id.create_variant == 'no_variant':
                return False
            if line.attribute_id.laundry_addon_code:
                return False
            attribute_name = str(
                line.attribute_id.with_context(lang='en_US').name or ''
            ).strip().casefold()
            if target_name and attribute_name == target_name:
                return True
            value_names = {
                str(value.with_context(lang='en_US').name or '').strip().casefold()
                for value in line.value_ids
            }
            return (
                target_attribute.laundry_addon_code == 'starch_type'
                and {'starch', 'no starch'}.issubset(value_names)
            )

        legacy_lines = self.attribute_line_ids.filtered(_is_legacy_twin)
        for legacy_line in legacy_lines:
            self._collapse_variant_line_without_losing_draft_orders(legacy_line)
            legacy_line.unlink()
        return legacy_lines

    def _ensure_laundry_addon_line(self, attribute):
        self.ensure_one()
        values = attribute.value_ids.sorted(key=lambda value: (value.sequence, value.id))
        if not values:
            return self.env['product.template.attribute.line']

        line = self.attribute_line_ids.filtered(
            lambda candidate: candidate.attribute_id == attribute
        )[:1]
        if line:
            if line.value_ids != values:
                line.write({'value_ids': [Command.set(values.ids)]})
        else:
            line = self.env['product.template.attribute.line'].create({
                'product_tmpl_id': self.id,
                'attribute_id': attribute.id,
                'value_ids': [Command.set(values.ids)],
            })

        price_by_value_id = {value.id: 0.0 for value in values}
        if attribute.laundry_addon_code == 'stain_removal':
            for xml_id, price in STAIN_REMOVAL_PRICES.items():
                value = self.env.ref(xml_id, raise_if_not_found=False)
                if value:
                    price_by_value_id[value.id] = price

        for ptav in line.product_template_value_ids:
            target_price = price_by_value_id.get(
                ptav.product_attribute_value_id.id,
                0.0,
            )
            if abs(ptav.price_extra - target_price) >= 1e-9:
                ptav.price_extra = target_price
        return line

    def _seed_laundry_headwear_addons(self, headwear_addons):
        """One-time assignment of the headwear add-ons to Shemagh / Ghutra.

        Product names are only ever consulted here. Once a template is seeded
        the assignment lives in ``laundry_addon_attribute_ids``, so renaming a
        product, or adding/removing an add-on by hand, is respected from then
        on and never silently reverted by a later module upgrade.
        """
        if not headwear_addons:
            return self.browse()

        pending = self.filtered(lambda template: not template.laundry_addon_seeded)
        if not pending:
            return self.browse()

        seeded = self.browse()
        for template in pending:
            if template._is_laundry_headwear_template():
                missing = headwear_addons - template.laundry_addon_attribute_ids
                if missing:
                    template.laundry_addon_attribute_ids = [
                        Command.link(attribute_id) for attribute_id in missing.ids
                    ]
                seeded |= template
        pending.laundry_addon_seeded = True
        return seeded

    def _get_wanted_laundry_addons(self, global_addons, managed_addons):
        """Add-on groups that should be offered for this product."""
        self.ensure_one()
        wanted = global_addons | (self.laundry_addon_attribute_ids & managed_addons)
        return wanted.sorted(key=lambda attribute: (attribute.sequence, attribute.id))

    def _remove_obsolete_laundry_addon_lines(self, wanted, managed_addons):
        """Drop managed add-on lines that no longer apply to this product."""
        self.ensure_one()
        obsolete = self.attribute_line_ids.filtered(
            lambda line: line.attribute_id in managed_addons
            and line.attribute_id not in wanted
        )
        if obsolete:
            obsolete.unlink()
        return obsolete

    @api.model
    def _setup_laundry_pos_addons(self):
        """Idempotently apply the managed add-ons to the POS catalogue.

        Runs on every install and upgrade of this module, which is what keeps a
        freshly upgraded database and the POS clients in agreement.
        """
        managed_addons = self.env['product.attribute']._get_laundry_addon_attributes()
        missing_codes = set(LAUNDRY_ADDON_CODES) - set(
            managed_addons.mapped('laundry_addon_code')
        )
        if missing_codes:
            raise ValueError(
                'Missing laundry add-on attributes: %s'
                % ', '.join(sorted(missing_codes))
            )

        templates = self.with_context(
            active_test=False,
            tracking_disable=True,
            mail_create_nolog=True,
            mail_notrack=True,
        ).search([
            ('available_in_pos', '=', True),
            ('active', '=', True),
        ])
        if not templates:
            return {'template_count': 0, 'headwear_count': 0, 'addon_line_count': 0}

        global_addons = managed_addons.filtered(
            lambda attribute: attribute.laundry_addon_scope == 'all'
        )
        headwear_addons = managed_addons.filtered(
            lambda attribute: attribute.laundry_addon_code in HEADWEAR_ADDON_CODES
        )
        seeded = templates._seed_laundry_headwear_addons(headwear_addons)

        addon_line_count = 0
        for template in templates:
            wanted = template._get_wanted_laundry_addons(global_addons, managed_addons)
            template._remove_obsolete_laundry_addon_lines(wanted, managed_addons)
            for attribute in wanted:
                # A legacy variant-creating attribute covering the same choice
                # is collapsed first, so the product does not end up offering
                # the same question twice.
                template._remove_legacy_starch_variant_lines(attribute)
                if template._ensure_laundry_addon_line(attribute):
                    addon_line_count += 1

        self.env['pos.session']._notify_laundry_addons_changed()

        return {
            'template_count': len(templates),
            'headwear_count': len(seeded),
            'addon_line_count': addon_line_count,
        }

    def action_normalize_laundry_pos_attributes(self):
        self._normalize_laundry_attributes()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Laundry POS attributes updated'),
                'message': _(
                    'Service pricing was normalized and optional laundry add-ons were moved to POS configurator fields.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }
