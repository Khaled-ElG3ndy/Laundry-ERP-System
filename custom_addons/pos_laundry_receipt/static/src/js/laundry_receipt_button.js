/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import {
    deserializeDateTime,
    formatDateTime as formatOdooDateTime,
} from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { PartnerListScreen } from "@point_of_sale/app/screens/partner_list/partner_list";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { patch } from "@web/core/utils/patch";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { Order } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { ConnectionLostError } from "@web/core/network/rpc_service";

const INVALID_ANIMATION_TTL = 220;
const QR_SUCCESS_VIBRATION_PATTERN = [28, 24, 72];
const QR_SCAN_DUPLICATE_WINDOW = 2_500;
const QR_RETRY_UNLOCK_DELAY = 1_400;
const QR_MODAL_CLOSE_DELAY = 120;
const ORDERS_PER_PAGE = 8;
// Safety net: the intake receipt prints even if the label printer stalls.
const LABEL_PRINT_MAX_WAIT = 30_000;
const RECEIPT_PRINT_DIALOG_DELAY = 120;
const RECEIPT_PRINT_FRAME_CLEANUP_DELAY = 120_000;
const REQUIRED_PHONE_DIGITS = 10;
const FREEFORM_PHONE_MAX_LENGTH = 32;
const POS_PARTNER_FIELDS = [
    "name",
    "street",
    "city",
    "state_id",
    "country_id",
    "vat",
    "lang",
    "phone",
    "zip",
    "mobile",
    "email",
    "barcode",
    "write_date",
    "property_account_position_id",
    "property_product_pricelist",
    "parent_name",
    "company_type",
    "is_company",
];
const QR_TYPE_INFO = {
    success: { icon: "fa-check-circle" },
    info: { icon: "fa-info-circle" },
    warning: { icon: "fa-exclamation-triangle" },
    error: { icon: "fa-times-circle" },
};

let successAudioContext;

function getTotalPages(itemCount) {
    return Math.max(1, Math.ceil((itemCount || 0) / ORDERS_PER_PAGE));
}

function getSafePage(page, itemCount) {
    return Math.min(getTotalPages(itemCount), Math.max(1, parseInt(page, 10) || 1));
}

function isArabicInterface() {
    const direction = String(
        localization.direction ||
        (typeof document !== "undefined" && document.documentElement ? document.documentElement.dir : "")
    ).toLowerCase();
    const language = String(
        localization.code ||
        localization.language ||
        (typeof document !== "undefined" && document.documentElement ? document.documentElement.lang : "") ||
        (typeof navigator !== "undefined" ? navigator.language : "") ||
        ""
    ).toLowerCase();
    return language.replace("_", "-").startsWith("ar") || direction === "rtl";
}

function localizeInterfaceText(arabicText, englishText) {
    return isArabicInterface() ? arabicText : englishText;
}

function paginateItems(items, page) {
    const safeItems = Array.isArray(items) ? items : [];
    const safePage = getSafePage(page, safeItems.length);
    const startIndex = (safePage - 1) * ORDERS_PER_PAGE;
    const endIndex = Math.min(startIndex + ORDERS_PER_PAGE, safeItems.length);
    return {
        items: safeItems.slice(startIndex, endIndex),
        page: safePage,
        totalPages: getTotalPages(safeItems.length),
        totalItems: safeItems.length,
        startNumber: safeItems.length ? startIndex + 1 : 0,
        endNumber: endIndex,
    };
}

function hasHtml5QrCodeSupport() {
    return Boolean(
        typeof window !== "undefined" &&
        window.Html5Qrcode &&
        navigator.mediaDevices?.getUserMedia
    );
}

function getHtml5QrCodeClass() {
    return window.Html5Qrcode || null;
}

function getHtml5QrFormats() {
    return window.Html5QrcodeSupportedFormats || null;
}

function getRearCamera(cameras = []) {
    return (
        cameras.find((camera) =>
            /back|rear|environment|traseira|trasera|arriere|rueck|후면/i.test(
                camera?.label || ""
            )
        ) || cameras[0] || null
    );
}

function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function getRpcErrorMessage(error, fallbackMessage) {
    return (
        error?.data?.message ||
        error?.message ||
        fallbackMessage
    );
}

function getMany2oneId(value) {
    if (Array.isArray(value)) {
        return value[0] || false;
    }
    if (value && typeof value === "object") {
        return value.id || false;
    }
    return value || false;
}

function normalizePartnerMany2one(value, fallbackRecord = null) {
    const id = getMany2oneId(value) || fallbackRecord?.id || false;
    if (!id) {
        return false;
    }
    if (Array.isArray(value)) {
        return value;
    }
    const name =
        (value && typeof value === "object" && (value.display_name || value.name)) ||
        fallbackRecord?.display_name ||
        fallbackRecord?.name ||
        "";
    return [id, name];
}

function normalizePartnerPricingFields(partner, pos) {
    if (!partner) {
        return partner;
    }
    partner.property_account_position_id = normalizePartnerMany2one(
        partner.property_account_position_id
    );
    partner.property_product_pricelist = normalizePartnerMany2one(
        partner.property_product_pricelist,
        pos?.default_pricelist || null
    );
    return partner;
}

function findRecordById(records, id) {
    if (!id || !Array.isArray(records)) {
        return null;
    }
    return records.find((record) => record.id === id) || null;
}

function afterNextPaint() {
    return new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
}

async function playSuccessChime() {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) {
        return;
    }

    successAudioContext = successAudioContext || new AudioContextClass();
    if (successAudioContext.state === "suspended") {
        try {
            await successAudioContext.resume();
        } catch {
            return;
        }
    }

    const now = successAudioContext.currentTime;
    const masterGain = successAudioContext.createGain();
    masterGain.connect(successAudioContext.destination);
    masterGain.gain.setValueAtTime(0.0001, now);
    masterGain.gain.exponentialRampToValueAtTime(0.2, now + 0.04);
    masterGain.gain.exponentialRampToValueAtTime(0.0001, now + 0.52);

    const shimmer = successAudioContext.createOscillator();
    shimmer.type = "triangle";
    shimmer.frequency.setValueAtTime(880, now);
    shimmer.frequency.exponentialRampToValueAtTime(1320, now + 0.24);
    shimmer.connect(masterGain);
    shimmer.start(now);
    shimmer.stop(now + 0.26);

    const body = successAudioContext.createOscillator();
    body.type = "sine";
    body.frequency.setValueAtTime(660, now + 0.12);
    body.frequency.exponentialRampToValueAtTime(990, now + 0.4);
    body.connect(masterGain);
    body.start(now + 0.1);
    body.stop(now + 0.44);
}

