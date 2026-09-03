/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { PosStore } from "@point_of_sale/app/store/pos_store";
import { Orderline } from "@point_of_sale/app/store/models";
import { Orderline as OrderlineComponent } from "@point_of_sale/app/generic_components/orderline/orderline";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
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

    if (entry.isOptional || entry.item.is_optional_attribute) {
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
    if (rawPrice) {
        // The POS formatter already applies the active language, currency and
        // bidi markers. Only remove the leading add-on plus sign in summaries.
        return rawPrice.replace(/^\+\s*/, "");
    }

    return amount.toFixed(2);
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
    droplet: "fa fa-tint",
    sliders: "fa fa-sliders",
    tag: "fa fa-tag",
};

const GROUP_THEMES = new Set(["blue", "orange", "teal", "primary"]);

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

function formatExtraPrice(pos, amount) {
    const numericAmount = Number(amount || 0);
    if (!numericAmount) {
        return "";
    }

    const formatted = pos.env?.utils?.formatCurrency
        ? pos.env.utils.formatCurrency(Math.abs(numericAmount))
        : `${Math.abs(numericAmount).toFixed(2)} ${pos.currency?.symbol || ""}`;
    return `${numericAmount > 0 ? "+" : "-"}${formatted}`;
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

export function normalizeLaundryVariantSelections(selections) {
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
            const groupCode = String(selection?.groupCode || "").trim();
            const productId = Number(selection?.productId || 0);
            const valueId = Number(selection?.valueId || 0);
            const groupId = Number(selection?.groupId || 0);
            const ptavId = Number(selection?.ptavId || 0);
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
                groupCode,
                value,
                productId,
                valueId,
                groupId,
                ptavId,
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

export function areLaundryVariantSelectionsEqual(left, right) {
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
        optionalGroups: [],
        optionalGroupByCode: {},
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
            selectionKind: "primary",
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
    if (valueId && bucket.valueIdToOptionId[valueId] !== undefined) {
        return;
    }
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
        key: `service-${product.id}`,
        isOptional: false,
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

function addOptionalGroupsToBucket(pos, bucket, product, metrics) {
    if (bucket.optionalGroups.length || !Array.isArray(product.laundry_optional_groups)) {
        return;
    }

    bucket.optionalGroups = product.laundry_optional_groups
        .map((rawGroup) => {
            const numericGroupId = Number(rawGroup.id || 0);
            const code = String(rawGroup.code || "").trim();
            const theme = getGroupTheme(rawGroup.theme);
            const themeClass = `laundry-service-group--${theme}`;
            const group = {
                id: `addon-${numericGroupId || code}`,
                numericGroupId,
                key: `addon-${numericGroupId || code}`,
                group: String(rawGroup.name || "").trim() || _t("Additional Service"),
                code,
                sequence: Number(rawGroup.sequence || numericGroupId || 0),
                required: Boolean(rawGroup.required),
                showDefault: Boolean(rawGroup.show_default),
                theme,
                themeClass,
                iconClass: getGroupIconClass(rawGroup.icon_key),
                selectionKind: "optional",
                optionById: {},
                optionByPtavId: {},
                optionByValueId: {},
                matchKeyToOptionId: {},
                items: [],
            };

            for (const rawItem of rawGroup.items || []) {
                const ptavId = Number(rawItem.ptav_id || rawItem.id || 0);
                const valueId = Number(rawItem.value_id || 0);
                const name = String(rawItem.name || rawItem.original_name || "").trim();
                if (!ptavId || !name) {
                    continue;
                }

                const priceStart = perfNow();
                const price = formatExtraPrice(pos, rawItem.price_extra);
                metrics.priceMs += perfNow() - priceStart;
                const baseClasses = `laundry-variant-card laundry-pos-card ${themeClass}`;
                const option = {
                    id: `addon-value-${ptavId}`,
                    key: `addon-value-${ptavId}`,
                    ptavId,
                    valueId,
                    groupId: numericGroupId,
                    groupCode: code,
                    originalName: String(rawItem.original_name || name).trim(),
                    name,
                    displayName: name,
                    groupName: group.group,
                    iconClass: group.iconClass,
                    theme,
                    themeClass,
                    classes: baseClasses,
                    selectedClasses: `${baseClasses} is-selected`,
                    price,
                    priceAmount: Number(rawItem.price_extra || 0),
                    sequence: Number(rawItem.sequence || ptavId),
                    isDefault: Boolean(rawItem.is_default),
                    isOptional: true,
                    item: {
                        id: ptavId,
                        is_optional_attribute: true,
                        price_extra: Number(rawItem.price_extra || 0),
                    },
                };
                group.items.push(option);
                group.optionById[option.id] = option;
                group.optionByPtavId[ptavId] = option.id;
                if (valueId) {
                    group.optionByValueId[valueId] = option.id;
                }
                for (const matchValue of [
                    name,
                    option.originalName,
                    `${group.group}:${name}`,
                    `${group.group}:${option.originalName}`,
                ]) {
                    const normalized = normalizeMatchText(matchValue);
                    if (normalized && group.matchKeyToOptionId[normalized] === undefined) {
                        group.matchKeyToOptionId[normalized] = option.id;
                    }
                }
            }

            group.items.sort(
                (left, right) =>
                    left.sequence - right.sequence ||
                    String(left.name).localeCompare(String(right.name))
            );
            group.defaultOptionId =
                group.items.find((item) => item.isDefault)?.id || null;
            return group;
        })
        .filter((group) => group.items.length)
        .sort(
            (left, right) =>
                left.sequence - right.sequence ||
                String(left.group).localeCompare(String(right.group))
        );

    if (bucket.optionalGroups.length) {
        // Products without a service axis (no "Service Type") still have to
        // open the laundry popup, otherwise the core product configurator
        // would take over and show a different, untranslated dialog.
        bucket.hasLaundryOptions = true;
    }

    bucket.optionalGroupByCode = Object.fromEntries(
        bucket.optionalGroups.map((group) => [group.code, group])
    );
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
        addOptionalGroupsToBucket(pos, bucket, product, metrics);
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

export function filterPrintableSelections(selections) {
    // A group whose default means "nothing extra" (No Stain Removal, No Mirzam)
    // is left off the ticket; groups without a default, such as starch, are
    // always printed because the choice is an instruction to the laundry floor.
    return (selections || []).filter((selection) => !selection?.isHiddenDefault);
}

export function bucketOffersLaundryPopup(bucket) {
    return Boolean(
        bucket?.hasLaundryOptions &&
        (bucket.groups?.length || bucket.optionalGroups?.length)
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

export function buildSelectedByGroup(bucket, selections) {
    const normalizedSelections = normalizeLaundryVariantSelections(selections);
    const selectedByGroup = {};

    for (const group of bucket.optionalGroups || []) {
        const selection = normalizedSelections.find((candidate) =>
            !candidate.isPrimary && (
                (candidate.groupCode && candidate.groupCode === group.code) ||
                (candidate.groupId && candidate.groupId === group.numericGroupId) ||
                normalizeMatchText(candidate.group) === normalizeMatchText(group.group)
            )
        );
        let optionId = null;
        if (selection) {
            optionId =
                group.optionByPtavId[selection.ptavId] ||
                group.optionByValueId[selection.valueId] ||
                null;
            if (!optionId) {
                for (const candidate of [
                    selection.displayText,
                    selection.value,
                    selection.originalValue,
                    selection.group && selection.value
                        ? `${selection.group}:${selection.value}`
                        : "",
                ]) {
                    optionId = group.matchKeyToOptionId[normalizeMatchText(candidate)];
                    if (optionId) {
                        break;
                    }
                }
            }
        }
        selectedByGroup[group.key] = optionId || group.defaultOptionId;
    }

    return selectedByGroup;
}

export function calculateLaundryAddonPrice(entries) {
    return (entries || [])
        .filter((entry) => entry?.isOptional)
        .reduce(
            (total, entry) => total + Number(entry.item?.price_extra || 0),
            0
        );
}

export function getLaundryAddonPtavIds(entries) {
    return (entries || [])
        .filter((entry) => entry?.isOptional && entry.ptavId)
        .map((entry) => entry.ptavId);
}

export function buildLaundryBarcodeOptions(product, code) {
    const options = {};
    const packagingQuantity = product?._getPackagingQty?.(code);
    if (packagingQuantity !== undefined) {
        options.quantity = packagingQuantity;
    }
    if (code?.type === "price") {
        Object.assign(options, {
            price: code.value,
            extras: { price_type: "manual" },
        });
    } else if (code?.type === "weight" || code?.type === "quantity") {
        Object.assign(options, { quantity: code.value, merge: false });
    } else if (code?.type === "discount") {
        Object.assign(options, { discount: code.value, merge: false });
    }
    return options;
}

function localizeLaundryVariantSelections(pos, product, selections) {
    const normalizedSelections = normalizeLaundryVariantSelections(selections);
    const bucket = getTemplateBucketForProduct(pos, product);
    if (!bucket) {
        return normalizedSelections;
    }

    return normalizedSelections.map((selection) => {
        let option = null;
        let groupName = selection.group;
        let groupCode = selection.groupCode;
        let groupId = selection.groupId;
        let isHiddenDefault = false;

        if (selection.isPrimary) {
            const optionId = buildSelectedIdFromSelections(
                selection.productId,
                bucket,
                [selection]
            );
            option = bucket.optionById[optionId];
        } else {
            const group = (bucket.optionalGroups || []).find(
                (candidate) =>
                    (selection.groupCode && candidate.code === selection.groupCode) ||
                    (selection.groupId && candidate.numericGroupId === selection.groupId) ||
                    normalizeMatchText(candidate.group) === normalizeMatchText(selection.group)
            );
            if (group) {
                const optionId =
                    group.optionByPtavId[selection.ptavId] ||
                    group.optionByValueId[selection.valueId] ||
                    group.matchKeyToOptionId[normalizeMatchText(selection.value)] ||
                    null;
                option = group.optionById[optionId];
                groupName = group.group;
                groupCode = group.code;
                groupId = group.numericGroupId;
                isHiddenDefault = Boolean(
                    option && !group.showDefault && option.isDefault
                );
            }
        }

        if (!option) {
            return selection;
        }

        return {
            ...selection,
            isHiddenDefault,
            group: option.groupName || groupName || "",
            groupCode: option.groupCode || groupCode || "",
            groupId: option.groupId || groupId || 0,
            value: option.name,
            originalValue: option.originalName || option.name,
            productId: option.isOptional ? 0 : option.item.id,
            valueId: option.valueId || selection.valueId || 0,
            ptavId: option.ptavId || selection.ptavId || 0,
            priceExtra: Number(option.item?.price_extra || 0),
            priceAmount: getSelectionPriceAmount(option),
            priceText: getSelectionPriceText(option),
            displayText: getSelectionDisplayText(option),
        };
    });
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
        optionalList: { type: Array, optional: true },
        optionById: { type: Object, optional: true },
        fallbackProduct: { type: Object, optional: true },
        selectedId: { type: [Number, { value: null }], optional: true },
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
        optionalList: [],
        optionById: {},
    };

    setup() {
        super.setup();

        this.state = useState({
            selectedId: this.props.selectedId || null,
            selectedByGroup: { ...(this.props.selectedByGroup || {}) },
            invalidSubmit: false,
            blockedGroupKey: null,
            confirming: false,
        });
        this.bodyRef = useRef("body");
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
        const optionalItems = (this.props.optionalList || [])
            .map((group) => group.optionById?.[this.state.selectedByGroup[group.key]])
            .filter(Boolean);
        return this.selectedItem
            ? [this.selectedItem, ...optionalItems]
            : optionalItems;
    }

    get unansweredGroup() {
        if (this.hasServiceGroups && !this.selectedItem) {
            return this.props.list[0] || null;
        }
        return (
            (this.props.optionalList || []).find(
                (group) =>
                    group.required &&
                    !group.optionById?.[this.state.selectedByGroup[group.key]]
            ) || null
        );
    }

    get hasServiceGroups() {
        return Boolean((this.props.list || []).length);
    }

    get canConfirm() {
        return Boolean(
            (this.hasServiceGroups
                ? this.selectedItem && !this.selectedItem.item?.is_optional_attribute
                : true) &&
            (this.props.optionalList || []).every(
                (group) =>
                    !group.required ||
                    Boolean(group.optionById?.[this.state.selectedByGroup[group.key]])
            ) &&
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
            selectBeforeConfirm: _t(
                "Select an option in every required group before confirming."
            ),
            additionalServices: _t("Additional Services"),
        };
    }

    get blockedMessage() {
        const group = this.unansweredGroup;
        return group
            ? _t("Choose %s to continue.", group.group)
            : this.uiText.selectBeforeConfirm;
    }

    isGroupBlocked(group) {
        return this.state.blockedGroupKey === group.key;
    }

    groupClasses(group) {
        const base = "laundry-service-group " + group.themeClass;
        return this.isGroupBlocked(group) ? base + " is-unanswered" : base;
    }

    isItemSelected(group, item) {
        return group.selectionKind === "optional"
            ? this.state.selectedByGroup[group.key] === item.id
            : this.state.selectedId === item.id;
    }

    cardClasses(group, item) {
        return this.isItemSelected(group, item)
            ? item.selectedClasses
            : item.classes;
    }

    popupCardClasses() {
        return this.state.invalidSubmit
            ? "laundry-pos-popup-card laundry-variant-popup laundry-pos-shake"
            : "laundry-pos-popup-card laundry-variant-popup";
    }

    selectItem(group, item) {
        const start = perfNow();

        if (group.selectionKind === "optional") {
            if (this.state.selectedByGroup[group.key] !== item.id) {
                this.state.selectedByGroup[group.key] = item.id;
            } else if (!group.required) {
                // An optional group starts unanswered, so tapping the chosen
                // card again has to be able to take it back to unanswered.
                // Without this the cashier could never undo a mis-tap.
                this.state.selectedByGroup[group.key] = null;
            }
        } else if (this.state.selectedId !== item.id) {
            this.state.selectedId = item.id;
        }

        this.state.invalidSubmit = false;
        this.state.blockedGroupKey = null;
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
            // The groups can run past the bottom of the popup, so simply
            // refusing the click looked to the cashier like the product would
            // not add at all. Say which group is missing, and bring it into
            // view rather than leaving them to hunt for it.
            const blocked = this.unansweredGroup;
            this.state.blockedGroupKey = blocked?.key || null;
            this.state.invalidSubmit = true;
            if (this.invalidSubmitTimer) {
                clearTimeout(this.invalidSubmitTimer);
            }
            this.invalidSubmitTimer = setTimeout(() => {
                if (!this.isUnmounted) {
                    this.state.invalidSubmit = false;
                }
            }, 240);

            if (blocked) {
                this.scrollGroupIntoView(blocked.key);
            }

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

    scrollGroupIntoView(groupKey) {
        const body = this.bodyRef?.el;
        if (!body || !groupKey) {
            return;
        }
        const target = body.querySelector(
            `[data-group-key="${CSS.escape(String(groupKey))}"]`
        );
        target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }

    getPayload() {
        const primarySelection = this.selectedItem;
        const hasPrimary = Boolean(
            primarySelection?.item && !primarySelection.item.is_optional_attribute
        );
        const product = hasPrimary
            ? primarySelection.item
            : this.props.fallbackProduct;

        if (!product || (this.hasServiceGroups && !hasPrimary)) {
            return null;
        }

        const selections = this.selectedItems.map((entry) => ({
            group: entry.groupName || "",
            groupCode: entry.groupCode || "",
            groupId: Number(entry.groupId || 0),
            value: entry.name,
            productId: entry.isOptional ? 0 : entry.item.id,
            valueId: entry.valueId || 0,
            ptavId: entry.ptavId || 0,
            originalValue: entry.originalName || entry.name,
            isPrimary: !entry.isOptional,
            priceExtra: Number(entry.item?.price_extra || 0),
            priceAmount: getSelectionPriceAmount(entry),
            priceText: getSelectionPriceText(entry),
            displayText: getSelectionDisplayText(entry),
        }));

        return {
            product,
            priceExtra: calculateLaundryAddonPrice(this.selectedItems),
            attributeValueIds: getLaundryAddonPtavIds(this.selectedItems),
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

        if (!bucketOffersLaundryPopup(bucket)) {
            return null;
        }

        const selectedId = buildSelectedIdFromSelections(
            buildSelectedIdFromVariant(realProduct),
            bucket,
            popupOptions.selectedSelections || []
        );
        const selectedByGroup = buildSelectedByGroup(
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
                    optionalList: bucket.optionalGroups,
                    optionById: bucket.optionById,
                    fallbackProduct: realProduct,
                    selectedId,
                    selectedByGroup,
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
        orderline.set_price_extra(payload.priceExtra);
        orderline.attribute_value_ids = payload.attributeValueIds || [];
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
        if (!bucketOffersLaundryPopup(bucket)) {
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
            attribute_value_ids: payload.attributeValueIds || [],
            extras: {
                ...(options.extras || {}),
                laundry_variant_selections: payload.selections,
            },
        });
    },
});

// Core barcode handling adds directly to the order and therefore bypasses
// PosStore.addProductToCurrentOrder. Route laundry products through the same
// configurator while preserving quantity/weight/price/discount barcode data.
patch(ProductScreen.prototype, {
    async _barcodeProductAction(code) {
        const product = await this._getProductByBarcode(code);
        const bucket = product && getTemplateBucketForProduct(this.pos, product);
        if (!product || !bucketOffersLaundryPopup(bucket)) {
            return await super._barcodeProductAction(...arguments);
        }

        const options = buildLaundryBarcodeOptions(product, code);
        return await this.pos.addProductToCurrentOrder(product, options);
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
        clonedLine.attribute_value_ids = [...(this.attribute_value_ids || [])];
        clonedLine.set_price_extra(this.get_price_extra());
        clonedLine.set_full_product_name();

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
        const selections = localizeLaundryVariantSelections(
            this.pos,
            this.product,
            this.laundry_variant_selections
        );

        if (selections.length) {
            data.productName =
                getTemplateName(this.product) ||
                data.productName;
            data.unit = "";
        }

        const printedSelections = filterPrintableSelections(selections);

        data.laundryVariantSelections = selections;
        data.laundryVariantSummaryItems = printedSelections.map((selection) => ({
            group: selection.group || "",
            value: selection.value || selection.displayText || "",
            priceText: selection.priceText || "",
            displayText: selection.displayText || "",
        }));
        // What the printed receipt, the tracking label and the intake record
        // show. It is composed here rather than reusing `displayText`, which
        // stays in the canonical "group : value" form because reopening a line
        // matches saved selections against it.
        data.laundryVariantSummaryLines = printedSelections.map(
            (selection) => {
                const value = selection.value || selection.displayText || "";
                const group = selection.group || "";
                // The chosen value leads on every row, matching the cart and
                // the review dialog: the emphasised half is always the one the
                // reader meets first.
                const pair = group ? `${value} · ${group}` : value;

                // The receipt splits a trailing amount back off this string, so
                // the " - " before the price has to stay.
                return selection.priceText
                    ? `${pair} - ${selection.priceText}`
                    : pair;
            }
        );

        return data;
    },
});

// ─────────────────────────────────────────────────────────────────────────────
// Cart line direction
//
// point_of_sale.index hardcodes a bare <html> with no dir attribute, and
// pos_app.scss pins `.pos { direction: ltr }`, so the till lays out
// left-to-right whatever language the cashier is in. rtlcss is not installed
// here either, so the "rtl" bundle never mirrors anything back. An Arabic
// cashier therefore got a cart that starts on the left.
//
// Each line states the direction its language asks for, so the name, the
// amount, the quantity row and the service summary all begin on the reading
// edge without depending on what the shell decides.
// ─────────────────────────────────────────────────────────────────────────────

patch(OrderlineComponent.prototype, {
    get lineDirection() {
        return localization.direction === "rtl" ? "rtl" : "ltr";
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
