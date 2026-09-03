from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPosAssetsWatchdog(TransactionCase):
    """The tills that are already open have to end up on the new build.

    A Point of Sale keeps its JavaScript and its product catalogue in memory
    for the whole session, so nothing reaches an open till by itself. Two
    paths cover that: a broadcast when the bundles change, and a version token
    the tab can ask for when it reconnects after being offline, because bus
    notifications are dropped after about two minutes.
    """

    def _pos_bundle_url(self, name="point_of_sale.assets_prod.min.js"):
        return "/web/assets/%s/%s" % (self.env.cr.dbname[:6], name)

    def _queued_notifications(self):
        return [
            entry
            for entry in self.env.cr.precommit.data.get("bus.bus.values", [])
            if "pos_laundry_assets_changed" in entry.get("message", "")
        ]

    def _reset_notifications(self):
        self.env.cr.precommit.data["bus.bus.values"] = []
        self.env.cr.precommit.data.pop("pos_laundry_assets_changed_queued", None)

    # ── The broadcast ─────────────────────────────────────────────────────

    def test_a_new_pos_bundle_tells_the_open_tills(self):
        self._reset_notifications()
        self.env["ir.attachment"].create({
            "name": "point_of_sale.assets_prod.min.js",
            "url": self._pos_bundle_url(),
        })
        self.assertTrue(
            self._queued_notifications(),
            "rebuilding a POS bundle must reach the open tills",
        )

    def test_an_unrelated_attachment_does_not_reload_the_tills(self):
        self._reset_notifications()
        self.env["ir.attachment"].create({
            "name": "some_customer_document.pdf",
            "url": "/web/content/1234",
        })
        self.assertFalse(
            self._queued_notifications(),
            "only POS bundles may trigger a reload",
        )

    def test_a_backend_only_bundle_does_not_reload_the_tills(self):
        self._reset_notifications()
        self.env["ir.attachment"].create({
            "name": "web.assets_backend.min.js",
            "url": "/web/assets/abc1234/web.assets_backend.min.js",
        })
        self.assertFalse(self._queued_notifications())

    # ── The version token ─────────────────────────────────────────────────

    def test_the_version_token_is_reachable_from_the_point_of_sale(self):
        """The tab calls this over RPC, so it has to be public and cheap."""
        version = self.env["pos.session"].get_pos_assets_version()
        self.assertIsInstance(version, str)
        self.assertTrue(version)

    def test_the_version_token_moves_when_the_bundles_are_rebuilt(self):
        before = self.env["pos.session"].get_pos_assets_version()
        self.env["ir.attachment"].create({
            "name": "point_of_sale.assets_prod.min.js",
            "url": self._pos_bundle_url("point_of_sale.assets_prod.v2.min.js"),
        })
        after = self.env["pos.session"].get_pos_assets_version()
        self.assertNotEqual(
            before,
            after,
            "a reconnecting till would not notice the new build",
        )

    def test_the_version_token_is_stable_while_nothing_changes(self):
        """A stable token is what keeps a reconnect from reloading for nothing."""
        first = self.env["pos.session"].get_pos_assets_version()
        self.env["ir.attachment"].create({
            "name": "unrelated.pdf",
            "url": "/web/content/9999",
        })
        self.assertEqual(first, self.env["pos.session"].get_pos_assets_version())
