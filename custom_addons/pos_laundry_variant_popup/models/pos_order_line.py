# -*- coding: utf-8 -*-

import math

from odoo import api, fields, models


SELECTION_STRING_FIELDS = (
    "group",
    "groupCode",
    "value",
    "originalValue",
    "priceText",
    "displayText",
)
SELECTION_INTEGER_FIELDS = (
    "productId",
    "valueId",
    "groupId",
    "ptavId",
)
SELECTION_FLOAT_FIELDS = (
    "priceExtra",
    "priceAmount",
)
MAX_SELECTION_COUNT = 12
MAX_SELECTION_TEXT_LENGTH = 256


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    laundry_variant_selections = fields.Json(
        string="Laundry Service Selections",
        default=list,
        copy=True,
        help="Service and add-on choices captured by the laundry POS configurator.",
    )

    @api.model
    def _sanitize_laundry_variant_selections(self, selections):
        if not isinstance(selections, list):
            return []

        normalized = []
        for raw_selection in selections[:MAX_SELECTION_COUNT]:
            if not isinstance(raw_selection, dict):
                continue

            value = str(raw_selection.get("value") or "").strip()
            display_text = str(raw_selection.get("displayText") or "").strip()
            if not value and not display_text:
                continue

            selection = {}
            for field_name in SELECTION_STRING_FIELDS:
                field_value = str(raw_selection.get(field_name) or "").strip()
                selection[field_name] = field_value[:MAX_SELECTION_TEXT_LENGTH]

            for field_name in SELECTION_INTEGER_FIELDS:
                try:
                    selection[field_name] = max(0, int(raw_selection.get(field_name) or 0))
                except (TypeError, ValueError, OverflowError):
                    selection[field_name] = 0

            for field_name in SELECTION_FLOAT_FIELDS:
                try:
                    field_value = float(raw_selection.get(field_name) or 0.0)
                except (TypeError, ValueError, OverflowError):
                    field_value = 0.0
                selection[field_name] = field_value if math.isfinite(field_value) else 0.0

            selection["isPrimary"] = bool(raw_selection.get("isPrimary"))
            normalized.append(selection)

        return normalized

    def _order_line_fields(self, line, session_id=None):
        line = super()._order_line_fields(line, session_id=session_id)
        if line and line[2].get("laundry_variant_selections") is not None:
            line[2]["laundry_variant_selections"] = (
                self._sanitize_laundry_variant_selections(
                    line[2]["laundry_variant_selections"]
                )
            )
        return line

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if "laundry_variant_selections" in values:
                values["laundry_variant_selections"] = (
                    self._sanitize_laundry_variant_selections(
                        values["laundry_variant_selections"]
                    )
                )
        return super().create(vals_list)

    def write(self, values):
        if "laundry_variant_selections" in values:
            values = dict(values)
            values["laundry_variant_selections"] = (
                self._sanitize_laundry_variant_selections(
                    values["laundry_variant_selections"]
                )
            )
        return super().write(values)

    def _export_for_ui(self, orderline):
        result = super()._export_for_ui(orderline)
        result["laundry_variant_selections"] = (
            self._sanitize_laundry_variant_selections(
                orderline.laundry_variant_selections
            )
        )
        return result

    def _prepare_refund_data(self, refund_order, PosOrderLineLot):
        values = super()._prepare_refund_data(refund_order, PosOrderLineLot)
        values["laundry_variant_selections"] = (
            self._sanitize_laundry_variant_selections(
                self.laundry_variant_selections
            )
        )
        return values