function triggerSuccessVibration() {
    if (navigator.vibrate) {
        navigator.vibrate(QR_SUCCESS_VIBRATION_PATTERN);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// LaundryReceiptPopup
// ─────────────────────────────────────────────────────────────────────────────

export class LaundryReceiptPopup extends AbstractAwaitablePopup {
    static template = "pos_laundry_receipt.LaundryReceiptPopup";
    static classes = ["o_laundry_receipt_popup_wrapper"];
    static defaultProps = {
        title: _t("Laundry Intake"),
        confirmText: _t("Save and Print"),
        cancelText: _t("Cancel"),
    };

    setup() {
        super.setup();

        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.popup = useService("popup");
        this.searchInputRef = useRef("customerSearchInput");
        this.searchCloseTimer = null;
        this.isUnmounted = false;

        const partners = this.getPartnersList({ sort: false });

        this.state = useState({
            partners: partners,
            customer_search: "",
            search_menu_open: false,
            selected_partner_id: "",
            partner_phone: "",
            delivery_date: new Date().toISOString().slice(0, 16),
            priority: "normal",
            note: "",
            show_create_customer: false,
            // Fixed by the till, not chosen by the cashier: retail creates
            // individuals, the hotel counter creates companies.
            customer_type: this.pos?.config?.is_hotel_pos ? "company" : "person",
            new_customer_name: "",
            new_customer_phone: "",
            duplicate_phone_info: null,
            creating_customer: false,
            invalidSubmit: false,
            errors: {
                selected_partner_id: "",
                delivery_date: "",
                new_customer_name: "",
                new_customer_phone: "",
            },
        });
        this.duplicateLookupToken = 0;

        // The cashier already picked the customer on the order itself, so carry
        // that choice in rather than making them find the same person a second
        // time. selectPartner() is reused so the phone number and the search
        // box are filled exactly as they would be by a manual pick.
        const orderPartner = this.getOrderPartner();
        if (orderPartner) {
            this.selectPartner(orderPartner);
        }

        onMounted(() => this.schedulePartnerSort());
        onWillUnmount(() => {
            this.isUnmounted = true;
        });
    }

    /**
     * The customer currently set on the order this popup was opened for, or
     * null when none has been chosen yet.
     */
    get isHotelPos() {
        return Boolean(this.pos?.config?.is_hotel_pos);
    }

    get defaultCustomerType() {
        return this.isHotelPos ? "company" : "person";
    }

    getOrderPartner() {
        let partner = null;
        try {
            partner =
                this.props.order?.get_partner?.() ||
                this.pos?.get_order?.()?.get_partner?.() ||
                null;
        } catch {
            partner = null;
        }
        if (!partner?.id) {
            return null;
        }
        // Prefer the record from the loaded list so the search box, the select
        // and the saved payload all agree on one instance.
        return this.state.partners.find((p) => p.id === partner.id) || partner;
    }

    getPartnersList({ sort = true } = {}) {
        let partners = [];

        try {
            if (this.pos?.db?.partner_by_id) {
                partners = Object.values(this.pos.db.partner_by_id);
            } else if (Array.isArray(this.pos?.partners)) {
                partners = this.pos.partners;
            } else if (this.pos?.models?.["res.partner"]?.getAll) {
                partners = this.pos.models["res.partner"].getAll();
            }
        } catch {
            partners = [];
        }

        partners = Array.isArray(partners) ? partners : [];

        partners = partners.filter((p) => p && p.id && p.name);

        if (!sort) {
            return partners;
        }

        return partners.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    }

    schedulePartnerSort() {
        const schedule = window.requestIdleCallback
            ? (callback) => window.requestIdleCallback(callback, { timeout: 240 })
            : (callback) => window.setTimeout(() => callback({ timeRemaining: () => 0 }), 80);

        schedule(() => {
            if (this.isUnmounted) {
                return;
            }
            const sortedPartners = this.getPartnersList({ sort: true });
            if (sortedPartners.length) {
                this.state.partners = sortedPartners;
            }
        });
    }

    fieldId(name) {
        return `laundry-receipt-${this.props.id}-${name}`;
    }

    fieldClasses({ filled = false, error = false, readonly = false, raised = false } = {}) {
        return [
            "laundry-pos-field",
            filled ? "has-value" : "",
            error ? "has-error" : "",
            readonly ? "is-readonly" : "",
            raised ? "is-raised" : "",
        ]
            .filter(Boolean)
            .join(" ");
    }

    popupClasses() {
        return [
            "laundry-pos-popup-card",
            "laundry-receipt-popup",
            this.state.invalidSubmit ? "laundry-pos-shake" : "",
        ]
            .filter(Boolean)
            .join(" ");
    }

    get selectedPartner() {
        return (
            this.state.partners.find((partner) => partner.id === this.state.selected_partner_id) ||
            null
        );
    }

    get selectedPartnerName() {
        return this.selectedPartner?.name || "";
    }

    get textDirection() {
        return localization.direction || document.documentElement.dir || "ltr";
    }

    get uiText() {
        return {
            customerSection: _t("Customer"),
            searchFieldLabel: _t("Search for a customer"),
            searchEmpty: _t("No Matching Customers"),
            closeForm: _t("Close Form"),
            addCustomer: _t("Add Customer"),
            customerTypeLabel: _t("Customer Type"),
            customerTypeCustomer: isArabicInterface() ? "أفراد" : _t("Individual"),
            customerTypeCompany: isArabicInterface() ? "شركات" : _t("Company"),
            customerName: _t("Customer Name"),
            companyName: _t("Company Name"),
            phone: _t("Phone"),
            phonePlaceholder: this.isTenDigitPhoneModeEnabled
                ? _t("Enter a 10-digit phone number")
                : _t("Enter Phone Number"),
            phoneDigitsHelper: _t("Enter the phone number in 10 boxes."),
            creatingCustomer: _t("Creating..."),
            createCustomer: _t("Create Customer"),
            duplicatePhoneTitle: _t("Phone Number Already in Use"),
            duplicatePhoneSubtitle: _t("This number is already registered to a customer. Select that customer instead of creating a new one."),
            existingCustomerLabel: _t("Existing Customer"),
            duplicatePhoneLabel: _t("Existing Phone Number"),
            useExistingCustomer: _t("Select This Customer"),
            detailsSection: _t("Details"),
            customerSelectPlaceholder: _t("Select a Customer"),
            deliveryDate: _t("Intake Date"),
            priority: _t("Priority"),
            priorityNormal: isArabicInterface() ? "عادي" : _t("Normal"),
            priorityUrgent: isArabicInterface() ? "عاجل" : _t("Urgent"),
            notesSection: _t("Notes"),
            specialNotes: _t("Special Notes"),
            receiptPopupSubtitle: _t("Search for a customer or create a new one for this order."),
        };
    }

    get isSaveDisabled() {
        return (
            !this.state.selected_partner_id ||
            !this.state.delivery_date ||
            this.state.creating_customer
        );
    }

    get filteredPartners() {
        const term = (this.state.customer_search || "").trim().toLowerCase();
        const partners = this.state.partners || [];

        if (!term) {
            return partners.slice(0, 80);
        }

        return partners
            .filter((p) => {
                const name = (p.name || "").toLowerCase();
                const phone = (p.mobile || p.phone || "").toLowerCase();
                return name.includes(term) || phone.includes(term);
            })
            .slice(0, 80);
    }

    get searchResults() {
        const term = (this.state.customer_search || "").trim().toLowerCase();
        const partners = this.state.partners || [];

        if (!term) {
            return partners.slice(0, 12);
        }

        return partners
            .map((partner) => {
                const name = (partner.name || "").toLowerCase();
                const phone = (partner.mobile || partner.phone || "").toLowerCase();
                let score = 0;

                if (name === term) score += 120;
                if (phone === term) score += 110;
                if (name.startsWith(term)) score += 90;
                if (phone.startsWith(term)) score += 80;
                if (name.includes(term)) score += 50;
                if (phone.includes(term)) score += 40;

                return { partner, score };
            })
            .filter((entry) => entry.score > 0)
            .sort((left, right) => {
                if (right.score !== left.score) return right.score - left.score;
                return (left.partner.name || "").localeCompare(right.partner.name || "");
            })
            .slice(0, 12)
            .map((entry) => entry.partner);
    }

    get showSearchResults() {
        return this.state.search_menu_open;
    }

    get selectablePartners() {
        const partners = this.filteredPartners.slice();
        const selectedPartner = this.selectedPartner;

        if (selectedPartner && !partners.some((partner) => partner.id === selectedPartner.id)) {
            partners.unshift(selectedPartner);
        }

        return partners;
    }

    get createCustomerButtonText() {
        return this.state.creating_customer
            ? this.uiText.creatingCustomer
            : this.uiText.createCustomer;
    }

    get isTenDigitPhoneModeEnabled() {
        return Boolean(this.pos?.config?.laundry_require_ten_digit_phone);
    }

    get phoneDigitIndexes() {
        return Array.from({ length: REQUIRED_PHONE_DIGITS }, (_, index) => index);
    }

    clearError(fieldName) {
        if (this.state.errors[fieldName]) {
            this.state.errors[fieldName] = "";
        }
    }

    pulseInvalidSubmit() {
        this.state.invalidSubmit = true;
        setTimeout(() => {
            this.state.invalidSubmit = false;
        }, INVALID_ANIMATION_TTL);
    }

    openSearchMenu() {
        if (this.searchCloseTimer) {
            clearTimeout(this.searchCloseTimer);
            this.searchCloseTimer = null;
        }
        this.state.search_menu_open = true;
    }

    closeSearchMenu() {
        this.searchCloseTimer = setTimeout(() => {
            this.state.search_menu_open = false;
        }, 120);
    }

    onSearchInput(ev) {
        this.state.customer_search = ev.target.value;
        this.openSearchMenu();
        if (!ev.target.value.trim()) {
            this.state.selected_partner_id = "";
            this.state.partner_phone = "";
        }
    }

    onSearchFocus() {
        this.openSearchMenu();
    }

    onSearchClick() {
        this.openSearchMenu();
    }

    onSearchResultMouseDown(ev) {
        const partnerId = parseInt(ev.currentTarget?.dataset?.partnerId, 10);
        if (!partnerId) return;
        const partner = this.state.partners.find((p) => p.id === partnerId);
        this.selectPartner(partner);
    }

    selectPartner(partner) {
        if (!partner) return;
        this.state.selected_partner_id = partner.id;
        this.state.partner_phone = partner.mobile || partner.phone || "";
        this.state.customer_search = partner.name || "";
        this.state.search_menu_open = false;
        this.clearError("selected_partner_id");
    }

    async loadPartnerById(partnerId) {
        const id = Array.isArray(partnerId) ? partnerId[0] : partnerId;
        if (!id) {
            return null;
        }

        try {
            await this.pos._loadPartners([id]);
        } catch (error) {
            console.warn("Loading created customer through POS loader failed:", error);
        }

        let partner = this.pos.db.get_partner_by_id(id);
        if (partner) {
            return partner;
        }

        const records = await this.orm.read("res.partner", [id], POS_PARTNER_FIELDS, {
            context: { active_test: false },
        });
        if (records?.length) {
            this.pos.addPartners(records);
            partner = this.pos.db.get_partner_by_id(id) || records[0];
        }
        return partner || null;
    }

    onDeliveryDateInput(ev) {
        this.state.delivery_date = ev.target.value;
        this.clearError("delivery_date");
    }

    onPriorityChange(ev) {
        this.state.priority = ev.target.value || "normal";
    }

    onNoteInput(ev) {
        this.state.note = ev.target.value;
    }

    onNewCustomerNameInput(ev) {
        this.state.new_customer_name = ev.target.value;
        this.clearError("new_customer_name");
    }

    onNewCustomerPhoneInput(ev) {
        this.state.new_customer_phone = this.normalizePhone(ev.target.value);
        this.clearError("new_customer_phone");
        this.clearDuplicatePhoneState();
        this.updateDuplicatePhoneState();
    }

    async findExistingPartnerByPhone(phone) {
        const normalizedPhone = this.normalizePhone(phone);
        if (!normalizedPhone) {
            return null;
        }

        const partners = this.pos?.db?.partner_by_id
            ? Object.values(this.pos.db.partner_by_id)
            : Array.isArray(this.state.partners)
                ? this.state.partners
                : [];

        const localPartner = (partners || []).find((partner) => {
            if (!partner?.id) {
                return false;
            }
            return [partner.mobile, partner.phone].some(
                (value) => this.normalizePhone(value) === normalizedPhone
            );
        });

        if (localPartner) {
            return localPartner;
        }

        const fields = ["id", "name", "phone", "mobile", "company_type", "is_company"];
        let remotePartners = [];

        try {
            remotePartners = await this.orm.searchRead(
                "res.partner",
                [
                    "&",
                    "&",
                    ["parent_id", "=", false],
                    "|",
                    ["type", "=", false],
                    ["type", "=", "contact"],
                    "|",
                    ["phone_unique_normalized", "=", normalizedPhone],
                    ["mobile_unique_normalized", "=", normalizedPhone],
                ],
                fields,
                {
                    context: { active_test: false },
                    limit: 10,
                }
            );
        } catch {
            remotePartners = await this.orm.searchRead(
                "res.partner",
                [
                    "|",
                    ["phone", "ilike", normalizedPhone],
                    ["mobile", "ilike", normalizedPhone],
                ],
                fields,
                {
                    context: { active_test: false },
                    limit: 10,
                }
            );
        }

        const matchedPartner = (remotePartners || []).find((partner) =>
            [partner.mobile, partner.phone].some(
                (value) => this.normalizePhone(value) === normalizedPhone
            )
        );

        if (matchedPartner) {
            this.pos.addPartners([matchedPartner]);
            return this.pos.db.partner_by_id?.[matchedPartner.id] || matchedPartner;
        }

        return null;
    }

    showDuplicatePhoneError(partner, phone, fallbackMessage = "") {
        const displayPhone = phone || this.state.new_customer_phone || "";
        const partnerName = partner?.name || "";
        const message = partnerName
            ? _t("Phone number %(phone)s is already used by customer %(customer)s.", {
                phone: displayPhone,
                customer: partnerName,
            })
            : fallbackMessage || _t("Phone number %(phone)s is already in use.", {
                phone: displayPhone,
            });

        this.state.duplicate_phone_info = {
            partner: partner || null,
            partnerName,
            partnerPhone: partner?.mobile || partner?.phone || displayPhone,
            phone: displayPhone,
            message,
        };
        this.state.errors.new_customer_phone = message;
    }

    clearDuplicatePhoneState() {
        this.duplicateLookupToken += 1;
        this.state.duplicate_phone_info = null;
    }

    async updateDuplicatePhoneState(phone = this.state.new_customer_phone) {
        const normalizedPhone = this.normalizePhone(phone);
        if (!normalizedPhone || !this.isValidPhone(normalizedPhone)) {
            this.state.duplicate_phone_info = null;
            return null;
        }

        const lookupToken = ++this.duplicateLookupToken;
        const existingPartner = await this.findExistingPartnerByPhone(normalizedPhone).catch(() => null);
        if (lookupToken !== this.duplicateLookupToken) {
            return null;
        }

        if (this.normalizePhone(this.state.new_customer_phone || "") !== normalizedPhone) {
            return null;
        }

        if (existingPartner) {
            this.showDuplicatePhoneError(existingPartner, normalizedPhone);
            return existingPartner;
        }

        this.state.duplicate_phone_info = null;
        return null;
    }

    useDuplicatePhonePartner() {
        if (!this.state.duplicate_phone_info?.partner) {
            return;
        }

        const partner = this.state.duplicate_phone_info.partner;
        this.selectPartner(partner);
        this.state.customer_search = partner.name || partner.mobile || partner.phone || "";
        this.state.show_create_customer = false;
        this.state.customer_type = this.defaultCustomerType;
        this.state.new_customer_name = "";
        this.state.new_customer_phone = "";
        this.clearDuplicatePhoneState();
        this.clearError("new_customer_name");
        this.clearError("new_customer_phone");
        this.notification.add(_t("The existing customer with the same phone number was selected."), {
            type: "success",
        });
    }

    onPartnerChange(ev) {
        const selectedId = parseInt(ev.target.value, 10) || false;
        const partner = this.state.partners.find((p) => p.id === selectedId);

        if (!partner) {
            this.state.selected_partner_id = "";
            this.state.partner_phone = "";
            return;
        }

        this.selectPartner(partner);
    }

    toggleCreateCustomer() {
        this.state.show_create_customer = !this.state.show_create_customer;
        if (!this.state.show_create_customer) {
            this.state.customer_type = this.defaultCustomerType;
            this.state.new_customer_name = "";
            this.state.new_customer_phone = "";
            this.clearError("new_customer_name");
            this.clearError("new_customer_phone");
        }
    }

    normalizePhone(value) {
        const rawValue = String(value || "");
        if (!this.isTenDigitPhoneModeEnabled) {
            return rawValue.slice(0, FREEFORM_PHONE_MAX_LENGTH);
        }
        return rawValue.replace(/\D/g, "").slice(0, REQUIRED_PHONE_DIGITS);
    }

    isValidPhone(phone) {
        if (!this.isTenDigitPhoneModeEnabled) {
            return true;
        }
        return new RegExp(`^\\d{${REQUIRED_PHONE_DIGITS}}$`).test(phone);
    }

    getPhoneDigitValue(index) {
        return (this.state.new_customer_phone || "").charAt(index) || "";
    }

    phoneBoxAriaLabel(index) {
        return `${this.uiText.phone} ${index + 1}`;
    }

    setPhoneDigits(digits) {
        this.state.new_customer_phone = this.normalizePhone(digits);
        this.clearError("new_customer_phone");
    }

    focusPhoneDigit(index) {
        afterNextPaint().then(() => {
            const el = document.getElementById(
                this.fieldId(`new-customer-phone-digit-${index}`)
            );
            el?.focus();
            el?.select?.();
        });
    }

    fillPhoneDigitsFrom(index, value) {
        const digits = String(value || "").replace(/\D/g, "");
        if (!digits) {
            return index;
        }

        const currentDigits = this.phoneDigitIndexes.map((digitIndex) =>
            this.getPhoneDigitValue(digitIndex)
        );
        let nextIndex = index;

        for (const digit of digits) {
            if (nextIndex >= REQUIRED_PHONE_DIGITS) {
                break;
            }
            currentDigits[nextIndex] = digit;
            nextIndex += 1;
        }

        this.setPhoneDigits(currentDigits.join(""));
        return nextIndex;
    }

    onPhoneBoxInput(index, ev) {
        const digits = String(ev.target.value || "").replace(/\D/g, "");
        if (!digits) {
            const currentDigits = this.phoneDigitIndexes.map((digitIndex) =>
                this.getPhoneDigitValue(digitIndex)
            );
            currentDigits[index] = "";
            this.setPhoneDigits(currentDigits.join(""));
            this.clearDuplicatePhoneState();
            return;
        }

        const nextIndex = this.fillPhoneDigitsFrom(index, digits);
        const targetIndex = Math.min(nextIndex, REQUIRED_PHONE_DIGITS - 1);
        this.focusPhoneDigit(targetIndex);
        this.updateDuplicatePhoneState();
    }

    onPhoneBoxKeyDown(index, ev) {
        if (ev.key === "Backspace") {
            ev.preventDefault();
            const currentDigits = this.phoneDigitIndexes.map((digitIndex) =>
                this.getPhoneDigitValue(digitIndex)
            );

            if (currentDigits[index]) {
                currentDigits[index] = "";
                this.setPhoneDigits(currentDigits.join(""));
                return;
            }

            if (index > 0) {
                currentDigits[index - 1] = "";
                this.setPhoneDigits(currentDigits.join(""));
                this.focusPhoneDigit(index - 1);
            }
            return;
        }

        if (ev.key === "ArrowLeft" && index > 0) {
            ev.preventDefault();
            this.focusPhoneDigit(index - 1);
            return;
        }

        if (ev.key === "ArrowRight" && index < REQUIRED_PHONE_DIGITS - 1) {
            ev.preventDefault();
            this.focusPhoneDigit(index + 1);
        }
    }

    onPhoneBoxPaste(index, ev) {
        ev.preventDefault();
        const digits = ev.clipboardData?.getData("text") || "";
        const nextIndex = this.fillPhoneDigitsFrom(index, digits);
        const targetIndex = Math.min(nextIndex, REQUIRED_PHONE_DIGITS - 1);
        this.focusPhoneDigit(targetIndex);
        this.updateDuplicatePhoneState();
    }

    onPhoneBoxFocus(ev) {
        ev.target.select();
    }

    async createCustomer() {
        const name = (this.state.new_customer_name || "").trim();
        const phone = (this.state.new_customer_phone || "").trim();

        if (!name) {
            this.state.errors.new_customer_name = _t("Customer name is required.");
            return;
        }

        if (!phone) {
            this.state.errors.new_customer_phone = _t("Phone number is required.");
            return;
        }

        if (!this.isValidPhone(phone)) {
            this.state.errors.new_customer_phone = _t("The phone number must contain 10 digits.");
            return;
        }

        const existingPartner = await this.updateDuplicatePhoneState(phone);
        if (existingPartner) {
            return;
        }

        this.state.creating_customer = true;

        try {
            const partnerId = await this.orm.create("res.partner", [
                {
                    name: name,
                    company_type: this.state.customer_type,
                    is_company: this.state.customer_type === "company",
                    // The hotel POS lists only contract customers, so without
                    // this the new account would disappear from the screen it
                    // was just created on.
                    ...(this.isHotelPos ? { is_hotel_customer: true } : {}),
                    mobile: phone || false,
                    phone: phone || false,
                    customer_rank: 1,
                },
            ]);

            if (!partnerId) throw new Error("Partner was not created");

            const newPartner = await this.loadPartnerById(partnerId);
            if (!newPartner) {
                throw new Error("Partner was not loaded after creation");
            }

            this.state.partners = this.getPartnersList();
            this.selectPartner(newPartner);
            this.state.customer_type = this.defaultCustomerType;
            this.state.new_customer_name = "";
            this.state.new_customer_phone = "";
            this.state.show_create_customer = false;
            this.clearError("new_customer_name");
            this.clearError("new_customer_phone");
            this.clearError("selected_partner_id");

            this.notification.add(_t("Customer created successfully."), { type: "success" });
        } catch (error) {
            console.error("Create customer failed:", error);
            const errorMessage = getRpcErrorMessage(error, _t("Failed to create the customer."));
            this.state.errors.new_customer_phone = errorMessage;
            await this.popup.add(ErrorPopup, {
                title: _t("Unable to Create Customer"),
                body: errorMessage,
            });
        } finally {
            this.state.creating_customer = false;
        }
    }

    validate() {
        const errors = {
            selected_partner_id: "",
            delivery_date: "",
            new_customer_name: this.state.errors.new_customer_name,
            new_customer_phone: this.state.errors.new_customer_phone,
        };

        if (!this.state.selected_partner_id) {
            errors.selected_partner_id = _t("Select a customer to continue.");
        }
        if (!this.state.delivery_date) {
            errors.delivery_date = _t("Select a delivery date.");
        }

        this.state.errors.selected_partner_id = errors.selected_partner_id;
        this.state.errors.delivery_date = errors.delivery_date;
        this.state.errors.new_customer_name = errors.new_customer_name;
        this.state.errors.new_customer_phone = errors.new_customer_phone;
        return !errors.selected_partner_id && !errors.delivery_date;
    }

    async confirm() {
        if (!this.validate()) {
            this.pulseInvalidSubmit();
            return;
        }
        return super.confirm();
    }

    getPayload() {
        return {
            partner_id: this.state.selected_partner_id,
            partner_name: this.selectedPartnerName || "",
            partner_phone: this.state.partner_phone || "",
            delivery_date: this.state.delivery_date || "",
            priority: this.state.priority || "normal",
            note: this.state.note || "",
        };
    }

    cancel() {
        this.props.close({ confirmed: false, payload: null });
    }
}

export class LaundryReceiptDuplicateWarningPopup extends AbstractAwaitablePopup {
    static template = "pos_laundry_receipt.LaundryReceiptDuplicateWarningPopup";
    static classes = ["o_laundry_receipt_popup_wrapper"];
    static defaultProps = {
        title: _t("Important Warning"),
        confirmText: _t("OK"),
        message: _t("These items were already received and cannot be received again."),
        hint: "",
        items: [],
        badgeText: _t("Warning"),
    };

    get detailItems() {
        return Array.isArray(this.props.items) ? this.props.items.filter(Boolean) : [];
    }

    get hasDetailItems() {
        return this.detailItems.length > 0;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// LaundryReceiptButton
// ─────────────────────────────────────────────────────────────────────────────

export class LaundryReceiptButton extends Component {
    static template = "pos_laundry_receipt.LaundryReceiptButton";

    setup() {
        this.pos = usePos();
        this.popup = useService("popup");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            isProcessing: false,
        });
    }

    get buttonLabel() {
        return _t("Laundry Intake");
    }

    get printPopupBlockedMessage() {
        return _t("The pop-up was blocked. Please allow pop-ups to print.");
    }

    get receiptHtmlText() {
        return {
            browserTitleFallback: _t("Laundry Intake Receipt"),
            companyNameFallback: _t("Foam Plus"),
            logoAlt: _t("Company Logo"),
            receiptTitle: _t("Intake Receipt"),
            orderNumber: _t("Order Number"),
            pickupDate: _t("Intake Date"),
            deliveryDate: _t("Delivery Date"),
            customerDetails: _t("Customer Details"),
            customerName: _t("Customer Name"),
            phone: _t("Phone"),
            itemDetails: _t("Item Details"),
            addedServices: _t("Added Services"),
            lineNumber: _t("#"),
            item: _t("Item"),
            quantity: _t("Quantity"),
            price: _t("Price"),
            subtotal: _t("Subtotal Before Tax"),
            notes: _t("Notes"),
            amountSummary: _t("Amount Summary"),
            subtotalAmount: _t("Subtotal Before Tax"),
            taxAmount: _t("Tax"),
            finalTotal: _t("Final Total"),
            footerMain: _t("Thank you for choosing Foam Plus"),
            footerSub: _t("We Care for Your Clothes"),
            qrCodeLabel: _t("QR Code"),
            qrCodeHint: _t("Scan the code to track the order status."),
            emptyValue: _t("-"),
        };
    }

    getAlreadyReceivedLines(order, lines) {
        if (!order?.hasLaundryLineBeenReceived) {
            return [];
        }
        return lines.filter((line) => order.hasLaundryLineBeenReceived(line));
    }

    getPendingLaundryLines(order, lines) {
        if (!order?.hasLaundryLineBeenReceived) {
            return lines;
        }
        return lines.filter((line) => !order.hasLaundryLineBeenReceived(line));
    }

    isCleanOrder(order) {
        return Boolean(
            order &&
            order.get_orderlines().length === 0 &&
            (!order.paymentlines || order.paymentlines.length === 0) &&
            !order.server_id &&
            !order.finalized &&
            !order.laundry_intake_id
        );
    }

    openCleanOrderAfterIntake(intakeOrder) {
        const reusableBlankOrder = [...(this.pos.get_order_list?.() || [])]
            .reverse()
            .find((candidate) => candidate !== intakeOrder && this.isCleanOrder(candidate));

        const cleanOrder = reusableBlankOrder || this.pos.add_new_order();

        if (cleanOrder && this.pos.get_order?.()?.uid !== cleanOrder.uid) {
            this.pos.set_order(cleanOrder);
        }

        cleanOrder?.save_to_db?.();
        return cleanOrder;
    }

    getLaundryTrackingLabelOrderId(order, intakeResult) {
        const candidates = [
            intakeResult?.pos_order_id,
            intakeResult?.order_id,
            intakeResult?.order_server_id,
            order?.server_id,
        ];
        for (const candidate of candidates) {
            const orderId = Number(candidate);
            if (Number.isInteger(orderId) && orderId > 0) {
                return orderId;
            }
        }
        return false;
    }

    getLabelPrintEnv() {
        return {
            ...(this.env || {}),
            services: {
                ...(this.env?.services || {}),
                orm: this.orm,
                notification: this.notification,
                pos_notification: this.env?.services?.pos_notification || this.notification,
            },
        };
    }

    getPrintFlowText(arabicText, englishText) {
        return localizeInterfaceText(arabicText, englishText);
    }

    openEarlyLabelPrintOverlay() {
        const createOverlay = window.posLaundryCreatePrintOverlay;
        if (typeof createOverlay !== "function") {
            return null;
        }
        try {
            return createOverlay(this.getLabelPrintEnv(), {
                status: this.getPrintFlowText("تجهيز الطباعة", "Preparing printing"),
                message: this.getPrintFlowText(
                    "يتم تجهيز الاستلام قبل إرسال الملصق للطابعة.",
                    "Preparing the intake before sending the label to the printer."
                ),
                progress: 2,
            });
        } catch (error) {
            console.warn("Could not open early print overlay:", error);
            return null;
        }
    }

    updateLabelPrintOverlay(overlay, { statusAr, statusEn, messageAr, messageEn, progress }) {
        if (!overlay?.update) {
            return;
        }
        overlay.update({
            status: this.getPrintFlowText(statusAr, statusEn),
            message: this.getPrintFlowText(messageAr, messageEn),
            progress,
        });
    }

    async closeLabelPrintOverlay(overlay, finalUpdate = null) {
        if (!overlay?.close) {
            return;
        }
        try {
            if (finalUpdate && overlay.update) {
                overlay.update(finalUpdate);
            }
            await overlay.close();
        } catch (error) {
            console.warn("Could not close print overlay:", error);
        }
    }

    async waitForLabelPrint(order, intakeResult, printOverlay = null) {
        try {
            await this.printLaundryTrackingLabelAfterIntake(order, intakeResult, printOverlay);
        } catch (error) {
            // Already reported to the cashier; the receipt opens after this print attempt settles.
            console.warn("Laundry label print failed:", error);
            await this.closeLabelPrintOverlay(printOverlay);
        }
    }

    async waitForReceiptPrintTurn() {
        await new Promise((resolve) => window.setTimeout(resolve, 80));
        await new Promise((resolve) => window.requestAnimationFrame(resolve));
    }

    async printLaundryTrackingLabelAfterIntake(order, intakeResult, printOverlay = null) {
        const orderId = this.getLaundryTrackingLabelOrderId(order, intakeResult);
        if (!orderId) {
            await this.closeLabelPrintOverlay(printOverlay, {
                status: this.getPrintFlowText("تعذر تجهيز الملصق", "Could not prepare label"),
                message: this.getPrintFlowText(
                    "تم حفظ الاستلام، لكن لم يتم العثور على طلب مرتبط للطباعة.",
                    "The intake was saved, but no linked order was found for printing."
                ),
                progress: 100,
                state: "warning",
            });
            this.notification.add(
                _t("The intake was saved, but no linked POS order was found for automatic label printing."),
                { type: "warning", sticky: true }
            );
            return;
        }

        let action;
        try {
            this.updateLabelPrintOverlay(printOverlay, {
                statusAr: "تجهيز بيانات الملصق",
                statusEn: "Preparing label data",
                messageAr: "يتم تجهيز بيانات الملصق من النظام.",
                messageEn: "Preparing label data from the system.",
                progress: 10,
            });
            action = await this.orm.call("pos.order", "get_laundry_label_action", [
                orderId,
                "print",
            ]);
        } catch (error) {
            console.warn("Automatic laundry label action failed:", error);
            await this.closeLabelPrintOverlay(printOverlay, {
                status: this.getPrintFlowText("تعذر تجهيز الملصق", "Could not prepare label"),
                message: getRpcErrorMessage(
                    error,
                    this.getPrintFlowText(
                        "تعذر تجهيز ملصق التتبع للطباعة.",
                        "The tracking label could not be prepared for printing."
                    )
                ),
                progress: 100,
                state: "warning",
            });
            this.notification.add(
                getRpcErrorMessage(
                    error,
                    _t("The intake was saved, but the tracking label could not be prepared for printing.")
                ),
                { type: "warning", sticky: true }
            );
            return;
        }

        const directPrint = window.posLaundryPrintLabelsDirect;
        if (typeof directPrint !== "function") {
            await this.closeLabelPrintOverlay(printOverlay, {
                status: this.getPrintFlowText("الطباعة غير جاهزة", "Printing is not ready"),
                message: this.getPrintFlowText(
                    "الطباعة التلقائية غير جاهزة حاليا. اطبع الملصق من قائمة الانتظار.",
                    "Automatic printing is not ready. Print the label from the queue."
                ),
                progress: 100,
                state: "warning",
            });
            this.notification.add(
                _t("Automatic label printing is not ready. Print the label from the queue."),
                { type: "warning", sticky: true }
            );
            return;
        }

        try {
            await directPrint(
                {
                    ...(this.env || {}),
                    services: {
                        ...(this.env?.services || {}),
                        orm: this.orm,
                        notification: this.notification,
                        pos_notification: this.env?.services?.pos_notification || this.notification,
                    },
                },
                {
                    ...action,
                    params: {
                        ...(action.params || {}),
                        max_wait_ms: LABEL_PRINT_MAX_WAIT,
                        print_overlay: printOverlay,
                    },
                }
            );
        } catch (error) {
            console.warn("Automatic laundry label print failed:", error);
            this.notification.add(
                getRpcErrorMessage(
                    error,
                    _t("The intake was saved, but the tracking label could not be printed automatically.")
                ),
                { type: "warning", sticky: true }
            );
        }
    }

    getDuplicateWarningItems(lines = []) {
        return lines
            .slice(0, 4)
            .map((line) => this.getReceiptLineName(line))
            .filter(Boolean);
    }

    async showDuplicateReceiptWarning(lines = []) {
        const previewItems = this.getDuplicateWarningItems(lines);
        const remainingCount = Math.max((lines?.length || 0) - previewItems.length, 0);
        const hint = remainingCount
            ? `${_t("There are also")} ${remainingCount} ${_t("other items linked to the same order.")}`
            : _t("Review the order before trying again.");

        await this.popup.add(LaundryReceiptDuplicateWarningPopup, {
            title: _t("Laundry Already Received"),
            message: _t("Laundry intake cannot be completed more than once for the same order lines."),
            hint,
            items: previewItems,
            confirmText: _t("Got It"),
        });
    }

    async onClick() {
        if (this.state.isProcessing) {
            return;
        }

        this.state.isProcessing = true;
        let labelPrintOverlay = null;

        try {
            const order = this.pos.get_order();

            if (!order) {
                this.notification.add(_t("No active order was found."), { type: "warning" });
                return;
            }

            const lines = order.get_orderlines();
            if (!lines.length) {
                this.notification.add(
                    _t("Add at least one item before printing the intake receipt."),
                    { type: "warning" }
                );
                return;
            }

            const alreadyReceivedLines = this.getAlreadyReceivedLines(order, lines);
            const pendingLaundryLines = this.getPendingLaundryLines(order, lines);

            if (alreadyReceivedLines.length || order.laundry_intake_id) {
                await this.showDuplicateReceiptWarning(alreadyReceivedLines);
                return;
            }

            // ── 1. Collect popup data ─────────────────────────────────────────
            const resultPopup = await this.popup.add(LaundryReceiptPopup, {
                title: _t("Laundry Intake Receipt"),
                order,
            });

            if (!resultPopup || !resultPopup.confirmed) return;

            const payload = resultPopup.payload || {};
            if (!payload.partner_id) {
                this.notification.add(_t("Please select a valid customer."), { type: "warning" });
                return;
            }

            labelPrintOverlay = this.openEarlyLabelPrintOverlay();

            // ── 2. Apply popup data to the current in-memory order ────────────
            order.laundry_delivery_date = payload.delivery_date || "";
            order.laundry_priority = payload.priority || "normal";
            order.laundry_note = payload.note || "";

            const selectedPartner =
                this.pos?.db?.partner_by_id?.[payload.partner_id] ||
                (Array.isArray(this.pos?.partners)
                    ? this.pos.partners.find((p) => p.id === payload.partner_id)
                    : null);

            if (selectedPartner) {
                order.set_partner(selectedPartner);
            }

            order.save_to_db();
            this.pos.addOrderToUpdateSet();

            const posReference = order.uid || order.name || "";

            try {
                this.updateLabelPrintOverlay(labelPrintOverlay, {
                    statusAr: "حفظ الطلب",
                    statusEn: "Saving order",
                    messageAr: "يتم حفظ الطلب قبل تجهيز ملصق الطباعة.",
                    messageEn: "Saving the order before preparing the print label.",
                    progress: 5,
                });
                await this.pos.sendDraftToServer();
            } catch (pushError) {
                console.error("Draft order push failed:", pushError);
                await this.closeLabelPrintOverlay(labelPrintOverlay, {
                    status: this.getPrintFlowText("فشل حفظ الطلب", "Order save failed"),
                    message: this.getPrintFlowText(
                        "تعذر حفظ الطلب على السيرفر. حاول مرة أخرى.",
                        "Could not save the order on the server. Please try again."
                    ),
                    progress: 100,
                    state: "failed",
                });
                labelPrintOverlay = null;
                this.notification.add(
                    _t("Failed to save the order on the server. Please try again."),
                    { type: "danger" }
                );
                return;
            }

            const serverId = order.server_id || false;

            // ── 4. Build lines payload ────────────────────────────────────────
            const posConfigId = this.pos.config.id;
            const linesPayload = pendingLaundryLines.map((line) => ({
                product_id: line.product?.id || false,
                product_name: this.getReceiptLineName(line),
                detail_lines: this.getReceiptLineDetails(line),
                qty: line.get_quantity(),
                price_unit: line.get_unit_price(),
            }));

            // ── 5. Create the laundry intake on the backend ───────────────────
            let result;
            try {
                this.updateLabelPrintOverlay(labelPrintOverlay, {
                    statusAr: "حفظ استلام المغسلة",
                    statusEn: "Saving laundry intake",
                    messageAr: "يتم إنشاء الاستلام وتجهيز بيانات الملصق.",
                    messageEn: "Creating the intake and preparing label data.",
                    progress: 8,
                });
                result = await this.orm.call(
                    "pos.session",
                    "create_laundry_intake_from_ui",
                    [
                        [
                            {
                                server_id: serverId,
                                partner_id: payload.partner_id,
                                order_name: order.name || "",
                                partner_name: payload.partner_name || "",
                                phone: payload.partner_phone || "",
                                delivery_date: payload.delivery_date || false,
                                priority: payload.priority || "normal",
                                note: payload.note || "",
                                amount_total: order.get_total_with_tax(),
                                pos_config_id: posConfigId,
                                pos_reference: posReference,
                                lines: linesPayload,
                            },
                        ],
                    ]
                );
            } catch (error) {
                console.error("Laundry intake creation failed:", error);
                await this.closeLabelPrintOverlay(labelPrintOverlay, {
                    status: this.getPrintFlowText("فشل حفظ الاستلام", "Intake save failed"),
                    message: this.getPrintFlowText(
                        "تعذر حفظ استلام المغسلة.",
                        "Could not save the laundry intake."
                    ),
                    progress: 100,
                    state: "failed",
                });
                labelPrintOverlay = null;
                this.notification.add(_t("Failed to save the laundry intake."), { type: "danger" });
                return;
            }

            if (!result) {
                await this.closeLabelPrintOverlay(labelPrintOverlay, {
                    status: this.getPrintFlowText("لم يتم حفظ الاستلام", "Intake was not created"),
                    message: this.getPrintFlowText(
                        "لم يتم إنشاء استلام المغسلة.",
                        "The laundry intake was not created."
                    ),
                    progress: 100,
                    state: "failed",
                });
                labelPrintOverlay = null;
                this.notification.add(_t("The laundry intake was not created."), { type: "danger" });
                return;
            }

            // ── 6. Store intake metadata on the local order object ────────────
            order.laundry_intake_id = result.id;
            order.laundry_intake_name = result.name;
            order.laundry_priority = result.priority || payload.priority || "normal";
            order.x_display_reference = result.x_display_reference || result.name || "";
            order.markLaundryLinesReceived?.(pendingLaundryLines, result.name || "");
            order.save_to_db();
            this.pos.addOrderToUpdateSet();

            // ── 6b. Deferred link safety net ──────────────────────────────────
            if (!result.pos_reference && result.id && posReference) {
                try {
                    await this.orm.call("pos.session", "finalize_laundry_order_link", [
                        [],
                        posReference,
                        result.id,
                    ]);
                } catch (linkError) {
                    console.warn("Deferred order link failed (non-fatal):", linkError);
                }
            }

            this.notification.add(_t("Laundry intake saved successfully."), {
                type: "success",
            });

            // ── 7. Clean order, then the label, then the intake receipt ───────
            // These used to run at once, so the receipt window and the label
            // progress card fought over the screen. They are now sequential:
            // the cashier sees the label card over an empty order screen, and
            // the receipt only opens once the labels are done.
            this.updateLabelPrintOverlay(labelPrintOverlay, {
                statusAr: "تجهيز شاشة الطباعة",
                statusEn: "Preparing print screen",
                messageAr: "يتم فتح طلب جديد قبل إرسال الملصق للطابعة.",
                messageEn: "Opening a clean order before sending the label to the printer.",
                progress: 12,
            });
            this.openCleanOrderAfterIntake(order);
            await this.waitForLabelPrint(order, result, labelPrintOverlay);
            labelPrintOverlay = null;
            await this.waitForReceiptPrintTurn();
            await this.printLaundryReceipt(result);
        } finally {
            if (labelPrintOverlay) {
                await this.closeLabelPrintOverlay(labelPrintOverlay);
            }
            this.state.isProcessing = false;
        }
    }

    // ── HTML receipt helpers ──────────────────────────────────────────────────

    escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    formatDateTime(value) {
        if (!value) return this.receiptHtmlText.emptyValue;
        try {
            // Odoo serializes server datetimes as naive UTC strings. Reuse the
            // same deserializer/formatter as the payment receipt so the value
            // is converted to the timezone configured for the current user.
            return formatOdooDateTime(deserializeDateTime(String(value)), {
                format: `${localization.dateFormat} - ${localization.timeFormat}`,
            });
        } catch {
            return value;
        }
    }

    formatAmount(value) {
        return Number(value || 0).toFixed(2);
    }

    formatReceiptMoney(value, currencySymbol) {
        const symbol = String(currencySymbol || "").trim();
        const amount = this.formatAmount(value);
        return symbol ? `${amount} ${symbol}` : amount;
    }

    normalizeCurrencyAtEnd(value) {
        const text = String(value ?? "").trim().replace(/\s+/g, " ");

        if (!text) {
            return text;
        }

        return text.replace(
            /(^|[\s:-])(SR|SAR|ر\.?س\.?|﷼)\s+([+-]?\d[\d,]*(?:\.\d+)?)/gi,
            (_match, prefix, symbol, amount) => `${prefix}${amount} ${symbol}`
        );
    }

    splitReceiptDetail(value, fallbackCurrencySymbol = "") {
        const rawText =
            value && typeof value === "object"
                ? value.label || value.text || value.displayText || value.name || value.value
                : value;
        const text = this.normalizeCurrencyAtEnd(rawText);
        const explicitPrice =
            value && typeof value === "object"
                ? this.normalizeCurrencyAtEnd(value.price || value.priceText)
                : "";
        const match =
            text.match(
                /(?:\s*[-–—:]\s*)?([+-]?\d[\d,]*(?:\.\d+)?)\s*(SR|SAR|ر\.?س\.?|﷼)\s*$/i
            ) ||
            text.match(/\s*[-–—]\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*$/i);

        if (!match) {
            return {
                label: text,
                price: explicitPrice,
            };
        }

        const label = text.slice(0, match.index).replace(/\s*[-–—:]\s*$/, "").trim();
        const currencySymbol = match[2] || fallbackCurrencySymbol;
        const price = this.normalizeCurrencyAtEnd(
            currencySymbol ? `${match[1]} ${currencySymbol}` : match[1]
        );

        return {
            label: label || text,
            price: label ? explicitPrice || price : explicitPrice,
        };
    }

    formatQuantity(value) {
        const number = Number(value || 0);
        return Number.isInteger(number) ? String(number) : number.toFixed(2);
    }

    getReceiptLineDetails(line) {
        if (!line) {
            return [];
        }

        const displayData = line.getDisplayData ? line.getDisplayData() : {};
        const detailLines = Array.isArray(displayData.laundryVariantSummaryLines)
            ? displayData.laundryVariantSummaryLines
            : [];

        return detailLines
            .map((detail) => this.normalizeCurrencyAtEnd(detail))
            .filter(Boolean);
    }

    getReceiptLineName(line) {
        if (!line) {
            return _t("Item");
        }

        const displayData = line.getDisplayData ? line.getDisplayData() : {};

        return (
            displayData.productName ||
            (line.get_full_product_name
                ? line.get_full_product_name()
                : line.product?.display_name || line.product?.name) ||
            _t("Item")
        );
    }

    buildReceiptHtml(data) {
        const text = this.receiptHtmlText;
        const companyName = this.escapeHtml(this.pos.company?.name || text.companyNameFallback);
        const logoUrl = "/pos_laundry_receipt/static/src/img/logo.png";
        const pickupDate = this.escapeHtml(this.formatDateTime(data.pickup_date));
        const deliveryDate = this.escapeHtml(this.formatDateTime(data.delivery_date));
        const partnerName = this.escapeHtml(data.partner_name || text.emptyValue);
        const phone = this.escapeHtml(data.phone || text.emptyValue);
        const note = this.escapeHtml(data.note || "");
        const reference = this.escapeHtml(
            data.x_display_reference || data.name || data.pos_reference || text.emptyValue
        );
        const currencySymbol = data.currency_symbol || "";
        const money = (value) => this.escapeHtml(this.formatReceiptMoney(value, currencySymbol));
        const qrValue =
            data.qr_value ||
            data.qr_reference ||
            data.x_display_reference ||
            data.name ||
            data.pos_reference ||
            "";
        logLaundryDebug("buildReceiptHtml", {
            canonical_reference: reference,
            rendered_reference: reference,
            qr_value: qrValue,
            data_name: data.name,
            data_x_display_reference: data.x_display_reference,
            data_pos_reference: data.pos_reference,
            data_qr_reference: data.qr_reference,
            data_qr_value: data.qr_value,
            data_qr_barcode_url: data.qr_barcode_url,
        });
        const qrImageUrl = this.escapeHtml(
            data.qr_barcode_url ||
            `/report/barcode/?barcode_type=QR&width=220&height=220&value=${encodeURIComponent(
                qrValue
            )}`
        );

        let subtotal = 0;
        if (data.lines) {
            data.lines.forEach((line) => {
                subtotal += line.price_subtotal || 0;
            });
        }
        const tax = Math.max(0, (data.amount_total || 0) - subtotal);
        const total = money(data.amount_total);

        const direction =
            localization.direction ||
            document.documentElement.dir ||
            "ltr";
        const language =
            document.documentElement.lang ||
            localization.code ||
            "en_US";

        const linesHtml = (data.lines || [])
            .map(
                (line, index) => `
                <div class="item-row">
                    <div class="item-row__top">
                        <div class="item-row__heading">
                            <span class="item-row__index">${index + 1}</span>
                            <span class="item-row__name" dir="auto">${this.escapeHtml(line.product_name || "")}</span>
                        </div>
                        <div class="item-row__subtotal" dir="ltr">${money(line.price_subtotal)}</div>
                    </div>
                    <div class="item-row__meta">
                        <span>${this.escapeHtml(text.quantity)}: <bdi>${this.formatQuantity(line.qty)}</bdi></span>
                        <span>${this.escapeHtml(text.price)}: <bdi>${money(line.price_unit)}</bdi></span>
                    </div>
                    ${(line.detail_lines || []).length
                        ? `<div class="item-row__details">
                                ${(line.detail_lines || [])
                            .map((detail, detailIndex) => {
                                const parsedDetail = this.splitReceiptDetail(detail, currencySymbol);
                                return `
                                        <div class="item-row__detail ${detailIndex === 0 ? "item-row__detail--primary" : ""}">
                                            <span class="item-row__detail-label" dir="${this.escapeHtml(direction)}">${this.escapeHtml(parsedDetail.label)}</span>
                                            ${parsedDetail.price
                                        ? `<bdi class="item-row__detail-price">${this.escapeHtml(parsedDetail.price)}</bdi>`
                                        : ""
                                    }
                                        </div>
                                    `;
                            })
                            .join("")}
                            </div>`
                        : ""
                    }
                </div>
            `
            )
            .join("");

        return `
            <html dir="${this.escapeHtml(direction)}" lang="${this.escapeHtml(language)}">
                <head>
                    <meta charset="UTF-8"/>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
                    <title>${reference || this.escapeHtml(text.browserTitleFallback)}</title>
                    <style>
                        * { box-sizing: border-box; }
                        @page {
                            size: 58mm auto;
                            margin: 0;
                        }
                        html {
                            margin: 0;
                            padding: 0;
                            width: 100%;
                            height: auto;
                            background: #ffffff;
                        }
                        body {
                            margin: 0;
                            padding: 0;
                            width: 100%;
                            min-width: 58mm;
                            display: flex;
                            justify-content: center;
                            align-items: flex-start;
                            background: #ffffff;
                            font-family: Tahoma, Arial, sans-serif;
                            color: #1e2f39;
                            direction: ${this.escapeHtml(direction)};
                            -webkit-print-color-adjust: exact;
                            print-color-adjust: exact;
                        }
                        .receipt-shell {
                            width: 58mm;
                            max-width: 58mm;
                            flex: 0 0 58mm;
                            margin: 0 auto;
                            padding: 2.5mm 2mm 3.5mm;
                            background: #ffffff;
                        }
                        .receipt-card {
                            position: relative;
                            overflow: hidden;
                            background: #ffffff;
                            border: none;
                            border-radius: 0;
                            box-shadow: none;
                            padding: 0;
                        }
                        .header-box {
                            display: flex;
                            flex-direction: column;
                            align-items: center;
                            justify-content: center;
                            gap: 8px;
                            padding: 0 0 10px;
                            border-radius: 0;
                            border: none;
                            background: transparent;
                            text-align: center;
                        }
                        .header-text { flex: 1; text-align: center; }
                        .receipt-title {
                            margin: -25px 0 3px;
                            font-size: 18px;
                            font-weight: 900;
                            color: #1b75bb;
                            letter-spacing: 0;
                        }
                        .receipt-subtitle {
                            margin: 0 0 4px;
                            font-size: 10px;
                            font-weight: 700;
                            color: #5f8faa;
                        }
                        .header-text div {
                            font-size: 10px;
                            font-weight: 700;
                            color: #7a8f9d;
                        }
                        .brand-box img {
                            max-width: 34mm;
                            max-height: 16mm;
                            object-fit: contain;
                        }
                        .meta-grid {
                            display: grid;
                            grid-template-columns: 1fr;
                            gap: 6px;
                            margin-bottom: 8px;
                        }
                        .meta-item,
                        .info-box {
                            background: #ffffff;
                            border: 1px solid #d8e3ea;
                            border-radius: 10px;
                            text-align: center;
                            display: flex;
                            flex-direction: column;
                            align-items: center;
                            justify-content: center;
                            padding: 2px;
                        }
                        @media print {
                            .meta-item,
                            .info-box {
                                border: 1.5px solid #000 !important;
                                border-radius: 6px !important;
                            }
                        }
                        .meta-item *,
                        .info-box * {
                            text-align: center !important;
                        }
                        .meta-label, .info-label {
                            font-size: 9px;
                            font-weight: 800;
                            margin-bottom: 3px;
                        }
                        .meta-value, .info-value {
                            font-size: 10px;
                            font-weight: 900;
                            color: #243742;
                            line-height: 1.45;
                            word-break: break-word;
                            unicode-bidi: plaintext;
                        }
                        .section { margin-bottom: 8px; }
                        .section-title {
                            display: inline-flex;
                            align-items: center;
                            padding: 3px 7px;
                            margin-bottom: 6px;
                            border-radius: 999px;
                            border: 1px solid #d6edf9;
                            background: #eef9ff;
                            color: #1469ab;
                            font-size: 9px;
                            font-weight: 900;
                        }
                        .info-grid {
                            display: grid;
                            grid-template-columns: 1fr;
                            gap: 6px;
                        }
                        .items-list {
                            display: flex;
                            flex-direction: column;
                            gap: 6px;
                        }
                        .item-row {
                            overflow: hidden;
                            padding: 0;
                            border: 1px solid #dce8f0;
                            border-radius: 8px;
                            background: #ffffff;
                            box-shadow: 0 1px 2px rgba(19, 59, 87, 0.04);
                        }
                            @media print {
                                .item-row {
                                    border: 1.5px solid #444 !important;
                                    box-shadow: none !important;
                                }
                            }
                        .item-row__top {
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            gap: 8px;
                            min-height: 34px;
                            padding: 7px 8px;
                            background: #ffffff;
                            border-bottom: 1px solid #edf3f7;
                            direction: inherit;
                        }
                        .item-row__heading {
                            display: flex;
                            align-items: flex-start;
                            gap: 6px;
                            flex: 1;
                            min-width: 0;
                        }
                        .item-row__index {
                            display: inline-flex;
                            align-items: center;
                            justify-content: center;
                            min-width: 18px;
                            width: 18px;
                            height: 18px;
                            border-radius: 999px;
                            background: #eaf6fd;
                            color: #1b75bb;
                            font-size: 9px;
                            font-weight: 900;
                            flex-shrink: 0;
                        }
                        .item-row__name {
                            font-size: 11px;
                            font-weight: 900;
                            color: #163247;
                            line-height: 1.45;
                            word-break: break-word;
                            text-align: start;
                            unicode-bidi: plaintext;
                        }
                        .item-row__subtotal {
                            font-size: 10px;
                            font-weight: 900;
                            color: #1b75bb;
                            white-space: nowrap;
                            direction: ltr;
                            unicode-bidi: isolate;
                            text-align: left;
                            flex-shrink: 0;
                        }
                        .item-row__meta {
                            display: flex;
                            flex-wrap: wrap;
                            gap: 5px 10px;
                            margin-top: 0;
                            padding: 7px 8px;
                            background: #f8fbfe;
                            font-size: 10px;
                            font-weight: 800;
                            text-align: start;
                            justify-content: space-between;
                            direction: inherit;
                        }
                        .item-row__meta span {
                            display: inline-flex;
                            align-items: center;
                            gap: 4px;
                            min-width: 0;
                        }
                        .item-row__meta bdi {
                            direction: ltr;
                            unicode-bidi: isolate;
                            white-space: nowrap;
                        }
                        .item-row__details {
                            display: flex;
                            flex-direction: column;
                            gap: 5px;
                            margin-top: 0;
                            padding: 8px;
                            border-radius: 0;
                            background: #ffffff;
                            border: none;
                            border-top: 1px solid #edf3f7;
                            direction: inherit;
                        }
                        .item-row__details::before {
                            content: "${this.escapeHtml(text.addedServices)}";
                            flex-basis: 100%;
                            font-size: 8px;
                            font-weight: 800;
                            line-height: 1;
                            text-align: start;
                        }
                        .item-row__detail {
                            display: flex;
                            align-items: center;
                            justify-content: space-between;
                            gap: 8px;
                            width: 100%;
                            min-height: 20px;
                            margin-top: 0;
                            padding: 5px 7px;
                            border-radius: 7px;
                            border: 1px solid #e1ebf2;
                            background: #fbfdff;
                            color: #294457;
                            font-size: 9px;
                            font-weight: 900;
                            line-height: 1.35;
                            word-break: break-word;
                            text-align: start;
                            unicode-bidi: plaintext;
                        }
                        .item-row__detail-label {
                            min-width: 0;
                            word-break: break-word;
                            text-align: start;
                        }
                        .item-row__detail-price {
                            flex-shrink: 0;
                            color: #1b75bb;
                            direction: ltr;
                            unicode-bidi: isolate;
                            white-space: nowrap;
                            text-align: left;
                        }
                        .item-row__detail + .item-row__detail {
                            margin-top: 0;
                        }
                        .item-row__detail--primary {
                            background: #f1fbf5;
                            border-color: #cdebd8;
                            color: #164f2a;
                        }
                        .note-box {
                            min-height: 0;
                            padding: 7px 8px;
                            border-radius: 8px;
                            border: 1px solid #dcebf5;
                            background: #fbfeff;
                            color: #314854;
                            font-size: 9px;
                            line-height: 1.6;
                            white-space: pre-wrap;
                        }
                        .summary-section {
                            display: flex;
                            flex-direction: column;
                            gap: 4px;
                            margin: 0;
                            padding: 0;
                            border-radius: 0;
                            border: none;
                            background: transparent;
                            border-top: none;
                        }
                        .summary-row {
                            display: flex;
                            justify-content: space-between;
                            align-items: center;
                            gap: 10px;
                            padding: 6px 0;
                            border-bottom: 1px dashed #e3edf4;
                            font-size: 10px;
                        }
                        .summary-label { font-weight: 700;  }
                        .summary-value {
                            font-weight: 900;
                            font-size: 10px;
                            direction: ltr;
                            unicode-bidi: isolate;
                            white-space: nowrap;
                            text-align: left;
                            flex-shrink: 0;
                        }
                        .total-row {
                            margin-top: 4px;
                            padding: 8px;
                            border: none;
                            border-radius: 10px;
                            background: linear-gradient(90deg, #1b75bb 0%, #29a1d7 100%);
                        }
                        .total-label { font-size: 11px; font-weight: 900; color: #ffffff; }
                        .total-row .summary-value { font-size: 13px; color: #ffffff; }
                        .qr-section {
                            margin: 10px 0;
                            padding: 8px 6px;
                            border-radius: 10px;
                            background: #f8fcff;
                            border: 1px dashed #1b75bb;
                            text-align: center;
                        }
                        .qr-label {
                            display: block;
                            margin-bottom: 6px;
                            font-size: 9px;
                            font-weight: 800;
                            color: #1b75bb;
                        }
                        .qr-hint {
                            margin: 0 0 6px;
                            font-size: 8px;
                            font-weight: 700;
                            line-height: 1.5;
                        }
                        .qr-code {
                            max-width: 20mm;
                            height: auto;
                            border-radius: 6px;
                            padding: 3px;
                            background: #ffffff;
                            border: 1px solid #d7e7f1;
                        }
                        .footer-box {
                            margin-top: 10px;
                            padding-top: 8px;
                            border-top: 1px dashed #d7e7f1;
                            text-align: center;
                        }
                        .footer-main { font-size: 10px; font-weight: 900; color: #1b75bb; }
                        .footer-sub { font-size: 8px; font-weight: 700; color: #7d97a6; }
                        @media print {
                            html, body {
                                width: 100%;
                                max-width: none;
                                min-width: 58mm;
                                height: auto;
                                margin: 0;
                                padding: 0;
                                background: #ffffff;
                            }
                            body {
                                display: flex;
                                align-items: flex-start;
                                justify-content: center;
                            }
                            .receipt-shell {
                                width: 58mm;
                                max-width: 58mm;
                                flex: 0 0 58mm;
                                margin: 0 auto;
                                padding: 2.5mm 2mm 3.5mm;
                            }
                        }
                            @media print {
    .section-title {
        border: 1px solid #000 !important;
        background: #fff !important;
        color: #000 !important;
    }
}
    .amountSummaryClsCustom {
        margin-top: 6px !important;
    }
    @media print {
    .item-row__top {
        border-bottom: 1px solid #888 !important;
    }

    .item-row__details {
        border-top: 1px solid #888 !important;
    }
}
    @media print {
    .item-row__detail {
        border: 1px solid #666 !important;
        background: #fff !important;
    }
}
    @media print {
    .qr-section {
        border: 1px dashed #000 !important;
    }
}
@media print {
    .total-row {
        background: transparent !important;
        border-top: 2px solid #000 !important;
        border-bottom: 2px solid #000 !important;
        border-left: none !important;
        border-right: none !important;
        border-radius: 0 !important;
    }

    .total-label,
    .total-row .summary-value {
        color: #000 !important;
    }
}
    @media print {
    .item-row__index {
        background: #fff !important;
        border: 1px solid #000 !important;
        color: #000 !important;
    }
}
                    </style>
                </head>
                <body>
                    <div class="receipt-shell">
                        <div class="receipt-card">
                            <div class="header-box">
                                <div class="brand-box">
                                    <img src="${logoUrl}" alt="${this.escapeHtml(text.logoAlt)}"/>
                                </div>
                                <div class="header-text">
                                    <h1 class="receipt-title">${this.escapeHtml(text.receiptTitle)}</h1>
                                </div>
                            </div>

                            <div class="meta-grid">
                                <div class="meta-item">
                                    <div class="meta-label">${this.escapeHtml(text.orderNumber)}</div>
                                    <div class="meta-value" dir="ltr">${reference}</div>
                                </div>
                                <div class="meta-item">
                                    <div class="meta-label">${this.escapeHtml(text.pickupDate)}</div>
                                    <div class="meta-value" dir="ltr">${pickupDate}</div>
                                </div>
                            </div>

                            <div class="section">
                                <div class="section-title">${this.escapeHtml(text.customerDetails)}</div>
                                <div class="info-grid">
                                    <div class="info-box">
                                        <div class="info-label">${this.escapeHtml(text.customerName)}</div>
                                        <div class="info-value" dir="auto">${partnerName}</div>
                                    </div>
                                    <div class="info-box">
                                        <div class="info-label">${this.escapeHtml(text.phone)}</div>
                                        <div class="info-value" dir="ltr">${phone}</div>
                                    </div>
                                </div>
                            </div>

                            <div class="section">
                                <div class="section-title">${this.escapeHtml(text.itemDetails)}</div>
                                <div class="items-list">${linesHtml}</div>
                            </div>

                            ${note
                ? `
                                <div class="section">
                                    <div class="section-title">${this.escapeHtml(text.notes)}</div>
                                    <div class="note-box">${note}</div>
                                </div>
                            `
                : ""
            }

                            <div class="section">
                               <div class="summary-row total-row">
                                        <span class="summary-label total-label">${this.escapeHtml(text.finalTotal)}</span>
                                        <span class="summary-value total-value">${total}</span>
                                </div>
                                <div class="section-title amountSummaryClsCustom">${this.escapeHtml(text.amountSummary)}</div>
                                <div class="summary-section">
                                    <div class="summary-row">
                                        <span class="summary-label">${this.escapeHtml(text.subtotalAmount)}</span>
                                        <span class="summary-value">${money(subtotal)}</span>
                                    </div>
                                    <div class="summary-row">
                                        <span class="summary-label">${this.escapeHtml(text.taxAmount)}</span>
                                        <span class="summary-value">${money(tax)}</span>
                                    </div>
                                  
                                </div>
                            </div>

                            <div class="qr-section">
                                <div class="qr-label">${this.escapeHtml(text.qrCodeLabel)}</div>
                                <div class="qr-hint">${this.escapeHtml(
                text.qrCodeHint
            )}</div>
                                <img
                                    src="${qrImageUrl}"
                                    alt="QR Code"
                                    class="qr-code"
                                />
                            </div>

                            <div class="footer-box">
                                <div class="footer-main">${this.escapeHtml(text.footerMain)}</div>
                                <div class="footer-sub">${this.escapeHtml(text.footerSub)}</div>
                            </div>
                        </div>
                    </div>
                </body>
            </html>
        `;
    }

    async waitForReceiptDocument(targetWindow) {
        const targetDocument = targetWindow.document;
        if (targetDocument.readyState !== "complete") {
            await Promise.race([
                new Promise((resolve) => {
                    targetWindow.addEventListener("load", resolve, { once: true });
                }),
                new Promise((resolve) => window.setTimeout(resolve, 5000)),
            ]);
        }
        if (targetDocument.fonts?.ready) {
            await Promise.race([
                targetDocument.fonts.ready.catch(() => undefined),
                new Promise((resolve) => window.setTimeout(resolve, 4000)),
            ]);
        }
        await new Promise((resolve) =>
            targetWindow.requestAnimationFrame(() =>
                targetWindow.requestAnimationFrame(resolve)
            )
        );
    }

    async waitForReceiptImages(targetWindow) {
        const images = [...targetWindow.document.images];
        await Promise.all(
            images.map((image) => {
                if (image.complete) {
                    return Promise.resolve();
                }
                return new Promise((resolve) => {
                    image.addEventListener("load", resolve, { once: true });
                    image.addEventListener("error", resolve, { once: true });
                });
            })
        );
    }

    async waitForReceiptImagesAndPrint(targetWindow) {
        await this.waitForReceiptDocument(targetWindow);
        await this.waitForReceiptImages(targetWindow);
        await new Promise((resolve) => window.setTimeout(resolve, RECEIPT_PRINT_DIALOG_DELAY));

        await new Promise((resolve) => {
            let finished = false;
            let timeoutId = null;

            const finish = () => {
                if (finished) {
                    return;
                }
                finished = true;
                if (timeoutId) {
                    window.clearTimeout(timeoutId);
                }
                targetWindow.removeEventListener("afterprint", finish);
                targetWindow.removeEventListener("pagehide", finish);
                resolve();
            };

            timeoutId = window.setTimeout(finish, RECEIPT_PRINT_FRAME_CLEANUP_DELAY);
            targetWindow.addEventListener("afterprint", finish);
            targetWindow.addEventListener("pagehide", finish);

            try {
                targetWindow.focus();
                targetWindow.print();
            } catch (error) {
                console.warn("Laundry receipt print failed:", error);
                finish();
            }
        });
    }

    async printReceiptFromHiddenFrame(html) {
        const frame = document.createElement("iframe");
        frame.setAttribute("aria-hidden", "true");
        frame.setAttribute("tabindex", "-1");
        frame.style.cssText = [
            "position:fixed",
            "left:-10000px",
            "top:0",
            "width:80mm",
            "height:1200px",
            "border:0",
            "opacity:0",
            "pointer-events:none",
        ].join(";");
        document.body.appendChild(frame);

        const frameWindow = frame.contentWindow;
        if (!frameWindow) {
            frame.remove();
            return false;
        }

        try {
            frameWindow.document.open();
            frameWindow.document.write(html);
            frameWindow.document.close();
            await this.waitForReceiptImagesAndPrint(frameWindow);
            return true;
        } finally {
            frame.remove();
        }
    }

    async printLaundryReceipt(data) {
        const html = this.buildReceiptHtml(data);
        return await this.printReceiptFromHiddenFrame(html);
    }
}

ProductScreen.addControlButton({
    component: LaundryReceiptButton,
    condition: function () {
        return true;
    },
});

// ─────────────────────────────────────────────────────────────────────────────
// PendingOrdersButton
// ─────────────────────────────────────────────────────────────────────────────

export class PendingOrdersButton extends Component {
    static template = "pos_laundry_receipt.PendingOrdersButton";

    setup() {
        this.pos = usePos();
    }

    get buttonLabel() {
        return localizeInterfaceText("دفع الفواتير", "Pay Bills");
    }

    async onClick() {
        this.pos.showScreen("PendingOrdersScreen");
    }
}

ProductScreen.addControlButton({
    component: PendingOrdersButton,
    position: ["replace", "SetSaleOrderButton"],
});

// ─────────────────────────────────────────────────────────────────────────────
// PendingOrdersScreen
// ─────────────────────────────────────────────────────────────────────────────

export class PendingOrdersScreen extends Component {
    static template = "pos_laundry_receipt.PendingOrdersScreen";

    setup() {
        this.pos = usePos();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.popup = useService("popup");
        this.scanner = null;
        this.scanLock = false;
        this.toastTimer = null;
        this.highlightTimer = null;
        this.closeModalTimer = null;
        this.lastScanFingerprint = "";
        this.lastScanAt = 0;
        this.scannerElementId = `laundry-qr-reader-${Date.now()}-${Math.round(
            Math.random() * 10_000
        )}`;
        this.state = useState({
            orders: [],
            statuses: [],
            paymentStatuses: [],
            loading: true,
            error: false,
            search: "",
            filter: "all",
            start_date: "",
            end_date: "",
            min_amount: "",
            max_amount: "",
            statusFilter: "all",
            paymentFilter: "all",
            showAdvancedFilters: false,
            updatingOrderIds: {},
            generated_at: false,
            isScannerSupported: hasHtml5QrCodeSupport(),
            scannerVisible: false,
            scannerClosing: false,
            scannerBooting: false,
            scannerProcessing: false,
            scannerError: "",
            scannerFeedback: "",
            scannerHint: "",
            highlightedOrderId: false,
            toastVisible: false,
            toastType: "success",
            toastMessage: "",
            tablePage: 1,
        });

        onMounted(() => {
            this.loadPendingOrders();
        });

        onWillUnmount(() => {
            this._clearToastTimer();
            this._clearHighlightTimer();
            this._clearCloseModalTimer();
            this.scanLock = false;
            void this.stopScanner();
        });
    }

    // ── Computed getters ──────────────────────────────────────────────────────

    get isArabic() {
        return isArabicInterface();
    }

    get textDirection() {
        return this.isArabic ? "rtl" : "ltr";
    }

    get interfaceLang() {
        return this.isArabic ? "ar" : "en";
    }

    get screenClasses() {
        return [
            "po-screen",
            "po-workflow-screen",
            this.isArabic ? "is-rtl" : "is-ltr",
        ].join(" ");
    }

    get backIconClass() {
        return this.isArabic ? "fa fa-arrow-right" : "fa fa-arrow-left";
    }

    get previousPageIconClass() {
        return this.isArabic ? "fa fa-chevron-right" : "fa fa-chevron-left";
    }

    get nextPageIconClass() {
        return this.isArabic ? "fa fa-chevron-left" : "fa fa-chevron-right";
    }

    get formatLocale() {
        return this.isArabic ? "ar-EG" : "en-US";
    }

    get filteredOrders() {
        return this._computeFilteredOrders();
    }

    get tablePagination() {
        return paginateItems(this.filteredOrders, this.state.tablePage);
    }

    get paginatedOrders() {
        return this.tablePagination.items;
    }

    get hasOrders() {
        return this.filteredOrders.length > 0;
    }

    get hasAnyOrders() {
        return this.state.orders.length > 0;
    }

    get orderCount() {
        return this.filteredOrders.length;
    }

    get totalAmount() {
        return this.filteredOrders.reduce(
            (total, order) => total + Number(order.amount_total || 0),
            0
        );
    }

    get receivedCount() {
        return this.state.orders.filter((order) => this.getOrderStatus(order) === "received").length;
    }

    get readyCount() {
        return this.state.orders.filter((order) => this.getOrderStatus(order) === "ready").length;
    }

    get deliveredCount() {
        return this.state.orders.filter((order) => this.getOrderStatus(order) === "delivered").length;
    }

    get unpaidCount() {
        return this.state.orders.filter((order) => this.getPaymentStatus(order) === "unpaid").length;
    }

    get partialCount() {
        return this.state.orders.filter((order) => this.getPaymentStatus(order) === "partial").length;
    }

    get paidCount() {
        return this.state.orders.filter((order) => this.getPaymentStatus(order) === "paid").length;
    }

    get payableCount() {
        return this.state.orders.filter((order) => this.canPayOrder(order)).length;
    }

    get statusFilterOptions() {
        const orders = this._computeFilteredOrders({ ignoreStatusFilter: true });
        const options = [
            {
                key: "all",
                label: this.uiText.filterAll,
                count: orders.length,
            },
        ];
        for (const status of this.state.statuses) {
            const statusMeta = this.getStatusMeta(status.key);
            options.push({
                key: status.key,
                label: statusMeta.label,
                count: orders.filter((order) => this.getOrderStatus(order) === status.key).length,
            });
        }
        return options;
    }

    get paymentFilterOptions() {
        const orders = this._computeFilteredOrders({ ignorePaymentFilter: true });
        const paymentStatuses = this.state.paymentStatuses?.length
            ? this.state.paymentStatuses
            : [
                { key: "unpaid", label: this.uiText.unpaidStatus },
                { key: "partial", label: this.uiText.partialStatus },
                { key: "paid", label: this.uiText.paidStatus },
                { key: "refunded", label: this.uiText.refundedStatus },
                { key: "cancelled", label: this.uiText.cancelledStatus },
            ];
        return [
            {
                key: "all",
                label: this.uiText.filterAll,
                count: orders.length,
            },
            ...paymentStatuses.map((status) => ({
                key: status.key,
                label: this.getPaymentStatusMeta(status.key).label,
                count: orders.filter((order) => this.getPaymentStatus(order) === status.key).length,
            })),
        ];
    }

    getFilterOptionLabel(filter) {
        if (!filter) {
            return "";
        }
        const count = this.formatInteger(filter.count || 0);
        return this.isArabic ? `${filter.label} - ${count}` : `${filter.label} (${count})`;
    }

    get boardColumns() {
        const groupedOrders = {};
        for (const status of this.state.statuses) {
            groupedOrders[status.key] = [];
        }

        for (const order of this.filteredOrders) {
            const statusKey = this.getOrderStatus(order);
            if (groupedOrders[statusKey]) {
                groupedOrders[statusKey].push(order);
            }
        }

        return this.state.statuses.map((status) => ({
            ...status,
            ...this.getStatusMeta(status.key),
            orders: groupedOrders[status.key] || [],
        }));
    }

    get summaryCards() {
        return [
            {
                key: "orders",
                icon: "fa-file-text-o",
                label: this.uiText.totalOrders,
                value: this.orderCount,
            },
            {
                key: "received",
                icon: "fa-inbox",
                label: this.uiText.atIntake,
                value: this.receivedCount,
            },
            {
                key: "ready",
                icon: "fa-check-circle",
                label: this.uiText.readyForCollection,
                value: this.readyCount,
            },
            {
                key: "delivered",
                icon: "fa-truck",
                label: this.uiText.deliveredStatus,
                value: this.deliveredCount,
            },
            {
                key: "amount",
                icon: "fa-money",
                label: this.uiText.payableOrders,
                value: this.payableCount,
            },
            {
                key: "paid",
                icon: "fa-check-square-o",
                label: this.uiText.paidOrders,
                value: this.paidCount,
            },
            {
                key: "total",
                icon: "fa-calculator",
                label: this.uiText.displayedTotal,
                value: this.formatMoney(this.totalAmount),
            },
        ];
    }

    get isScannerBusy() {
        return this.state.scannerBooting || this.state.scannerProcessing;
    }

    get scannerStatusText() {
        return (
            this.state.scannerError ||
            this.state.scannerHint ||
            this.uiText.scannerPointCamera
        );
    }

    get scannerStatusMeta() {
        if (this.state.scannerError || this.state.scannerFeedback === "error") {
            return {
                tone: "error",
                icon: "fa-exclamation-circle",
                label: this.uiText.scannerAttentionLabel,
            };
        }
        if (this.state.scannerProcessing || this.state.scannerBooting) {
            return {
                tone: "processing",
                icon: "fa-refresh",
                label: this.uiText.scannerProcessingLabel,
            };
        }
        if (this.state.scannerFeedback === "success") {
            return {
                tone: "success",
                icon: "fa-check-circle",
                label: this.uiText.scannerSuccessLabel,
            };
        }
        if (this.state.scannerFeedback === "warning") {
            return {
                tone: "warning",
                icon: "fa-exclamation-circle",
                label: this.uiText.scannerAttentionLabel,
            };
        }
        if (this.state.scannerFeedback === "info") {
            return {
                tone: "info",
                icon: "fa-info-circle",
                label: this.uiText.scannerReadyLabel,
            };
        }
        return {
            tone: "ready",
            icon: "fa-crosshairs",
            label: this.uiText.scannerReadyLabel,
        };
    }

    get toastMeta() {
        const meta = QR_TYPE_INFO[this.state.toastType] || QR_TYPE_INFO.info;
        const titles = {
            success: this.uiText.toastSuccess,
            info: this.uiText.toastInfo,
            warning: this.uiText.toastWarning,
            error: this.uiText.toastError,
        };
        return {
            ...meta,
            title: titles[this.state.toastType] || this.uiText.toastInfo,
        };
    }

    _computeFilteredOrders(options = {}) {
        const { ignoreStatusFilter = false, ignorePaymentFilter = false } = options;
        const query = String(this.state.search || "").trim().toLowerCase();

        return this.state.orders.filter((order) => {
            if (query) {
                const haystack = [
                    order.name,
                    order.partner_name,
                    order.pos_reference,
                    order.x_laundry_intake_ref,
                    order.partner_phone,
                ]
                    .filter(Boolean)
                    .join(" ")
                    .toLowerCase();
                const digitQuery = query.replace(/\D+/g, "");
                const phoneDigits = String(order.partner_phone || "").replace(/\D+/g, "");
                if (!haystack.includes(query) && !(digitQuery && phoneDigits.includes(digitQuery))) {
                    return false;
                }
            }

            if (this.state.filter === "olderThanMonth") {
                const orderDate = this.parseOrderDate(order.date_order);
                if (!orderDate) return false;
                const daysAgo = (Date.now() - orderDate.getTime()) / 86_400_000;
                if (daysAgo <= 30) return false;
            }

            const hasDateRange = this.state.start_date || this.state.end_date;
            if (hasDateRange) {
                const orderDate = this.parseOrderDate(order.date_order);
                if (!orderDate) return false;
                if (this.state.start_date) {
                    const startDate = new Date(this.state.start_date);
                    if (!Number.isNaN(startDate.getTime()) && orderDate < startDate)
                        return false;
                }
                if (this.state.end_date) {
                    const endDate = new Date(this.state.end_date);
                    endDate.setDate(endDate.getDate() + 1);
                    if (!Number.isNaN(endDate.getTime()) && orderDate >= endDate)
                        return false;
                }
            }

            const amount = Number(order.amount_total || 0);
            const minAmount = parseFloat(this.state.min_amount);
            if (!Number.isNaN(minAmount) && minAmount >= 0 && amount < minAmount)
                return false;
            const maxAmount = parseFloat(this.state.max_amount);
            if (!Number.isNaN(maxAmount) && maxAmount >= 0 && amount > maxAmount)
                return false;

            if (!ignoreStatusFilter && this.state.statusFilter && this.state.statusFilter !== "all") {
                const orderStatus = this.getOrderStatus(order);
                if (orderStatus !== this.state.statusFilter) {
                    return false;
                }
            }

            if (!ignorePaymentFilter && this.state.paymentFilter && this.state.paymentFilter !== "all") {
                const paymentStatus = this.getPaymentStatus(order);
                if (paymentStatus !== this.state.paymentFilter) {
                    return false;
                }
            }

            return true;
        }).sort((a, b) => {
            const aDate = this.parseOrderDate(a.date_order)?.getTime() || 0;
            const bDate = this.parseOrderDate(b.date_order)?.getTime() || 0;
            if (aDate !== bDate) {
                return bDate - aDate;
            }
            return (b.id || 0) - (a.id || 0);
        });
    }

    setStatusFilter(filterValue) {
        this.state.statusFilter = filterValue || "all";
        this.state.tablePage = 1;
    }

    setPaymentFilter(filterValue) {
        this.state.paymentFilter = filterValue || "all";
        this.state.tablePage = 1;
    }

    // ── UI text ───────────────────────────────────────────────────────────────

    get uiText() {
        if (this.isArabic) {
            return {
                back: "العودة",
                workflowTitle: "دفع الفواتير",
                workflowSubtitle: "لوحة مباشرة لاستلام الطلبات وتحديث حالتها والدفع",
                liveBoard: "لوحة مباشرة",
                qrReady: "جاهز للمسح",
                loading: "جاري تحميل طلبات المغسلة...",
                noUnpaidBills: "لا توجد طلبات غير مدفوعة حاليا",
                noOrders: "لا توجد طلبات حاليا",
                noSearchResults: "لا توجد طلبات مطابقة للفلاتر الحالية",
                clearSearch: "مسح البحث",
                searchPlaceholder: "ابحث برقم الفاتورة أو اسم العميل أو رقم الجوال",
                filterAll: "الكل",
                filterOlderThanMonth: "أقدم من شهر",
                filterRange: "نطاق مخصص",
                receivedStatus: "تم الاستلام",
                readyStatus: "جاهز للاستلام",
                deliveredStatus: "تم التسليم",
                unpaidStatus: "غير مدفوع",
                partialStatus: "مدفوع جزئيا",
                paidStatus: "مدفوع",
                refundedStatus: "مسترد",
                cancelledStatus: "ملغي",
                paymentFilters: "الدفع",
                statusFilters: "الحالة",
                fromDate: "من تاريخ",
                toDate: "إلى تاريخ",
                minAmount: "أقل مبلغ",
                maxAmount: "أكبر مبلغ",
                clearFilters: "مسح الفلاتر",
                refresh: "تحديث",
                scanQr: "مسح الرمز",
                scanning: "جاري تشغيل الكاميرا...",
                generatedAt: "آخر تحديث",
                ordersTableTitle: "جدول الطلبات",
                ordersTableSubtitle: "عرض موحد لطلبات المغسلة مع حالة الدفع والمرحلة",
                invoiceNumber: "رقم الطلب",
                customer: "العميل",
                total: "الإجمالي",
                date: "التاريخ",
                status: "الحالة",
                paymentStatus: "الدفع",
                actions: "الإجراءات",
                pay: "دفع",
                paid: "مدفوع",
                notPayable: "لا يحتاج دفع",
                deliveryRequiresPayment: "لا يمكن تأكيد التسليم قبل أن تكون حالة الدفع مدفوع.",
                moveToReady: "وضع جاهز",
                moveToDelivered: "تأكيد التسليم",
                columnEmpty: "لا توجد طلبات في هذه المرحلة",
                orderNotes: "طلب مغسلة غير مدفوع",
                orderReference: "مرجع نقطة البيع",
                walkInCustomer: "عميل بدون تسجيل",
                scannerTitle: "مسح الرمز",
                scannerSubtitle: "وجه الكاميرا إلى رمز الفاتورة وسيتم تحديث الطلب تلقائيا",
                scannerLiveLabel: "ماسح مباشر",
                scannerReadyLabel: "جاهز للمسح",
                scannerSuccessLabel: "تم بنجاح",
                scannerProcessingLabel: "جاري الفحص",
                scannerAttentionLabel: "تنبيه",
                scannerFrameHint: "ضع رمز الفاتورة داخل الإطار ليتم المسح تلقائيا.",
                scannerPointCamera: "وجه الكاميرا إلى رمز QR داخل إطار المسح",
                scannerProcessing: "جاري فحص الطلب وتحديث حالته...",
                scannerSuccessHint: "تم تحديث الحالة بنجاح. يمكنك متابعة المسح.",
                scannerFlowTitle: "مسار تحديث الحالة",
                scannerFlowReceivedReadyTitle: "من الاستلام إلى الجاهزية",
                scannerFlowReceivedReadyBody: "المسح الأول ينقل الطلب من تم الاستلام إلى جاهز.",
                scannerFlowReadyDeliveredTitle: "من الجاهزية إلى التسليم",
                scannerFlowReadyDeliveredBody: "إذا كان الطلب جاهزا فالمسح التالي يؤكد التسليم.",
                scannerTipsTitle: "نصائح سريعة",
                scannerTipCancelled: "الطلبات الملغية والرموز غير المطابقة لن يتم تغييرها.",
                scannerTipLighting: "استخدم إضاءة جيدة واجعل الرمز بالكامل داخل الإطار.",
                scannerTipDistance: "قرب أو أبعد الكاميرا إذا كان الرمز صغيرا أو غير واضح.",
                scannerClose: "إغلاق",
                scannerSecureContext: "الوصول للكاميرا يتطلب اتصال HTTPS آمن.",
                scannerPermissionDenied: "تم رفض إذن الكاميرا. فعل الوصول للكاميرا ثم حاول مرة أخرى.",
                scannerCameraUnavailable: "لم يتم العثور على كاميرا مناسبة للمسح.",
                scannerCameraBusy: "الكاميرا مستخدمة في تطبيق آخر. أغلقه وحاول مرة أخرى.",
                scannerStartFailed: "تعذر تشغيل ماسح QR. حاول مرة أخرى.",
                scannerUnsupported: "هذا الجهاز أو المتصفح لا يدعم مسح QR داخل نقطة البيع.",
                toastSuccess: "تم التحديث",
                toastInfo: "معلومة",
                toastWarning: "تنبيه",
                toastError: "خطأ",
                totalOrders: "إجمالي الطلبات",
                atIntake: "عند الاستلام",
                readyForCollection: "جاهز للاستلام",
                payableOrders: "طلبات قابلة للدفع",
                paidOrders: "طلبات مدفوعة",
                displayedTotal: "إجمالي المعروض",
                qrProcessFailed: "تعذر معالجة رمز QR. حاول مرة أخرى.",
                qrUnableToRead: "تعذر قراءة هذا الرمز أو العثور على الطلب المطلوب.",
                failedLoadOrders: "فشل تحميل طلبات المغسلة. حاول مرة أخرى.",
                failedUpdateStatus: "فشل تحديث حالة الطلب.",
            };
        }
        return {
            back: "Back",
            workflowTitle: "Pay Bills",
            workflowSubtitle: "Live board for quick intake, status updates, and payment",
            liveBoard: "Live Board",
            qrReady: "Ready to Scan",
            loading: "Loading laundry orders...",
            noUnpaidBills: "There are no unpaid orders at the moment",
            noOrders: "There are no orders at the moment",
            noSearchResults: "No orders match the current filters",
            clearSearch: "Clear Search",
            searchPlaceholder: "Search by invoice number, customer name, or mobile",
            filterAll: "All",
            filterOlderThanMonth: "Older Than One Month",
            filterRange: "Custom Range",
            receivedStatus: "Received",
            readyStatus: "Ready",
            deliveredStatus: "Delivered",
            unpaidStatus: "Unpaid",
            partialStatus: "Partially Paid",
            paidStatus: "Paid",
            refundedStatus: "Refunded",
            cancelledStatus: "Cancelled",
            paymentFilters: "Payment",
            statusFilters: "Status",
            fromDate: "From Date",
            toDate: "To Date",
            minAmount: "Minimum Amount",
            maxAmount: "Maximum Amount",
            clearFilters: "Clear Filters",
            refresh: "Refresh",
            scanQr: "Scan QR",
            scanning: "Starting camera...",
            generatedAt: "Last Updated",
            ordersTableTitle: "Orders Table",
            ordersTableSubtitle: "Unified view of all laundry orders with payment and stage status",
            invoiceNumber: "Order Number",
            customer: "Customer",
            total: "Total",
            date: "Date",
            status: "Status",
            paymentStatus: "Payment",
            actions: "Actions",
            pay: "Pay",
            paid: "Paid",
            notPayable: "No Payment Needed",
            deliveryRequiresPayment: "Delivery cannot be confirmed until the payment status is Paid.",
            moveToReady: "Mark Ready",
            moveToDelivered: "Confirm Delivery",
            columnEmpty: "There are no orders at this stage",
            orderNotes: "Unpaid Laundry Order",
            orderReference: "POS Reference",
            walkInCustomer: "Walk-in Customer",
            scannerTitle: "Scan QR",
            scannerSubtitle: "Point the camera at the receipt code and the order will be updated automatically",
            scannerLiveLabel: "Live Scanner",
            scannerReadyLabel: "Ready to Scan",
            scannerSuccessLabel: "Success",
            scannerProcessingLabel: "Checking",
            scannerAttentionLabel: "Warning",
            scannerFrameHint: "Place the receipt code inside the frame for automatic scanning.",
            scannerPointCamera: "Point the camera at the QR code inside the scan frame",
            scannerProcessing: "Checking the order and updating its status...",
            scannerSuccessHint: "The status was updated successfully. You can continue scanning.",
            scannerFlowTitle: "Status Update Flow",
            scannerFlowReceivedReadyTitle: "Received to Ready",
            scannerFlowReceivedReadyBody: "The first scan moves the order from received to ready.",
            scannerFlowReadyDeliveredTitle: "Ready to Delivered",
            scannerFlowReadyDeliveredBody: "If the order is ready, the next scan confirms delivery.",
            scannerTipsTitle: "Quick Tips",
            scannerTipCancelled: "Cancelled orders and mismatched codes will not be changed.",
            scannerTipLighting: "Use good lighting and keep the entire code inside the frame.",
            scannerTipDistance: "Move the camera closer or farther away if the code is small or unclear.",
            scannerClose: "Close",
            scannerSecureContext: "Camera access requires a secure HTTPS connection.",
            scannerPermissionDenied: "Camera permission was denied. Enable camera access and try again.",
            scannerCameraUnavailable: "No suitable camera was found for scanning.",
            scannerCameraBusy: "The camera is being used by another application. Close it and try again.",
            scannerStartFailed: "Unable to start the QR scanner. Try again.",
            scannerUnsupported: "This device or browser does not support QR scanning in the POS.",
            toastSuccess: "Updated",
            toastInfo: "Information",
            toastWarning: "Warning",
            toastError: "Error",
            totalOrders: "Total Orders",
            atIntake: "At Intake",
            readyForCollection: "Ready for Collection",
            payableOrders: "Payable Orders",
            paidOrders: "Paid Orders",
            displayedTotal: "Displayed Total",
            qrProcessFailed: "Unable to process the QR code. Try again.",
            qrUnableToRead: "Unable to read this code or find the requested order.",
            failedLoadOrders: "Failed to load laundry orders. Try again.",
            failedUpdateStatus: "Failed to update the order status.",
        };
    }

    get hasOrdersValue() {
        return this.hasOrders;
    }

    get orderCountValue() {
        return this.orderCount;
    }

    get totalAmountValue() {
        return this.totalAmount;
    }

    // ── Data loading ──────────────────────────────────────────────────────────

    normalizeBoardOrder(order) {
        const statusKey = order.laundry_status || order.x_laundry_status || "received";
        const paymentStatusKey = order.x_payment_status || "unpaid";
        const paymentMeta = this.getPaymentStatusMeta(paymentStatusKey);
        const statusMeta = this.getStatusMeta(statusKey);
        const normalizedOrder = {
            ...order,
            name: order.x_display_reference || order.name || "",
            partner_name: order.partner_name || "",
            partner_phone: order.partner_phone || "",
            amount_total: Number(order.amount_total || 0),
            amount_paid: Number(order.amount_paid || 0),
            amount_due: Number(order.amount_due || 0),
            pos_reference: order.pos_reference || "",
            x_display_reference: order.x_display_reference || "",
            x_laundry_intake_id: order.x_laundry_intake_id || 0,
            x_laundry_intake_ref: order.x_laundry_intake_ref || "",
            x_qr_token: order.x_qr_token || "",
            qr_value: order.qr_value || "",
            qr_barcode_url: order.qr_barcode_url || "",
            laundry_status: statusKey,
            x_laundry_status: statusKey,
            laundry_status_label: statusMeta.label || order.laundry_status_label || order.x_laundry_status_label,
            x_laundry_status_label: statusMeta.label || order.x_laundry_status_label || order.laundry_status_label,
            status_color: order.status_color || statusMeta.color,
            status_surface: order.status_surface || statusMeta.surface,
            status_badge: order.status_badge || statusMeta.badge,
            x_payment_status: paymentStatusKey,
            x_payment_status_label: paymentMeta.label || order.x_payment_status_label,
            payment_color: order.payment_color || paymentMeta.color,
            payment_surface: order.payment_surface || paymentMeta.surface,
            available_actions: Array.isArray(order.available_actions)
                ? order.available_actions
                : this.getStatusActions(statusKey),
        };
        return normalizedOrder;
    }

    async loadPendingOrders(options = {}) {
        const { silent = false } = options;

        if (!silent) {
            this.state.loading = true;
            this.state.error = false;
        }

        try {
            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error("Order load timeout")), 15_000)
            );

            const ordersPromise = this.orm.call("pos.order", "get_pending_laundry_board_data", []);

            const data = await Promise.race([ordersPromise, timeoutPromise]);
            this.state.statuses = [...(data?.statuses || [])].sort(
                (left, right) => (left.sequence || 0) - (right.sequence || 0)
            );
            this.state.paymentStatuses = [...(data?.payment_statuses || [])].sort(
                (left, right) => (left.sequence || 0) - (right.sequence || 0)
            );
            this.state.generated_at = data?.generated_at || false;
            this.state.orders = (data?.orders || [])
                .map((order) => this.normalizeBoardOrder(order))
                .filter(Boolean);
            this.state.tablePage = 1;
        } catch (error) {
            console.error("Pending orders load failed", error);
            if (!silent) {
                this.notification.add(this.uiText.failedLoadOrders, {
                    type: "danger",
                });
                this.state.error = true;
            }
        } finally {
            if (!silent) {
                this.state.loading = false;
            }
        }
    }

    replaceOrder(updatedOrder) {
        const normalizedOrder = this.normalizeBoardOrder(updatedOrder);
        const isVisibleStatus =
            !this.state.statuses.length ||
            this.state.statuses.some(
                (status) => status.key === this.getOrderStatus(normalizedOrder)
            );
        const index = this.state.orders.findIndex((order) => order.id === normalizedOrder.id);
        if (!isVisibleStatus && index >= 0) {
            this.state.orders.splice(index, 1);
        } else if (index >= 0) {
            this.state.orders.splice(index, 1, normalizedOrder);
        } else if (isVisibleStatus) {
            this.state.orders.unshift(normalizedOrder);
        }
        this.state.generated_at = new Date().toISOString().slice(0, 19).replace("T", " ");
    }

    // ── Formatters ────────────────────────────────────────────────────────────

    formatDate(value) {
        if (!value) return "";
        try {
            const date = this.parseOrderDate(value);
            if (!date) return value;
            return new Intl.DateTimeFormat(this.formatLocale, {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                hour12: true,
            }).format(date);
        } catch {
            return value;
        }
    }

    parseOrderDate(value) {
        if (!value) return null;
        try {
            const date = new Date(String(value).replace(" ", "T"));
            return Number.isNaN(date.getTime()) ? null : date;
        } catch {
            return null;
        }
    }

    formatMoney(amount) {
        const value = Number(amount || 0);
        const formattedValue = new Intl.NumberFormat(this.formatLocale, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(value);
        const rawSymbol = String(this.pos.currency?.symbol || "").trim();
        const symbol = this.isArabic && /^(sr|sar)$/i.test(rawSymbol) ? "ر.س" : rawSymbol;
        return symbol ? `${formattedValue} ${symbol}` : formattedValue;
    }

    formatInteger(value) {
        try {
            return new Intl.NumberFormat(this.formatLocale, {
                maximumFractionDigits: 0,
            }).format(Number(value || 0));
        } catch {
            return String(value || 0);
        }
    }

    formatGeneratedAt() {
        return this.formatDate(this.state.generated_at);
    }

    formatPageStatus(pagination) {
        if (!pagination?.totalItems) {
            return "";
        }
        const startNumber = this.formatInteger(pagination.startNumber);
        const endNumber = this.formatInteger(pagination.endNumber);
        const totalItems = this.formatInteger(pagination.totalItems);
        return this.isArabic
            ? `${startNumber}-${endNumber} من ${totalItems}`
            : `${startNumber}-${endNumber} / ${totalItems}`;
    }

    getOrderStatus(order) {
        return order?.laundry_status || order?.x_laundry_status || "received";
    }

    getPaymentStatus(order) {
        return order?.x_payment_status || "unpaid";
    }

    getStatusMeta(statusKey) {
        const fallback = {
            received: {
                label: this.uiText.receivedStatus,
                color: "#2563eb",
                surface: "#eff6ff",
                badge: "#dbeafe",
            },
            ready: {
                label: this.uiText.readyStatus,
                color: "#16a34a",
                surface: "#f0fdf4",
                badge: "#dcfce7",
            },
            delivered: {
                label: this.uiText.deliveredStatus,
                color: "#166534",
                surface: "#ecfdf5",
                badge: "#d1fae5",
            },
        };
        const backendMeta = this.state.statuses.find((status) => status.key === statusKey);
        return {
            label: fallback[statusKey]?.label || backendMeta?.label || statusKey || "",
            color: backendMeta?.color || fallback[statusKey]?.color || "#2563eb",
            surface: backendMeta?.surface || fallback[statusKey]?.surface || "#eff6ff",
            badge: backendMeta?.badge || fallback[statusKey]?.badge || "#dbeafe",
        };
    }

    getPaymentStatusMeta(paymentStatus) {
        const fallback = {
            unpaid: { label: this.uiText.unpaidStatus, color: "#64748b", surface: "#f1f5f9" },
            partial: { label: this.uiText.partialStatus, color: "#d97706", surface: "#fef3c7" },
            paid: { label: this.uiText.paidStatus, color: "#15803d", surface: "#dcfce7" },
            refunded: { label: this.uiText.refundedStatus, color: "#0f766e", surface: "#ccfbf1" },
            cancelled: { label: this.uiText.cancelledStatus, color: "#dc2626", surface: "#fee2e2" },
        };
        const backendMeta = this.state.paymentStatuses.find((status) => status.key === paymentStatus);
        return {
            label: fallback[paymentStatus]?.label || backendMeta?.label || paymentStatus || "",
            color: backendMeta?.color || fallback[paymentStatus]?.color || "#64748b",
            surface: backendMeta?.surface || fallback[paymentStatus]?.surface || "#f1f5f9",
        };
    }

    canPayOrder(order) {
        return ["unpaid", "partial"].includes(this.getPaymentStatus(order));
    }

    getPayButtonLabel(order) {
        if (this.canPayOrder(order)) {
            return this.uiText.pay;
        }
        if (this.getPaymentStatus(order) === "paid") {
            return this.uiText.paid;
        }
        return this.uiText.notPayable;
    }

    getStatusActions(statusKey) {
        if (statusKey === "received") {
            return [
                {
                    key: "ready",
                    label: this.uiText.moveToReady,
                    icon: "fa-check-circle",
                },
            ];
        }
        if (statusKey === "ready") {
            return [
                {
                    key: "delivered",
                    label: this.uiText.moveToDelivered,
                    icon: "fa-truck",
                },
            ];
        }
        return [];
    }

    getPrimaryAction(order) {
        const action = (order?.available_actions || [])[0] || null;
        if (!action) {
            return null;
        }
        const localizedAction = this.getStatusActions(this.getOrderStatus(order)).find(
            (candidate) => candidate.key === action.key
        );
        return {
            ...action,
            ...(localizedAction || {}),
            icon: action.icon || localizedAction?.icon,
        };
    }

    isUpdating(orderId) {
        return !!this.state.updatingOrderIds[orderId];
    }

    isHighlighted(orderId) {
        return this.state.highlightedOrderId === orderId;
    }

    // ── Event handlers ────────────────────────────────────────────────────────

    onSearchInput(event) {
        this.state.search = event.target.value || "";
        this.state.tablePage = 1;
    }

    onRangeInput(event) {
        const name = event.target.name;
        if (name && Object.prototype.hasOwnProperty.call(this.state, name)) {
            this.state[name] = event.target.value || "";
            this.state.tablePage = 1;
        }
    }

    onStatusFilterChange(event) {
        this.setStatusFilter(event.target.value);
    }

    onPaymentFilterChange(event) {
        this.setPaymentFilter(event.target.value);
    }

    toggleAdvancedFilters() {
        this.state.showAdvancedFilters = !this.state.showAdvancedFilters;
    }

    clearFilters() {
        this.state.start_date = "";
        this.state.end_date = "";
        this.state.min_amount = "";
        this.state.max_amount = "";
        this.state.statusFilter = "all";
        this.state.paymentFilter = "all";
        this.state.showAdvancedFilters = false;
        this.state.tablePage = 1;
    }

    clearSearch() {
        this.state.search = "";
        this.state.tablePage = 1;
    }

    setFilter(filterValue) {
        this.state.filter = filterValue;
        this.state.tablePage = 1;
    }

    changeTablePage(nextPage) {
        this.state.tablePage = getSafePage(nextPage, this.filteredOrders.length);
    }

    _clearToastTimer() {
        if (this.toastTimer) {
            clearTimeout(this.toastTimer);
            this.toastTimer = null;
        }
    }

    _clearHighlightTimer() {
        if (this.highlightTimer) {
            clearTimeout(this.highlightTimer);
            this.highlightTimer = null;
        }
    }

    _clearCloseModalTimer() {
        if (this.closeModalTimer) {
            clearTimeout(this.closeModalTimer);
            this.closeModalTimer = null;
        }
    }

    showToast(type, message, options = {}) {
        const { duration = 2_800 } = options;
        if (!message) {
            return;
        }
        this._clearToastTimer();
        this.state.toastType = type || "info";
        this.state.toastMessage = message;
        this.state.toastVisible = true;
        if (duration > 0) {
            this.toastTimer = setTimeout(() => {
                this.state.toastVisible = false;
            }, duration);
        }
    }

    async showDeliveryPaymentWarning(message) {
        const body = message || this.uiText.deliveryRequiresPayment;
        this.showToast("warning", body, { duration: 3_600 });
        await this.popup.add(ErrorPopup, {
            title: this.uiText.scannerAttentionLabel,
            body,
        });
    }

    highlightOrder(orderId) {
        if (!orderId) {
            return;
        }
        this._clearHighlightTimer();
        this.state.highlightedOrderId = orderId;
        this.highlightTimer = setTimeout(() => {
            this.state.highlightedOrderId = false;
        }, 2_600);
    }

    describeScannerError(error) {
        if (!window.isSecureContext && window.location.hostname !== "localhost") {
            return this.uiText.scannerSecureContext;
        }

        const message = String(error?.message || error || "");
        if (/NotAllowedError|Permission|denied/i.test(message)) {
            return this.uiText.scannerPermissionDenied;
        }
        if (/NotFoundError|OverconstrainedError|camera/i.test(message)) {
            return this.uiText.scannerCameraUnavailable;
        }
        if (/NotReadableError|TrackStartError|busy|Could not start video source/i.test(message)) {
            return this.uiText.scannerCameraBusy;
        }
        return this.uiText.scannerStartFailed;
    }

    async stopScanner() {
        const scanner = this.scanner;
        this.scanner = null;
        if (!scanner) {
            return;
        }

        try {
            await scanner.stop();
        } catch {
            // noop: stop throws when scanner never fully started
        }

        try {
            await scanner.clear();
        } catch {
            // noop: clear is best-effort cleanup
        }
    }

    async startScanner() {
        const Html5Qrcode = getHtml5QrCodeClass();
        if (!Html5Qrcode) {
            throw new Error(this.uiText.scannerUnsupported);
        }

        await this.stopScanner();
        this.scanner = new Html5Qrcode(this.scannerElementId);

        const config = {
            fps: 10,
            disableFlip: true,
            rememberLastUsedCamera: false,
        };
        const formats = getHtml5QrFormats();
        if (formats?.QR_CODE) {
            config.formatsToSupport = [formats.QR_CODE];
        }

        const onScanSuccess = (decodedText) => {
            void this.handleDecodedQr(decodedText);
        };
        const onScanFailure = () => { };

        try {
            await this.scanner.start(
                { facingMode: "environment" },
                config,
                onScanSuccess,
                onScanFailure
            );
            return;
        } catch (primaryError) {
            const cameras = await Html5Qrcode.getCameras();
            const rearCamera = getRearCamera(cameras);
            if (!rearCamera) {
                throw primaryError;
            }
            await this.scanner.start(rearCamera.id, config, onScanSuccess, onScanFailure);
        }
    }

    async openScannerModal() {
        if (!this.state.isScannerSupported) {
            this.showToast("warning", this.uiText.scannerUnsupported, { duration: 4_000 });
            return;
        }

        this.scanLock = false;
        this.lastScanFingerprint = "";
        this.lastScanAt = 0;
        this.state.scannerVisible = true;
        this.state.scannerClosing = false;
        this.state.scannerBooting = true;
        this.state.scannerProcessing = false;
        this.state.scannerError = "";
        this.state.scannerFeedback = "";
        this.state.scannerHint = this.uiText.scannerPointCamera;

        await afterNextPaint();

        try {
            await this.startScanner();
        } catch (error) {
            console.error("Failed to start QR scanner:", error);
            this.state.scannerError = this.describeScannerError(error);
            this.showToast("warning", this.state.scannerError, { duration: 4_000 });
        } finally {
            this.state.scannerBooting = false;
        }
    }

    async closeScannerModal() {
        this._clearCloseModalTimer();
        this.scanLock = false;
        this.state.scannerBooting = false;
        this.state.scannerProcessing = false;
        this.state.scannerClosing = true;
        await this.stopScanner();
        this.closeModalTimer = setTimeout(() => {
            this.state.scannerVisible = false;
            this.state.scannerClosing = false;
            this.state.scannerError = "";
            this.state.scannerFeedback = "";
            this.state.scannerHint = "";
        }, QR_MODAL_CLOSE_DELAY);
    }

    unlockScannerSoon(delay = QR_RETRY_UNLOCK_DELAY) {
        setTimeout(() => {
            this.scanLock = false;
            if (!this.state.scannerProcessing) {
                this.state.scannerFeedback = "";
                if (!this.state.scannerError) {
                    this.state.scannerHint = this.uiText.scannerPointCamera;
                }
            }
        }, delay);
    }

    async handleDecodedQr(decodedText) {
        const normalizedValue = String(decodedText || "").trim();
        if (!normalizedValue || !this.state.scannerVisible || this.scanLock) {
            return;
        }

        const now = Date.now();
        if (
            this.lastScanFingerprint === normalizedValue &&
            now - this.lastScanAt < QR_SCAN_DUPLICATE_WINDOW
        ) {
            return;
        }

        this.scanLock = true;
        this.lastScanFingerprint = normalizedValue;
        this.lastScanAt = now;
        this.state.scannerProcessing = true;
        this.state.scannerFeedback = "";
        this.state.scannerError = "";
        this.state.scannerHint = this.uiText.scannerProcessing;

        try {
            const response = await this.orm.call("pos.order", "process_laundry_qr_scan", [
                normalizedValue,
            ]);
            await this.handleQrScanResponse(response, normalizedValue);
        } catch (error) {
            console.error("QR scan processing failed:", error);
            this.state.scannerProcessing = false;
            this.state.scannerFeedback = "error";
            this.state.scannerError = this.uiText.qrProcessFailed;
            this.showToast("error", this.state.scannerError, { duration: 3_500 });
            this.unlockScannerSoon();
        }
    }

    async handleQrScanResponse(response, fallbackValue) {
        const code = response?.code || "invalid_qr";
        const message = response?.message || this.uiText.qrUnableToRead;

        if (response?.order) {
            this.replaceOrder(response.order);
        }
        if (code === "updated") {
            this.state.scannerFeedback = "success";
            this.state.scannerHint = message;
            this.state.scannerError = "";

            if (response?.order?.id) {
                this.highlightOrder(response.order.id);
            }

            this.showToast("success", message);

            triggerSuccessVibration();
            await playSuccessChime();

            this.state.scannerProcessing = false;
            this.state.scannerHint = this.uiText.scannerSuccessHint;

            this.unlockScannerSoon(650);

            if (this.scanner?.resume) {
                try {
                    await this.scanner.resume();
                } catch (e) {
                    console.warn("Scanner resume failed", e);
                }
            }

            void this.loadPendingOrders({ silent: true });
            return;
        }

        if (code === "already_ready" || code === "already_delivered") {
            this.state.scannerFeedback = code === "already_ready" ? "info" : "warning";
            this.state.scannerHint = message;
            if (response?.order?.id) {
                this.highlightOrder(response.order.id);
            }
            this.showToast(code === "already_ready" ? "info" : "warning", message, {
                duration: 3_200,
            });
            this.state.scannerProcessing = false;
            await this.closeScannerModal();
            void this.loadPendingOrders({ silent: true });
            return;
        }

        if (code === "payment_required") {
            this.state.scannerFeedback = "warning";
            this.state.scannerHint = message;
            if (response?.order?.id) {
                this.highlightOrder(response.order.id);
            }
            this.state.scannerProcessing = false;
            await this.showDeliveryPaymentWarning(message);
            await this.closeScannerModal();
            void this.loadPendingOrders({ silent: true });
            return;
        }

        this.state.scannerProcessing = false;
        this.state.scannerFeedback = "error";
        this.state.scannerError = message;
        this.state.scannerHint = message;
        this.showToast("error", message, { duration: 3_600 });
        this.unlockScannerSoon();
    }

    async changeOrderStatus(order, targetStatus) {
        if (!order || !targetStatus || this.isUpdating(order.id)) {
            return;
        }

        const previousStatus = this.getOrderStatus(order);
        if (previousStatus === targetStatus) {
            return;
        }
        if (targetStatus === "delivered" && this.getPaymentStatus(order) !== "paid") {
            await this.showDeliveryPaymentWarning();
            return;
        }

        const statusMeta = this.getStatusMeta(targetStatus);
        this.state.updatingOrderIds[order.id] = true;
        order.laundry_status = targetStatus;
        order.x_laundry_status = targetStatus;
        order.laundry_status_label = statusMeta?.label || order.laundry_status_label;
        order.x_laundry_status_label = statusMeta?.label || order.x_laundry_status_label;
        order.status_color = statusMeta?.color || order.status_color;
        order.status_surface = statusMeta?.surface || order.status_surface;
        order.status_badge = statusMeta?.badge || order.status_badge;
        order.available_actions = this.getStatusActions(targetStatus);

        try {
            const updatedOrder = await this.orm.call(
                "pos.order",
                "update_laundry_order_status",
                [order.id, targetStatus]
            );
            this.replaceOrder(updatedOrder);
        } catch (error) {
            order.laundry_status = previousStatus;
            order.x_laundry_status = previousStatus;
            order.available_actions = this.getStatusActions(previousStatus);
            console.error("Failed to update laundry status:", error);
            const errorMessage = getRpcErrorMessage(error, this.uiText.failedUpdateStatus);
            if (targetStatus === "delivered") {
                await this.showDeliveryPaymentWarning(errorMessage);
            } else {
                this.notification.add(errorMessage, {
                    type: "danger",
                });
            }
        } finally {
            delete this.state.updatingOrderIds[order.id];
        }
    }

    // ── Pay action ────────────────────────────────────────────────────────────

    /**
     * Resolve the canonical laundry reference for a pending order row.
     *
     * Priority (highest → lowest):
     *   1. x_display_reference  – set by the backend when the order is renamed
     *      to INV/xxxxxx; most reliable when the backend field is populated.
     *   2. name                 – already resolved to (x_display_reference || name)
     *      in loadPendingOrders(), so it is the INV ref when x_display_reference
     *      is blank on the server but the name was renamed.
     *   3. x_laundry_intake_ref – the many2one display string of x_laundry_intake_id,
     *      e.g. "INV/000012". Reliable fallback when neither of the above is set.
     *
     * This value is stamped onto the local order object immediately after it is
     * located so that export_for_printing() always sees the correct reference.
     */
    _resolveRef(order) {
        return (
            order.x_laundry_intake_ref ||
            order.x_display_reference ||
            order.name ||
            ""
        );
    }

    /**
     * Stamp the canonical INV reference onto a local POS order object and
     * persist it to localStorage so it survives any subsequent auto-sync before
     * the user reaches the receipt screen.
     *
     * Three fields are written so that every consumer that might read the
     * reference finds a consistent value:
     *   • laundry_intake_name   – primary field checked by export_for_printing
     *   • x_display_reference   – secondary field checked by export_for_printing
     *                             and by the OWL receipt template
     *   • laundry_intake_id     – preserved if already set; filled from the
     *                             state row as a belt-and-suspenders measure
     */
    _stampLaundryRef(posOrder, ref, intakeId) {
        if (!posOrder || !ref) return;

        posOrder.pos_reference = posOrder.pos_reference || posOrder.name || "";
        posOrder.laundry_intake_name = ref;
        posOrder.x_display_reference = ref;
        posOrder.name = ref;
        // Keep laundry_intake_id in sync so backend _process_order can always
        // write the DB link even if it was lost during a prior sync cycle.
        if (intakeId && !posOrder.laundry_intake_id) {
            posOrder.laundry_intake_id = intakeId;
        }

        // Persist immediately so localStorage is authoritative before any
        // background auto-sync fires and overwrites the in-memory values.
        try {
            posOrder.save_to_db();
        } catch (e) {
            console.warn("save_to_db after laundry ref stamp failed (non-fatal):", e);
        }
    }

    /**
     * Pay a pending laundry order.
     *
     * We must always resume the ORIGINAL draft order from the backend.
     * Creating a replacement order produces duplicate references and leaves
     * the original record behind as unpaid.
     */
    payOrder = async (order) => {
        try {
            if (!this.canPayOrder(order)) {
                this.showToast("info", this.uiText.notPayable, { duration: 2_400 });
                return;
            }

            this.state.loading = true;

            // Canonical INV reference from the pending-orders list row.
            const resolvedLaundryReference = this._resolveRef(order);
            const intakeId = order.x_laundry_intake_id || 0;

            // ── Tier 1: Check if order is already in the local session ────────
            const existingLocalOrder = this.pos.orders?.find(
                (o) => o.server_id === order.id
            );

            if (existingLocalOrder) {
                this._stampLaundryRef(existingLocalOrder, resolvedLaundryReference, intakeId);
                this.pos.set_order(existingLocalOrder);
                this.state.loading = false;
                this.pos.showScreen("PaymentScreen");
                return;
            }

            // ── Tier 2: Refresh shared draft orders from the backend ──────────
            if (typeof this.pos._syncAllOrdersFromServer === "function") {
                try {
                    await this.pos._syncAllOrdersFromServer();
                    const syncedOrder = this.pos.orders?.find(
                        (localOrder) => localOrder.server_id === order.id
                    );
                    if (syncedOrder) {
                        // _syncAllOrdersFromServer calls init_from_JSON which may
                        // not carry laundry_intake_name (JS-only field) or may set
                        // x_display_reference to the raw POS reference instead of
                        // the LND sequence. Stamp the correct value now.
                        this._stampLaundryRef(syncedOrder, resolvedLaundryReference, intakeId);
                        this.pos.set_order(syncedOrder);
                        window.__LAST_LAUNDRY_REF__ = resolvedLaundryReference;
                        this.state.loading = false;
                        this.pos.showScreen("PaymentScreen");
                        return;
                    }
                } catch (loadErr) {
                    console.warn(
                        "_syncAllOrdersFromServer failed while preparing payment:",
                        loadErr
                    );
                }
            }

            this.state.loading = false;
            this.notification.add(
                _t("Unable to load the original order for payment. No new order was created."),
                { type: "danger" }
            );
        } catch (error) {
            console.error("Failed to load order for payment:", error);
            this.notification.add(_t("Failed to prepare the order for payment."), { type: "danger" });
            this.state.loading = false;
        }
    };

    goBack() {
        this.pos.showScreen("ProductScreen");
    }
}

