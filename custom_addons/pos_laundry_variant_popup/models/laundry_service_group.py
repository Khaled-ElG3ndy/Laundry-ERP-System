# -*- coding: utf-8 -*-

from odoo import fields, models


class LaundryServiceGroup(models.Model):
    _name = "laundry.service.group"
    _description = "Laundry Service Group"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    color_theme = fields.Selection(
        [
            ("blue", "Blue"),
            ("orange", "Orange"),
            ("primary", "Primary"),
        ],
        default="primary",
        required=True,
    )
    icon_key = fields.Selection(
        [
            ("leaf", "Leaf"),
            ("sparkles", "Sparkles"),
            ("clock", "Clock"),
            ("zap", "Zap"),
            ("tag", "Tag"),
        ],
        default="tag",
        required=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "laundry_service_group_code_uniq",
            "unique(code)",
            "The laundry service group code must be unique.",
        ),
    ]
