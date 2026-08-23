import secrets
from urllib.parse import urlencode

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PosLaundryLabelPrintWizard(models.TransientModel):
    _name = "pos.laundry.label.print.wizard"
    _description = "Laundry Label Print Wizard"

    label_ids = fields.Many2many(
        "pos.laundry.label",
        string="Labels",
        required=True,
    )
    label_count = fields.Integer(
        string="Label Count",
        compute="_compute_label_count",
    )
    pending_count = fields.Integer(
        string="Pending",
        compute="_compute_label_count",
    )
    reprint_count = fields.Integer(
        string="Reprints",
        compute="_compute_label_count",
    )
    user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    access_token = fields.Char(
        default=lambda self: secrets.token_urlsafe(24),
        required=True,
        readonly=True,
        copy=False,
    )

    @api.depends("label_ids", "label_ids.state", "label_ids.print_count")
    def _compute_label_count(self):
        for wizard in self:
            wizard.label_count = len(wizard.label_ids)
            wizard.pending_count = len(
                wizard.label_ids.filtered(lambda label: label.is_pending)
            )
            wizard.reprint_count = len(
                wizard.label_ids.filtered(lambda label: label.print_count > 0)
            )

    @api.constrains("label_ids")
    def _check_labels(self):
        for wizard in self:
            if not wizard.label_ids:
                raise UserError(_("Select at least one label to continue."))

    def _get_batch_url(self, auto_print=False, download=False):
        self.ensure_one()
        if self.user_id != self.env.user:
            raise UserError(_("This print batch belongs to another user."))
        self.label_ids._check_print_access()
        query = urlencode(
            {
                "token": self.access_token,
                "print": "1" if auto_print else "0",
                "download": "1" if download else "0",
            }
        )
        return "/pos_laundry_receipt/labels/batch/%s?%s" % (self.id, query)

    def action_preview(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "name": _("Preview Laundry Labels"),
            "url": self._get_batch_url(),
            "target": "new",
        }

    def action_print(self):
        self.ensure_one()
        return self.label_ids._get_direct_print_action(
            wizard=self,
            close_on_done=True,
        )

    def action_download_pdf(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "name": _("Download Laundry Labels"),
            "url": self._get_batch_url(download=True),
            "target": "new",
        }