registry.category("pos_screens").add("PendingOrdersScreen", PendingOrdersScreen);

// ─────────────────────────────────────────────────────────────────────────────
// Order model patch
// ─────────────────────────────────────────────────────────────────────────────

function normalizeLaundryReference(value) {
    return String(value || "").trim();
}

function isLaundryReference(value) {
    return /^INV\/\d+$/.test(normalizeLaundryReference(value));
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
    ].map(normalizeLaundryReference);

    return candidates.find(Boolean) || "";
}

function resolveLaundryReference(payload = {}) {
    const candidates = [
        payload.x_display_reference,
        payload.laundry_intake_name,
        payload.x_laundry_intake_name,
        payload.name,
    ].map(normalizeLaundryReference);

    return candidates.find(isLaundryReference) || "";
}

function applyLaundryReference(order, reference) {
    const normalizedReference = normalizeLaundryReference(reference);
    if (!order || !normalizedReference) {
        return;
    }

    order.pos_reference = order.pos_reference || order.name || "";
    order.laundry_intake_name = normalizedReference;
    order.x_display_reference = normalizedReference;
    order.name = normalizedReference;
}

function logLaundryDebug(stage, payload) {
    console.log(`[LaundryDebug] ${stage}`, payload);
}

/**
 * Extend the base Order model with laundry-specific fields so they survive
 * every serialisation/deserialisation cycle (local storage, backend sync,
 * session restore).
 *
 * Fields added:
 *   laundry_delivery_date  — ISO datetime string from the popup
 *   laundry_priority       — SLA/business priority selected at intake time
 *   laundry_note           — free-text notes from the popup
 *   laundry_intake_id      — backend id of the linked pos.laundry.intake
 *   laundry_intake_name    — canonical laundry reference (e.g. INV/000042);
 *                            PRIMARY source for receipt rendering
 *   x_display_reference    — SECONDARY source for receipt rendering;
 *                            must be initialised here so it is never undefined
 */
