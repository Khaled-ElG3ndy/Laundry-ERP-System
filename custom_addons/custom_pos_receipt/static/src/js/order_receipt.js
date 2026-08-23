/** @odoo-module **/

import { Order } from "@point_of_sale/app/store/models";
import { PrinterService } from "@point_of_sale/app/printer/printer_service";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PaymentScreenStatus } from "@point_of_sale/app/screens/payment_screen/payment_status/payment_status";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";

function normalizeReference(value) {
    return String(value || "").trim();
}

function isBackendLaundryReference(value) {
    return /^INV\/\d+$/.test(normalizeReference(value));
}

function resolveAccountingReference(payload = {}) {
    const accountMove = payload.account_move;
    const accountMoveDisplay = Array.isArray(accountMove) ? accountMove[1] : "";
    const accountMoveString =
        typeof accountMove === "string" && !/^\d+$/.test(accountMove)
            ? accountMove
            : "";
    const candidates = [
        payload.account_move_name,
        payload.invoice_number,
        payload.invoice_name,
        payload.account_move_display_name,
        accountMoveDisplay,
        accountMoveString,
    ].map(normalizeReference);

    return candidates.find(Boolean) || "";
}

function normalizeLineText(value) {
    return String(value || "").trim();
}

function isArabicInterface() {
    const direction = String(
        localization.direction ||
            (typeof document !== "undefined" && document.documentElement?.dir) ||
            ""
    ).toLowerCase();
    const language = String(
        localization.code ||
            localization.language ||
            (typeof document !== "undefined" && document.documentElement?.lang) ||
            (typeof navigator !== "undefined" && navigator.language) ||
            ""
    )
        .replace("_", "-")
        .toLowerCase();
    return direction === "rtl" || language.startsWith("ar");
}

function localizedText(arabic, english) {
    return isArabicInterface() ? arabic : english;
}

function displayMany2one(value) {
    if (Array.isArray(value)) {
        return normalizeLineText(value[1]);
    }
    if (value && typeof value === "object") {
        return normalizeLineText(value.name || value.display_name);
    }
    return normalizeLineText(value);
}

function normalizeCompanyLogo(logo) {
    if (!logo) return "";
    if (String(logo).startsWith("data:")) return logo;
    return `data:image/png;base64,${logo}`;
}

function encodeSvgAsBase64(svgText) {
    const bytes = new TextEncoder().encode(svgText);
    let binary = "";
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
    }
    return window.btoa(binary);
}

/**
 * ZXing's POS QR writer emits a transparent 200 × 200 SVG without a viewBox.
 * Some raster print paths composite the transparent modules against black,
 * while printing the small 22 mm rendering also causes adjacent modules to
 * bleed together. Keep the ZATCA payload untouched and only normalize its
 * vector presentation.
 */
function normalizeQrSvgDataUri(value) {
    const source = String(value || "");
    const prefix = "data:image/svg+xml;base64,";
    if (!source.startsWith(prefix)) return source;

    try {
        const svgText = window.atob(source.slice(prefix.length));
        const documentNode = new DOMParser().parseFromString(svgText, "image/svg+xml");
        const svg = documentNode.documentElement;
        if (svg.localName !== "svg" || documentNode.querySelector("parsererror")) {
            return source;
        }

        const sourceWidth = Number.parseFloat(svg.getAttribute("width")) || 200;
        const sourceHeight = Number.parseFloat(svg.getAttribute("height")) || sourceWidth;
        svg.setAttribute("viewBox", `0 0 ${sourceWidth} ${sourceHeight}`);
        svg.setAttribute("width", "400");
        svg.setAttribute("height", "400");
        svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
        svg.setAttribute("shape-rendering", "crispEdges");

        if (!svg.querySelector("[data-laundry-qr-background]")) {
            const background = documentNode.createElementNS(
                "http://www.w3.org/2000/svg",
                "rect"
            );
            background.setAttribute("data-laundry-qr-background", "true");
            background.setAttribute("x", "0");
            background.setAttribute("y", "0");
            background.setAttribute("width", String(sourceWidth));
            background.setAttribute("height", String(sourceHeight));
            background.setAttribute("fill", "#ffffff");
            background.setAttribute("stroke", "none");
            svg.insertBefore(background, svg.firstChild);
        }

        for (const module of svg.querySelectorAll("rect:not([data-laundry-qr-background])")) {
            module.setAttribute("shape-rendering", "crispEdges");
            module.setAttribute("stroke", "none");
        }

        const normalized = new XMLSerializer().serializeToString(svg);
        return `${prefix}${encodeSvgAsBase64(normalized)}`;
    } catch {
        return source;
    }
}

const PAYMENT_RECEIPT_CSS_URL =
    "/custom_pos_receipt/static/src/css/receipt.css";

