from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class ReportTax(models.AbstractModel):
    _inherit = "report.accounting_pdf_reports.report_tax"

    def _unit_config(self, form):
        unit = form.get("currency_unit") or "base_decimal"
        if unit == "million":
            return 1000000.0, 2
        if unit == "thousand":
            return 1000.0, 2
        if unit == "base":
            return 1.0, 0
        return 1.0, 2

    def _format_tax_amount(self, value, form=None):
        factor, decimals = self._unit_config(form or {})
        value = (value or 0.0) / factor
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            value = 0.0
        amount = ("{:,.%sf}" % decimals).format(abs(value))
        return "%s-" % amount if value < 0 else amount

    def _tax_value_class(self, value):
        value = value or 0.0
        currency = self.env.company.currency_id
        if currency and currency.is_zero(value):
            return "o_tax_muted"
        return "o_tax_negative" if value < 0 else ""

    def _period_label(self, form):
        date_from = form.get("date_from")
        date_to = form.get("date_to")
        start = fields.Date.to_date(date_from) if date_from else False
        end = fields.Date.to_date(date_to) if date_to else False
        if start and end and start.day == 1 and start.year == end.year and start.month == end.month:
            return format_date(self.env, end, date_format="MMMM yyyy")
        if start and end:
            return "%s - %s" % (date_from, date_to)
        return date_to or date_from or ""

    def _section(self, key, label, amount, lines=None, tax_ids=None, drilldown_type=None):
        return {
            "key": key,
            "label": label,
            "amount": amount or 0.0,
            "row_type": "section",
            "lines": lines or [],
            "tax_ids": tax_ids or [],
            "tax_ids_csv": ",".join(str(tax_id) for tax_id in (tax_ids or [])),
            "drilldown_type": drilldown_type,
        }

    def _line(self, key, label, amount, tax_ids=None, drilldown_type=None):
        return {
            "key": key,
            "label": label,
            "amount": amount or 0.0,
            "row_type": "line",
            "tax_ids": tax_ids or [],
            "tax_ids_csv": ",".join(str(tax_id) for tax_id in (tax_ids or [])),
            "drilldown_type": drilldown_type,
        }

    @api.model
    def get_lines(self, options):
        """Keep the tax identifier on every report row for the journal-item link.

        The parent report only exposes the tax display name and amounts.  That is
        sufficient for printing, but not for a reliable drilldown because tax
        names are not necessarily unique.  This follows its calculation while
        retaining the source tax ID.
        """
        taxes = {}
        for tax in self.env["account.tax"].search([("type_tax_use", "!=", "none")]):
            if tax.children_tax_ids:
                for child in tax.children_tax_ids:
                    if child.type_tax_use != "none":
                        continue
                    taxes[child.id] = {
                        "tax_id": child.id,
                        "tax": 0,
                        "net": 0,
                        "name": child.name,
                        "type": tax.type_tax_use,
                    }
            else:
                taxes[tax.id] = {
                    "tax_id": tax.id,
                    "tax": 0,
                    "net": 0,
                    "name": tax.name,
                    "type": tax.type_tax_use,
                }

        self.with_context(
            date_from=options["date_from"],
            date_to=options["date_to"],
            state=options["target_move"],
            strict_range=True,
        )._compute_from_amls(options, taxes)
        groups = {tax_type: [] for tax_type in ("sale", "purchase")}
        for tax in taxes.values():
            if tax["tax"]:
                groups[tax["type"]].append(tax)
        return groups

    def _tax_lines_by_type(self, lines, tax_type):
        rows = []
        for idx, tax in enumerate(lines.get(tax_type) or [], start=1):
            rows.append({
                "idx": idx,
                "tax_id": tax.get("tax_id"),
                "name": tax.get("name") or "",
                "net": tax.get("net") or 0.0,
                "tax": tax.get("tax") or 0.0,
            })
        return rows

    def _numbered_tax_label(self, row, rows, suffix=""):
        label = row["name"]
        if suffix:
            label = "%s %s" % (label, suffix)
        if len(rows) > 1:
            return "%s. %s" % (row["idx"], label)
        return label

    def _vat_return_sections(self, lines):
        sale_rows = self._tax_lines_by_type(lines, "sale")
        purchase_rows = self._tax_lines_by_type(lines, "purchase")
        sale_tax_ids = [row["tax_id"] for row in sale_rows if row.get("tax_id")]
        purchase_tax_ids = [row["tax_id"] for row in purchase_rows if row.get("tax_id")]
        sale_net = sum(row["net"] for row in sale_rows)
        sale_tax = sum(row["tax"] for row in sale_rows)
        purchase_net = sum(row["net"] for row in purchase_rows)
        purchase_tax = sum(row["tax"] for row in purchase_rows)

        sections = [
            self._section(
                "sale_base",
                _("Sales VAT (Base)"),
                sale_net,
                [
                    self._line(
                        "sale_base_%s" % row["idx"],
                        self._numbered_tax_label(row, sale_rows, _("(Base)")),
                        row["net"],
                        [row["tax_id"]] if row.get("tax_id") else [],
                        "base",
                    )
                    for row in sale_rows
                ],
                sale_tax_ids,
                "base",
            ),
            self._section(
                "sale_tax",
                _("Sales VAT (Tax)"),
                sale_tax,
                [
                    self._line(
                        "sale_tax_%s" % row["idx"],
                        self._numbered_tax_label(row, sale_rows, _("(Tax)")),
                        row["tax"],
                        [row["tax_id"]] if row.get("tax_id") else [],
                        "tax",
                    )
                    for row in sale_rows
                ],
                sale_tax_ids,
                "tax",
            ),
            self._section(
                "purchase_base",
                _("Purchase VAT (Base)"),
                purchase_net,
                [
                    self._line(
                        "purchase_base_%s" % row["idx"],
                        self._numbered_tax_label(row, purchase_rows, _("(Base)")),
                        row["net"],
                        [row["tax_id"]] if row.get("tax_id") else [],
                        "base",
                    )
                    for row in purchase_rows
                ],
                purchase_tax_ids,
                "base",
            ),
            self._section(
                "purchase_tax",
                _("Purchase VAT (Tax)"),
                purchase_tax,
                [
                    self._line(
                        "purchase_tax_%s" % row["idx"],
                        self._numbered_tax_label(row, purchase_rows, _("(Tax)")),
                        row["tax"],
                        [row["tax_id"]] if row.get("tax_id") else [],
                        "tax",
                    )
                    for row in purchase_rows
                ],
                purchase_tax_ids,
                "tax",
            ),
        ]
        sections.append({
            "key": "net_due",
            "label": _("Net Tax Due"),
            "amount": sale_tax - purchase_tax,
            "row_type": "due",
            "tax_ids": sale_tax_ids + purchase_tax_ids,
            "tax_ids_csv": ",".join(str(tax_id) for tax_id in sale_tax_ids + purchase_tax_ids),
            "drilldown_type": "tax",
            "lines": [
                self._line(
                    "due_sale_tax",
                    _("Total VAT due for the current period"),
                    sale_tax,
                    sale_tax_ids,
                    "tax",
                ),
                self._line(
                    "due_purchase_tax",
                    _("Total prepaid VAT"),
                    purchase_tax,
                    purchase_tax_ids,
                    "tax",
                ),
                self._line(
                    "due_net_tax",
                    _("Net VAT payable or refundable"),
                    sale_tax - purchase_tax,
                    sale_tax_ids + purchase_tax_ids,
                    "tax",
                ),
            ],
        })
        return sections

    def _generic_tax_sections(self, lines):
        sections = []
        labels = {
            "sale": _("Sales Taxes"),
            "purchase": _("Purchase Taxes"),
        }
        for tax_type in ("sale", "purchase"):
            rows = self._tax_lines_by_type(lines, tax_type)
            tax_ids = [row["tax_id"] for row in rows if row.get("tax_id")]
            sections.append(self._section(
                tax_type,
                labels[tax_type],
                sum(row["tax"] for row in rows),
                [
                    self._line(
                        "%s_%s" % (tax_type, row["idx"]),
                        _("%s - Base: %s",
                            self._numbered_tax_label(row, rows),
                            self._format_tax_amount(row["net"], {}),
                        ),
                        row["tax"],
                        [row["tax_id"]] if row.get("tax_id") else [],
                        "tax",
                    )
                    for row in rows
                ],
                tax_ids,
                "tax",
            ))
        return sections

    @api.model
    def _get_report_values(self, docids, data=None):
        if not (data or {}).get("form"):
            raise UserError(_("Form content is missing, this report cannot be printed."))
        values = super()._get_report_values(docids, data=data)
        form = values.get("data") or {}
        lines = values.get("lines") or {"sale": [], "purchase": []}
        if form.get("tax_report_type") == "eg_vat_return":
            sections = self._vat_return_sections(lines)
        else:
            sections = self._generic_tax_sections(lines)
        values.update({
            "tax_period_label": self._period_label(form),
            "tax_report_sections": sections,
            "format_tax_amount": self._format_tax_amount,
            "tax_value_class": self._tax_value_class,
        })
        return values