patch(Order.prototype, {
    setup() {
        super.setup(...arguments);
        this.laundry_delivery_date = this.laundry_delivery_date || "";
        this.laundry_priority = this.laundry_priority || "normal";
        this.laundry_note = this.laundry_note || "";
        this.laundry_intake_id = this.laundry_intake_id || 0;
        this.laundry_processed_line_uuids = Array.isArray(this.laundry_processed_line_uuids)
            ? [...new Set(this.laundry_processed_line_uuids.filter(Boolean))]
            : [];
        this.laundry_line_receipt_map = this.laundry_line_receipt_map || {};
        this.pos_reference = this.pos_reference || "";
        this.laundry_intake_name = this.laundry_intake_name || "";
        this.x_display_reference = this.x_display_reference || "";
        this.account_move_name = this.account_move_name || this.invoice_number || "";
        this.invoice_number = this.invoice_number || this.account_move_name || "";

        const reference = resolveLaundryReference(this);
        if (reference) {
            applyLaundryReference(this, reference);
        }
    },

    updatePricelistAndFiscalPosition(newPartner) {
        const defaultFiscalPositionId = getMany2oneId(
            this.pos?.config?.default_fiscal_position_id
        );
        const defaultFiscalPosition = findRecordById(
            this.pos?.fiscal_positions,
            defaultFiscalPositionId
        );
        let newPartnerFiscalPosition = defaultFiscalPosition;
        let newPartnerPricelist = this.pos?.default_pricelist || null;

        if (newPartner) {
            normalizePartnerPricingFields(newPartner, this.pos);

            const fiscalPositionId = getMany2oneId(newPartner.property_account_position_id);
            const pricelistId = getMany2oneId(newPartner.property_product_pricelist);

            newPartnerFiscalPosition =
                findRecordById(this.pos?.fiscal_positions, fiscalPositionId) ||
                defaultFiscalPosition ||
                null;
            newPartnerPricelist =
                findRecordById(this.pos?.pricelists, pricelistId) ||
                this.pos?.default_pricelist ||
                null;
        }

        this.set_fiscal_position(newPartnerFiscalPosition || null);
        this.set_pricelist(newPartnerPricelist);
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json.laundry_delivery_date = this.laundry_delivery_date || "";
        json.laundry_priority = this.laundry_priority || "normal";
        json.laundry_note = this.laundry_note || "";
        json.laundry_intake_id = this.laundry_intake_id || 0;
        json.laundry_processed_line_uuids = this.laundry_processed_line_uuids || [];
        json.laundry_line_receipt_map = this.laundry_line_receipt_map || {};
        json.pos_reference = this.pos_reference || "";
        json.laundry_intake_name = this.laundry_intake_name || "";
        json.x_display_reference = resolveLaundryReference(this);
        json.account_move_name = resolveAccountingReference(this);
        json.invoice_number = json.account_move_name;
        return json;
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.laundry_delivery_date = json.laundry_delivery_date || "";
        this.laundry_priority = json.laundry_priority || json.x_laundry_priority || "normal";
        this.laundry_note = json.laundry_note || "";
        this.laundry_intake_id = json.laundry_intake_id || 0;
        this.laundry_processed_line_uuids = Array.isArray(json.laundry_processed_line_uuids)
            ? [...new Set(json.laundry_processed_line_uuids.filter(Boolean))]
            : [];
        this.laundry_line_receipt_map = json.laundry_line_receipt_map || {};
        this.pos_reference = json.pos_reference || (isLaundryReference(json.name) ? "" : json.name) || "";
        this.laundry_intake_name = json.laundry_intake_name || "";
        this.x_display_reference = json.x_display_reference || "";
        this.account_move_name = resolveAccountingReference(json);
        this.invoice_number = this.account_move_name;

        const reference = resolveLaundryReference(json);
        if (reference) {
            applyLaundryReference(this, reference);
        }
    },

    hasLaundryLineBeenReceived(line) {
        return Boolean(line?.uuid && this.laundry_processed_line_uuids?.includes(line.uuid));
    },

    markLaundryLinesReceived(lines = [], reference = "") {
        const processedLineUuids = new Set(this.laundry_processed_line_uuids || []);
        const receiptMap = { ...(this.laundry_line_receipt_map || {}) };

        for (const line of lines) {
            if (!line?.uuid) {
                continue;
            }
            processedLineUuids.add(line.uuid);
            if (reference) {
                receiptMap[line.uuid] = reference;
            }
        }

        this.laundry_processed_line_uuids = [...processedLineUuids];
        this.laundry_line_receipt_map = receiptMap;
    },

    export_for_printing() {
        logLaundryDebug("export_for_printing:before", {
            uid: this.uid,
            server_id: this.server_id,
            name: this.name,
            pos_reference: this.pos_reference,
            x_display_reference: this.x_display_reference,
            laundry_intake_name: this.laundry_intake_name,
        });

        const result = super.export_for_printing(...arguments);

        let laundryRef = resolveLaundryReference({
            x_display_reference: this.x_display_reference,
            laundry_intake_name: this.laundry_intake_name,
            name: this.name,
        });

        // global fallback
        if (!laundryRef && window.__LAST_LAUNDRY_REF__) {
            laundryRef = normalizeLaundryReference(window.__LAST_LAUNDRY_REF__);
        }

        if (laundryRef) {
            result.name = laundryRef;
            result.x_display_reference = laundryRef;

            if (!result.headerData) {
                result.headerData = {};
            }

            result.headerData.name = laundryRef;
            result.headerData.x_display_reference = laundryRef;
        }

        const accountingRef = resolveAccountingReference(this);
        if (accountingRef) {
            result.account_move_name = accountingRef;
            result.invoice_number = accountingRef;
            result.receipt_number = accountingRef;

            if (!result.headerData) {
                result.headerData = {};
            }

            result.headerData.account_move_name = accountingRef;
            result.headerData.invoice_number = accountingRef;
        }

        logLaundryDebug("export_for_printing:after", {
            uid: this.uid,
            server_id: this.server_id,
            name: this.name,
            pos_reference: this.pos_reference,
            x_display_reference: this.x_display_reference,
            laundry_intake_name: this.laundry_intake_name,
            resolved_laundry_ref: laundryRef,
            result_name: result.name,
            result_x_display_reference: result.x_display_reference,
            result_header_name: result.headerData?.name,
            result_header_x_display_reference: result.headerData?.x_display_reference,
        });

        return result;
    },

    get_name() {
        return resolveLaundryReference(this) || super.get_name(...arguments);
    },
});