const ISOLATED_PAYMENT_RECEIPT_PRINT_CSS = `
    :root {
        color-scheme: light;
    }

    *,
    *::before,
    *::after {
        box-sizing: border-box;
    }

    @page {
        size: 58mm auto;
        margin: 0;
    }

    html {
        width: 100%;
        min-width: 58mm;
        max-width: none;
        height: auto;
        min-height: 0;
        margin: 0;
        padding: 0;
        background: #fff;
        overflow: visible;
    }

    body {
        display: block;
        width: 58mm;
        min-width: 58mm;
        max-width: 58mm;
        height: auto;
        min-height: 0;
        margin: 0 auto;
        padding: 0;
        background: #fff;
        overflow: visible;
    }

    body > .laundry-payment-receipt {
        box-sizing: border-box;
        display: block;
        width: 58mm;
        min-width: 58mm;
        max-width: 58mm;
        flex: 0 0 58mm;
        height: auto;
        min-height: 0;
        margin: 0 auto;
        padding: 2mm;
        position: static;
        inset: auto;
        transform: none;
        overflow: visible;
        box-shadow: none;
        break-before: auto;
        break-after: auto;
        page-break-before: auto;
        page-break-after: auto;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }

    body > .laundry-payment-receipt .custom-pos-payment-receipt__qr-image {
        width: 40mm;
        height: 40mm;
        min-width: 40mm;
        min-height: 40mm;
        max-width: 40mm;
        max-height: 40mm;
        aspect-ratio: 1 / 1;
        object-fit: contain;
        background: #fff;
    }

    @media screen {
        html {
            min-width: 58mm;
        }
    }

    @media print {
        html,
        body {
            height: auto !important;
            min-height: 0 !important;
            padding: 0 !important;
            background: #fff !important;
            overflow: visible !important;
        }

        html {
            width: 100% !important;
            min-width: 58mm !important;
            max-width: none !important;
            margin: 0 !important;
        }

        body {
            width: 58mm !important;
            min-width: 58mm !important;
            max-width: 58mm !important;
            display: block !important;
            margin: 0 auto !important;
        }

        body > .laundry-payment-receipt {
            width: 58mm !important;
            min-width: 58mm !important;
            max-width: 58mm !important;
            height: auto !important;
            min-height: 0 !important;
            margin: 0 auto !important;
            padding: 2mm !important;
            position: static !important;
            inset: auto !important;
            transform: none !important;
            overflow: visible !important;
            box-shadow: none !important;
            break-before: auto !important;
            break-after: auto !important;
            page-break-before: auto !important;
            page-break-after: auto !important;
        }

        body > .laundry-payment-receipt .laundry-receipt-box,
        body > .laundry-payment-receipt .custom-pos-payment-receipt__line,
        body > .laundry-payment-receipt .custom-pos-payment-receipt__qr,
        body > .laundry-payment-receipt .laundry-payment-receipt__footer {
            break-inside: avoid !important;
            page-break-inside: avoid !important;
        }

        body > .laundry-payment-receipt .custom-pos-payment-receipt__section--summary {
            break-inside: auto !important;
            page-break-inside: auto !important;
        }

        body > .laundry-payment-receipt .laundry-payment-receipt__footer {
            position: static !important;
            height: auto !important;
            min-height: 0 !important;
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
            overflow: visible !important;
            break-before: auto !important;
            page-break-before: auto !important;
        }
    }
`;

let paymentReceiptCssPromise;

function escapeHtml(value) {
    return String(value || "").replace(
        /[&<>"']/g,
        (character) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[character]
    );
}

function extractPaymentReceiptCssFromPosDocument() {
    const rules = [];
    for (const styleSheet of document.styleSheets) {
        try {
            for (const rule of styleSheet.cssRules || []) {
                if (
                    rule.cssText.includes(".laundry-payment-receipt") ||
                    rule.cssText.includes(".custom-pos-payment-receipt")
                ) {
                    rules.push(rule.cssText);
                }
            }
        } catch {
            // Cross-origin stylesheets are not required for this receipt.
        }
    }
    return rules.join("\n");
}

async function loadPaymentReceiptCss() {
    if (!paymentReceiptCssPromise) {
        paymentReceiptCssPromise = fetch(PAYMENT_RECEIPT_CSS_URL, {
            credentials: "same-origin",
            cache: "no-cache",
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`Receipt CSS request failed: ${response.status}`);
                }
                return response.text();
            })
            .catch(() => extractPaymentReceiptCssFromPosDocument());
    }
    return paymentReceiptCssPromise;
}

function waitForEvent(target, eventName, timeoutMs = 10000) {
    return new Promise((resolve) => {
        let settled = false;
        const finish = () => {
            if (settled) return;
            settled = true;
            target.removeEventListener(eventName, finish);
            window.clearTimeout(timeout);
            resolve();
        };
        const timeout = window.setTimeout(finish, timeoutMs);
        target.addEventListener(eventName, finish, { once: true });
    });
}

