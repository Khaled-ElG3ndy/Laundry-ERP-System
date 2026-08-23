/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Orderline } from "@point_of_sale/app/store/models";
import { ProductsWidget } from "@point_of_sale/app/screens/product_screen/product_list/product_list";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";

const PERF_PREFIX = "LaundryVariantPerf";
let perfSequence = 0;

function isPerfDebugEnabled() {
    try {
        const params = new URLSearchParams(window.location.search || "");
        return (
            params.has("debug") ||
            window.localStorage?.getItem("laundryVariantPerf") === "1"
        );
    } catch {
        return false;
    }
}

function perfNow() {
    return window.performance?.now ? window.performance.now() : Date.now();
}

function createPerfTrace(source = "open") {
    if (!isPerfDebugEnabled()) {
        return null;
    }

    const trace = {
        id: ++perfSequence,
        source,
        marks: {},
    };

    markPerf(trace, "click");
    return trace;
}

function markPerf(trace, name) {
    if (!trace) {
        return 0;
    }

    const value = perfNow();
    trace.marks[name] = value;

    try {
        window.performance?.mark?.(`${PERF_PREFIX}:${trace.id}:${name}`);
    } catch {
        // Ignore browser performance API failures in production POS.
    }

    return value;
}

function logPerf(label, duration) {
    if (!isPerfDebugEnabled()) {
        return;
    }

    // eslint-disable-next-line no-console
    console.debug(`[${PERF_PREFIX}] ${label}: ${duration.toFixed(1)}ms`);
}

function measurePerf(trace, label, startName, endName) {
    if (!trace || trace.marks[startName] === undefined) {
        return;
    }

    if (trace.marks[endName] === undefined) {
        markPerf(trace, endName);
    }

    const duration = trace.marks[endName] - trace.marks[startName];
    logPerf(`${trace.source} #${trace.id} ${label}`, duration);

    try {
        window.performance?.measure?.(
            `${PERF_PREFIX}:${trace.id}:${label}`,
            `${PERF_PREFIX}:${trace.id}:${startName}`,
            `${PERF_PREFIX}:${trace.id}:${endName}`
        );
    } catch {
        // The numeric log above is the source of truth during debugging.
    }
}

function getRelationId(record) {
    if (Array.isArray(record)) {
        return record[0];
    }

    if (record && typeof record === "object") {
        return record.id || null;
    }

    return record || null;
}

function getTmplId(product) {
    return getRelationId(product?.product_tmpl_id) || null;
}

function getTemplateIdentity(product) {
    return getTmplId(product) || `product-${product?.id || product?.display_name || ""}`;
}

function cleanTemplateNameFromDisplay(displayName) {
    return String(displayName || "")
        .replace(/\s*\([^)]*\)\s*$/, "")
        .replace(/\s+/g, " ")
        .trim();
}

function getTemplateName(product) {
    const name = String(product?.name || "").trim();
    const displayName = String(product?.display_name || "").trim();

    if (name && (!displayName || displayName.startsWith(name))) {
        return name;
    }

    return cleanTemplateNameFromDisplay(displayName || name);
}

function getAllProducts(pos) {
    return Object.values(pos?.db?.product_by_id || {});
}

function getCategoryProducts(pos, selectedCategoryId) {
    if (selectedCategoryId && selectedCategoryId !== 0) {
        return (pos.db.product_by_category_id?.[selectedCategoryId] || [])
            .map((id) => pos.db.product_by_id[id])
            .filter(Boolean);
    }

    return getAllProducts(pos);
}

function getProductDisplayAmount(pos, product) {
    try {
        if (typeof product.get_display_price === "function") {
            return Number(product.get_display_price());
        }
    } catch {
        // The loaded lst_price is still the POS source value.
    }

    return Number(product?.lst_price || 0);
}

function formatPrice(pos, product) {
    const amount = getProductDisplayAmount(pos, product);

    if (pos.env?.utils?.formatCurrency) {
        return pos.env.utils.formatCurrency(amount);
    }

    const symbol = pos.currency?.symbol || "";
    return `${amount.toFixed(2)} ${symbol}`;
}

function getProductPrice(product) {
    return Number(product?.lst_price || 0);
}

function getSelectionPriceAmount(entry) {
    if (!entry?.item) {
        return 0;
    }

    if (entry.item.is_optional_attribute) {
        return Number(entry.item.price_extra || 0);
    }

    return Number(entry.item.lst_price || 0);
}

