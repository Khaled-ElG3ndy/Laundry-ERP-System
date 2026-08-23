/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { ProductsWidget } from "@point_of_sale/app/screens/product_screen/product_list/product_list";
import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { PosDB } from "@point_of_sale/app/store/db";
import { Product } from "@point_of_sale/app/store/models";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { unaccent } from "@web/core/utils/strings";
import { useService } from "@web/core/utils/hooks";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { onMounted, useExternalListener, useRef, useState } from "@odoo/owl";

const REQUIRED_PHONE_DIGITS = 10;
const TOP_PRODUCT_SEARCH_EVENT = "pos-right-panel-product-search";
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

const originalSearchProductInCategory = PosDB.prototype.search_product_in_category;

function notifyTopProductSearchChanged() {
    window.dispatchEvent(new CustomEvent(TOP_PRODUCT_SEARCH_EVENT));
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

function normalizeProductSearchText(value) {
    return unaccent(String(value || ""))
        .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
        .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
        .replace(/[\u064B-\u065F\u0670\u0640]/g, "")
        .replace(/[أإآٱ]/g, "ا")
        .replace(/[ؤ]/g, "و")
        .replace(/[ئ]/g, "ي")
        .replace(/[ى]/g, "ي")
        .replace(/[ة]/g, "ه")
        .replace(/[ک]/g, "ك")
        .toLowerCase()
        .replace(/[^0-9a-z\u0600-\u06ff]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
}

function getProductSmartSearchText(product) {
    return normalizeProductSearchText([
        product?.display_name,
        product?.name,
        product?.barcode,
        product?.default_code,
        product?.description,
        product?.description_sale,
    ].filter(Boolean).join(" "));
}

function scoreSmartProductMatch(product, query) {
    const normalizedQuery = normalizeProductSearchText(query);
    if (!normalizedQuery) {
        return 0;
    }

    const searchableText = getProductSmartSearchText(product);
    if (!searchableText) {
        return 0;
    }

    const words = searchableText.split(" ").filter(Boolean);
    const productName = normalizeProductSearchText(product?.display_name || product?.name || "");
    let score = 0;

    if (productName === normalizedQuery || searchableText === normalizedQuery) {
        score += 1000;
    }
    if (productName.startsWith(normalizedQuery)) {
        score += 900;
    }
    if (words.some((word) => word.startsWith(normalizedQuery))) {
        score += 820;
    }
    if (productName.includes(normalizedQuery)) {
        score += 700;
    }
    if (searchableText.includes(normalizedQuery)) {
        score += 580;
    }

    return score;
}

function getProductsForSmartSearch(posdb, categoryId) {
    const productIds = categoryId
        ? (posdb.product_by_category_id?.[categoryId] || [])
        : Object.keys(posdb.product_by_id || {});
    const products = [];
    for (const productId of productIds) {
        const product = posdb.get_product_by_id(Number(productId));
        if (product && posdb.shouldAddProduct(product, products)) {
            products.push(product);
        }
    }
    return products;
}

patch(PosDB.prototype, {
    search_product_in_category(categoryId, query) {
        const safeCategoryId = categoryId || 0;
        const rawQuery = String(query || "").trim();
        if (!rawQuery) {
            return [];
        }

        const exactResults = originalSearchProductInCategory.call(this, safeCategoryId, rawQuery) || [];
        const exactResultIds = new Set(exactResults.map((product) => product.id));
        const smartResults = [];

        for (const product of getProductsForSmartSearch(this, safeCategoryId)) {
            const score = scoreSmartProductMatch(product, rawQuery);
            if (!score || exactResultIds.has(product.id)) {
                continue;
            }
            smartResults.push({ product, score });
        }

        smartResults.sort((left, right) => {
            if (right.score !== left.score) {
                return right.score - left.score;
            }
            return String(left.product.display_name || "").localeCompare(
                String(right.product.display_name || "")
            );
        });

        return [
            ...exactResults,
            ...smartResults.map((result) => result.product),
        ].slice(0, this.limit);
    },
});

patch(ProductsWidget.prototype, {
    setup() {
        super.setup(...arguments);
        useExternalListener(window, TOP_PRODUCT_SEARCH_EVENT, () => this.render(true));
    },
});

patch(Product.prototype, {
    getImageUrl() {
        if (!this.image_128) {
            return "";
        }
        return `/web/image?model=product.product&field=image_1920&id=${this.id}&unique=${this.write_date}`;
    },
});

function getRpcErrorMessage(error, fallbackMessage) {
    const candidates = [
        error?.data?.arguments?.[0],
        error?.data?.exceptionMessage,
        error?.data?.message,
        error?.message,
        error?.cause?.data?.arguments?.[0],
        error?.cause?.data?.message,
        error?.cause?.message,
    ];

    for (const candidate of candidates) {
        if (
            typeof candidate === "string" &&
            candidate.trim() &&
            !["RPC_ERROR", "Odoo Server Error"].includes(candidate.trim())
        ) {
            return candidate.trim();
        }
    }

    const debugMatch = error?.data?.debug?.match(/(?:ValidationError|UserError):\s*([^\n]+)/);
    return debugMatch?.[1]?.trim() || fallbackMessage;
}

function afterNextPaint() {
    return new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
}

function isDuplicatePhoneErrorMessage(message) {
    return /رقم الهاتف.*(?:مستخدم|مكرر)|(?:duplicate|exist).*(?:phone|mobile)/i.test(
        String(message || "")
    );
}

class ClearOrderPopup extends AbstractAwaitablePopup {
    static template = "pos_right_panel.ClearOrderPopup";
    static defaultProps = {
        title: _t("Start a New Order"),
        subtitle: _t("The current items will be cleared and a new order will be opened."),
        detailLabel: _t("Current Items"),
        detailValue: "0",
        confirmText: _t("Continue"),
        cancelText: _t("Back"),
    };
}

patch(Navbar.prototype, {
    get showTopProductSearch() {
        return Boolean(
            !this.ui?.isSmall &&
            this.pos?.mainScreen?.component === ProductScreen
        );
    },

    get topProductSearchPlaceholder() {
        return _t("Search products...").replace(/[.…]+$/u, "");
    },

    get topProductSearchDirection() {
        let localizedDirection = "";
        try {
            localizedDirection = localization.direction;
        } catch {
            localizedDirection = "";
        }
        return (
            localizedDirection === "rtl" ||
            document.documentElement.dir === "rtl" ||
            document.body?.classList.contains("o_rtl")
        ) ? "rtl" : "ltr";
    },

    get topProductSearchClearLabel() {
        return _t("Clear search");
    },

    get hasTopProductSearchValue() {
        return Boolean((this.pos?.searchProductWord || "").trim());
    },

    onTopProductSearchInput(ev) {
        if (!this.pos) {
            return;
        }
        this.pos.searchProductWord = ev.target.value || "";
        if (this.pos.searchProductWord && !this.pos.selectedCategoryId) {
            this.pos.setSelectedCategoryId?.(0);
        }
        this.render(true);
        notifyTopProductSearchChanged();
    },

    onTopProductSearchKeydown(ev) {
        if (ev.key === "Escape") {
            this.clearTopProductSearch();
            ev.currentTarget?.blur?.();
        }
    },

    clearTopProductSearch() {
        if (!this.pos) {
            return;
        }
        this.pos.searchProductWord = "";
        this.render(true);
        notifyTopProductSearchChanged();
    },
});

class CustomerPopup extends AbstractAwaitablePopup {
    static template = "pos_right_panel.CustomerPopup";
    static defaultProps = {
        title: _t("Select Customer"),
        confirmText: _t("Set Customer"),
        cancelText: _t("Cancel"),
        removeText: _t("Remove Customer"),

        subtitle: _t("Search for and select the customer for this order."),

        searchLabel: _t("Customer Search"),

        customerSection: _t("Customer"),

        customerTypeLabel: _t("Type"),

        customerTypeCustomer: isArabicInterface() ? "أفراد" : _t("Individual"),

        customerTypeCompany: isArabicInterface() ? "شركات" : _t("Company"),

        customerName: _t("Customer Name"),
        companyName: _t("Company Name"),

        phone: _t("Phone"),

        addCustomer: _t("Add Customer"),

        closeForm: _t("Close Form"),

        createCustomer: _t("Create Customer"),

        creatingCustomer: _t("Creating..."),

        selectedBadge: _t("Selected"),

        searchPlaceholder: _t("Search by name or phone"),

        phonePlaceholder: _t("The phone number must contain 8 or 11 digits"),

        emptyText: _t("There are no customers."),

        duplicatePhoneTitle: _t("Phone Number Already in Use"),
        duplicatePhoneSubtitle: _t("This number is already registered to a customer. Select that customer instead of creating a new one."),
        existingCustomerLabel: _t("Existing Customer"),
        duplicatePhoneLabel: _t("Existing Phone Number"),
        useExistingCustomer: _t("Select This Customer"),

        partner: null,
    };

    setup() {
        super.setup();
        this.pos = usePos();
        this.notification = useService("pos_notification");
        this.orm = useService("orm");
        this.searchInputRef = useRef("customer-popup-search");
        this.state = useState({
            query: "",
            selectedPartner: this.props.partner || null,
            showCreateCustomer: false,
            // Each till serves one kind of account, so the type is decided by
            // the POS rather than left to the cashier: the retail counter
            // creates individuals, the hotel counter creates companies.
            newCustomerType: this.pos?.config?.is_hotel_pos ? "company" : "person",
            newCustomerName: "",
            newCustomerPhone: "",
            creatingCustomer: false,
            duplicatePhoneInfo: null,
            createCustomerError: "",
            errors: {
                newCustomerName: "",
                newCustomerPhone: "",
            },
        });
        this.duplicateLookupToken = 0;

        onMounted(() => {
            this.searchInputRef.el?.focus();
        });
    }

    get isTenDigitPhoneModeEnabled() {
        return Boolean(this.pos?.config?.laundry_require_ten_digit_phone);
    }

    get phoneDigitIndexes() {
        return Array.from({ length: REQUIRED_PHONE_DIGITS }, (_, index) => index);
    }

    get phonePlaceholder() {
        return this.isTenDigitPhoneModeEnabled
            ? _t("Enter a 10-digit phone number")
            : _t("The phone number must contain 8 or 11 digits");
    }

    get phoneDigitsHelper() {
        return _t("Enter the phone number in 10 boxes.");
    }

    getPhoneDigitValue(index) {
        return (this.state.newCustomerPhone || "").charAt(index) || "";
    }

    phoneBoxAriaLabel(index) {
        return `${this.props.phone} ${index + 1}`;
    }

    setPhoneDigits(digits) {
        this.state.newCustomerPhone = this.normalizePhone(digits);
        this.clearError("newCustomerPhone");
    }

    focusPhoneDigit(index) {
        afterNextPaint().then(() => {
            const el = document.getElementById(
                `customer-popup-new-phone-digit-${index}`
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
            return;
        }

        const nextIndex = this.fillPhoneDigitsFrom(index, digits);
        const targetIndex = Math.min(nextIndex, REQUIRED_PHONE_DIGITS - 1);
        this.focusPhoneDigit(targetIndex);
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
    }

    onPhoneBoxFocus(ev) {
        ev.target.select();
    }

    get partners() {
        const query = (this.state.query || "").trim();
        let partners = [];

        if (query) {
            partners = this.pos.db.search_partner(query) || [];
        } else {
            partners = this.pos.db.get_partners_sorted(200) || [];
        }

        partners = [...partners]
            .filter((partner) => partner && partner.id && partner.name)
            .sort((left, right) => (left.name || "").localeCompare(right.name || ""));

        if (this.state.selectedPartner) {
            const selectedId = this.state.selectedPartner.id;
            const selectedIndex = partners.findIndex((partner) => partner.id === selectedId);
            if (selectedIndex !== -1) {
                partners.splice(selectedIndex, 1);
            }
            partners.unshift(this.state.selectedPartner);
        }

        return partners.slice(0, 200);
    }

    get canConfirm() {
        return Boolean(this.state.selectedPartner);
    }

    get canRemoveCustomer() {
        return Boolean(this.props.partner);
    }

    get createToggleText() {
        return this.state.showCreateCustomer ? this.props.closeForm : this.props.addCustomer;
    }

    get createCustomerButtonText() {
        return this.state.creatingCustomer ? this.props.creatingCustomer : this.props.createCustomer;
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
    }

    clearSearch() {
        this.state.query = "";
        if (this.searchInputRef.el) {
            this.searchInputRef.el.value = "";
            this.searchInputRef.el.focus();
        }
    }

    clearError(fieldName) {
        if (this.state.errors[fieldName]) {
            this.state.errors[fieldName] = "";
        }
    }

    clearDuplicatePhoneState() {
        this.duplicateLookupToken += 1;
        this.state.duplicatePhoneInfo = null;
        this.state.createCustomerError = "";
    }

    resetCreateCustomerForm() {
        this.state.showCreateCustomer = false;
        this.state.newCustomerType = this.defaultCustomerType;
        this.state.newCustomerName = "";
        this.state.newCustomerPhone = "";
        this.clearDuplicatePhoneState();
        this.clearError("newCustomerName");
        this.clearError("newCustomerPhone");
    }

    normalizePhone(value) {
        const rawValue = String(value || "");
        if (!this.isTenDigitPhoneModeEnabled) {
            return rawValue.replace(/\D/g, "").slice(0, 11);
        }
        return rawValue.replace(/\D/g, "").slice(0, REQUIRED_PHONE_DIGITS);
    }

    isValidPhone(phone) {
        if (!this.isTenDigitPhoneModeEnabled) {
            return /^(?:\d{8}|\d{11})$/.test(phone);
        }
        return new RegExp(`^\\d{${REQUIRED_PHONE_DIGITS}}$`).test(phone);
    }

    get isHotelPos() {
        return Boolean(this.pos?.config?.is_hotel_pos);
    }

    get defaultCustomerType() {
        return this.isHotelPos ? "company" : "person";
    }

    toggleCreateCustomer() {
        this.state.showCreateCustomer = !this.state.showCreateCustomer;
        if (!this.state.showCreateCustomer) {
            this.resetCreateCustomerForm();
        }
    }

    onCustomerTypeClick(ev) {
        const type = ev.currentTarget?.dataset?.customerType;
        if (!["person", "company"].includes(type)) {
            return;
        }
        this.state.newCustomerType = type;
    }

    onNewCustomerNameInput(ev) {
        this.state.newCustomerName = ev.target.value;
        this.state.createCustomerError = "";
        this.clearError("newCustomerName");
    }

    async onNewCustomerPhoneInput(ev) {
        this.state.newCustomerPhone = this.normalizePhone(ev.target.value);
        this.clearDuplicatePhoneState();
        this.clearError("newCustomerPhone");
        await this.updateDuplicatePhoneState();
    }

    selectPartner(partner) {
        if (!partner) {
            return;
        }
        this.state.selectedPartner = partner;
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

    onPartnerClick(ev) {
        const partnerId = parseInt(ev.currentTarget?.dataset?.partnerId, 10);
        if (!partnerId) {
            return;
        }
        const partner = this.partners.find((item) => item.id === partnerId);
        this.selectPartner(partner);
    }

    getDuplicatePhonePartnerLabel() {
        return (
            this.state.duplicatePhoneInfo?.partnerPhone ||
            this.state.duplicatePhoneInfo?.phone ||
            this.state.newCustomerPhone ||
            ""
        );
    }

    async findExistingPartnerByPhone(phone) {
        const normalizedPhone = this.normalizePhone(phone);
        if (!normalizedPhone) {
            return null;
        }

        const localPartner = Object.values(this.pos.db.partner_by_id || {}).find((partner) => {
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

        const fields = ["id", "name", "phone", "mobile", "email", "company_type", "is_company"];
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
            return this.pos.db.get_partner_by_id(matchedPartner.id) || matchedPartner;
        }

        return null;
    }

    extractDuplicatePartnerName(message) {
        return message?.match(/لدى:\s*(.+?)(?:[.،]| يرجى|$)/)?.[1]?.trim() || "";
    }

    showDuplicatePhoneError(partner, phone, fallbackMessage = "") {
        const displayPhone = phone || this.state.newCustomerPhone || "";
        const partnerName = partner?.name || this.extractDuplicatePartnerName(fallbackMessage);
        const message = partnerName
            ? _t("Phone number %(phone)s is already used by customer %(customer)s.", {
                phone: displayPhone,
                customer: partnerName,
            })
            : fallbackMessage || _t("Phone number %(phone)s is already in use.", {
                phone: displayPhone,
            });

        this.state.duplicatePhoneInfo = {
            partner: partner || null,
            partnerName,
            partnerPhone: partner?.mobile || partner?.phone || displayPhone,
            phone: displayPhone,
            message,
        };
        if (partner) {
            this.selectPartner(partner);
            this.state.query = partner.name || displayPhone;
        }
        this.state.errors.newCustomerPhone = message;
    }

    async updateDuplicatePhoneState(phone = this.state.newCustomerPhone) {
        const normalizedPhone = this.normalizePhone(phone);
        if (!normalizedPhone || !this.isValidPhone(normalizedPhone)) {
            this.state.duplicatePhoneInfo = null;
            return null;
        }

        const lookupToken = ++this.duplicateLookupToken;
        const existingPartner = await this.findExistingPartnerByPhone(normalizedPhone).catch(() => null);

        if (lookupToken !== this.duplicateLookupToken) {
            return null;
        }

        if (this.normalizePhone(this.state.newCustomerPhone || "") !== normalizedPhone) {
            return null;
        }

        if (existingPartner) {
            this.showDuplicatePhoneError(existingPartner, normalizedPhone);
            return existingPartner;
        }

        this.state.duplicatePhoneInfo = null;
        return null;
    }

    useDuplicatePhonePartner() {
        if (!this.state.duplicatePhoneInfo?.partner) {
            return;
        }

        const partner = this.state.duplicatePhoneInfo.partner;
        this.selectPartner(partner);
        this.state.query = partner.name || partner.mobile || partner.phone || "";
        this.state.showCreateCustomer = false;
        this.state.newCustomerType = this.defaultCustomerType;
        this.state.newCustomerName = "";
        this.state.newCustomerPhone = "";
        this.clearDuplicatePhoneState();
        this.clearError("newCustomerName");
        this.clearError("newCustomerPhone");
        this.notification.add(_t("The existing customer with the same phone number was selected."), {
            type: "success",
        });
    }

    async createCustomer() {
        const name = (this.state.newCustomerName || "").trim();
        const phone = (this.state.newCustomerPhone || "").trim();

        this.clearDuplicatePhoneState();
        this.clearError("newCustomerName");
        this.clearError("newCustomerPhone");

        if (!name) {
            this.state.errors.newCustomerName = _t("Customer name is required.");
            return;
        }

        if (!phone) {
            this.state.errors.newCustomerPhone = _t("Phone number is required.");
            return;
        }

        if (!this.isValidPhone(phone)) {
            this.state.errors.newCustomerPhone = this.isTenDigitPhoneModeEnabled
                ? _t("The phone number must contain 10 digits.")
                : _t("The phone number must contain 8 or 11 digits.");
            return;
        }

        this.state.creatingCustomer = true;

        try {
            const existingPartner = await this.updateDuplicatePhoneState(phone);
            if (existingPartner) {
                this.showDuplicatePhoneError(existingPartner, phone);
                this.notification.add(_t("A customer with the same phone number was found."), {
                    type: "warning",
                });
                return;
            }

            const values = {
                name: name,
                company_type: this.state.newCustomerType,
                is_company: this.state.newCustomerType === "company",
                mobile: phone || false,
                phone: phone || false,
                customer_rank: 1,
            };
            if (this.isHotelPos) {
                // The hotel POS only lists partners flagged as contract
                // customers, so without this the account would vanish from the
                // very screen it was just created on. The flag only exists when
                // the hotel module is installed, which is also the only way
                // is_hotel_pos can be true.
                values.is_hotel_customer = true;
            }

            const partnerId = await this.orm.create("res.partner", [values]);
            const partner = await this.loadPartnerById(partnerId);

            if (!partner) {
                throw new Error("Partner was not loaded after creation");
            }

            this.selectPartner(partner);
            this.state.query = partner.name || "";
            this.resetCreateCustomerForm();

            this.notification.add(_t("Customer created successfully."), {
                type: "success",
            });
            this.props.close({ confirmed: true, payload: partner });
        } catch (error) {
            const errorMessage = getRpcErrorMessage(error, _t("Failed to create the customer."));
            const existingPartner = await this.updateDuplicatePhoneState(phone);

            if (existingPartner || isDuplicatePhoneErrorMessage(errorMessage)) {
                this.showDuplicatePhoneError(existingPartner, phone, errorMessage);
                this.notification.add(_t("A customer with the same phone number was found."), {
                    type: "warning",
                });
                return;
            }

            console.warn("Create customer from popup failed:", {
                message: errorMessage,
                error,
            });
            this.state.createCustomerError = errorMessage;
            this.notification.add(errorMessage, {
                type: "danger",
            });
        } finally {
            this.state.creatingCustomer = false;
        }
    }

    confirmSelection() {
        if (!this.state.selectedPartner) {
            this.notification.add(_t("Select a customer first."), {
                type: "warning",
            });
            return;
        }
        this.props.close({ confirmed: true, payload: this.state.selectedPartner });
    }

    clearCustomer() {
        this.props.close({ confirmed: true, payload: null });
    }

    isSelected(partner) {
        return this.state.selectedPartner?.id === partner.id;
    }
}

patch(PosStore.prototype, {
    async selectPartner() {
        const currentOrder = this.get_order();
        if (!currentOrder) {
            return;
        }

        const currentPartner = currentOrder.get_partner();
        if (currentPartner && currentOrder.getHasRefundLines()) {
            this.popup.add(ErrorPopup, {
                title: _t("Customer Cannot Be Changed"),
                body: _t(
                    "This order already contains refunded items for customer %s, so its customer cannot be changed. Create a new order for the new customer.",
                    currentPartner.name
                ),
            });
            return;
        }

        const { confirmed, payload: newPartner } = await this.popup.add(CustomerPopup, {
            partner: currentPartner,
        });
        if (confirmed) {
            currentOrder.set_partner(newPartner);
            currentOrder.save_to_db?.();
            this.addOrderToUpdateSet?.();
        }
    },
});

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.pos = usePos();
        this.popup = useService("popup");
    },

    get controlButtons() {
        return (super.controlButtons || []).filter((button) => {
            return button.name !== "SetPricelistButton";
        });
    },

    get sidebarActionButtonNames() {
        return [
            "NewOrderButton",
            "PendingOrdersButton",
            "LaundryReceiptButton",
            "LaundryOrderTrackingButton",
            "OrderlineCustomerNoteButton",
            "RefundButton",
        ];
    },

    get primarySidebarActionButtonNames() {
        return [
            "NewOrderButton",
            "PendingOrdersButton",
        ];
    },

    get secondarySidebarActionButtonNames() {
        return [
            "LaundryReceiptButton",
            "LaundryOrderTrackingButton",
        ];
    },

    get utilitySidebarActionButtonNames() {
        return [
            "OrderlineCustomerNoteButton",
            "RefundButton",
        ];
    },

    get sidebarActionButtons() {
        const visibleButtons = new Map((this.controlButtons || []).map((button) => [button.name, button]));
        return this.sidebarActionButtonNames
            .map((name) => visibleButtons.get(name))
            .filter(Boolean);
    },

    get primarySidebarActionButtons() {
        const visibleButtons = new Map((this.controlButtons || []).map((button) => [button.name, button]));
        return this.primarySidebarActionButtonNames
            .map((name) => visibleButtons.get(name))
            .filter(Boolean);
    },

    get secondarySidebarActionButtons() {
        const visibleButtons = new Map((this.controlButtons || []).map((button) => [button.name, button]));
        return this.secondarySidebarActionButtonNames
            .map((name) => visibleButtons.get(name))
            .filter(Boolean);
    },

    get utilitySidebarActionButtons() {
        const visibleButtons = new Map((this.controlButtons || []).map((button) => [button.name, button]));
        return this.utilitySidebarActionButtonNames
            .map((name) => visibleButtons.get(name))
            .filter(Boolean);
    },

    get leftControlButtons() {
        const sidebarButtons = new Set(this.sidebarActionButtonNames);
        return (this.controlButtons || []).filter((button) => {
            return button.name !== "SetPricelistButton" && !sidebarButtons.has(button.name);
        });
    },

    get rootCategories() {
        const db = this.pos?.db;
        if (!db || !db.category_by_id) {
            return [];
        }

        return Object.values(db.category_by_id).filter((cat) => {
            return cat && cat.id !== 0 && (!cat.parent_id || cat.parent_id[0] === 0);
        });
    },

    get selectedCategoryIdForSidebar() {
        return this.pos?.selectedCategoryId || 0;
    },

    _getOrderlineActionTarget(orderline) {
        return orderline?.comboParent || orderline;
    },

    _selectOrderlineForAction(orderline) {
        const targetLine = this._getOrderlineActionTarget(orderline);
        if (!targetLine) {
            return null;
        }

        this.numberBuffer?.reset?.();
        this.pos?.get_order()?.select_orderline(targetLine);
        return targetLine;
    },

    async onClickEditOrderline(orderline) {
        const targetLine = this._selectOrderlineForAction(orderline);
        if (!targetLine) {
            return;
        }

        if (this.pos?.editLaundryVariantOrderline) {
            const updated = await this.pos.editLaundryVariantOrderline(targetLine);
            if (updated) {
                this.render(true);
            }
            return;
        }

        this.notification.add(_t("The service edit window cannot be opened for this item."), {
            type: "warning",
        });
    },

    onClickDeleteOrderline(orderline) {
        const targetLine = this._selectOrderlineForAction(orderline);
        if (!targetLine) {
            return;
        }

        this.pos.numpadMode = "quantity";
        this._setValue("remove");
        this.numberBuffer?.reset?.();
        this.render(true);
    },

    selectSidebarCategory(categoryId) {
        if (!this.pos) return;
        this.pos.selectedCategoryId = categoryId;
        this.pos.searchProductWord = "";
        this.render(true);
        notifyTopProductSearchChanged();
    },

    isSidebarCategoryActive(categoryId) {
        return (this.pos?.selectedCategoryId || 0) === categoryId;
    },

    async onClickClearOrder() {
        const order = this.pos?.get_order();
        if (!order) {
            this.notification.add(_t("There is no active order."), {
                type: "danger",
            });
            return;
        }

        const orderLines = [...order.get_orderlines()];
        if (!orderLines.length) {
            this.notification.add(_t("There are no items to remove."), {
                type: "warning",
            });
            return;
        }

        const shouldKeepExistingOrder = Boolean(
            order.server_id ||
            order.finalized ||
            order.laundry_intake_id ||
            (order.paymentlines && order.paymentlines.length > 0)
        );

        const { confirmed } = await this.popup.add(ClearOrderPopup, {
            title: shouldKeepExistingOrder ? _t("Open a New Order") : _t("Clear Current Order"),
            subtitle: shouldKeepExistingOrder
                ? _t("The current order will remain saved and a clean order will be opened for the next customer.")
                : _t("The items in this order will be deleted and a new empty order will be opened."),
            detailLabel: _t("Item Count"),
            detailValue: String(orderLines.length),
            confirmText: shouldKeepExistingOrder ? _t("Open New Order") : _t("Confirm Clear"),
            cancelText: _t("Back"),
        });

        if (!confirmed) {
            return;
        }

        if (shouldKeepExistingOrder) {
            order.save_to_db?.();
            this.pos.addOrderToUpdateSet?.();
            this.pos.add_new_order();

            this.notification.add(_t("A new order was opened and the previous order was kept."), {
                type: "success",
            });
            return;
        }

        for (const line of orderLines) {
            if (line.order === order) {
                order.removeOrderline(line);
            }
        }

        this.pos.removeOrder(order);

        if (!this.pos.get_order()) {
            this.pos.add_new_order();
        }

        this.notification.add(_t("The current order was cleared and a new order was opened."), {
            type: "success",
        });
    },

    async onClickCustomer() {
        const order = this.pos?.get_order();
        if (!order) {
            this.notification.add(_t("There is no active order."), {
                type: "danger",
            });
            return;
        }

        const currentPartner = order.get_partner();
        const { confirmed, payload } = await this.popup.add(CustomerPopup, {
            partner: currentPartner,
        });

        if (!confirmed) {
            return;
        }

        if (order.get_partner() !== payload) {
            order.set_partner(payload || null);
            order.save_to_db?.();
            this.pos.addOrderToUpdateSet?.();
        }
    },

    onClickReprint() {
        this.notification.add(_t("Reprint action is not connected yet."), {
            type: "warning",
        });
    },

    onClickDailyReport() {
        this.notification.add(_t("Daily Report action is not connected yet."), {
            type: "warning",
        });
    },

    onClickOrders() {
        if (this.pos && this.pos.showScreen) {
            this.pos.showScreen("TicketScreen");
        } else {
            this.notification.add(_t("Orders screen is not available."), {
                type: "danger",
            });
        }
    },

    onClickRefund() {
        if (this.pos && this.pos.showScreen) {
            this.pos.showScreen("TicketScreen");
            this.notification.add(_t("Open an order from Orders to refund it."), {
                type: "info",
            });
        } else {
            this.notification.add(_t("Refund flow is not available."), {
                type: "danger",
            });
        }
    },

    onClickPayment() {
        const order = this.pos.get_order();
        if (!order) {
            this.notification.add(_t("There is no active order."), {
                type: "danger",
            });
            return;
        }

        if (this.pos && this.pos.showScreen) {
            this.pos.showScreen("PaymentScreen");
        } else {
            this.notification.add(_t("Payment screen is not available."), {
                type: "danger",
            });
        }
    },
});
