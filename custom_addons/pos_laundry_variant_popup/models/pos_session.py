# -*- coding: utf-8 -*-

from odoo import models


class PosSession(models.Model):
    _inherit = "pos.session"

    def _process_pos_ui_product_product(self, products):
        super()._process_pos_ui_product_product(products)

        product_ids = [product["id"] for product in products if product.get("id")]
        if not product_ids:
            return

        product_by_id = {
            product.id: product
            for product in self.env["product.product"].browse(product_ids).exists()
        }

        for product_data in products:
            product = product_by_id.get(product_data.get("id"))
            if not product:
                continue

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