function getSelectionPriceText(entry) {
    const amount = getSelectionPriceAmount(entry);

    if (!amount) {
        return "";
    }

    const rawPrice = String(entry.price || "").replace(/\u00a0/g, " ").trim();
    const matchedNumber = rawPrice.match(/-?\d+(?:[.,]\d+)?/);
    const readableAmount = matchedNumber
        ? matchedNumber[0].replace(",", ".")
        : amount.toFixed(2);

    return `${readableAmount} SR`;
}

function getSelectionDisplayText(entry) {
    const value = String(entry?.name || "").trim();
    const group = String(entry?.groupName || "").trim();
    const prefix = group ? `${group} : ${value}` : value;
    const priceText = getSelectionPriceText(entry);

    return priceText ? `${prefix} - ${priceText}` : prefix;
}

const GROUP_ICON_CLASSES = {
    leaf: "fa fa-leaf",
    sparkles: "fa fa-magic",
    clock: "fa fa-clock-o",
    zap: "fa fa-bolt",
    tag: "fa fa-tag",
};

const GROUP_THEMES = new Set(["blue", "orange", "primary"]);

function getGroupIconClass(iconKey) {
    return GROUP_ICON_CLASSES[iconKey] || GROUP_ICON_CLASSES.tag;
}

function getGroupTheme(themeKey) {
    return GROUP_THEMES.has(themeKey) ? themeKey : "primary";
}

function cloneProductKeepingPrototype(product, overrides = {}) {
    const clone = Object.create(Object.getPrototypeOf(product));

    Object.assign(clone, product, overrides);

    return clone;
}

function normalizeMatchText(value) {
    return String(value || "").trim().toLowerCase();
}

function makeDisplayProduct(product, templateName) {
    return cloneProductKeepingPrototype(product, {
        name: templateName,
        display_name: templateName,
        __template_display_only: true,
    });
}

function normalizeLaundryVariantSelections(selections) {
    if (!Array.isArray(selections)) {
        return [];
    }

    return selections
        .map((selection, index) => {
            const value =
                String(
                    selection?.value ||
                    selection?.name ||
                    selection?.displayText ||
                    ""
                ).trim();

            if (!value) {
                return null;
            }

            const group = String(selection?.group || "").trim();
            const productId = Number(selection?.productId || 0);
            const valueId = Number(selection?.valueId || 0);
            const originalValue = String(selection?.originalValue || "").trim();
            const isPrimary =
                selection?.isPrimary !== undefined
                    ? Boolean(selection.isPrimary)
                    : index === 0;
            const priceExtra = Number(selection?.priceExtra || 0);
            const priceAmount = Number(selection?.priceAmount || 0);
            const priceText = String(selection?.priceText || "").trim();

            return {
                group,
                value,
                productId,
                valueId,
                originalValue,
                isPrimary,
                priceExtra,
                priceAmount,
                priceText,
                displayText:
                    selection?.displayText ||
                    (group ? `${group}: ${value}` : value),
            };
        })
        .filter(Boolean);
}

function areLaundryVariantSelectionsEqual(left, right) {
    return (
        JSON.stringify(normalizeLaundryVariantSelections(left)) ===
        JSON.stringify(normalizeLaundryVariantSelections(right))
    );
}

function createTemplateBucket(templateId, product) {
    const productName = getTemplateName(product);

    return {
        templateId,
        productName,
        firstProduct: product,
        displayProduct: makeDisplayProduct(product, productName),
        groupsById: new Map(),
        groups: [],
        optionById: {},
        valueIdToOptionId: {},
        matchKeyToOptionId: {},
        hasLaundryOptions: false,
    };
}

function getOrCreateGroup(bucket, product) {
    const groupId = product.laundry_service_group_id || `template-${bucket.templateId}`;
    const theme = getGroupTheme(product.laundry_service_group_theme);
    const iconClass = getGroupIconClass(product.laundry_service_group_icon_key);

    if (!bucket.groupsById.has(groupId)) {
        bucket.groupsById.set(groupId, {
            id: groupId,
            key: `group-${groupId}`,
            group:
                product.laundry_service_group_name ||
                _t("Service"),
            code: product.laundry_service_group_code || "",
            sequence: Number(product.laundry_service_group_sequence || 0),
            theme,
            themeClass: `laundry-service-group--${theme}`,
            iconClass,
            items: [],
        });
    }

    return bucket.groupsById.get(groupId);
}

