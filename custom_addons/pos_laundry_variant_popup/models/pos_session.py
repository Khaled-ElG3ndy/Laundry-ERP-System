# -*- coding: utf-8 -*-

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# The POS assets watchdog shipped by pos_laundry_receipt already listens for
# this event and reloads idle Point of Sale tabs. Reusing it means a laundry
# add-on change reaches every open session through a path that is already
# proven in production, instead of a second, parallel mechanism.
POS_REFRESH_EVENT = "pos_laundry_assets_changed"


class PosSession(models.Model):
    _inherit = "pos.session"

    def _get_laundry_optional_groups_by_template(self, products):
        templates = products.mapped("product_tmpl_id")
        groups_by_template = {}

        for template in templates:
            groups = []
            addon_lines = template.attribute_line_ids.filtered(
                lambda line: bool(line.attribute_id.laundry_addon_code)
            ).sorted(
                key=lambda line: (
                    line.attribute_id.sequence,
                    line.sequence,
                    line.id,
                )
            )
            for line in addon_lines:
                attribute = line.attribute_id
                items = []
                for ptav in line.product_template_value_ids.filtered(
                    "ptav_active"
                ).sorted(
                    key=lambda value: (
                        value.product_attribute_value_id.sequence,
                        value.id,
                    )
                ):
                    value = ptav.product_attribute_value_id
                    items.append(
                        {
                            "id": ptav.id,
                            "ptav_id": ptav.id,
                            "value_id": value.id,
                            "name": value.laundry_pos_display_name
                            or ptav.name
                            or value.name
                            or "",
                            "original_name": ptav.name or value.name or "",
                            "price_extra": ptav.price_extra or 0.0,
                            "is_default": bool(value.laundry_is_default),
                            "sequence": value.sequence or ptav.id,
                        }
                    )

                if items:
                    groups.append(
                        {
                            "id": attribute.id,
                            "line_id": line.id,
                            "code": attribute.laundry_addon_code,
                            "name": attribute.name or "",
                            "required": bool(attribute.laundry_addon_required),
                            "show_default": bool(
                                attribute.laundry_addon_show_default
                            ),
                            "theme": attribute.laundry_addon_theme or "primary",
                            "icon_key": attribute.laundry_addon_icon_key or "tag",
                            "sequence": attribute.sequence or line.sequence or line.id,
                            "items": items,
                        }
                    )

            groups_by_template[template.id] = groups

        return groups_by_template

    def _process_pos_ui_product_product(self, products):
        super()._process_pos_ui_product_product(products)

        product_ids = [product["id"] for product in products if product.get("id")]
        if not product_ids:
            return

        product_records = self.env["product.product"].browse(product_ids).exists()
        product_by_id = {
            product.id: product
            for product in product_records
        }
        optional_groups_by_template = self._get_laundry_optional_groups_by_template(
            product_records
        )

        for product_data in products:
            product = product_by_id.get(product_data.get("id"))
            if not product:
                continue

            product_data["laundry_optional_groups"] = (
                optional_groups_by_template.get(product.product_tmpl_id.id, [])
            )

            service_ptav = product.product_template_attribute_value_ids.filtered(
                lambda ptav: ptav.product_attribute_value_id.laundry_service_group_id
            )[:1]
            if not service_ptav:
                product_data.update(
                    {
                        "laundry_service_group_id": False,
                        "laundry_service_group_name": "",
                        "laundry_service_group_code": "",
                        "laundry_service_group_sequence": 0,
                        "laundry_service_group_theme": "primary",
                        "laundry_service_group_icon_key": "tag",
                        "laundry_service_value_id": False,
                        "laundry_service_value_name": "",
                        "laundry_service_display_name": "",
                        "laundry_service_sequence": 0,
                    }
                )
                continue

            service_value = service_ptav.product_attribute_value_id
            service_group = service_value.laundry_service_group_id
            product_data.update(
                {
                    "laundry_service_group_id": service_group.id,
                    "laundry_service_group_name": service_group.name or "",
                    "laundry_service_group_code": service_group.code or "",
                    "laundry_service_group_sequence": service_group.sequence or 0,
                    "laundry_service_group_theme": service_group.color_theme or "primary",
                    "laundry_service_group_icon_key": service_group.icon_key or "tag",
                    "laundry_service_value_id": service_value.id,
                    "laundry_service_value_name": service_ptav.name or service_value.name or "",
                    "laundry_service_display_name": service_value.laundry_pos_display_name
                    or service_ptav.name
                    or service_value.name
                    or "",
                    "laundry_service_sequence": service_value.sequence or service_ptav.id,
                }
            )

    @api.model
    def _notify_laundry_addons_changed(self):
        """Tell every open Point of Sale that the add-on setup changed.

        A POS keeps its product catalogue in memory for the whole session, so a
        backend change would otherwise stay invisible until somebody refreshed
        the browser by hand. The notification carries a version stamp; the POS
        watchdog reloads the tab once the cashier is idle, and only prompts when
        an order is in progress, so no keyed-in order is ever lost.
        """
        if "bus.bus" not in self.env:
            return False
        try:
            precommit = self.env.cr.precommit.data
            if precommit.get("laundry_addons_changed_queued"):
                return False
            precommit["laundry_addons_changed_queued"] = True
            self.env["bus.bus"]._sendone(
                "broadcast",
                POS_REFRESH_EVENT,
                {"version": "laundry-addons:%s" % fields.Datetime.now()},
            )
        except Exception:  # never fail a data write over a notification
            _logger.warning(
                "Could not broadcast the laundry add-on change.", exc_info=True
            )
            return False
        return True
