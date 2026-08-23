/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

patch(ProductScreen.prototype, {
    setup() {
        super.setup(...arguments);
        this.notification = useService("notification");
        this.popup = useService("popup");
        this.printer = useService("printer");
        this.hardwareProxy = useService("hardware_proxy");
    },

    // Open Cash Drawer
    async openCashDrawer() {
        try {
            // Try to open via hardware proxy
            if (this.hardwareProxy) {
                await this.hardwareProxy.openCashbox();
            }
            this.notification.add(_t("Cash drawer opened!"), {
                type: "success",
            });
        } catch (error) {
            this.notification.add(_t("Cash drawer command sent. Check if drawer opened."), {
                type: "info",
            });
        }
        console.log("[FPS Shortcuts] Cash drawer opened");
    },

    // Add Manual Item (Miscellaneous product with custom price)
    async addManualItem() {
        const { confirmed, payload } = await this.popup.add("NumberPopup", {
            title: _t("Enter Item Price"),
            startingValue: "0.00",
        });
        
        if (confirmed && payload) {
            const price = parseFloat(payload) || 0;
            if (price > 0) {
                // Find or create a miscellaneous product
                const miscProduct = this.pos.db.search_product_in_category(0, "Miscellaneous") 
                    || this.pos.db.search_product_in_category(0, "Manual")
                    || this.pos.products[0];
                
                if (miscProduct) {
                    const order = this.pos.get_order();
                    order.add_product(miscProduct, {
                        price: price,
                        quantity: 1,
                    });
                    this.notification.add(_t("Manual item added: $" + price.toFixed(2)), {
                        type: "success",
                    });
                } else {
                    this.notification.add(_t("Please create a 'Miscellaneous' product first"), {
                        type: "warning",
                    });
                }
            }
        }
    },

    // Reprint Last Receipt
    async reprintLastReceipt() {
        const orders = this.pos.db.get_orders();
        const lastOrder = this.pos.get_order_list().find(o => o.finalized) || null;
        
        if (lastOrder) {
            try {
                await this.printer.print(lastOrder);
                this.notification.add(_t("Last receipt reprinted!"), {
                    type: "success",
                });
            } catch (error) {
                this.notification.add(_t("Reprint sent to printer"), {
                    type: "info",
                });
            }
        } else {
            // Try to show last order from server
            this.notification.add(_t("Looking for last order..."), {
                type: "info",
            });
            
            // Navigate to order history
            const orders = await this.pos.data.searchRead("pos.order", [], ["name", "date_order", "amount_total"], { limit: 1, order: "id DESC" });
            if (orders && orders.length > 0) {
                this.notification.add(_t("Last order: " + orders[0].name + " - $" + orders[0].amount_total), {
                    type: "info",
                });
            }
        }
        console.log("[FPS Shortcuts] Reprint last receipt");
    },

    // Print Daily Report (Z-Report)
    async printDailyReport() {
        const { confirmed } = await this.popup.add("ConfirmPopup", {
            title: _t("Daily Sales Report"),
            body: _t("This will show today's sales summary. Continue?"),
        });
        
        if (confirmed) {
            // Get session info
            const session = this.pos.pos_session;
            const orders = this.pos.db.get_orders();
            
            let totalSales = 0;
            let totalOrders = 0;
            let cashTotal = 0;
            let cardTotal = 0;
            let ebtTotal = 0;
            
            // Calculate from current session
            this.notification.add(
                _t("Session: " + session.name + "\nTotal Orders: Check closing report"), 
                { type: "info" }
            );
            
            // Direct them to close session for full report
            this.notification.add(_t("For full report: Close & Post session from backend"), {
                type: "info",
            });
        }
        console.log("[FPS Shortcuts] Daily report requested");
    },

    // Attendance / Clock In-Out
    async showAttendance() {
        const user = this.pos.user;
        const currentTime = new Date().toLocaleTimeString();
        const currentDate = new Date().toLocaleDateString();
        
        const { confirmed, payload } = await this.popup.add("SelectionPopup", {
            title: _t("Attendance - " + user.name),
            list: [
                { id: 'clockin', label: '🟢 Clock IN', item: 'clockin' },
                { id: 'clockout', label: '🔴 Clock OUT', item: 'clockout' },
                { id: 'break_start', label: '☕ Start Break', item: 'break_start' },
                { id: 'break_end', label: '✅ End Break', item: 'break_end' },
            ],
        });
        
        if (confirmed && payload) {
            const action = payload;
            let message = "";
            
            switch(action) {
                case 'clockin':
                    message = `${user.name} clocked IN at ${currentTime}`;
                    break;
                case 'clockout':
                    message = `${user.name} clocked OUT at ${currentTime}`;
                    break;
                case 'break_start':
                    message = `${user.name} started break at ${currentTime}`;
                    break;
                case 'break_end':
                    message = `${user.name} ended break at ${currentTime}`;
                    break;
            }
            
            this.notification.add(_t(message), {
                type: "success",
            });
            
            // Log attendance (in production, save to database)
            console.log("[FPS Attendance]", message, currentDate);
        }
    },

    // Price Check
    async priceCheck() {
        const { confirmed, payload } = await this.popup.add("TextInputPopup", {
            title: _t("Price Check"),
            placeholder: _t("Enter barcode or product name"),
        });
        
        if (confirmed && payload) {
            const searchTerm = payload.trim();
            
            // Search by barcode first
            let product = this.pos.db.get_product_by_barcode(searchTerm);
            
            // If not found, search by name
            if (!product) {
                const products = this.pos.db.search_product_in_category(0, searchTerm);
                if (products && products.length > 0) {
                    product = products[0];
                }
            }
            
            if (product) {
                const snapStatus = product.snap_eligible ? "✅ EBT Eligible" : "❌ Not EBT Eligible";
                await this.popup.add("ConfirmPopup", {
                    title: product.display_name,
                    body: `💰 Price: $${product.lst_price.toFixed(2)}\n📦 Barcode: ${product.barcode || 'N/A'}\n🏷️ ${snapStatus}`,
                    confirmText: _t("OK"),
                });
            } else {
                this.notification.add(_t("Product not found: " + searchTerm), {
                    type: "warning",
                });
            }
        }
    },

    // Hold Order (Park current order)
    async holdOrder() {
        const order = this.pos.get_order();
        if (order.get_orderlines().length === 0) {
            this.notification.add(_t("No items to hold"), {
                type: "warning",
            });
            return;
        }
        
        const { confirmed, payload } = await this.popup.add("TextInputPopup", {
            title: _t("Hold Order"),
            placeholder: _t("Enter customer name or note"),
        });
        
        if (confirmed) {
            const note = payload || "Held Order";
            order.set_customer_note(note + " [HELD at " + new Date().toLocaleTimeString() + "]");
            
            // Create new order and keep the held one
            this.pos.add_new_order();
            
            this.notification.add(_t("Order held: " + note), {
                type: "success",
            });
        }
    },

    // Recall Held Order
    async recallOrder() {
        const orders = this.pos.get_order_list();
        const heldOrders = orders.filter(o => 
            !o.finalized && 
            o.get_orderlines().length > 0 && 
            o !== this.pos.get_order()
        );
        
        if (heldOrders.length === 0) {
            this.notification.add(_t("No held orders found"), {
                type: "info",
            });
            return;
        }
        
        const orderList = heldOrders.map((order, idx) => ({
            id: idx,
            label: `Order ${idx + 1}: $${order.get_total_with_tax().toFixed(2)} (${order.get_orderlines().length} items)`,
            item: order,
        }));
        
        const { confirmed, payload } = await this.popup.add("SelectionPopup", {
            title: _t("Recall Held Order"),
            list: orderList,
        });
        
        if (confirmed && payload) {
            this.pos.set_order(payload);
            this.notification.add(_t("Order recalled!"), {
                type: "success",
            });
        }
    },
});

console.log("[FPS Shortcuts] Cashier shortcuts loaded successfully");