function addOptionToBucket(pos, bucket, product, metrics) {
    if (!product.laundry_service_group_id) {
        return;
    }

    bucket.hasLaundryOptions = true;

    const group = getOrCreateGroup(bucket, product);
    const priceStart = perfNow();
    const price = formatPrice(pos, product);
    metrics.priceMs += perfNow() - priceStart;

    const themeClass = group.themeClass;
    const baseClasses = `laundry-variant-card laundry-pos-card ${themeClass}`;
    const valueId = Number(product.laundry_service_value_id || 0);
    const serviceName =
        String(product.laundry_service_display_name || "").trim() ||
        String(product.laundry_service_value_name || "").trim() ||
        getTemplateName(product);

    const option = {
        id: product.id,
        productProductId: product.id,
        valueId,
        originalName:
            product.laundry_service_value_name ||
            product.laundry_service_display_name ||
            serviceName,
        name: serviceName,
        displayName: serviceName,
        groupId: group.id,
        groupName: group.group,
        iconClass: group.iconClass,
        iconKey: product.laundry_service_group_icon_key || "tag",
        theme: group.theme,
        themeClass,
        classes: baseClasses,
        selectedClasses: `${baseClasses} is-selected`,
        price,
        priceAmount: getProductPrice(product),
        item: product,
        sequence: Number(product.laundry_service_sequence || product.id || 0),
    };

    group.items.push(option);
    bucket.optionById[option.id] = option;

    if (valueId) {
        bucket.valueIdToOptionId[valueId] = option.id;
    }

    for (const key of [
        option.name,
        option.originalName,
        `${option.groupName}:${option.name}`,
        `${option.groupName}:${option.originalName}`,
    ]) {
        const normalized = normalizeMatchText(key);
        if (normalized && bucket.matchKeyToOptionId[normalized] === undefined) {
            bucket.matchKeyToOptionId[normalized] = option.id;
        }
    }
}

function finalizeTemplateBucket(bucket) {
    const groups = [...bucket.groupsById.values()]
        .map((group) => {
            group.items.sort(
                (a, b) =>
                    (a.sequence || 0) - (b.sequence || 0) ||
                    String(a.name || "").localeCompare(String(b.name || ""))
            );
            return group;
        })
        .filter((group) => group.items.length)
        .sort(
            (a, b) =>
                (a.sequence || 0) - (b.sequence || 0) ||
                String(a.group || "").localeCompare(String(b.group || ""))
        );

    bucket.groups = groups;
    bucket.groupsById = null;

    return bucket;
}

function buildLaundryVariantIndex(pos) {
    const totalStart = perfNow();
    const index = {
        byTemplateId: new Map(),
        byProductId: new Map(),
        displayProductByProductId: new Map(),
        displayProductsByCategoryId: new Map(),
    };
    const metrics = {
        priceMs: 0,
        groupMs: 0,
    };

    for (const product of getAllProducts(pos)) {
        const templateId = getTemplateIdentity(product);
        if (!index.byTemplateId.has(templateId)) {
            index.byTemplateId.set(
                templateId,
                createTemplateBucket(templateId, product)
            );
        }

        const bucket = index.byTemplateId.get(templateId);
        index.byProductId.set(product.id, bucket);
        addOptionToBucket(pos, bucket, product, metrics);
    }

    const groupStart = perfNow();
    for (const bucket of index.byTemplateId.values()) {
        finalizeTemplateBucket(bucket);
        for (const optionId of Object.keys(bucket.optionById)) {
            index.byProductId.set(Number(optionId), bucket);
        }
    }
    metrics.groupMs = perfNow() - groupStart;

    for (const product of getAllProducts(pos)) {
        const bucket = index.byTemplateId.get(getTemplateIdentity(product));
        if (bucket?.displayProduct) {
            index.displayProductByProductId.set(product.id, bucket.displayProduct);
        }
    }

    logPerf("cache build total", perfNow() - totalStart);
    logPerf("cache group build", metrics.groupMs);
    logPerf("cache price formatting", metrics.priceMs);

    return index;
}

function ensureLaundryVariantIndex(pos) {
    if (!pos.__laundryVariantIndex) {
        pos.__laundryVariantIndex = buildLaundryVariantIndex(pos);
    }

    return pos.__laundryVariantIndex;
}

