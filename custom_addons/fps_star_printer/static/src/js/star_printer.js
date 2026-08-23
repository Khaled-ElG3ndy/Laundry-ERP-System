/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";

// Star TSP100 WebPRNT Configuration
const STAR_PRINTER_CONFIG = {
    ip: "192.168.1.222",
    port: 80,
    endpoint: "/StarWebPRNT/SendMessage"
};

// Star WebPRNT helper functions
const StarPrinter = {
    getUrl() {
        return `http://${STAR_PRINTER_CONFIG.ip}:${STAR_PRINTER_CONFIG.port}${STAR_PRINTER_CONFIG.endpoint}`;
    },
    
    async printReceipt(receiptContent) {
        try {
            // Build Star WebPRNT request
            const request = this.buildStarRequest(receiptContent);
            
            const response = await fetch(this.getUrl(), {
                method: 'POST',
                headers: {
                    'Content-Type': 'text/xml; charset="utf-8"'
                },
                body: request,
                mode: 'cors'
            });
            
            if (response.ok) {
                console.log('[Star TSP100] Print successful');
                return true;
            } else {
                console.error('[Star TSP100] Print failed:', response.status);
                return false;
            }
        } catch (error) {
            console.error('[Star TSP100] Print error:', error);
            return false;
        }
    },
    
    buildStarRequest(content) {
        // Star WebPRNT XML format
        return `<?xml version="1.0" encoding="UTF-8"?>
<StarWebPrint xmlns="http://www.star-m.jp" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
    <Request>
        <Initialize/>
        <Alignment Align="Center"/>
        <SetBold>true</SetBold>
        <PrintText>${this.escapeXml(content.header || 'FAIR PRICE SUPERMARKET')}</PrintText>
        <SetBold>false</SetBold>
        <Alignment Align="Left"/>
        <PrintText>${this.escapeXml(content.body || '')}</PrintText>
        <Alignment Align="Center"/>
        <PrintText>------------------------</PrintText>
        <PrintText>${this.escapeXml(content.footer || 'Thank You!')}</PrintText>
        <PrintText></PrintText>
        <PrintText></PrintText>
        <CutPaper Feed="true"/>
    </Request>
</StarWebPrint>`;
    },
    
    escapeXml(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&apos;');
    },
    
    // Simple text print for testing
    async printTest() {
        const testContent = {
            header: 'FAIR PRICE SUPERMARKET',
            body: `
5703 Edsall Rd
Alexandria, VA 22304
(703) 751-0786

*** TEST PRINT ***
${new Date().toLocaleString()}

Printer: Star TSP100
IP: 192.168.1.222
Status: Connected

Thank you for shopping!
            `,
            footer: 'We Accept EBT/SNAP'
        };
        return this.printReceipt(testContent);
    }
};

// Make available globally for testing
window.StarPrinter = StarPrinter;

console.log('[Star TSP100] Printer module loaded. Test with: StarPrinter.printTest()');
