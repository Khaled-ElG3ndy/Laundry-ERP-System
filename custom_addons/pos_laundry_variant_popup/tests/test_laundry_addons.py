import os

from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestLaundryAddons(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.regular_group = cls.env["laundry.service.group"].create(
            {
                "name": "Test Regular",
                "code": "test_addon_regular",
                "sequence": 1,
                "color_theme": "blue",
                "icon_key": "leaf",
            }
        )
        cls.service_attribute = cls.env["product.attribute"].create(
            {
                "name": "Test Service Type",
                "display_type": "radio",
                "create_variant": "always",
            }
        )
        cls.service_iron = cls.env["product.attribute.value"].create(
            {
                "attribute_id": cls.service_attribute.id,
                "name": "Test Ironing",
                "sequence": 10,
                "laundry_service_group_id": cls.regular_group.id,
            }
        )
        cls.service_wash = cls.env["product.attribute.value"].create(
            {
                "attribute_id": cls.service_attribute.id,
                "name": "Test Wash + Iron",
                "sequence": 20,
                "laundry_service_group_id": cls.regular_group.id,
            }
        )
        cls.legacy_starch_attribute = cls.env["product.attribute"].create(
            {
                "name": "Starch Type",
                "display_type": "radio",
                "create_variant": "always",
            }
        )
        cls.legacy_starch = cls.env["product.attribute.value"].create(
            {
                "attribute_id": cls.legacy_starch_attribute.id,
                "name": "Starch",
                "sequence": 10,
            }
        )
        cls.legacy_no_starch = cls.env["product.attribute.value"].create(
            {
                "attribute_id": cls.legacy_starch_attribute.id,
                "name": "No Starch",
                "sequence": 20,
            }
        )

        cls.generic_template = cls._create_laundry_template("Test Shirt")
        cls.shemagh_template = cls._create_laundry_template(
            "Shemagh",
            include_legacy_starch=True,
        )
        cls.ghutra_template = cls._create_laundry_template("Ghutra")
        cls.non_laundry_template = cls.env["product.template"].create(
            {
                "name": "Test Retail Bag",
                "available_in_pos": True,
                "list_price": 5.0,
                "taxes_id": [Command.clear()],
            }
        )

        cls.back_office_template = cls.env["product.template"].create(
            {
                "name": "Test Back Office Supply",
                "available_in_pos": False,
                "list_price": 7.0,
                "taxes_id": [Command.clear()],
            }
        )

        cls.pos_config = cls.env["pos.config"].create(
            {"name": "Laundry Add-on Test POS"}
        )
        cls.session = cls.env["pos.session"].create(
            {"config_id": cls.pos_config.id}
        )
        starch_ptav = cls.shemagh_template.attribute_line_ids.filtered(
            lambda line: line.attribute_id == cls.legacy_starch_attribute
        ).product_template_value_ids.filtered(
            lambda ptav: ptav.product_attribute_value_id == cls.legacy_starch
        )
        cls.draft_product = cls.shemagh_template.product_variant_ids.filtered(
            lambda product: bool(
                product.product_template_attribute_value_ids & starch_ptav
            )
        ).sorted("id")[:1]
        cls.draft_order = cls.env["pos.order"].create(
            {
                "company_id": cls.env.company.id,
                "session_id": cls.session.id,
                "pricelist_id": cls.env.company.partner_id.property_product_pricelist.id,
                "lines": [
                    Command.create(
                        {
                            "name": "Test Shemagh",
                            "product_id": cls.draft_product.id,
                            "price_unit": 10.0,
                            "qty": 1.0,
                            "price_subtotal": 10.0,
                            "price_subtotal_incl": 10.0,
                        }
                    )
                ],
                "amount_total": 10.0,
                "amount_tax": 0.0,
                "amount_paid": 0.0,
                "amount_return": 0.0,
                "last_order_preparation_change": "{}",
            }
        )

        cls.setup_result = cls.env["product.template"]._setup_laundry_pos_addons()
        cls.generic_template.invalidate_recordset()
        cls.shemagh_template.invalidate_recordset()
        cls.ghutra_template.invalidate_recordset()
        cls.draft_order.invalidate_recordset()

    @classmethod
    def _create_laundry_template(cls, name, include_legacy_starch=False):
        lines = [
            Command.create(
                {
                    "attribute_id": cls.service_attribute.id,
                    "value_ids": [
                        Command.set([cls.service_iron.id, cls.service_wash.id])
                    ],
                }
            )
        ]
        if include_legacy_starch:
            lines.append(
                Command.create(
                    {
                        "attribute_id": cls.legacy_starch_attribute.id,
                        "value_ids": [
                            Command.set(
                                [cls.legacy_starch.id, cls.legacy_no_starch.id]
                            )
                        ],
                    }
                )
            )
        return cls.env["product.template"].create(
            {
                "name": name,
                "available_in_pos": True,
                "list_price": 10.0,
                "taxes_id": [Command.clear()],
                "attribute_line_ids": lines,
            }
        )

    def _addon_lines_by_code(self, template):
        return {
            line.attribute_id.laundry_addon_code: line
            for line in template.attribute_line_ids
            if line.attribute_id.laundry_addon_code
        }

    def test_setup_is_idempotent(self):
        before = {
            template.id: (
                template.with_context(active_test=False).product_variant_ids.ids,
                template.attribute_line_ids.ids,
            )
            for template in (
                self.generic_template,
                self.shemagh_template,
                self.ghutra_template,
            )
        }
        result = self.env["product.template"]._setup_laundry_pos_addons()
        after = {
            template.id: (
                template.with_context(active_test=False).product_variant_ids.ids,
                template.attribute_line_ids.ids,
            )
            for template in (
                self.generic_template,
                self.shemagh_template,
                self.ghutra_template,
            )
        }
        self.assertGreaterEqual(result["template_count"], 3)
        self.assertEqual(before, after)

    def test_stain_removal_covers_every_point_of_sale_product(self):
        """Stain removal is offered on every product sold in the POS."""
        for template in (
            self.generic_template,
            self.shemagh_template,
            self.ghutra_template,
            # A POS product without any service attribute still gets it.
            self.non_laundry_template,
        ):
            self.assertIn(
                "stain_removal",
                self._addon_lines_by_code(template),
                "%s should offer stain removal" % template.display_name,
            )

    def test_products_outside_the_point_of_sale_are_untouched(self):
        self.assertFalse(self._addon_lines_by_code(self.back_office_template))
        self.assertFalse(self.back_office_template.attribute_line_ids)

    def test_archived_products_are_not_configured(self):
        archived = self.env["product.template"].create({
            "name": "Test Archived Item",
            "available_in_pos": True,
            "active": False,
            "list_price": 3.0,
            "taxes_id": [Command.clear()],
        })
        self.env["product.template"]._setup_laundry_pos_addons()
        self.assertFalse(archived.attribute_line_ids)

    def test_stain_prices_are_exact(self):
        """Only the three sizes exist, priced 1 / 2 / 3."""
        line = self._addon_lines_by_code(self.generic_template)["stain_removal"]
        prices = {
            ptav.product_attribute_value_id.name: ptav.price_extra
            for ptav in line.product_template_value_ids
        }
        self.assertEqual(prices, {"S": 1.0, "M": 2.0, "L": 3.0})

    def test_stain_removal_has_no_none_option(self):
        names = self._addon("stain_removal").value_ids.mapped("name")
        self.assertEqual(sorted(names), ["L", "M", "S"])
        self.assertNotIn("No Stain Removal", names)

    def test_headwear_has_exact_free_mirzam_and_starch_choices(self):
        expected_values = {
            "mirzam_type": ["No Mirzam", "Mirzam", "Inverted Mirzam"],
            "starch_type": ["Light", "Medium", "Heavy"],
        }
        for template in (self.shemagh_template, self.ghutra_template):
            lines = self._addon_lines_by_code(template)
            self.assertEqual(set(lines), {"stain_removal", "mirzam_type", "starch_type"})
            for code, names in expected_values.items():
                ptavs = lines[code].product_template_value_ids.sorted(
                    lambda ptav: ptav.product_attribute_value_id.sequence
                )
                self.assertEqual(
                    ptavs.mapped("product_attribute_value_id.name"),
                    names,
                )
                self.assertEqual(set(ptavs.mapped("price_extra")), {0.0})
            for code in ("mirzam_type", "starch_type"):
                self.assertFalse(
                    lines[code].value_ids.filtered("laundry_is_default"),
                    "%s must open with nothing ticked" % code,
                )

    def test_legacy_starch_variants_are_collapsed_and_draft_product_survives(self):
        self.assertNotIn(
            self.legacy_starch_attribute,
            self.shemagh_template.attribute_line_ids.attribute_id,
        )
        self.assertEqual(len(self.shemagh_template.product_variant_ids), 2)
        self.assertTrue(self.draft_product.active)
        self.assertEqual(self.draft_order.lines.product_id, self.draft_product)

    def test_pos_loader_exposes_groups_defaults_and_prices(self):
        products = self.generic_template.product_variant_ids
        product_data = products.read(["id", "categ_id", "image_128"])
        self.session._process_pos_ui_product_product(product_data)
        for data in product_data:
            groups = data["laundry_optional_groups"]
            self.assertEqual([group["code"] for group in groups], ["stain_removal"])
            group = groups[0]
            # Optional: the cashier may confirm the line without picking a size.
            self.assertFalse(group["required"])
            self.assertEqual(
                [item["name"] for item in group["items"]], ["S", "M", "L"]
            )
            self.assertEqual(
                [item["price_extra"] for item in group["items"]],
                [1.0, 2.0, 3.0],
            )
            self.assertEqual(
                [item["is_default"] for item in group["items"]],
                [False, False, False],
                "nothing may be preselected for stain removal",
            )

    def test_pos_loader_limits_headwear_options_to_shemagh_and_ghutra(self):
        for template in (self.shemagh_template, self.ghutra_template):
            product_data = template.product_variant_ids[:1].read(
                ["id", "categ_id", "image_128"]
            )
            self.session._process_pos_ui_product_product(product_data)
            self.assertEqual(
                [group["code"] for group in product_data[0]["laundry_optional_groups"]],
                ["stain_removal", "mirzam_type", "starch_type"],
            )

    def test_order_line_selections_are_sanitized_persisted_and_exported(self):
        line = self.draft_order.lines
        raw_selection = {
            "group": "Stain Removal",
            "groupCode": "stain_removal",
            "groupId": "10",
            "value": "S",
            "valueId": "20",
            "ptavId": "30",
            "priceExtra": "1.0",
            "priceAmount": "1.0",
            "priceText": "1 SR",
            "displayText": "Stain Removal: S - 1 SR",
            "isPrimary": False,
            "ignored": "must not be stored",
        }
        line.write({"laundry_variant_selections": [raw_selection, None, "bad"]})
        selection = line.laundry_variant_selections[0]
        self.assertEqual(selection["groupCode"], "stain_removal")
        self.assertEqual(selection["ptavId"], 30)
        self.assertEqual(selection["priceExtra"], 1.0)
        self.assertNotIn("ignored", selection)
        self.assertEqual(
            line._export_for_ui(line)["laundry_variant_selections"],
            line.laundry_variant_selections,
        )

    def test_order_line_payload_rejects_invalid_and_non_finite_values(self):
        line_values = self.env["pos.order.line"]._order_line_fields(
            [
                0,
                0,
                {
                    "product_id": self.draft_product.id,
                    "laundry_variant_selections": [
                        {
                            "value": "S",
                            "priceExtra": "nan",
                            "productId": "not-an-id",
                        }
                    ],
                },
            ],
            session_id=self.session.id,
        )[2]
        self.assertEqual(
            line_values["laundry_variant_selections"][0]["priceExtra"],
            0.0,
        )
        self.assertEqual(
            line_values["laundry_variant_selections"][0]["productId"],
            0,
        )

    def test_refund_data_copies_laundry_selections(self):
        self.draft_order.lines.write(
            {
                "laundry_variant_selections": [
                    {
                        "group": "Stain Removal",
                        "groupCode": "stain_removal",
                        "value": "M",
                        "priceExtra": 2.0,
                        "isPrimary": False,
                    }
                ]
            }
        )
        refund_order = self.draft_order.copy({"lines": [Command.clear()]})
        values = self.draft_order.lines._prepare_refund_data(refund_order, [])
        self.assertEqual(
            values["laundry_variant_selections"],
            self.draft_order.lines.laundry_variant_selections,
        )

    # ── Per-product add-on assignment ──────────────────────────────────────

    def _addon(self, code):
        return self.env.ref("pos_laundry_variant_popup.attribute_%s" % code)

    def test_headwear_seeding_assigns_mirzam_and_starch_once(self):
        starch = self._addon("starch_type")
        mirzam = self._addon("mirzam_type")
        for template in (self.shemagh_template, self.ghutra_template):
            self.assertTrue(template.laundry_addon_seeded)
            self.assertEqual(
                template.laundry_addon_attribute_ids,
                mirzam | starch,
                "%s should be seeded with both headwear add-ons"
                % template.display_name,
            )
        self.assertTrue(self.generic_template.laundry_addon_seeded)
        self.assertFalse(self.generic_template.laundry_addon_attribute_ids)

    def test_manual_addon_removal_survives_a_later_upgrade(self):
        """A manager unassigning an add-on is never overruled by an upgrade."""
        starch = self._addon("starch_type")
        self.shemagh_template.laundry_addon_attribute_ids = [Command.unlink(starch.id)]

        self.env["product.template"]._setup_laundry_pos_addons()
        self.shemagh_template.invalidate_recordset()

        self.assertNotIn(starch, self.shemagh_template.laundry_addon_attribute_ids)
        self.assertNotIn("starch_type", self._addon_lines_by_code(self.shemagh_template))
        # The other headwear add-on is untouched.
        self.assertIn("mirzam_type", self._addon_lines_by_code(self.shemagh_template))

    def test_manual_addon_assignment_is_applied(self):
        """Any product can be given the headwear add-ons from the backend."""
        starch = self._addon("starch_type")
        self.generic_template.laundry_addon_attribute_ids = [Command.link(starch.id)]

        self.env["product.template"]._setup_laundry_pos_addons()
        self.generic_template.invalidate_recordset()

        lines = self._addon_lines_by_code(self.generic_template)
        self.assertIn("starch_type", lines)
        self.assertEqual(
            lines["starch_type"].product_template_value_ids.mapped(
                "product_attribute_value_id.name"
            ),
            ["Light", "Medium", "Heavy"],
        )

    def test_renaming_a_headwear_product_keeps_its_addons(self):
        """The name is only read once, at seeding time."""
        self.shemagh_template.name = "Renamed Head Cover"
        self.env["product.template"]._setup_laundry_pos_addons()
        self.shemagh_template.invalidate_recordset()

        self.assertEqual(
            set(self._addon_lines_by_code(self.shemagh_template)),
            {"stain_removal", "mirzam_type", "starch_type"},
        )

    def test_switching_scope_to_template_narrows_the_catalogue(self):
        stain = self._addon("stain_removal")
        stain.laundry_addon_scope = "template"

        self.env["product.template"]._setup_laundry_pos_addons()
        self.generic_template.invalidate_recordset()

        self.assertNotIn("stain_removal", self._addon_lines_by_code(self.generic_template))

        stain.laundry_addon_scope = "all"
        self.env["product.template"]._setup_laundry_pos_addons()
        self.generic_template.invalidate_recordset()
        self.assertIn("stain_removal", self._addon_lines_by_code(self.generic_template))

    # ── Defaults ──────────────────────────────────────────────────────────

    def test_starch_has_no_preselected_value(self):
        """Nothing is assumed, and nothing is forced either."""
        line = self._addon_lines_by_code(self.shemagh_template)["starch_type"]
        self.assertFalse(
            any(line.value_ids.mapped("laundry_is_default")),
            "starch must not preselect a value",
        )
        self.assertFalse(self._addon("starch_type").laundry_addon_required)

    def test_no_addon_group_preselects_anything(self):
        """Nothing is ticked when the popup opens - every choice is the cashier's."""
        for attribute in self.env["product.attribute"]._get_laundry_addon_attributes():
            preselected = attribute.value_ids.filtered("laundry_is_default")
            self.assertFalse(
                preselected,
                "%s preselects %s"
                % (attribute.laundry_addon_code, preselected.mapped("name")),
            )

    def test_mirzam_still_offers_an_explicit_no_option(self):
        """"No Mirzam" stays available - it is just no longer assumed."""
        names = self._addon("mirzam_type").value_ids.sorted("sequence").mapped("name")
        self.assertEqual(names, ["No Mirzam", "Mirzam", "Inverted Mirzam"])

    def test_stain_removal_is_optional_and_unanswered(self):
        """Nothing is charged unless the cashier deliberately picks a size."""
        stain = self._addon("stain_removal")
        self.assertFalse(stain.laundry_addon_required)
        self.assertFalse(
            any(stain.value_ids.mapped("laundry_is_default")),
            "stain removal must not preselect a size",
        )

    def test_no_addon_group_blocks_the_sale(self):
        """Every add-on is the cashier's choice, so none of them can hold up a sale.

        Making mirzam and starch required is what stopped a Shemagh being added
        at all: with five groups on that product the two mandatory ones sat
        below the fold, so Confirm just refused with no visible reason.
        """
        for attribute in self.env["product.attribute"]._get_laundry_addon_attributes():
            self.assertFalse(
                attribute.laundry_addon_required,
                "%s is required, which can block a sale"
                % attribute.laundry_addon_code,
            )

    def test_every_deliberate_choice_reaches_the_ticket(self):
        """No group hides a value now that no group preselects one."""
        for code in ("mirzam_type", "starch_type"):
            self.assertTrue(
                self._addon(code).laundry_addon_show_default,
                "%s would hide a choice the cashier made on purpose" % code,
            )

    def test_a_group_cannot_have_two_defaults(self):
        from odoo.exceptions import ValidationError

        starch = self._addon("starch_type")
        values = starch.value_ids.sorted("sequence")
        values[0].laundry_is_default = True
        with self.assertRaises(ValidationError):
            values[1].laundry_is_default = True

    # ── POS loader ────────────────────────────────────────────────────────

    def test_pos_loader_exposes_show_default_per_group(self):
        product_data = self.shemagh_template.product_variant_ids[:1].read(
            ["id", "categ_id", "image_128"]
        )
        self.session._process_pos_ui_product_product(product_data)
        groups = {
            group["code"]: group
            for group in product_data[0]["laundry_optional_groups"]
        }
        self.assertFalse(groups["stain_removal"]["show_default"])
        self.assertTrue(groups["mirzam_type"]["show_default"])
        self.assertTrue(groups["starch_type"]["show_default"])
        # The loader must tell the POS that nothing starts ticked.
        for group in groups.values():
            self.assertFalse(
                any(item["is_default"] for item in group["items"]),
                "%s ships a preselected item to the POS" % group["code"],
            )

    def test_pos_loader_marks_addon_only_products(self):
        """A POS product with no service axis still ships its add-on groups."""
        product_data = self.non_laundry_template.product_variant_ids.read(
            ["id", "categ_id", "image_128"]
        )
        self.session._process_pos_ui_product_product(product_data)
        data = product_data[0]
        self.assertFalse(data["laundry_service_group_id"])
        self.assertEqual(
            [group["code"] for group in data["laundry_optional_groups"]],
            ["stain_removal"],
        )

    def test_pos_loader_orders_groups_by_sequence(self):
        product_data = self.shemagh_template.product_variant_ids[:1].read(
            ["id", "categ_id", "image_128"]
        )
        self.session._process_pos_ui_product_product(product_data)
        self.assertEqual(
            [g["code"] for g in product_data[0]["laundry_optional_groups"]],
            ["stain_removal", "mirzam_type", "starch_type"],
        )

    # ── Open Point of Sale sessions ───────────────────────────────────────

    def _sent_pos_refresh_notifications(self):
        return [
            entry
            for entry in self.env.cr.precommit.data.get("bus.bus.values", [])
            if "pos_laundry_assets_changed" in entry.get("message", "")
        ]

    def _reset_pos_refresh_notifications(self):
        self.env.cr.precommit.data["bus.bus.values"] = []
        self.env.cr.precommit.data.pop("laundry_addons_changed_queued", None)

    def test_price_change_notifies_open_sessions(self):
        self._reset_pos_refresh_notifications()
        line = self._addon_lines_by_code(self.generic_template)["stain_removal"]
        ptav = line.product_template_value_ids.filtered(
            lambda value: value.product_attribute_value_id.name == "S"
        )
        ptav.price_extra = 1.5
        self.assertTrue(
            self._sent_pos_refresh_notifications(),
            "changing an add-on price must reach open POS sessions",
        )

    def test_attribute_change_notifies_open_sessions(self):
        self._reset_pos_refresh_notifications()
        self._addon("mirzam_type").laundry_addon_required = True
        self.assertTrue(self._sent_pos_refresh_notifications())

    def test_value_rename_notifies_open_sessions(self):
        self._reset_pos_refresh_notifications()
        self.env.ref("pos_laundry_variant_popup.addon_stain_s").name = "S+"
        self.assertTrue(self._sent_pos_refresh_notifications())

    def test_unrelated_attribute_change_is_silent(self):
        self._reset_pos_refresh_notifications()
        self.service_attribute.name = "Test Service Type Renamed"
        self.assertFalse(self._sent_pos_refresh_notifications())

    def test_setup_notifies_open_sessions(self):
        self._reset_pos_refresh_notifications()
        self.env["product.template"]._setup_laundry_pos_addons()
        self.assertTrue(self._sent_pos_refresh_notifications())

    # ── Arabic ────────────────────────────────────────────────────────────

    @classmethod
    def _load_arabic(cls):
        cls.env["res.lang"]._activate_lang("ar_001")
        cls.env["ir.module.module"]._load_module_terms(
            ["pos_laundry_variant_popup"], ["ar_001"], overwrite=True
        )
        cls.env.invalidate_all()

    def test_arabic_translations_are_loaded_for_every_addon(self):
        self._load_arabic()
        expected = {
            "attribute_stain_removal": "إزالة البقع",
            "attribute_mirzam_type": "نوع المرزام",
            "attribute_starch_type": "نوع النشاء",
        }
        for xml_id, arabic in expected.items():
            attribute = self.env.ref("pos_laundry_variant_popup.%s" % xml_id)
            self.assertEqual(
                attribute.with_context(lang="ar_001").name,
                arabic,
                "%s is not translated" % xml_id,
            )

    def test_arabic_translations_are_loaded_for_every_value(self):
        self._load_arabic()
        expected = {
            "addon_mirzam_none": "بدون مرزام",
            "addon_mirzam_regular": "مرزام",
            "addon_mirzam_inverted": "مرزام مقلوب",
            "addon_starch_light": "خفيف",
            "addon_starch_medium": "وسط",
            "addon_starch_heavy": "ثقيل",
        }
        for xml_id, arabic in expected.items():
            value = self.env.ref("pos_laundry_variant_popup.%s" % xml_id)
            self.assertEqual(
                value.with_context(lang="ar_001").name,
                arabic,
                "%s is not translated" % xml_id,
            )

    def test_english_names_are_unchanged_by_the_arabic_load(self):
        self._load_arabic()
        self.assertEqual(
            self.env.ref(
                "pos_laundry_variant_popup.attribute_stain_removal"
            ).with_context(lang="en_US").name,
            "Stain Removal",
        )

    # ── Appearance ────────────────────────────────────────────────────────

    def test_addons_never_share_a_colour_with_a_service_group(self):
        """An extra must not be mistakable for an urgency level.

        The service groups own blue (normal) and orange (urgent); the optional
        extras own their own family. Reusing orange for stain removal made the
        two blocks look identical on screen.
        """
        service_themes = set(
            self.env["laundry.service.group"].search([]).mapped("color_theme")
        )
        addon_themes = set(
            self.env["product.attribute"]
            ._get_laundry_addon_attributes()
            .mapped("laundry_addon_theme")
        )
        self.assertTrue(addon_themes, "no add-on themes configured")
        self.assertFalse(
            addon_themes & service_themes,
            "add-on groups reuse a service group colour: %s"
            % sorted(addon_themes & service_themes),
        )

    def test_every_addon_shares_one_calm_colour(self):
        """One family for all extras keeps the popup from turning into a rainbow."""
        themes = set(
            self.env["product.attribute"]
            ._get_laundry_addon_attributes()
            .mapped("laundry_addon_theme")
        )
        self.assertEqual(themes, {"teal"})

    def test_addon_groups_are_told_apart_by_icon(self):
        """Same colour, so the icon has to carry the difference."""
        addons = self.env["product.attribute"]._get_laundry_addon_attributes()
        icons = addons.mapped("laundry_addon_icon_key")
        self.assertEqual(len(icons), len(set(icons)), "add-on icons are not unique")

    def _popup_styles(self):
        import os

        scss = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "src", "scss", "pos_laundry_variant_popup.scss",
        )
        with open(scss, encoding="utf-8") as handle:
            return handle.read()

    def test_addons_are_not_boxed_differently_from_the_service_groups(self):
        """The extras must sit on the page like every other block.

        Giving that one section a panel of its own made it the only block in
        the popup with a background, which read as a mistake rather than as a
        distinction. Colour and icon carry the difference instead.
        """
        styles = self._popup_styles()
        start = styles.index(".laundry-variant-popup__addons {")
        block = styles[start:styles.index("}", start)]
        for decoration in ("background", "border", "border-radius", "padding"):
            self.assertNotIn(
                decoration,
                block,
                "the add-on section declares %r, which no other group block has"
                % decoration,
            )

    def test_addons_reuse_the_service_group_layout(self):
        """No size overrides: same headings, same icons, same cards, same grid."""
        styles = self._popup_styles()
        for override in (
            ".laundry-variant-popup__addons .laundry-service-group__name",
            ".laundry-variant-popup__addons .laundry-service-group__icon",
            ".laundry-variant-popup__addons .laundry-variant-card",
            ".laundry-variant-popup__addons .laundry-variant-popup__grid",
        ):
            self.assertNotIn(
                override,
                styles,
                "%s makes the extras look unlike the service groups" % override,
            )

    def test_the_stain_theme_is_a_known_css_family(self):
        """A theme with no stylesheet would silently fall back to primary."""
        import os

        scss = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "src", "scss", "pos_laundry_variant_popup.scss",
        )
        with open(scss, encoding="utf-8") as handle:
            styles = handle.read()
        for theme in self.env["product.attribute"]._get_laundry_addon_attributes().mapped(
            "laundry_addon_theme"
        ):
            self.assertIn(
                ".laundry-service-group--%s" % theme,
                styles,
                "theme %r has no stylesheet" % theme,
            )

    def test_a_blocked_confirm_can_always_be_explained(self):
        """Reported: a Shemagh could not be added and nothing said why.

        Shemagh and Ghutra carry five groups, two of them required with no
        default. The message explaining that used to sit at the end of the
        scrolling body, well past the fold, so pressing Confirm looked like it
        simply did nothing. It now lives in the footer next to the button, and
        the popup scrolls the offending group into view.
        """
        markup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "src", "xml", "pos_laundry_variant_popup.xml",
        )
        with open(markup_path, encoding="utf-8") as handle:
            markup = handle.read()

        footer = markup[markup.index("<footer"):markup.index("</footer>")]
        self.assertIn(
            "blockedMessage",
            footer,
            "the reason a confirm was refused must sit in the always-visible "
            "footer, not at the bottom of the scrolling body",
        )
        self.assertIn(
            "data-group-key",
            markup,
            "groups need a handle for the popup to scroll the blocking one "
            "into view",
        )

    def test_a_headwear_product_adds_with_no_addons_chosen(self):
        """The exact case that was reported broken.

        Shemagh carries the most groups of any product, and none of them may
        stand between the cashier and the Confirm button.
        """
        lines = self._addon_lines_by_code(self.shemagh_template)
        self.assertEqual(
            sorted(lines), ["mirzam_type", "stain_removal", "starch_type"]
        )
        for code, line in lines.items():
            self.assertFalse(
                line.attribute_id.laundry_addon_required,
                "%s would block adding a Shemagh" % code,
            )
            self.assertFalse(
                line.value_ids.filtered("laundry_is_default"),
                "%s would tick itself" % code,
            )