function getTemplateBucketForProduct(pos, product) {
    const index = ensureLaundryVariantIndex(pos);
    const realProduct = pos.db.product_by_id?.[product?.id] || product;
    const templateId = getTemplateIdentity(realProduct);

    return (
        index.byTemplateId.get(templateId) ||
        index.byProductId.get(realProduct?.id) ||
        null
    );
}

function buildSelectedIdFromVariant(variant) {
    return variant?.id || null;
}

function buildSelectedIdFromSelections(defaultSelectedId, bucket, selections) {
    const normalizedSelections = normalizeLaundryVariantSelections(selections);

    for (const selection of normalizedSelections) {
        if (selection.productId && bucket.optionById[selection.productId]) {
            return selection.productId;
        }

        if (
            selection.valueId &&
            bucket.valueIdToOptionId[selection.valueId] !== undefined
        ) {
            return bucket.valueIdToOptionId[selection.valueId];
        }

        const candidates = [
            selection.displayText,
            selection.value,
            selection.originalValue,
            selection.group && selection.value
                ? `${selection.group}:${selection.value}`
                : "",
            selection.group && selection.originalValue
                ? `${selection.group}:${selection.originalValue}`
                : "",
        ];

        for (const candidate of candidates) {
            const optionId = bucket.matchKeyToOptionId[normalizeMatchText(candidate)];
            if (optionId !== undefined) {
                return optionId;
            }
        }
    }

    return bucket.optionById[defaultSelectedId]
        ? defaultSelectedId
        : bucket.groups?.[0]?.items?.[0]?.id || null;
}

