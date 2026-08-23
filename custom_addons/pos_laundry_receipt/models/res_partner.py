import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import str2bool


LAUNDRY_PHONE_VALIDATION_PARAM = "pos_laundry_receipt.require_ten_digit_phone"
LAUNDRY_PHONE_REQUIRED_LENGTH = 10


class ResPartner(models.Model):
    _inherit = "res.partner"

    phone_unique_normalized = fields.Char(
        compute="_compute_unique_phone_normalized",
        store=True,
        index=True,
        copy=False,
    )
    mobile_unique_normalized = fields.Char(
        compute="_compute_unique_phone_normalized",
        store=True,
        index=True,
        copy=False,
    )

    @api.depends("phone", "mobile")
    def _compute_unique_phone_normalized(self):
        for partner in self:
            partner.phone_unique_normalized = partner._normalize_unique_phone(partner.phone)
            partner.mobile_unique_normalized = partner._normalize_unique_phone(partner.mobile)

    @api.model
    def _normalize_unique_phone(self, value):
        return re.sub(r"\D+", "", value or "")

    @api.model
    def _is_ten_digit_phone_validation_enabled(self):
        return str2bool(
            self.env["ir.config_parameter"].sudo().get_param(
                LAUNDRY_PHONE_VALIDATION_PARAM,
                "False",
            )
        )

    @api.model
    def _sanitize_phone_field_value(self, value):
        if value in (False, None, ""):
            return value
        return self._normalize_unique_phone(value)

    @api.model
    def _prepare_phone_values(self, values):
        prepared_values = dict(values)
        if not self._is_ten_digit_phone_validation_enabled():
            return prepared_values

        for field_name in ("phone", "mobile"):
            if field_name in prepared_values:
                prepared_values[field_name] = self._sanitize_phone_field_value(
                    prepared_values[field_name]
                )
        return prepared_values

    @api.model
    def _validate_phone_values(self, values):
        if not self._is_ten_digit_phone_validation_enabled():
            return

        for field_name in ("phone", "mobile"):
            if field_name not in values:
                continue

            value = values.get(field_name)
            if not value:
                continue

            if len(value) != LAUNDRY_PHONE_REQUIRED_LENGTH:
                raise ValidationError(
                    _(
                        "The phone number must contain exactly 10 digits when customer phone validation is enabled."
                    )
                )

    @api.model
    def _is_unique_phone_target(self, values=None, partner=None):
        values = values or {}
        partner = partner or self.env["res.partner"]

        parent_id = values["parent_id"] if "parent_id" in values else partner.parent_id.id
        partner_type = values["type"] if "type" in values else partner.type
        partner_type = partner_type or "contact"

        return not parent_id and partner_type == "contact"

    @api.model
    def _get_unique_phone_numbers(self, values=None, partner=None):
        values = values or {}
        partner = partner or self.env["res.partner"]

        phone = values["phone"] if "phone" in values else partner.phone
        mobile = values["mobile"] if "mobile" in values else partner.mobile

        return {
            number
            for number in (
                self._normalize_unique_phone(phone),
                self._normalize_unique_phone(mobile),
            )
            if number
        }

    @api.model
    def _raise_duplicate_phone_error(self, duplicate_partner=None):
        if duplicate_partner:
            raise ValidationError(
                _(
                    "The customer or company cannot be saved because this phone number is already used by: %s. Please enter a different number."
                )
                % (duplicate_partner.display_name,)
            )

        raise ValidationError(
            _(
                "The customer or company cannot be saved because the same phone number appears more than once in this operation. Please enter a different number."
            )
        )

    @api.model
    def _find_partner_with_duplicate_phone(self, normalized_numbers, excluded_partner_ids=None):
        if not normalized_numbers:
            return self.env["res.partner"]

        domain = [
            ("id", "not in", list(excluded_partner_ids or [])),
            ("parent_id", "=", False),
            "|",
            ("type", "=", False),
            ("type", "=", "contact"),
            "|",
            ("phone_unique_normalized", "in", list(normalized_numbers)),
            ("mobile_unique_normalized", "in", list(normalized_numbers)),
        ]
        return self.with_context(active_test=False).search(domain, limit=1)

    @api.model
    def _check_duplicate_phones_for_payloads(self, payloads):
        seen_numbers = {}

        for payload in payloads:
            normalized_numbers = payload["normalized_numbers"]
            if not normalized_numbers:
                continue

            for number in normalized_numbers:
                duplicate_payload = seen_numbers.get(number)
                if duplicate_payload and duplicate_payload["token"] != payload["token"]:
                    self._raise_duplicate_phone_error()
                seen_numbers[number] = payload

            duplicate_partner = self._find_partner_with_duplicate_phone(
                normalized_numbers,
                excluded_partner_ids=payload["excluded_partner_ids"],
            )
            if duplicate_partner:
                self._raise_duplicate_phone_error(duplicate_partner)

    @api.model_create_multi
    def create(self, vals_list):
        payloads = []
        prepared_vals_list = []

        for index, original_values in enumerate(vals_list):
            values = self._prepare_phone_values(original_values)
            self._validate_phone_values(values)
            prepared_vals_list.append(values)

            if not self._is_unique_phone_target(values=values):
                continue

            normalized_numbers = self._get_unique_phone_numbers(values=values)
            if not normalized_numbers:
                continue

            payloads.append(
                {
                    "token": f"create-{index}",
                    "normalized_numbers": normalized_numbers,
                    "excluded_partner_ids": [],
                }
            )

        if payloads:
            self._check_duplicate_phones_for_payloads(payloads)

        return super().create(prepared_vals_list)

    def write(self, values):
        values = self._prepare_phone_values(values)

        if not {"phone", "mobile", "parent_id", "type"} & set(values):
            return super().write(values)

        self._validate_phone_values(values)
        payloads = []

        for partner in self:
            if not self._is_unique_phone_target(values=values, partner=partner):
                continue

            normalized_numbers = self._get_unique_phone_numbers(values=values, partner=partner)
            if not normalized_numbers:
                continue

            payloads.append(
                {
                    "token": f"write-{partner.id}",
                    "normalized_numbers": normalized_numbers,
                    "excluded_partner_ids": [partner.id],
                }
            )

        if payloads:
            self._check_duplicate_phones_for_payloads(payloads)

        return super().write(values)
