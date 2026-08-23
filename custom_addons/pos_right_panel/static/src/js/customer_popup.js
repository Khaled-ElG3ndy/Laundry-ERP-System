/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { onMounted, useRef, useState } from "@odoo/owl";

export class CustomerPopup extends AbstractAwaitablePopup {
    static template = "pos_right_panel.CustomerPopup";
    static defaultProps = {
        title: _t("Select Customer"),
        confirmText: _t("Set Customer"),
        cancelText: _t("Cancel"),
        clearText: _t("Clear Customer"),
        searchPlaceholder: _t("Search customers by name, phone, or email"),
        emptyText: _t("No customers found."),
        partner: null,
    };

    setup() {
        super.setup();
        this.pos = usePos();
        this.notification = useService("pos_notification");
        this.searchInputRef = useRef("customer-popup-search");
        this.state = useState({
            query: "",
            selectedPartner: this.props.partner || null,
        });

        onMounted(() => {
            this.searchInputRef.el?.focus();
        });
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

    selectPartner(partner) {
        if (!partner) {
            return;
        }
        this.state.selectedPartner = partner;
    }

    onPartnerClick(ev) {
        const partnerId = parseInt(ev.currentTarget?.dataset?.partnerId, 10);
        if (!partnerId) {
            return;
        }
        const partner = this.partners.find((item) => item.id === partnerId);
        this.selectPartner(partner);
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