async function waitForPrintDocument(printWindow) {
    const printDocument = printWindow.document;
    if (printDocument.readyState !== "complete") {
        await waitForEvent(printWindow, "load");
    }

    if (printDocument.fonts?.ready) {
        await Promise.race([
            printDocument.fonts.ready.catch(() => undefined),
            new Promise((resolve) => window.setTimeout(resolve, 10000)),
        ]);
    }

    await Promise.all(
        [...printDocument.images].map(async (image) => {
            if (!image.complete) {
                await Promise.race([
                    waitForEvent(image, "load"),
                    waitForEvent(image, "error"),
                ]);
            }
            if (typeof image.decode === "function") {
                await image.decode().catch(() => undefined);
            }
        })
    );

    await new Promise((resolve) =>
        printWindow.requestAnimationFrame(() =>
            printWindow.requestAnimationFrame(resolve)
        )
    );
    await new Promise((resolve) => window.setTimeout(resolve, 300));
}

function getPaymentReceiptTitle(receipt) {
    return normalizeReference(
        receipt.querySelector(
            ".custom-pos-payment-receipt__header-card-value"
        )?.textContent
    ) || _t("Payment Receipt");
}

async function printPaymentReceiptInIsolatedWindow(receipt) {
    const printWindow = window.open(
        "about:blank",
        "_blank",
        "width=500,height=800"
    );
    if (!printWindow) {
        window.alert(_t("Unable to open the print window. Please allow pop-ups."));
        return false;
    }

    const receiptCss = await loadPaymentReceiptCss();
    if (printWindow.closed) return false;

    const receiptClone = receipt.cloneNode(true);
    const title = getPaymentReceiptTitle(receiptClone);
    const direction =
        receiptClone.getAttribute("dir") ||
        localization.direction ||
        document.documentElement.dir ||
        "ltr";
    const language =
        document.documentElement.lang ||
        localization.code ||
        "en_US";
    const printHtml = `<!DOCTYPE html>
        <html dir="${escapeHtml(direction)}" lang="${escapeHtml(language)}">
            <head>
                <meta charset="UTF-8"/>
                <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
                <title>${escapeHtml(title)}</title>
                <style>
                    ${receiptCss}
                    ${ISOLATED_PAYMENT_RECEIPT_PRINT_CSS}
                </style>
            </head>
            <body>${receiptClone.outerHTML}</body>
        </html>`;

    printWindow.document.open();
    printWindow.document.write(printHtml);
    printWindow.document.close();

    await waitForPrintDocument(printWindow);
    if (printWindow.closed) return false;

    const isolatedReceipt = printWindow.document.querySelector(
        "body > .laundry-payment-receipt"
    );
    const forbiddenElements = printWindow.document.querySelectorAll(
        ".pos, .pos-content, .receipt-screen, .pos-receipt-container, " +
            ".render-container, .o_web_client, .o-main-components-container"
    );
    if (!isolatedReceipt || forbiddenElements.length) {
        printWindow.close();
        console.error("The isolated payment receipt document is invalid.");
        return false;
    }

    printWindow.__laundryPaymentReceiptPrintState = {
        ready: true,
        receiptCount: 1,
        forbiddenElementCount: 0,
        width: isolatedReceipt.getBoundingClientRect().width,
        height: isolatedReceipt.getBoundingClientRect().height,
    };
    printWindow.focus();
    printWindow.print();
    return true;
}

function uniqueFilledParts(parts) {
    const seen = new Set();
    return parts.map(normalizeLineText).filter((part) => {
        if (!part || seen.has(part)) return false;
        seen.add(part);
        return true;
    });
}

function buildCompanyAddress(company = {}) {
    return uniqueFilledParts([
        company.street,
        company.street2,
        company.city,
        displayMany2one(company.state_id),
        company.zip,
        displayMany2one(company.country_id),
    ]).join("، ");
}

function buildCompanyTaxInfo(company = {}) {
    const phone = normalizeLineText(company.phone) || normalizeLineText(company.mobile);
    const info = {
        name: normalizeLineText(company.name),
        vat: normalizeLineText(company.vat),
        registry: normalizeLineText(company.company_registry),
        address: buildCompanyAddress(company),
        phone,
    };
    return {
        ...info,
        has_any: Boolean(info.name || info.vat || info.registry || info.address || info.phone),
    };
}

function normalizeCurrencyAtEnd(value) {
    const text = normalizeLineText(value).replace(/\s+/g, " ");
    if (!text) return text;
    return text.replace(
        /(^|[\s:-])(SR|SAR|ر\.?س\.?|﷼)\s+([+-]?\d[\d,]*(?:\.\d+)?)/gi,
        (_match, prefix, symbol, amount) => `${prefix}${amount} ${symbol}`
    );
}

