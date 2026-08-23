/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";

/**
 * Extra Arabic terms for POS strings introduced or customized locally.
 *
 * Keeping the source language in English lets Odoo follow the active system
 * language, while these references make every term part of the POS frontend
 * translation catalogue.
 */
export const corePosTranslationTerms = [
    _t("Customer"),
    _t("Qty"),
    _t("% Disc"),
    _t("Price"),
    _t("Pay"),
    _t("Review"),
    _t("Items"),
    _t("Total:"),
    _t("Taxes:"),
    _t("Select Customer"),
    _t("Do you want to change the current customer? Click Select to change it."),
    _t("Please select a customer from the next screen."),
    _t("Select"),
    _t("Cancel"),
    _t("You need to select the customer before taking payment."),
    _t("You need to select the customer before you can validate payment for this order."),
];