patch(PartnerListScreen.prototype, {
    async saveChanges(processedChanges) {
        try {
            return await super.saveChanges(...arguments);
        } catch (error) {
            const errorMessage = getRpcErrorMessage(error, _t("Unable to save the customer."));
            await this.pos.env.services.popup.add(ErrorPopup, {
                title: _t("Unable to Save Customer"),
                body: errorMessage,
            });
        }
    },
});

patch(PosStore.prototype, {
    addPartners(partners) {
        if (Array.isArray(partners)) {
            partners = partners.map((partner) => normalizePartnerPricingFields(partner, this));
        }
        return super.addPartners(partners);
    },

    _applyLaundryOrderMetadata(order, payload) {
        if (!order || !payload) {
            return;
        }

        logLaundryDebug("_applyLaundryOrderMetadata:before", {
            order_uid: order.uid,
            order_server_id: order.server_id,
            order_name: order.name,
            order_pos_reference: order.pos_reference,
            order_x_display_reference: order.x_display_reference,
            order_laundry_intake_name: order.laundry_intake_name,
            payload,
        });

        if (payload.pos_reference) {
            order.pos_reference = payload.pos_reference;
        }

        if (payload.account_move) {
            order.account_move = Array.isArray(payload.account_move)
                ? payload.account_move[0]
                : payload.account_move;
        }

        const accountingReference = resolveAccountingReference(payload);
        if (accountingReference) {
            order.account_move_name = accountingReference;
            order.invoice_number = accountingReference;
        }

        const reference = resolveLaundryReference(payload);
        if (reference) {
            applyLaundryReference(order, reference);
        }

        if (payload.id) {
            order.server_id = payload.id;
        }

        if (payload.pos_reference) {
            this.validated_orders_name_server_id_map[payload.pos_reference] = payload.id;
        }

        if (reference) {
            this.validated_orders_name_server_id_map[reference] = payload.id;
        }

        logLaundryDebug("_applyLaundryOrderMetadata:after", {
            order_uid: order.uid,
            order_server_id: order.server_id,
            order_name: order.name,
            order_pos_reference: order.pos_reference,
            order_x_display_reference: order.x_display_reference,
            order_laundry_intake_name: order.laundry_intake_name,
            payload,
        });
    },

    _findLaundryOrderFromServerPayload(payload) {
        return this.orders.find((order) =>
            order.server_id === payload.id ||
            (payload.pos_reference && (
                order.pos_reference === payload.pos_reference ||
                order.name === payload.pos_reference ||
                order.uid === payload.pos_reference
            )) ||
            (payload.x_display_reference && (
                order.x_display_reference === payload.x_display_reference ||
                order.laundry_intake_name === payload.x_display_reference ||
                order.name === payload.x_display_reference
            ))
        );
    },

    async _fetchCanonicalLaundryPayload(payload) {
        if (!payload?.id || (resolveLaundryReference(payload) && resolveAccountingReference(payload))) {
            logLaundryDebug("_fetchCanonicalLaundryPayload:skip", payload);
            return payload;
        }

        try {
            const records = await this.orm.silent.call(
                "pos.order",
                "search_read",
                [[["id", "=", payload.id]]],
                {
                    fields: ["id", "name", "pos_reference", "x_display_reference", "x_laundry_intake_id", "account_move"],
                    limit: 1,
                }
            );

            const record = records?.[0];
            if (!record) {
                return payload;
            }

            const intakeReference = Array.isArray(record.x_laundry_intake_id)
                ? record.x_laundry_intake_id[1]
                : "";
            const displayReference =
                normalizeLaundryReference(record.x_display_reference) ||
                normalizeLaundryReference(intakeReference) ||
                (isLaundryReference(record.name) ? normalizeLaundryReference(record.name) : "");

            const canonicalPayload = {
                ...payload,
                id: record.id,
                name: displayReference || record.name || payload.name || payload.pos_reference,
                pos_reference: record.pos_reference || payload.pos_reference || "",
                x_display_reference: displayReference,
                laundry_intake_name: displayReference,
                account_move: record.account_move || payload.account_move || false,
                account_move_name: resolveAccountingReference(record) || resolveAccountingReference(payload),
                invoice_number: resolveAccountingReference(record) || resolveAccountingReference(payload),
            };

            logLaundryDebug("_fetchCanonicalLaundryPayload:fetched", {
                original_payload: payload,
                record,
                canonicalPayload,
            });

            return canonicalPayload;
        } catch (error) {
            console.warn("Unable to fetch canonical laundry reference after payment sync:", error);
            return payload;
        }
    },

    async _save_to_server(orders, options = {}) {
        const serverIds = await super._save_to_server(...arguments);

        for (const payload of serverIds || []) {
            const order = this._findLaundryOrderFromServerPayload(payload);
            if (order) {
                this._applyLaundryOrderMetadata(order, payload);
            }
        }

        return serverIds;
    },

    async push_single_order(order) {
        const serverIds = await super.push_single_order(...arguments);
        const payload = Array.isArray(serverIds) ? serverIds[0] : null;

        logLaundryDebug("push_single_order:server_response", {
            order_uid: order?.uid,
            order_server_id: order?.server_id,
            order_name: order?.name,
            order_pos_reference: order?.pos_reference,
            order_x_display_reference: order?.x_display_reference,
            order_laundry_intake_name: order?.laundry_intake_name,
            payload,
            serverIds,
        });

        if (order && payload) {
            const canonicalPayload = await this._fetchCanonicalLaundryPayload(payload);
            this._applyLaundryOrderMetadata(order, canonicalPayload);
            serverIds[0] = canonicalPayload;

            logLaundryDebug("push_single_order:after_hydration", {
                order_uid: order.uid,
                order_server_id: order.server_id,
                order_name: order.name,
                order_pos_reference: order.pos_reference,
                order_x_display_reference: order.x_display_reference,
                order_laundry_intake_name: order.laundry_intake_name,
                canonicalPayload,
            });
        }

        return serverIds;
    },

    _updateOrder(ordersResponseData, orders) {
        const order = super._updateOrder(...arguments);
        this._applyLaundryOrderMetadata(order || this._findLaundryOrderFromServerPayload(ordersResponseData), ordersResponseData);
        return order;
    },
});