function parseAmount(value) {
    if (value == null) return 0;
    const text = String(value).replace(/[^0-9+\-.,]/g, "").trim();
    if (!text) return 0;
    // remove thousands separators (commas) and normalize decimal point
    const normalized = text.replace(/,/g, "");
    const parsed = parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : 0;
}

function toLatinDigits(value) {
    const arabicDigits = "٠١٢٣٤٥٦٧٨٩";
    const persianDigits = "۰۱۲۳۴۵۶۷۸۹";
    return String(value || "").replace(/[٠-٩۰-۹]/g, (digit) => {
        const arabicIndex = arabicDigits.indexOf(digit);
        return String(arabicIndex >= 0 ? arabicIndex : persianDigits.indexOf(digit));
    });
}

function formatReceiptDateTime(value) {
    try {
        if (value?.isValid && typeof value.toFormat === "function") {
            return toLatinDigits(value.toFormat("yyyy-MM-dd HH:mm:ss"));
        }
        if (value instanceof Date && !Number.isNaN(value.getTime())) {
            const pad = (part) => String(part).padStart(2, "0");
            return [
                value.getFullYear(),
                pad(value.getMonth() + 1),
                pad(value.getDate()),
            ].join("-") + ` ${pad(value.getHours())}:${pad(value.getMinutes())}:${pad(
                value.getSeconds()
            )}`;
        }
    } catch {
        // Fall back to the original formatted value below.
    }
    return toLatinDigits(normalizeLineText(value));
}

function getCurrencyPrecision(pos) {
    const decimals = Number(pos?.currency?.decimal_places);
    if (Number.isInteger(decimals) && decimals >= 0) {
        return 10 ** -decimals;
    }
    return Number(pos?.currency?.rounding) || 0.01;
}

function roundCurrencyAmount(amount, pos) {
    const precision = getCurrencyPrecision(pos);
    if (!precision) return amount;
    return Math.round((Number(amount) || 0) / precision) * precision;
}

function isZeroCurrencyAmount(amount, pos) {
    return Math.abs(roundCurrencyAmount(amount, pos)) < getCurrencyPrecision(pos) / 2;
}

function joinPaymentReceiptText(...parts) {
    return uniqueFilledParts(parts).join("\n");
}

function paymentMethodKey(paymentMethod) {
    return paymentMethod?.id || normalizeLineText(paymentMethod?.name);
}

function isMergeablePaymentLine(line) {
    if (!line || line.is_change || !line.payment_method) {
        return false;
    }
    return !line.get_payment_status?.();
}

function findMergeablePaymentLine(order, paymentMethod) {
    const key = paymentMethodKey(paymentMethod);
    if (!key || !order?.get_paymentlines) {
        return null;
    }
    return (
        order
            .get_paymentlines()
            .find(
                (line) =>
                    isMergeablePaymentLine(line) &&
                    paymentMethodKey(line.payment_method) === key
            ) || null
    );
}

function mergeDuplicatePaymentLines(order, { removeEmpty = true } = {}) {
    if (!order?.get_paymentlines) {
        return false;
    }

    const groups = new Map();
    const duplicateLines = [];
    const emptyLines = [];
    let selectedReplacement = null;

    for (const line of [...order.get_paymentlines()]) {
        if (!isMergeablePaymentLine(line)) {
            continue;
        }

        if (isZeroCurrencyAmount(line.get_amount(), order.pos)) {
            emptyLines.push(line);
            continue;
        }

        const key = paymentMethodKey(line.payment_method);
        if (!key) {
            continue;
        }

        const existing = groups.get(key);
        if (!existing) {
            groups.set(key, {
                line,
                amount: line.get_amount(),
                ticket: line.ticket,
                cashier_receipt: line.cashier_receipt,
            });
            continue;
        }

        existing.amount += line.get_amount();
        existing.ticket = joinPaymentReceiptText(existing.ticket, line.ticket);
        existing.cashier_receipt = joinPaymentReceiptText(
            existing.cashier_receipt,
            line.cashier_receipt
        );
        duplicateLines.push(line);
        if (line.selected) {
            selectedReplacement = existing.line;
        }
    }

    for (const group of groups.values()) {
        group.line.set_amount(roundCurrencyAmount(group.amount, order.pos));
        group.line.ticket = group.ticket || "";
        group.line.cashier_receipt = group.cashier_receipt || "";
    }

    const removableLines = removeEmpty ? [...duplicateLines, ...emptyLines] : duplicateLines;
    for (const line of removableLines) {
        if (line.selected && !selectedReplacement) {
            selectedReplacement = undefined;
        }
        order.remove_paymentline(line);
    }

    if (selectedReplacement) {
        order.select_paymentline(selectedReplacement);
    }

    return duplicateLines.length > 0 || (removeEmpty && emptyLines.length > 0);
}

function getReceiptPaymentLineAmount(line) {
    if (typeof line?.get_amount === "function") {
        return line.get_amount();
    }
    return Number(line?.amount) || 0;
}

