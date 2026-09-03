import os
import re

from odoo.modules.module import get_module_path
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPosScrollPerformance(TransactionCase):
    """Keep the till's scrolling surfaces cheap to paint.

    Scrolling on the POS used to stutter because the styling leaned on effects
    the compositor cannot cache: a blurred backdrop behind the popup footer was
    re-blurred for every scrolled pixel, every product card carried its own
    blurred pseudo element, and `transition: all` made the browser watch every
    animatable property on elements that repeat once per product or order line.
    These checks stop that creeping back in.
    """

    # Stylesheets that end up in the Point of Sale bundle.
    POS_STYLESHEETS = [
        ("fps_pos_theme", "static/src/css/pos_theme.css"),
        ("pos_foam_modern_ui", "static/src/css/pos_foam_modern_ui.css"),
        ("pos_right_panel", "static/src/scss/product_screen.scss"),
        ("pos_right_panel", "static/src/css/cash_drawer_popup.css"),
        ("pos_right_panel", "static/src/css/customer_popup.css"),
        ("pos_laundry_receipt", "static/src/scss/laundry_pos_design_system.scss"),
        ("pos_laundry_receipt", "static/src/scss/laundry_print_overlay.scss"),
        ("pos_laundry_variant_popup", "static/src/scss/pos_laundry_variant_popup.scss"),
    ]

    # The backend tracking dashboard ships in the same file but never renders on
    # the till, so its rules are outside what this guards.
    BACKEND_ONLY_PREFIXES = (".po-workflow", ".po-qr-modal")

    def _stylesheets(self):
        found = []
        for module, relative in self.POS_STYLESHEETS:
            path = get_module_path(module, display_warning=False)
            if not path:
                continue
            full = os.path.join(path, relative)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as handle:
                    found.append((f"{module}/{relative}", handle.read()))
        return found

    def _strip_comments(self, css):
        return re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def test_no_transition_all_on_the_scrolling_surfaces(self):
        offenders = []
        for name, css in self._stylesheets():
            for match in re.finditer(r"transition:\s*all\b", self._strip_comments(css)):
                line = css[: match.start()].count("\n") + 1
                offenders.append(f"{name}:{line}")
        self.assertFalse(
            offenders,
            "`transition: all` is back on the POS; name the properties that "
            "actually animate instead: %s" % ", ".join(offenders),
        )

    def test_no_backdrop_blur_on_the_scrolling_surfaces(self):
        offenders = []
        for name, css in self._stylesheets():
            body = self._strip_comments(css)
            for match in re.finditer(r"([^{}]*)\{([^{}]*)\}", body):
                selector, block = match.group(1), match.group(2)
                if "backdrop-filter" not in block or "backdrop-filter: none" in block:
                    continue
                if any(p in selector for p in self.BACKEND_ONLY_PREFIXES):
                    continue
                offenders.append(f"{name}: {selector.strip()[:60]}")
        self.assertFalse(
            offenders,
            "a blurred backdrop is re-rasterised on every frame the content "
            "behind it moves: %s" % "; ".join(offenders),
        )

    def test_product_cards_do_not_carry_a_blur_filter(self):
        offenders = []
        for name, css in self._stylesheets():
            body = self._strip_comments(css)
            for match in re.finditer(r"([^{}]*)\{([^{}]*)\}", body):
                selector, block = match.group(1), match.group(2)
                if not re.search(r"filter:\s*blur\(", block):
                    continue
                if any(p in selector for p in self.BACKEND_ONLY_PREFIXES):
                    continue
                offenders.append(f"{name}: {selector.strip()[:60]}")
        self.assertFalse(
            offenders,
            "a blur filter gives the element its own rasterised layer; on "
            "anything that repeats per product this shows up as scroll "
            "stutter: %s" % "; ".join(offenders),
        )

    def test_repeated_elements_do_not_pin_a_compositor_layer(self):
        """`will-change` on a repeating element is one permanent layer each."""
        offenders = []
        for name, css in self._stylesheets():
            body = self._strip_comments(css)
            for match in re.finditer(r"([^{}]*)\{([^{}]*)\}", body):
                selector, block = match.group(1), match.group(2)
                if "will-change" not in block or "will-change: auto" in block:
                    continue
                if any(p in selector for p in self.BACKEND_ONLY_PREFIXES):
                    continue
                offenders.append(f"{name}: {selector.strip()[:60]}")
        self.assertFalse(
            offenders,
            "browsers promote an element on their own while a transform or "
            "opacity animation runs; a standing will-change just holds memory: "
            "%s" % "; ".join(offenders),
        )

    def test_the_scrolling_surfaces_are_set_up_for_a_touch_till(self):
        design = dict(self._stylesheets()).get(
            "pos_laundry_receipt/static/src/scss/laundry_pos_design_system.scss", ""
        )
        for surface in (
            ".pos .product-list-container",
            ".pos .order-container",
            ".laundry-pos-popup-body",
        ):
            self.assertIn(surface, design, "%s is not covered" % surface)
        self.assertIn("overscroll-behavior: contain", design)
        self.assertIn("-webkit-overflow-scrolling: touch", design)
