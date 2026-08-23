/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { AppsBar } from "@muk_web_appsbar/webclient/appsbar/appsbar";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";

const SIDEBAR_STORAGE_KEY = "pos_laundry_receipt.sidebar_type";

patch(AppsBar.prototype, {
    setup() {
        super.setup(...arguments);
        this.orm = useService("orm");
        this.user = useService("user");
        this.notification = useService("notification");
        this.state = useState({
            isCollapsed: this.getInitialSidebarType() === "small",
            isSaving: false,
        });
        this.sidebarLabels = {
            collapse: _t("Collapse Sidebar"),
            expand: _t("Expand Sidebar"),
        };
        this.onSidebarStorageUpdate = (event) => {
            if (event.key !== SIDEBAR_STORAGE_KEY) {
                return;
            }
            const nextType = event.newValue === "small" ? "small" : "large";
            const nextCollapsed = nextType === "small";
            if (this.state.isCollapsed !== nextCollapsed) {
                this.state.isCollapsed = nextCollapsed;
                this.syncSidebarClasses();
            }
        };
        onMounted(() => {
            this.syncSidebarClasses();
            browser.addEventListener("storage", this.onSidebarStorageUpdate);
        });
        onWillUnmount(() => {
            browser.removeEventListener("storage", this.onSidebarStorageUpdate);
        });
    },

    getInitialSidebarType() {
        const storedType = browser.localStorage.getItem(SIDEBAR_STORAGE_KEY);
        if (storedType === "small" || storedType === "large") {
            return storedType;
        }
        return document.body.classList.contains("mk_sidebar_type_small") ? "small" : "large";
    },

    syncSidebarClasses() {
        const nextType = this.state.isCollapsed ? "small" : "large";
        document.body.classList.remove("mk_sidebar_type_small", "mk_sidebar_type_large");
        document.body.classList.add(`mk_sidebar_type_${nextType}`);
        document
            .querySelector(".o_web_client")
            ?.classList.toggle("o_laundry_sidebar_collapsed", this.state.isCollapsed);
    },

    get sidebarToggleTitle() {
        return this.state.isCollapsed ? this.sidebarLabels.expand : this.sidebarLabels.collapse;
    },

    async toggleSidebar() {
        if (this.state.isSaving) {
            return;
        }
        const nextType = this.state.isCollapsed ? "large" : "small";
        this.state.isCollapsed = nextType === "small";
        this.state.isSaving = true;
        browser.localStorage.setItem(SIDEBAR_STORAGE_KEY, nextType);
        this.syncSidebarClasses();
        try {
            await this.orm.write("res.users", [this.user.userId], {
                sidebar_type: nextType,
            });
        } catch (error) {
            console.error("Unable to persist sidebar type:", error);
            this.notification.add(_t("Unable to save the sidebar preference."), {
                type: "warning",
            });
        } finally {
            this.state.isSaving = false;
        }
    },
});