function isReceiptCashPaymentLine(line) {
    return Boolean(line?.payment_method?.is_cash_count || line?.is_cash_count);
}

function getReceiptPaymentLineKey(line) {
    return (
        paymentMethodKey(line?.payment_method) ||
        line?.payment_method_id ||
        normalizeLineText(line?.name)
    );
}

function getReceiptPaymentLineName(line) {
    return normalizeLineText(line?.name || line?.payment_method?.name);
}

function summarizeReceiptPaymentLines(paymentLines, changeAmount = 0, pos) {
    const groups = [];
    const groupByKey = new Map();

    for (const line of paymentLines || []) {
        if (!line || line.is_change) {
            continue;
        }

        const amount = getReceiptPaymentLineAmount(line);
        if (isZeroCurrencyAmount(amount, pos)) {
            continue;
        }

        const key = getReceiptPaymentLineKey(line);
        const name = getReceiptPaymentLineName(line);
        if (!key || !name) {
            continue;
        }

        let group = groupByKey.get(key);
        if (!group) {
            group = {
                key,
                name,
                amount: 0,
                ticket: "",
                is_cash_count: isReceiptCashPaymentLine(line),
            };
            groupByKey.set(key, group);
            groups.push(group);
        }

        group.amount += amount;
        group.ticket = joinPaymentReceiptText(group.ticket, line.ticket);
        group.is_cash_count = group.is_cash_count || isReceiptCashPaymentLine(line);
    }

    let remainingChange = Math.max(0, Number(changeAmount) || 0);
    const reduceChangeFromGroup = (group) => {
        if (!group || remainingChange <= 0 || group.amount <= 0) {
            return;
        }
        const reduction = Math.min(group.amount, remainingChange);
        group.amount = roundCurrencyAmount(group.amount - reduction, pos);
        remainingChange = roundCurrencyAmount(remainingChange - reduction, pos);
    };

    for (const group of groups.filter((group) => group.is_cash_count).reverse()) {
        reduceChangeFromGroup(group);
    }
    for (const group of groups.filter((group) => !group.is_cash_count).reverse()) {
        reduceChangeFromGroup(group);
    }

    return {
        paymentlines: groups
            .map((group) => ({
                name: group.name,
                amount: roundCurrencyAmount(group.amount, pos),
                ticket: group.ticket,
                is_cash_count: group.is_cash_count,
            }))
            .filter((group) => !isZeroCurrencyAmount(group.amount, pos)),
        change: Math.max(0, roundCurrencyAmount(remainingChange, pos)),
    };
}

function isStrictNoChangeOrder(order) {
    return roundCurrencyAmount(order?.get_total_with_tax?.() || 0, order?.pos) > 0;
}

function getStrictPaymentDifference(order) {
    return roundCurrencyAmount(order?.get_due?.() || 0, order?.pos);
}

function hasRemainingStrictPaymentDue(order) {
    return getStrictPaymentDifference(order) > getCurrencyPrecision(order?.pos) / 2;
}

function getLineStrictMaxAmount(order, line) {
    const currentAmount = line?.get_amount?.() || 0;
    return Math.max(0, roundCurrencyAmount(currentAmount + getStrictPaymentDifference(order), order?.pos));
}

function formatNumberBufferAmount(amount, pos) {
    const decimals = Number(pos?.currency?.decimal_places);
    if (Number.isInteger(decimals) && decimals >= 0) {
        return roundCurrencyAmount(amount, pos).toFixed(decimals);
    }
    return String(roundCurrencyAmount(amount, pos));
}

function notifyNoChangeAllowed(screen, message) {
    screen.notification?.add(
        message ||
            localizedText(
                "يجب أن يكون المبلغ المدفوع مساويا لإجمالي الفاتورة. لا يسمح بدفع مبلغ زائد.",
                "The paid amount must equal the invoice total. Overpayment is not allowed."
            ),
        3000
    );
}

function enforceNoChangeOnSelectedPaymentLine(screen) {
    const order = screen.currentOrder;
    const line = screen.selectedPaymentLine;
    if (!isStrictNoChangeOrder(order) || !line || line.get_payment_status?.()) {
        return false;
    }

    const difference = getStrictPaymentDifference(order);
    if (difference >= -getCurrencyPrecision(order?.pos) / 2) {
        return false;
    }

    const maxAmount = getLineStrictMaxAmount(order, line);
    line.set_amount(maxAmount);
    screen.numberBuffer?.set?.(formatNumberBufferAmount(maxAmount, order?.pos));
    notifyNoChangeAllowed(
        screen,
        localizedText(
            "لا يمكن أن يتجاوز الدفع إجمالي الفاتورة. تم تعديل المبلغ.",
            "Payment cannot exceed the invoice total. The amount was adjusted."
        )
    );
    return true;
}

