# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Writing any of these changes what an open Point of Sale should be showing.
POS_RELEVANT_VALUE_FIELDS = frozenset({
    "name",
    "sequence",
    "laundry_pos_display_name",
    "laundry_is_default",
})


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    laundry_service_group_id = fields.Many2one(
        "laundry.service.group",
        string="Laundry Service Group",
        index=True,
        ondelete="set null",
    )
    laundry_pos_display_name = fields.Char(
        string="Laundry POS Display Name",
        translate=True,
        help="Short label shown inside the POS service card.",
    )
    laundry_is_default = fields.Boolean(
        string="Default Laundry Add-on Value",
        default=False,
        help="Preselect this value when its laundry add-on group is displayed.",
    )

    @api.constrains("laundry_is_default", "attribute_id")
    def _check_single_laundry_default(self):
        for value in self.filtered(
            lambda item: item.laundry_is_default
            and item.attribute_id.laundry_addon_code
        ):
            duplicate = self.search_count(
                [
                    ("attribute_id", "=", value.attribute_id.id),
                    ("laundry_is_default", "=", True),
                    ("id", "!=", value.id),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _("A laundry add-on group can only have one default value.")
                )

    def write(self, vals):
        result = super().write(vals)
        if POS_RELEVANT_VALUE_FIELDS.intersection(vals) and any(
            self.mapped("attribute_id.laundry_addon_code")
        ):
            self.env["pos.session"]._notify_laundry_addons_changed()
        return result


class ProductTemplateAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"

    def write(self, vals):
        result = super().write(vals)
        # ``price_extra`` is what the cashier is charging, so a change here has
        # to reach the tills that are already open.
        if {"price_extra", "ptav_active"}.intersection(vals) and any(
            self.mapped("attribute_id.laundry_addon_code")
        ):
            self.env["pos.session"]._notify_laundry_addons_changed()
        return result
