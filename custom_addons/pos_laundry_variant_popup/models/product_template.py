# -*- coding: utf-8 -*-

from odoo import Command, api, fields, models, _


SERVICE_ATTRIBUTE_NAME = 'Service Type'
LEGACY_SERVICE_ATTRIBUTES = ('NORMAL', 'URGENT')
STAIN_ATTRIBUTE_NONE_LABELS = {
    'Removing Stains': 'None',
    'ازاله البقع': 'بدون',
    'إزالة البقع': 'بدون',
}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    has_legacy_laundry_service_attributes = fields.Boolean(
        compute='_compute_has_legacy_laundry_service_attributes',
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