function showStrictPaymentError(screen) {
    const order = screen.currentOrder;
    const difference = getStrictPaymentDifference(order);
    const formattedDifference = screen.env.utils.formatCurrency(Math.abs(difference));
    const body =
        difference < 0
            ? localizedText(
                `الدفع يزيد عن إجمالي الفاتورة بمقدار ${formattedDifference}. قلل مبلغ الدفع.`,
                `Payment exceeds the invoice total by ${formattedDifference}. Reduce the payment amount.`
            )
            : localizedText(
                `يجب دفع المبلغ المتبقي بالضبط: ${formattedDifference}.`,
                `Remaining amount must be paid exactly: ${formattedDifference}.`
            );

    screen.popup.add(ErrorPopup, {
        title: localizedText(
            "يجب أن يساوي الدفع إجمالي الفاتورة",
            "Payment must match the invoice total"
        ),
        body,
    });
}

const SERVICE_PRICE_WITH_CURRENCY_PATTERN =
    /(?:\s*[-–—:]\s*)?([+-]?\d[\d,]*(?:\.\d+)?)\s*(SR|SAR|ر\.?س\.?|﷼)\s*$/i;
const SERVICE_PRICE_AMOUNT_ONLY_PATTERN =
    /\s*[-–—]\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*$/i;

function extractCurrencySymbol(...values) {
    const match = values
        .map((value) => normalizeLineText(value))
        .join(" ")
        .match(/(SR|SAR|ر\.?س\.?|﷼)/i);
    return match ? match[1] : "";
}

function splitSelectionLabelAndPrice(value, fallbackCurrencySymbol = "") {
    const rawText =
        value && typeof value === "object"
            ? value.label || value.text || value.displayText || value.name || value.value
            : value;
    const text = normalizeCurrencyAtEnd(rawText);
    const explicitPrice =
        value && typeof value === "object"
            ? normalizeCurrencyAtEnd(value.price || value.priceText)
            : "";
    const match =
        text.match(SERVICE_PRICE_WITH_CURRENCY_PATTERN) ||
        text.match(SERVICE_PRICE_AMOUNT_ONLY_PATTERN);

    if (!match) return { label: text, price: explicitPrice };

    const label = text.slice(0, match.index).replace(/\s*[-–—:]\s*$/, "").trim();
    const currencySymbol = match[2] || fallbackCurrencySymbol;
    const parsedPrice = normalizeCurrencyAtEnd(
        currencySymbol ? `${match[1]} ${currencySymbol}` : match[1]
    );
    return {
        label: label || text,
        price: label ? explicitPrice || parsedPrice : explicitPrice,
    };
}

function buildSelectionSummaryFromAttributes(line) {
    if (!Array.isArray(line?.attributes) || !line.attributes.length) return [];
    return line.attributes
        .map((attribute, index) => {
            const values = (attribute?.valuesForOrderLine || [])
                .map((value) => normalizeLineText(value?.name))
                .filter(Boolean);
            if (!values.length) return null;
            const valueText = values.join(" | ");
            const label = normalizeLineText(attribute?.name);
            if (index === 0 || !label) return valueText;
            return `${label}: ${valueText}`;
        })
        .filter(Boolean);
}

function appendSelectionPrice(text, selection) {
    const priceText = normalizeCurrencyAtEnd(selection?.priceText);
    if (!priceText || text.includes(priceText)) return text;
    return `${text} - ${priceText}`;
}

function buildSelectionSummaryFromSelections(line) {
    if (!Array.isArray(line?.laundryVariantSelections) || !line.laundryVariantSelections.length) return [];
    return line.laundryVariantSelections
        .map((selection, index) => {
            const value = normalizeLineText(selection?.value || selection?.name);
            const group = normalizeLineText(selection?.group);
            const displayText = normalizeLineText(selection?.displayText);
            const baseText =
                displayText || (index === 0 || !group ? value : `${group}: ${value}`);
            return baseText ? normalizeCurrencyAtEnd(appendSelectionPrice(baseText, selection)) : "";
        })
        .filter(Boolean);
}

function splitProductNameAndSelections(productName) {
    const normalizedName = normalizeLineText(productName);
    const match = normalizedName.match(/^(.*?)\s*\(([^()]+)\)\s*$/);
    if (!match) return { productName: normalizedName, summaryLines: [] };
    const baseName = normalizeLineText(match[1]);
    const summaryLines = match[2].split(",").map((value) => normalizeLineText(value)).filter(Boolean);
    return { productName: baseName || normalizedName, summaryLines };
}

