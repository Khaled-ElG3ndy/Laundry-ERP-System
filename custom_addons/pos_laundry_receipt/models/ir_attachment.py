import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Every Point of Sale bundle attachment is stored under this prefix, e.g.
# /web/assets/<unique>/point_of_sale.assets_prod.min.js
ASSET_URL_PREFIX = "/web/assets/"
POS_BUNDLE_MARKER = "point_of_sale."


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        if any(self._is_pos_bundle_url(vals.get("url")) for vals in vals_list):
            self._notify_pos_assets_changed(attachments)
        return attachments

    @api.model
    def _is_pos_bundle_url(self, url):
        url = url or ""
        return url.startswith(ASSET_URL_PREFIX) and POS_BUNDLE_MARKER in url

    @api.model
    def _get_pos_bundle_version(self):
        """Opaque token identifying the POS bundles currently on the server.

        A Point of Sale that reconnects after being offline may have missed the
        broadcast below, because bus notifications are garbage collected after
        about two minutes. Comparing this token against the one the tab booted
        with closes that hole: the tab notices the update by itself instead of
        waiting for a notification that is already gone.
        """
        attachment = self.sudo().search(
            [("url", "=like", ASSET_URL_PREFIX + "%" + POS_BUNDLE_MARKER + "%")],
            order="id desc",
            limit=1,
        )
        return str(attachment.id or 0)

    @api.model
    def _notify_pos_assets_changed(self, attachments=None):
        """Tell every open Point of Sale tab that its bundle is out of date.

        Odoo only broadcasts ``bundle_changed`` for ``web.assets_web``, so an
        open POS keeps running the JavaScript it was loaded with until someone
        refreshes it by hand. The POS side listens for this notification and
        reloads itself (see laundry_pos_assets_watchdog.js).
        """
        if "bus.bus" not in self.env:
            return
        try:
            if self.env.cr.precommit.data.get("pos_laundry_assets_changed_queued"):
                return
            self.env.cr.precommit.data["pos_laundry_assets_changed_queued"] = True
            attachment_ids = ",".join(
                str(attachment_id) for attachment_id in (attachments or self).ids
            )
            version = f"{fields.Datetime.now()}:{attachment_ids}"
            self.env["bus.bus"]._sendone(
                "broadcast",
                "pos_laundry_assets_changed",
                {"version": version},
            )
        except Exception:  # never break asset generation over a notification
            _logger.warning("Could not broadcast the POS asset change.", exc_info=True)