patch(PaymentScreen.prototype, {
    async _finalizeValidation() {
        if (this.currentOrder.is_paid_with_cash() || this.currentOrder.get_change()) {
            this.hardwareProxy.openCashbox();
        }

        this.currentOrder.date_order = luxon.DateTime.now();
        for (const line of this.paymentLines) {
            if (!line.amount === 0) {
                this.currentOrder.remove_paymentline(line);
            }
        }
        this.currentOrder.finalized = true;

        this.env.services.ui.block();
        let syncOrderResult;
        try {
            syncOrderResult = await this.pos.push_single_order(this.currentOrder);
            if (!syncOrderResult) {
                return;
            }

            logLaundryDebug("PaymentScreen._finalizeValidation:after_push_single_order", {
                currentOrder: {
                    uid: this.currentOrder.uid,
                    server_id: this.currentOrder.server_id,
                    name: this.currentOrder.name,
                    pos_reference: this.currentOrder.pos_reference,
                    x_display_reference: this.currentOrder.x_display_reference,
                    laundry_intake_name: this.currentOrder.laundry_intake_name,
                },
                syncOrderResult,
            });

            const payload = syncOrderResult[0];
            if (payload && this.pos._fetchCanonicalLaundryPayload && this.pos._applyLaundryOrderMetadata) {
                const canonicalPayload = await this.pos._fetchCanonicalLaundryPayload(payload);
                this.pos._applyLaundryOrderMetadata(this.currentOrder, canonicalPayload);
                syncOrderResult[0] = canonicalPayload;
                this.pos.set_order(this.currentOrder);

                logLaundryDebug("PaymentScreen._finalizeValidation:after_canonical_hydration", {
                    currentOrder: {
                        uid: this.currentOrder.uid,
                        server_id: this.currentOrder.server_id,
                        name: this.currentOrder.name,
                        pos_reference: this.currentOrder.pos_reference,
                        x_display_reference: this.currentOrder.x_display_reference,
                        laundry_intake_name: this.currentOrder.laundry_intake_name,
                    },
                    canonicalPayload,
                });
                try {
                    this.currentOrder.save_to_db();
                } catch {
                    // Non-fatal: receipt rendering only needs in-memory hydration.
                }
            }

            if (this.shouldDownloadInvoice() && this.currentOrder.is_to_invoice()) {
                if (syncOrderResult[0]?.account_move) {
                    await this.report.doAction("account.account_invoices", [
                        syncOrderResult[0].account_move,
                    ]);
                } else {
                    throw {
                        code: 401,
                        message: "Backend Invoice",
                        data: { order: this.currentOrder },
                    };
                }
            }
        } catch (error) {
            if (error instanceof ConnectionLostError) {
                this.pos.showScreen(this.nextScreen);
                Promise.reject(error);
                return error;
            }
            throw error;
        } finally {
            this.env.services.ui.unblock();
        }

        if (
            syncOrderResult &&
            syncOrderResult.length > 0 &&
            this.currentOrder.wait_for_push_order()
        ) {
            await this.postPushOrderResolve(syncOrderResult.map((res) => res.id));
        }

        await this.afterOrderValidation(!!syncOrderResult && syncOrderResult.length > 0);
    },
});