function enrichLaundryReceiptLine(line) {
    if (!line || typeof line !== "object") return line;
    const explicitSummary = Array.isArray(line.laundryVariantSummaryLines)
        ? line.laundryVariantSummaryLines.map(normalizeLineText).filter(Boolean)
        : [];
    const selectionSummary = buildSelectionSummaryFromSelections(line);
    const attributeSummary = buildSelectionSummaryFromAttributes(line);
    const parsedName = splitProductNameAndSelections(line.productName);
    const summaryLines =
        selectionSummary.length ? selectionSummary
            : explicitSummary.length ? explicitSummary
                : attributeSummary.length ? attributeSummary
                    : parsedName.summaryLines;
    const currencySymbol = extractCurrencySymbol(line.price, line.unitPrice);
    const normalizedPrice = normalizeCurrencyAtEnd(line.price);
    const normalizedUnitPrice = normalizeCurrencyAtEnd(line.unitPrice);
    const selections = summaryLines
        .map((selection) => splitSelectionLabelAndPrice(selection, currencySymbol))
        .filter((selection) => selection.label)
        .map((s) => ({ label: s.label, price: s.price, price_amount: parseAmount(s.price) }));
    return {
        ...line,
        productName:
            summaryLines.length && parsedName.productName
                ? parsedName.productName
                : line.productName,
        price: normalizedPrice,
        unitPrice: normalizedUnitPrice,
        price_amount: parseAmount(normalizedPrice),
        unit_price_amount: parseAmount(normalizedUnitPrice),
        laundryVariantSummaryLines: selections,
    };
}

patch(Order.prototype, {
    export_for_printing() {
        const result = super.export_for_printing(...arguments);

        const accountingReference = resolveAccountingReference({
            account_move: this.account_move || result.account_move,
            account_move_name: this.account_move_name || result.account_move_name || result.headerData?.account_move_name,
            invoice_number: this.invoice_number || result.invoice_number || result.headerData?.invoice_number,
            invoice_name: this.invoice_name || result.invoice_name,
            account_move_display_name: this.account_move_display_name || result.account_move_display_name,
        });

        const explicitReference =
            normalizeReference(this.x_display_reference) ||
            normalizeReference(this.x_laundry_intake_name) ||
            normalizeReference(this.laundry_intake_name) ||
            normalizeReference(result.headerData?.x_display_reference) ||
            normalizeReference(result.x_display_reference);

        const backendReference =
            explicitReference ||
            [this.name, result.headerData?.name, result.name]
                .map(normalizeReference)
                .find(isBackendLaundryReference) ||
            normalizeReference(result.headerData?.name) ||
            normalizeReference(result.name);

        if (backendReference) {
            result.name = backendReference;
            result.x_display_reference = backendReference;
            if (!result.headerData) result.headerData = {};
            result.headerData.name = backendReference;
            result.headerData.x_display_reference = backendReference;
        }

        if (accountingReference) {
            result.name = accountingReference;
            result.account_move_name = accountingReference;
            result.invoice_number = accountingReference;
            result.receipt_number = accountingReference;
            result.order_reference = backendReference || result.x_display_reference || "";
            if (!result.headerData) result.headerData = {};
            result.headerData.name = accountingReference;
            result.headerData.account_move_name = accountingReference;
            result.headerData.invoice_number = accountingReference;
        } else if (backendReference) {
            result.receipt_number = backendReference;
        }

        if (Array.isArray(result.orderlines)) {
            result.orderlines = result.orderlines.map(enrichLaundryReceiptLine);
        }

        result.localized_date = result.date;
        result.receipt_datetime = formatReceiptDateTime(this.date_order || result.date);
        result.date = result.receipt_datetime;

        const paymentSummary = summarizeReceiptPaymentLines(
            this.paymentlines,
            result.change,
            this.pos
        );
        result.raw_paymentlines = result.paymentlines;
        result.paymentlines = paymentSummary.paymentlines;
        result.change = paymentSummary.change;
        result.payment_summary_is_net = true;

        const partner = this.get_partner();
        if (partner) {
            result.partner = {
                name: normalizeLineText(partner.name || partner.display_name),
                phone: normalizeLineText(partner.phone),
                mobile: normalizeLineText(partner.mobile),
                display_name: normalizeLineText(partner.display_name || partner.name),
            };
        }

        const companyTaxInfo = buildCompanyTaxInfo(result.headerData?.company || this.pos?.company);
        result.company_tax_info = companyTaxInfo;
        if (!result.headerData) result.headerData = {};
        result.headerData.company_tax_info = companyTaxInfo;

        const companyLogo =
            this.pos?.company_logo_base64 ||
            result.headerData.company_logo ||
            normalizeCompanyLogo(result.headerData.company?.logo);
        if (companyLogo) {
            result.company_logo = companyLogo;
            result.headerData.company_logo = companyLogo;
        }

        if (result.qr_code) {
            result.qr_code = normalizeQrSvgDataUri(result.qr_code);
        }
        if (result.headerData?.qr_code) {
            result.headerData.qr_code = normalizeQrSvgDataUri(result.headerData.qr_code);
        }

        result.receipt_direction =
            localization.direction ||
            document.documentElement.dir ||
            "ltr";
        result.receipt_language =
            document.documentElement.lang ||
            localization.code ||
            "en_US";

        return result;
    },
});

