/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

// Odoo only broadcasts "bundle_changed" for web.assets_web, so an open Point of
// Sale keeps running the JavaScript it was loaded with. The server side of this
// module broadcasts "pos_laundry_assets_changed" whenever a POS bundle is
// rebuilt (see models/ir_attachment.py); this service reacts to it.
const POS_ASSETS_CHANGED_EVENT = "pos_laundry_assets_changed";
const UPDATE_STORAGE_KEY = "pos_laundry_receipt.pos_assets_changed";
const RELOADED_VERSION_KEY = "pos_laundry_receipt.pos_assets_reloaded_version";
const IDLE_RELOAD_DELAY = 1200;
const IDLE_RECHECK_DELAY = 1500;
// Let a freshly opened POS finish booting before a replayed bus notification can
// reload it. The notification is delayed, never dropped.
const STARTUP_SETTLE_DELAY = 2500;

function getPayloadVersion(payload) {
    if (!payload || typeof payload !== "object") {
        return "legacy";
    }
    const version = payload.version || payload.server_version || payload.checksum || payload.id;
    return version ? String(version) : "legacy";
}

function getStoredUpdate() {
    try {
        const update = browser.localStorage.getItem(UPDATE_STORAGE_KEY);
        return update ? JSON.parse(update) : null;
    } catch {
        return null;
    }
}

function storeUpdate(version) {
    try {
        const previous = getStoredUpdate();
        if (previous?.version === version) {
            return;
        }
        browser.localStorage.setItem(
            UPDATE_STORAGE_KEY,
            JSON.stringify({
                version,
                time: Date.now(),
            })
        );
    } catch {
        // Cross-tab notification is a backup path; the bus notification already
        // reached the current tab.
    }
}

function getSessionReloadedVersion() {
    try {
        return browser.sessionStorage.getItem(RELOADED_VERSION_KEY);
    } catch {
        return null;
    }
}

function setSessionReloadedVersion(version) {
    try {
        browser.sessionStorage.setItem(RELOADED_VERSION_KEY, version);
    } catch {
        // A blocked sessionStorage should not prevent the update reload.
    }
}

function isCashierBusy(env) {
    try {
        const pos = env.services.pos;
        const order = pos?.get_order?.();
        if (!order) {
            return false;
        }
        const hasLines = Boolean(order.get_orderlines?.().length);
        const hasPayments = Boolean(order.paymentlines?.length);
        return hasLines || hasPayments;
    } catch {
        // Never block the reload prompt because of an unexpected POS state.
        return false;
    }
}

export const laundryPosAssetsWatchdog = {
    dependencies: ["bus_service", "notification"],

    start(env, { bus_service, notification }) {
        const startedAt = Date.now();
        let activeVersion = null;
        let idleCheckTimer = null;
        let notificationDisplayed = false;
        let reloadTimer = null;

        const reload = (version = activeVersion) => {
            if (version) {
                setSessionReloadedVersion(version);
            }
            browser.location.reload();
        };

        const scheduleReload = (version, delay = IDLE_RELOAD_DELAY) => {
            if (reloadTimer) {
                browser.clearTimeout(reloadTimer);
            }
            reloadTimer = browser.setTimeout(() => reload(version), delay);
        };

        const askToReload = (version) => {
            if (notificationDisplayed) {
                return;
            }
            notificationDisplayed = true;
            notification.add(_t("A new version of the Point of Sale is ready."), {
                title: _t("Update available"),
                type: "warning",
                sticky: true,
                buttons: [
                    {
                        name: _t("Refresh now"),
                        primary: true,
                        onClick: () => reload(version),
                    },
                ],
                onClose: () => {
                    notificationDisplayed = false;
                },
            });
        };

        const waitForIdleThenReload = (version) => {
            if (idleCheckTimer) {
                browser.clearTimeout(idleCheckTimer);
            }

            const checkIdle = () => {
                if (activeVersion !== version || getSessionReloadedVersion() === version) {
                    return;
                }
                if (isCashierBusy(env)) {
                    askToReload(version);
                    idleCheckTimer = browser.setTimeout(checkIdle, IDLE_RECHECK_DELAY);
                    return;
                }
                notification.add(_t("Updating the Point of Sale to the latest version..."), {
                    type: "info",
                });
                scheduleReload(version);
            };

            checkIdle();
        };

        const handleAssetsChanged = (payload, { fromStorage = false } = {}) => {
            const version = getPayloadVersion(payload);
            if (activeVersion === version || getSessionReloadedVersion() === version) {
                return;
            }
            activeVersion = version;

            if (!fromStorage) {
                storeUpdate(version);
            }

            const settleDelay = Math.max(0, STARTUP_SETTLE_DELAY - (Date.now() - startedAt));
            browser.setTimeout(() => waitForIdleThenReload(version), settleDelay);
        };

        browser.addEventListener("storage", (event) => {
            if (event.key !== UPDATE_STORAGE_KEY || !event.newValue) {
                return;
            }
            try {
                handleAssetsChanged(JSON.parse(event.newValue), { fromStorage: true });
            } catch {
                // Ignore malformed cross-tab messages.
            }
        });

        bus_service.subscribe(POS_ASSETS_CHANGED_EVENT, handleAssetsChanged);
        bus_service.start();
    },
};

registry.category("services").add("laundry_pos_assets_watchdog", laundryPosAssetsWatchdog);
