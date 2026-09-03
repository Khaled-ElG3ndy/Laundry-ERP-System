# -*- coding: utf-8 -*-

from odoo import api, fields, models

# Attributes carrying a ``laundry_addon_code`` are managed by
# ``product.template._setup_laundry_pos_addons``.
LAUNDRY_ADDON_SCOPES = [
    ("template", "Selected products only"),
    ("all", "Every Point of Sale product"),
]

# Writing any of these changes what an open Point of Sale should be showing,
# so connected POS clients are told to pick the new configuration up.
POS_RELEVANT_FIELDS = frozenset({
    "name",
    "sequence",
    "display_type",
    "laundry_addon_code",
    "laundry_addon_scope",
    "laundry_addon_required",
    "laundry_addon_show_default",
    "laundry_addon_theme",
    "laundry_addon_icon_key",
})


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    laundry_addon_code = fields.Char(
        string="Laundry Add-on Code",
        copy=False,
        index=True,
        help="Stable technical code used to expose this optional attribute in the laundry POS.",
    )
    laundry_addon_scope = fields.Selection(
        LAUNDRY_ADDON_SCOPES,
        string="Laundry Add-on Scope",
        default="template",
        required=True,
        help=(
            "Every Point of Sale product: the add-on is offered on every product "
            "sold in the Point of Sale.\n"
            "Selected products only: the add-on is offered on the products that "
            "list it in their Laundry Add-ons field."
        ),
    )
    laundry_addon_show_default = fields.Boolean(
        string="Print Default Choice",
        default=False,
        help=(
            "Keep this group's default choice on the order line, the intake and "
            "the receipt.\n"
            "Leave it off when the default means \"nothing extra\", so tickets "
            "stay short."
        ),
    )
    laundry_addon_required = fields.Boolean(
        string="Required in Laundry POS",
        default=False,
        help="Require one value from this add-on group before the laundry service can be confirmed.",
    )
    laundry_addon_theme = fields.Selection(
        [
            ("blue", "Blue"),
            ("orange", "Orange"),
            ("teal", "Teal"),
            ("primary", "Primary"),
        ],
        string="Laundry POS Theme",
        help="Colour family used for this group's cards. Keep the add-on groups "
             "on a family the service groups do not use, so an extra is never "
             "mistaken for an urgent service.",
        default="primary",
        required=True,
    )
    laundry_addon_icon_key = fields.Selection(
        [
            ("droplet", "Droplet"),
            ("sliders", "Sliders"),
            ("sparkles", "Sparkles"),
            ("tag", "Tag"),
        ],
        string="Laundry POS Icon",
        default="tag",
        required=True,
    )

    _sql_constraints = [
        (
            "laundry_addon_code_uniq",
            "unique(laundry_addon_code)",
            "The laundry add-on code must be unique.",
        ),
    ]

    @api.model
    def _get_laundry_addon_attributes(self, codes=None):
        """Return every attribute managed as a laundry POS add-on."""
        domain = [("laundry_addon_code", "!=", False)]
        if codes is not None:
            domain.append(("laundry_addon_code", "in", list(codes)))
        return self.search(domain, order="sequence, id")

    def write(self, vals):
        result = super().write(vals)
        if POS_RELEVANT_FIELDS.intersection(vals) and any(
            self.mapped("laundry_addon_code")
        ):
            self.env["pos.session"]._notify_laundry_addons_changed()
        return result