patch(PaymentScreenStatus.prototype, {
    get strictPaidText() {
        return this.env.utils.formatCurrency(
            Math.max(0, this.props.order.get_total_paid() - this.props.order.get_change())
        );
    },

    get strictRemainingText() {
        return this.env.utils.formatCurrency(
            Math.max(0, this.props.order.get_due())
        );
    },

    get strictTotalDueText() {
        return this.env.utils.formatCurrency(
            this.props.order.get_total_with_tax() + this.props.order.get_rounding_applied()
        );
    },

    get strictPaidLabel() {
        return localizedText("المدفوع", "Paid");
    },

    get strictRemainingLabel() {
        return localizedText("المتبقي", "Remaining");
    },

    get strictTotalDueLabel() {
        return localizedText("الإجمالي المستحق", "Total Due");
    },

    get strictPaymentPrompt() {
        return localizedText("اختر طريقة دفع.", "Please select a payment method.");
    },
});

patch(PaymentScreen.prototype, {
    async addNewPaymentLine(paymentMethod) {
        const existingLine = findMergeablePaymentLine(this.currentOrder, paymentMethod);
        if (existingLine) {
            mergeDuplicatePaymentLines(this.currentOrder, { removeEmpty: false });
            this.currentOrder.select_paymentline(
                findMergeablePaymentLine(this.currentOrder, paymentMethod) || existingLine
            );
            this.numberBuffer.reset();
            this.notification?.add(
                localizedText(
                    "طريقة الدفع موجودة بالفعل. عدل مبلغ السطر الموجود.",
                    "This payment method is already added. Edit the existing line amount."
                ),
                3000
            );
            return true;
        }

        if (
            isStrictNoChangeOrder(this.currentOrder) &&
            !hasRemainingStrictPaymentDue(this.currentOrder)
        ) {
            notifyNoChangeAllowed(
                this,
                localizedText("تم دفع الفاتورة بالكامل بالفعل.", "The invoice is already fully paid.")
            );
            return false;
        }

        const result = await super.addNewPaymentLine(...arguments);
        if (result) {
            mergeDuplicatePaymentLines(this.currentOrder, { removeEmpty: false });
            enforceNoChangeOnSelectedPaymentLine(this);
        }
        return result;
    },

    updateSelectedPaymentline() {
        const result = super.updateSelectedPaymentline(...arguments);
        mergeDuplicatePaymentLines(this.currentOrder, { removeEmpty: false });
        enforceNoChangeOnSelectedPaymentLine(this);
        return result;
    },

    async _isOrderValid() {
        mergeDuplicatePaymentLines(this.currentOrder);
        if (
            isStrictNoChangeOrder(this.currentOrder) &&
            getStrictPaymentDifference(this.currentOrder) < -getCurrencyPrecision(this.pos) / 2
        ) {
            showStrictPaymentError(this);
            return false;
        }

        const result = await super._isOrderValid(...arguments);
        if (!result || !isStrictNoChangeOrder(this.currentOrder)) {
            return result;
        }

        if (!isZeroCurrencyAmount(getStrictPaymentDifference(this.currentOrder), this.pos)) {
            showStrictPaymentError(this);
            return false;
        }

        return true;
    },

    async _finalizeValidation() {
        mergeDuplicatePaymentLines(this.currentOrder);
        return super._finalizeValidation(...arguments);
    },
});

const originalPreloadImages = PosStore.prototype.preloadImages;
patch(PosStore.prototype, {
    async preloadImages() {
        await originalPreloadImages.apply(this, arguments);
        if (!this.company_logo_base64 && this.company?.id) {
            try {
                const img = new Image();
                img.crossOrigin = "anonymous";
                const logoUrl = `/web/image?model=res.company&id=${this.company.id}&field=logo`;
                await new Promise((resolve, reject) => {
                    img.onload = resolve;
                    img.onerror = reject;
                    img.src = logoUrl;
                });
                const targetWidth = 300;
                const maxHeight = 150;
                let ratio = 1;
                if (img.width !== targetWidth) ratio = targetWidth / img.width;
                if (img.height * ratio > maxHeight) ratio = maxHeight / img.height;
                const width = Math.floor(img.width * ratio);
                const height = Math.floor(img.height * ratio);
                const canvas = document.createElement("canvas");
                canvas.width = width;
                canvas.height = height;
                canvas.getContext("2d").drawImage(img, 0, 0, width, height);
                this.company_logo_base64 = canvas.toDataURL();
            } catch (error) {
                // Ignore logo preload failure
            }
        }
    },
});

patch(PrinterService.prototype, {
    async printWeb(el) {
        if (!el?.classList?.contains("laundry-payment-receipt")) {
            return super.printWeb(...arguments);
        }
        return printPaymentReceiptInIsolatedWindow(el);
    },
});