function dedupeProductsByTemplate(pos, products, renameToTemplate = false) {
    const index = ensureLaundryVariantIndex(pos);
    const seenTemplates = new Set();
    const result = [];

    for (const product of products || []) {
        const templateId = getTemplateIdentity(product);

        if (seenTemplates.has(templateId)) {
            continue;
        }

        seenTemplates.add(templateId);

        if (renameToTemplate) {
            result.push(
                index.displayProductByProductId.get(product.id) ||
                makeDisplayProduct(product, getTemplateName(product))
            );
        } else {
            result.push(product);
        }
    }

    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Popup
// ─────────────────────────────────────────────────────────────────────────────

export class LaundryVariantPopup extends AbstractAwaitablePopup {
    static template =
        "pos_laundry_variant_popup.LaundryVariantPopup";

    static props = {
        title: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        confirmText: { type: String, optional: true },
        cancelText: { type: String, optional: true },
        list: { type: Array, optional: true },
        optionById: { type: Object, optional: true },
        selectedId: { type: Number, optional: true },
        selectedByGroup: { type: Object, optional: true },
        perfTrace: { type: Object, optional: true },

        id: { type: Number, optional: true },
        resolve: { type: Function, optional: true },
        close: { type: Function, optional: true },
        zIndex: { type: Number, optional: true },
        cancelKey: { optional: true },
        confirmKey: { optional: true },
    };

    static defaultProps = {
        title: _t("Laundry Service"),
        subtitle: "",
        confirmText: _t("Confirm"),
        cancelText: _t("Cancel"),
        list: [],
        optionById: {},
    };

    setup() {
        super.setup();

        this.state = useState({
            selectedId:
                this.props.selectedId ||
                Object.values(this.props.selectedByGroup || {})[0] ||
                null,
            invalidSubmit: false,
            confirming: false,
        });
        this.invalidSubmitTimer = null;
        this.isUnmounted = false;

        onMounted(() => {
            const trace = this.props.perfTrace;
            markPerf(trace, "mounted");
            measurePerf(trace, "OWL render to mounted", "popupInvoke", "mounted");

            requestAnimationFrame(() => {
                if (this.isUnmounted) {
                    return;
                }

                markPerf(trace, "firstFrame");
                measurePerf(trace, "Click -> first visible frame", "click", "firstFrame");
                measurePerf(trace, "Popup invoke -> first frame", "popupInvoke", "firstFrame");
            });
        });

        onWillUnmount(() => {
            this.isUnmounted = true;
            if (this.invalidSubmitTimer) {
                clearTimeout(this.invalidSubmitTimer);
            }
        });
    }

    get selectedItem() {
        return this.props.optionById?.[this.state.selectedId] || null;
    }

    get selectedItems() {
        return this.selectedItem ? [this.selectedItem] : [];
    }

    get canConfirm() {
        return Boolean(
            this.selectedItem &&
            !this.selectedItem.item?.is_optional_attribute &&
            !this.state.confirming
        );
    }

    get textDirection() {
        return (
            localization.direction ||
            document.documentElement.dir ||
            "ltr"
        );
    }

    get uiText() {
        return {
            empty: _t("No services are available for this product."),
            selectBeforeConfirm: _t("Select a service before confirming."),
        };
    }

    cardClasses(item) {
        return this.state.selectedId === item.id
            ? item.selectedClasses
            : item.classes;
    }

    popupCardClasses() {
        return this.state.invalidSubmit
            ? "laundry-pos-popup-card laundry-variant-popup laundry-pos-shake"
            : "laundry-pos-popup-card laundry-variant-popup";
    }

    selectItem(item) {
        const start = perfNow();

        if (this.state.selectedId !== item.id) {
            this.state.selectedId = item.id;
        }

        this.state.invalidSubmit = false;
        logPerf("Service selection state update", perfNow() - start);

        if (isPerfDebugEnabled()) {
            requestAnimationFrame(() => {
                logPerf("Service selection first frame", perfNow() - start);
            });
        }
    }

    async confirm() {
        const start = perfNow();

        if (!this.canConfirm) {
            this.state.invalidSubmit = true;
            if (this.invalidSubmitTimer) {
                clearTimeout(this.invalidSubmitTimer);
            }
            this.invalidSubmitTimer = setTimeout(() => {
                if (!this.isUnmounted) {
                    this.state.invalidSubmit = false;
                }
            }, 240);

            return;
        }

        this.state.confirming = true;

        if (isPerfDebugEnabled()) {
            requestAnimationFrame(() => {
                logPerf("Confirm response", perfNow() - start);
            });
        }

        return super.confirm();
    }

    getPayload() {
        const primarySelection = this.selectedItem;

        if (!primarySelection?.item || primarySelection.item.is_optional_attribute) {
            return null;
        }

        const selections = this.selectedItems.map((entry, index) => ({
            group: entry.groupName || "",
            value: entry.name,
            productId: entry.item?.is_optional_attribute ? 0 : entry.item.id,
            valueId: entry.valueId || 0,
            originalValue: entry.originalName || entry.name,
            isPrimary: index === 0,
            priceExtra: Number(entry.item?.price_extra || 0),
            priceAmount: getSelectionPriceAmount(entry),
            priceText: getSelectionPriceText(entry),
            displayText: getSelectionDisplayText(entry),
        }));

        return {
            product: primarySelection.item,
            priceExtra: 0,
            selections,
        };
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// POS patch
// ─────────────────────────────────────────────────────────────────────────────

patch(PosStore.prototype, {
    invalidateLaundryVariantIndex() {
        this.__laundryVariantIndex = null;
    },

    async getLaundryVariantPayload(product, popupOptions = {}) {
        if (Number.isInteger(product)) {
            product = this.db.get_product_by_id(product);
        }

        const trace = popupOptions.perfTrace || createPerfTrace("open");
        const prepareStart = perfNow();
        const realProduct =
            this.db.product_by_id?.[product?.id] || product;
        const bucket = getTemplateBucketForProduct(this, realProduct);

        if (!bucket?.hasLaundryOptions || !bucket.groups.length) {
            return null;
        }

        const selectedId = buildSelectedIdFromSelections(
            buildSelectedIdFromVariant(realProduct),
            bucket,
            popupOptions.selectedSelections || []
        );

        logPerf("variants data prepare from cache", perfNow() - prepareStart);
        markPerf(trace, "popupInvoke");
        measurePerf(trace, "Click -> Popup invoked", "click", "popupInvoke");

        const { confirmed, payload } =
            await this.popup.add(
                LaundryVariantPopup,
                {
                    title: popupOptions.title || _t("Laundry Service"),
                    subtitle: popupOptions.subtitle || bucket.productName,
                    confirmText: popupOptions.confirmText || _t("Confirm"),
                    cancelText: popupOptions.cancelText || _t("Cancel"),
                    list: bucket.groups,
                    optionById: bucket.optionById,
                    selectedId,
                    perfTrace: trace,
                }
            );

        if (!confirmed || !payload) {
            return null;
        }

        return payload;
    },

    async editLaundryVariantOrderline(orderline) {
        if (!orderline?.product) {
            return false;
        }

        const payload = await this.getLaundryVariantPayload(orderline.product, {
            title: _t("Edit Service"),
            subtitle: getTemplateName(orderline.product),
            confirmText: _t("Save"),
            selectedSelections: orderline.laundry_variant_selections,
            perfTrace: createPerfTrace("edit"),
        });

        if (!payload) {
            return false;
        }

        const quantity = orderline.get_quantity();

        orderline.product = payload.product;
        orderline.set_product_lot(payload.product);
        orderline.set_quantity(quantity);
        orderline.price_extra = payload.priceExtra;
        orderline.set_unit_price(
            payload.product.get_price(
                orderline.order.pricelist,
                quantity,
                payload.priceExtra
            )
        );
        orderline.order.fix_tax_included_price(orderline);
        orderline.laundry_variant_selections =
            normalizeLaundryVariantSelections(payload.selections);
        orderline.set_full_product_name();
        orderline.order.select_orderline(orderline);

        return true;
    },

    async addProductToCurrentOrder(product, options = {}) {
        if (Number.isInteger(product)) {
            product = this.db.get_product_by_id(product);
        }

        if (!product) {
            return await super.addProductToCurrentOrder(
                ...arguments
            );
        }

        if (options.__variant_popup_selected) {

            const order = this.get_order();

            return order.add_product(product, {
                ...options,
                quantity: options.quantity ?? 1,
                merge: false,
            });
        }

        const trace = createPerfTrace("add");
        const bucket = getTemplateBucketForProduct(this, product);
        if (!bucket?.hasLaundryOptions || !bucket.groups.length) {
            return await super.addProductToCurrentOrder(product, options);
        }

        const payload = await this.getLaundryVariantPayload(product, {
            perfTrace: trace,
        });

        if (!payload) {
            return;
        }

        return await this.addProductToCurrentOrder(payload.product, {
            ...options,
            __variant_popup_selected: true,
            price_extra: payload.priceExtra,
            extras: {
                ...(options.extras || {}),
                laundry_variant_selections: payload.selections,
            },
        });
    },
});

patch(Orderline.prototype, {
    setup() {
        super.setup(...arguments);
        this.laundry_variant_selections =
            normalizeLaundryVariantSelections(
                this.laundry_variant_selections
            );
    },

    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        this.laundry_variant_selections =
            normalizeLaundryVariantSelections(
                json?.laundry_variant_selections
            );
    },

    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);

        json.laundry_variant_selections =
            normalizeLaundryVariantSelections(
                this.laundry_variant_selections
            );

        return json;
    },

    clone() {
        const clonedLine = super.clone(...arguments);

        clonedLine.laundry_variant_selections =
            normalizeLaundryVariantSelections(
                this.laundry_variant_selections
            );

        return clonedLine;
    },

    can_be_merged_with(orderline) {
        return (
            super.can_be_merged_with(...arguments) &&
            areLaundryVariantSelectionsEqual(
                this.laundry_variant_selections,
                orderline?.laundry_variant_selections
            )
        );
    },

    getDisplayData() {
        const data = super.getDisplayData(...arguments);
        const selections =
            normalizeLaundryVariantSelections(
                this.laundry_variant_selections
            );

        if (selections.length) {
            data.productName =
                getTemplateName(this.product) ||
                data.productName;
            data.unit = "";
        }

        data.laundryVariantSelections = selections;
        data.laundryVariantSummaryItems = selections.map((selection) => ({
            group: selection.group || "",
            value: selection.value || selection.displayText || "",
            priceText: selection.priceText || "",
            displayText: selection.displayText || "",
        }));
        data.laundryVariantSummaryLines = selections.map(
            (selection) => selection.displayText
        );

        return data;
    },
});

// ─────────────────────────────────────────────────────────────────────────────
// Product widget patch
// ─────────────────────────────────────────────────────────────────────────────

patch(ProductsWidget.prototype, {
    get productsToDisplay() {
        const searchWord = String(this.pos.searchProductWord || "").trim();
        const products = searchWord
            ? this.pos.db.search_product_in_category(this.pos.selectedCategoryId, searchWord)
            : getCategoryProducts(this.pos, this.pos.selectedCategoryId);

        return dedupeProductsByTemplate(
            this.pos,
            products,
            true
        );
    },
});
