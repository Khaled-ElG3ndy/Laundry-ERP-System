/** @odoo-module **/
/**
 * Patches the laundry.order form to inject the LaundryOrderLinePicker
 * widget into the order lines section.
 * Uses the standard Odoo formView override pattern.
 */

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { LaundryOrderLinePicker } from "./widgets/order_line_picker";
import { Component, useRef, onMounted, useState } from "@odoo/owl";

// We mount the picker into the DOM container after the form renders
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
    },
});
