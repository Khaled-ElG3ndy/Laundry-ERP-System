/** @odoo-module **/

import { useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";

class VariantPopup extends AbstractAwaitablePopup {
    static template = "pos_variant_popup.VariantPopup";
    static defaultProps = {
        title: "اختر النوع",
        confirmText: "إضافة للطلب",
        cancelText: "إلغاء",
        productName: "",
        variants: [],
    };

    setup() {
        super.setup();
        this.state = useState({
            selectedId: null,
            selectedVariant: null,
        });
    }

    selectVariant(variant) {
        this.state.selectedId = variant.id;
        this.state.selectedVariant = variant;
    }

    async confirm() {
        if (!this.state.selectedVariant) {
            return;
        }

        this.props.resolve({
            confirmed: true,
            payload: this.state.selectedVariant,
        });
        this.props.close();
    }

    cancel() {
        this.props.resolve({
            confirmed: false,
            payload: null,
        });
        this.props.close();
    }
}

function getTemplateId(product) {
    const tmpl = product.product_tmpl_id;
    if (!tmpl) return null;
    if (Array.isArray(tmpl)) return tmpl[0];
    return tmpl;
}

function getVariantTone(index) {
    const tones = [
        "vp-tone-1",
        "vp-tone-2",
        "vp-tone-3",
        "vp-tone-4",
        "vp-tone-5",
        "vp-tone-6",
        "vp-tone-7",
        "vp-tone-8",
    ];
    return tones[index % tones.length];
}

patch(ProductScreen.prototype, {
    setup() {
        super.setup();
        this.popup = useService("popup");
        this.pos = usePos();
    },

    async addProductToOrder(product) {
        const tmplId = getTemplateId(product);
        if (!tmplId) {
            return super.addProductToOrder(product);
        }

        const allProducts = Object.values(this.pos.db.product_by_id || {});
        const variants = allProducts.filter((p) => getTemplateId(p) === tmplId);

        if (variants.length <= 1) {
            return super.addProductToOrder(product);
        }

        const currency = this.pos.currency;
        const symbol = currency?.symbol || "";

        const variantItems = variants.map((variant, index) => ({
            id: variant.id,
            variantName: variant.display_name || variant.name || "",
            priceStr: `${Number(variant.lst_price || 0).toFixed(2)} ${symbol}`,
            toneClass: getVariantTone(index),
            product: variant,
        }));

        const { confirmed, payload } = await this.popup.add(VariantPopup, {
            title: "اختر النوع",
            productName: product.display_name || product.name || "",
            variants: variantItems,
            confirmText: "إضافة للطلب",
            cancelText: "إلغاء",
        });

        if (confirmed && payload) {
            return super.addProductToOrder(payload.product);
        }
    },
});

export { VariantPopup };