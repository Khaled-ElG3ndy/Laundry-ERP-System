/** @odoo-module **/

import {
    areLaundryVariantSelectionsEqual,
    buildLaundryBarcodeOptions,
    buildSelectedByGroup,
    calculateLaundryAddonPrice,
    getLaundryAddonPtavIds,
    normalizeLaundryVariantSelections,
} from "@pos_laundry_variant_popup/js/pos_laundry_variant_popup";

QUnit.module("Laundry variant add-ons", () => {
    QUnit.test("normalizes durable service and add-on identifiers", (assert) => {
        const [selection] = normalizeLaundryVariantSelections([
            {
                group: "Stain Removal",
                groupCode: "stain_removal",
                groupId: "8",
                value: "M",
                valueId: "12",
                ptavId: "42",
                priceExtra: "2",
                isPrimary: false,
            },
        ]);

        assert.strictEqual(selection.groupCode, "stain_removal");
        assert.strictEqual(selection.groupId, 8);
        assert.strictEqual(selection.valueId, 12);
        assert.strictEqual(selection.ptavId, 42);
        assert.strictEqual(selection.priceExtra, 2);
        assert.false(selection.isPrimary);
    });

    QUnit.test("different add-ons prevent accidental order-line merging", (assert) => {
        const base = [{ groupCode: "stain_removal", value: "S", ptavId: 10 }];
        const other = [{ groupCode: "stain_removal", value: "M", ptavId: 11 }];

        assert.true(areLaundryVariantSelectionsEqual(base, [...base]));
        assert.false(areLaundryVariantSelectionsEqual(base, other));
    });

    QUnit.test("restores a saved option by stable PTAV id", (assert) => {
        const group = {
            key: "addon-8",
            code: "stain_removal",
            numericGroupId: 8,
            defaultOptionId: "addon-value-40",
            optionByPtavId: { 40: "addon-value-40", 42: "addon-value-42" },
            optionByValueId: {},
            matchKeyToOptionId: {},
        };
        const selected = buildSelectedByGroup(
            { optionalGroups: [group] },
            [
                {
                    groupCode: "stain_removal",
                    value: "M",
                    ptavId: 42,
                    isPrimary: false,
                },
            ]
        );

        assert.strictEqual(selected["addon-8"], "addon-value-42");
    });

    QUnit.test("uses configured defaults when an old order has no add-ons", (assert) => {
        const selected = buildSelectedByGroup(
            {
                optionalGroups: [
                    {
                        key: "addon-8",
                        code: "stain_removal",
                        numericGroupId: 8,
                        defaultOptionId: "addon-value-40",
                        optionByPtavId: {},
                        optionByValueId: {},
                        matchKeyToOptionId: {},
                    },
                ],
            },
            []
        );

        assert.strictEqual(selected["addon-8"], "addon-value-40");
    });

    QUnit.test("keeps a required group empty when no default is configured", (assert) => {
        const selected = buildSelectedByGroup(
            {
                optionalGroups: [
                    {
                        key: "addon-starch",
                        code: "starch_type",
                        numericGroupId: 9,
                        defaultOptionId: null,
                        optionByPtavId: {},
                        optionByValueId: {},
                        matchKeyToOptionId: {},
                    },
                ],
            },
            []
        );

        assert.strictEqual(selected["addon-starch"], null);
    });

    QUnit.test("adds only optional prices and exports their PTAV ids", (assert) => {
        const entries = [
            { isOptional: false, item: { price_extra: 99 } },
            { isOptional: true, ptavId: 20, item: { price_extra: 1 } },
            { isOptional: true, ptavId: 30, item: { price_extra: 0 } },
            { isOptional: true, ptavId: 40, item: { price_extra: 3 } },
        ];

        assert.strictEqual(calculateLaundryAddonPrice(entries), 4);
        assert.deepEqual(getLaundryAddonPtavIds(entries), [20, 30, 40]);
    });

    QUnit.test("preserves barcode quantity, weight, price and discount options", (assert) => {
        const product = { _getPackagingQty: () => 6 };

        assert.deepEqual(buildLaundryBarcodeOptions(product, { type: "product" }), {
            quantity: 6,
        });
        assert.deepEqual(buildLaundryBarcodeOptions(product, { type: "quantity", value: 3 }), {
            quantity: 3,
            merge: false,
        });
        assert.deepEqual(buildLaundryBarcodeOptions(product, { type: "price", value: 12 }), {
            quantity: 6,
            price: 12,
            extras: { price_type: "manual" },
        });
        assert.deepEqual(buildLaundryBarcodeOptions(product, { type: "discount", value: 10 }), {
            quantity: 6,
            discount: 10,
            merge: false,
        });
    });

    QUnit.test("a product with only add-on groups still opens the popup", (assert) => {
        const addonOnly = {
            hasLaundryOptions: true,
            groups: [],
            optionalGroups: [{ key: "addon-8", items: [{ id: "a" }] }],
        };
        const serviceOnly = {
            hasLaundryOptions: true,
            groups: [{ items: [{ id: "s" }] }],
            optionalGroups: [],
        };
        const plain = { hasLaundryOptions: false, groups: [], optionalGroups: [] };

        assert.true(bucketOffersLaundryPopup(addonOnly));
        assert.true(bucketOffersLaundryPopup(serviceOnly));
        assert.false(bucketOffersLaundryPopup(plain));
        assert.false(bucketOffersLaundryPopup(null));
    });

    QUnit.test("a group with no default forces an explicit choice", (assert) => {
        const starch = {
            key: "addon-9",
            code: "starch_type",
            numericGroupId: 9,
            defaultOptionId: null,
            optionByPtavId: {},
            optionByValueId: {},
            matchKeyToOptionId: {},
        };

        const selected = buildSelectedByGroup({ optionalGroups: [starch] }, []);

        assert.strictEqual(
            selected["addon-9"],
            null,
            "starch must stay unanswered until the cashier picks one"
        );
    });

    QUnit.test("silent defaults are kept off the printed ticket", (assert) => {
        const printed = filterPrintableSelections([
            { value: "Ironing", isPrimary: true },
            { value: "No Stain Removal", isHiddenDefault: true },
            { value: "No Mirzam", isHiddenDefault: true },
            { value: "Light", isHiddenDefault: false },
        ]);

        assert.deepEqual(
            printed.map((selection) => selection.value),
            ["Ironing", "Light"]
        );
    });

    QUnit.test("printable filtering tolerates missing input", (assert) => {
        assert.deepEqual(filterPrintableSelections(), []);
        assert.deepEqual(filterPrintableSelections(null), []);
    });

    QUnit.test("stain sizes price at exactly 1, 2 and 3", (assert) => {
        const sizes = [
            { isOptional: true, ptavId: 1, item: { price_extra: 1 } },
            { isOptional: true, ptavId: 2, item: { price_extra: 2 } },
            { isOptional: true, ptavId: 3, item: { price_extra: 3 } },
        ];

        assert.strictEqual(calculateLaundryAddonPrice([sizes[0]]), 1);
        assert.strictEqual(calculateLaundryAddonPrice([sizes[1]]), 2);
        assert.strictEqual(calculateLaundryAddonPrice([sizes[2]]), 3);
    });

    QUnit.test("free groups never change the line price", (assert) => {
        const entries = [
            { isOptional: false, item: { price_extra: 0, lst_price: 10 } },
            { isOptional: true, ptavId: 20, item: { price_extra: 0 } },
            { isOptional: true, ptavId: 30, item: { price_extra: 0 } },
        ];

        assert.strictEqual(calculateLaundryAddonPrice(entries), 0);
    });
});
