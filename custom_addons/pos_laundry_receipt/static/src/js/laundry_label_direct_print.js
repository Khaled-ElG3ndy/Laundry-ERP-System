/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { localization } from "@web/core/l10n/localization";
import { registry } from "@web/core/registry";
import { getFontEmbedCSS, toCanvas } from "@point_of_sale/app/utils/html-to-image";

const EPOS_DEVICE_ID = "local_printer";
const DEFAULT_PRINTER_DOT_WIDTH = 576;
const PRINT_OVERLAY_SETTLE_DELAY = 140;
const PRINT_OVERLAY_STATE = {
    printing: { icon: "fa fa-print" },
    done: { icon: "fa fa-check" },
    warning: { icon: "fa fa-info" },
    failed: { icon: "fa fa-exclamation" },
    cancelled: { icon: "fa fa-ban" },
};
const PRINT_OVERLAY_PRINTER_ICON = `
    <svg class="o_laundry_print_printer_icon" viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <path d="M20 25V10h24v15"></path>
        <path d="M18 48h-6a6 6 0 0 1-6-6V30a6 6 0 0 1 6-6h40a6 6 0 0 1 6 6v12a6 6 0 0 1-6 6h-6"></path>
        <path d="M20 42h24v16H20z"></path>
        <path d="M25 49h14"></path>
        <path d="M46 34h.01"></path>
    </svg>
`;
const PRINT_OVERLAY_CLOSE_ICON = `
    <svg class="o_laundry_print_x_icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M6 6l12 12"></path>
        <path d="M18 6L6 18"></path>
    </svg>
`;
let printOverlayLocaleContext = null;

function normalizeLanguageCode(value) {
    return String(value || "")
        .trim()
        .replace("_", "-")
        .toLowerCase();
}

function firstValue(values) {
    for (const value of values) {
        if (value !== undefined && value !== null && String(value).trim()) {
            return value;
        }
    }
    return "";
}

function getOdooSessionInfo() {
    if (typeof window === "undefined") {
        return {};
    }
    return window.odoo?.session_info || window.odoo?.__session_info__ || {};
}

function getOverlayLocaleContext(env = null) {
    const userService = env?.services?.user || {};
    const userContext = userService.context || userService.user_context || {};
    const sessionInfo = getOdooSessionInfo();
    const sessionContext = sessionInfo.user_context || sessionInfo.context || {};
    return {
        language: firstValue([
            userContext.lang,
            userService.lang,
            userService.language,
            sessionContext.lang,
            sessionInfo.lang,
            sessionInfo.user_lang,
            localization.code,
            localization.language,
        ]),
        direction: firstValue([
            userContext.direction,
            userService.direction,
            sessionContext.direction,
            localization.direction,
        ]),
    };
}

function hasRtlClass() {
    if (typeof document === "undefined") {
        return false;
    }
    return Boolean(
        document.documentElement?.classList?.contains("o_rtl") ||
            document.documentElement?.classList?.contains("is-rtl") ||
            document.body?.classList?.contains("o_rtl") ||
            document.body?.classList?.contains("is-rtl")
    );
}

function getInterfaceLanguage() {
    const context = printOverlayLocaleContext || getOverlayLocaleContext();
    return normalizeLanguageCode(
        firstValue([
            context.language,
            localization.code,
            localization.language,
            typeof document !== "undefined" ? document.documentElement?.lang : "",
            typeof document !== "undefined" ? document.body?.lang : "",
            typeof navigator !== "undefined" ? navigator.language : "",
            typeof navigator !== "undefined" ? navigator.userLanguage : "",
        ])
    );
}

function getInterfaceDirection() {
    const language = getInterfaceLanguage();
    if (language.startsWith("ar")) {
        return "rtl";
    }
    const context = printOverlayLocaleContext || getOverlayLocaleContext();
    const direction = String(
        firstValue([
            context.direction,
            localization.direction,
            typeof document !== "undefined" ? document.documentElement?.dir : "",
            typeof document !== "undefined" ? document.body?.dir : "",
        ])
    ).toLowerCase();
    if (direction === "rtl" || hasRtlClass()) {
        return "rtl";
    }
    return "ltr";
}

function isArabicInterface() {
    return getInterfaceLanguage().startsWith("ar") || getInterfaceDirection() === "rtl";
}

function getOverlayDirection() {
    return getInterfaceDirection();
}

function formatOverlayText(template, values) {
    return values.reduce((text, value) => text.replace("%s", value), template);
}

function overlayText(english, arabic, ...values) {
    return formatOverlayText(isArabicInterface() ? arabic : english, values);
}

class PrintCancelledError extends Error {
    constructor() {
        super(overlayText("Printing was stopped.", "تم إيقاف الطباعة."));
        this.name = "PrintCancelledError";
    }
}

function isPrintCancelled(error) {
    return error instanceof PrintCancelledError || error?.name === "PrintCancelledError";
}

function normalizeMessage(error) {
    if (!error) {
        return overlayText("Unknown print error", "خطأ غير معروف في الطباعة");
    }
    return error.message || error.body || String(error);
}

function getPrintTimeoutMessage() {
    return overlayText(
        "The printer did not respond before the intake receipt timeout.",
        "لم تستجب الطابعة قبل انتهاء مهلة فاتورة الاستلام."
    );
}

function getNotification(env) {
    const services = env?.services || {};
    const webNotification = services.notification;
    if (webNotification?.add) {
        return {
            add: (message, options = {}) => webNotification.add(message, options),
        };
    }
    const posNotification = services.pos_notification;
    if (posNotification?.add) {
        return {
            add: (message, options = {}) =>
                posNotification.add(message, options?.sticky ? 8000 : 3000),
        };
    }
    return {
        add: () => {},
    };
}

function getNextAction(params) {
    if (params.close_on_done) {
        return { type: "ir.actions.act_window_close" };
    }
    return { type: "ir.actions.client", tag: "soft_reload" };
}

function createPrintOverlay() {
    const overlay = document.createElement("div");
    overlay.className = "o_laundry_print_overlay";
    overlay.dir = getOverlayDirection();
    overlay.lang = isArabicInterface() ? "ar" : "en";
    overlay.innerHTML = `
        <section class="o_laundry_print_panel" role="status" aria-live="polite">
            <div class="o_laundry_print_header">
                <span class="o_laundry_print_loader" aria-hidden="true">
                    ${PRINT_OVERLAY_PRINTER_ICON}
                </span>
                <div class="o_laundry_print_title_block">
                    <h2 class="o_laundry_print_title"></h2>
                    <p class="o_laundry_print_detail"></p>
                </div>
                <span class="o_laundry_print_counter" aria-hidden="true"></span>
            </div>
            <div class="o_laundry_print_progress" aria-hidden="true">
                <span class="o_laundry_print_progress_bar"></span>
            </div>
            <div class="o_laundry_print_actions">
                <button type="button" class="o_laundry_print_cancel">
                    <span class="o_laundry_print_cancel_icon" aria-hidden="true">
                        ${PRINT_OVERLAY_CLOSE_ICON}
                    </span>
                    <span class="o_laundry_print_cancel_text">${overlayText("Stop", "إيقاف")}</span>
                </button>
            </div>
        </section>
    `;

    document.body.appendChild(overlay);
    const title = overlay.querySelector(".o_laundry_print_title");
    const detail = overlay.querySelector(".o_laundry_print_detail");
    const counter = overlay.querySelector(".o_laundry_print_counter");
    const progressBar = overlay.querySelector(".o_laundry_print_progress_bar");
    const loader = overlay.querySelector(".o_laundry_print_loader");
    const cancelButton = overlay.querySelector(".o_laundry_print_cancel");
    const cancelText = overlay.querySelector(".o_laundry_print_cancel_text");
    const cancelListeners = new Set();
    let cancelled = false;
    let shownProgress = 0;

    const update = ({ status, message, progress, current, total, state }) => {
        const overlayState = state || "printing";
        const stateData = PRINT_OVERLAY_STATE[overlayState] || PRINT_OVERLAY_STATE.printing;
        title.textContent = status || overlayText("Printing", "طباعة");
        detail.textContent = message || "";
        if (overlayState === "printing") {
            if (loader.dataset.iconState !== "printing") {
                loader.innerHTML = PRINT_OVERLAY_PRINTER_ICON;
                loader.dataset.iconState = "printing";
            }
        } else if (loader.dataset.iconState !== stateData.icon) {
            loader.innerHTML = `<i class="${stateData.icon}"></i>`;
            loader.dataset.iconState = stateData.icon;
        }
        overlay.dataset.state = overlayState;
        counter.textContent = current && total > 1 ? `${current} / ${total}` : "";
        let target = shownProgress;
        if (overlayState === "done" || overlayState === "warning") {
            target = 100;
        } else if (overlayState === "printing" && Number.isFinite(Number(progress))) {
            target = Number(progress);
        }
        shownProgress = Math.min(100, Math.max(shownProgress, target));
        progressBar.style.width = `${shownProgress}%`;
        cancelButton.disabled = overlayState !== "printing";
    };

    const requestStop = () => {
        if (cancelled) {
            return;
        }
        cancelled = true;
        cancelButton.disabled = true;
        cancelText.textContent = overlayText("Stopping...", "جار الإيقاف...");
        update({
            status: overlayText("Stopping print", "إيقاف الطباعة"),
            message: overlayText(
                "Stopping now; remaining labels will not be sent.",
                "يتم الإيقاف الآن؛ لن يتم إرسال الملصقات المتبقية."
            ),
            state: "cancelled",
        });
        for (const listener of cancelListeners) {
            listener();
        }
    };

    cancelButton.addEventListener("click", requestStop);

    update({
        status: overlayText("Preparing labels", "تجهيز الملصقات"),
        message: overlayText(
            "Preparing files before sending to the printer.",
            "يتم تجهيز الملفات قبل إرسالها للطابعة."
        ),
        progress: 4,
    });
    window.requestAnimationFrame(() => overlay.classList.add("is-visible"));

    return {
        update,
        isCancelled: () => cancelled,
        throwIfCancelled: () => {
            if (cancelled) {
                throw new PrintCancelledError();
            }
        },
        onCancel: (listener) => {
            cancelListeners.add(listener);
            return () => cancelListeners.delete(listener);
        },
        close: () =>
            new Promise((resolve) => {
                const delay = overlay.dataset.state === "printing" ? 0 : PRINT_OVERLAY_SETTLE_DELAY;
                window.setTimeout(() => {
                    overlay.classList.remove("is-visible");
                    window.setTimeout(() => {
                        overlay.remove();
                        resolve();
                    }, 90);
                }, delay);
            }),
    };
}

function createReusablePrintOverlay(env = null, initialUpdate = {}) {
    printOverlayLocaleContext = getOverlayLocaleContext(env);
    const overlay = createPrintOverlay();
    overlay.update({
        status: overlayText("Preparing printing", "تجهيز الطباعة"),
        message: overlayText(
            "Preparing the request before sending it to the printer.",
            "يتم تجهيز الطلب قبل إرساله للطابعة."
        ),
        progress: 2,
        ...initialUpdate,
    });
    return overlay;
}

function getPrinterBaseUrl(printer) {
    const ip = String((printer && printer.ip) || "").trim().replace(/\/+$/, "");
    if (!ip) {
        throw new Error(_t("The process printer does not have an IP address."));
    }
    if (/^https?:\/\//i.test(ip)) {
        return ip;
    }
    return `${window.location.protocol}//${ip}`;
}

function getPrinterAddress(printer) {
    return `${getPrinterBaseUrl(printer)}/cgi-bin/epos/service.cgi?devid=${EPOS_DEVICE_ID}`;
}

function eposEnvelope(content) {
    return `<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <epos-print xmlns="http://www.epson-pos.com/schemas/2011/03/epos-print">
      ${content}
    </epos-print>
  </s:Body>
</s:Envelope>`;
}

function canvasToRaster(canvas) {
    const imageData = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
    const pixels = imageData.data;
    const { width, height } = imageData;
    // Same Floyd-Steinberg dithering as before, but the diffused error only ever
    // reaches the current and the next row, so two rolling rows replace the full
    // width x height matrix and the bits are packed straight into bytes.
    let rowErrors = new Float64Array(width);
    let nextErrors = new Float64Array(width);
    const bytes = new Uint8Array(Math.ceil((width * height) / 8));
    let byteIndex = 0;
    let bitCount = 0;
    let currentByte = 0;

    for (let y = 0; y < height; y++) {
        const hasNextRow = y < height - 1;
        for (let x = 0; x < width; x++) {
            const idx = (y * width + x) * 4;
            let oldColor = pixels[idx] * 0.299 + pixels[idx + 1] * 0.587 + pixels[idx + 2] * 0.114;
            oldColor = Math.min(255, Math.max(0, oldColor + rowErrors[x]));

            const newColor = oldColor < 128 ? 0 : 255;
            currentByte = (currentByte << 1) | (newColor ? 0 : 1);
            if (++bitCount === 8) {
                bytes[byteIndex++] = currentByte;
                currentByte = 0;
                bitCount = 0;
            }

            const error = oldColor - newColor;
            if (error) {
                if (x < width - 1) {
                    rowErrors[x + 1] += (7 / 16) * error;
                }
                if (x > 0 && hasNextRow) {
                    nextErrors[x - 1] += (3 / 16) * error;
                }
                if (hasNextRow) {
                    nextErrors[x] += (5 / 16) * error;
                }
                if (x < width - 1 && hasNextRow) {
                    nextErrors[x + 1] += (1 / 16) * error;
                }
            }
        }
        const recycledRow = rowErrors;
        rowErrors = nextErrors;
        nextErrors = recycledRow;
        nextErrors.fill(0);
    }

    if (bitCount) {
        bytes[byteIndex++] = currentByte;
    }
    return bytes;
}

function encodeRaster(rasterData) {
    const chunkSize = 0x8000;
    let encodedData = "";
    for (let i = 0; i < rasterData.length; i += chunkSize) {
        encodedData += String.fromCharCode.apply(
            null,
            rasterData.subarray(i, Math.min(i + chunkSize, rasterData.length))
        );
    }
    return btoa(encodedData);
}

function scaleCanvasToPrinterWidth(canvas, printerDotWidth) {
    const width = Math.max(8, Number(printerDotWidth) || DEFAULT_PRINTER_DOT_WIDTH);
    const targetWidth = width - (width % 8);
    if (canvas.width === targetWidth) {
        return canvas;
    }

    const scale = targetWidth / canvas.width;
    const scaledCanvas = document.createElement("canvas");
    scaledCanvas.width = targetWidth;
    scaledCanvas.height = Math.max(1, Math.ceil(canvas.height * scale));
    const context = scaledCanvas.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, scaledCanvas.width, scaledCanvas.height);
    context.drawImage(canvas, 0, 0, scaledCanvas.width, scaledCanvas.height);
    return scaledCanvas;
}

function canvasToEposXml(canvas) {
    const encodedRaster = encodeRaster(canvasToRaster(canvas));
    return eposEnvelope(
        `<image width="${canvas.width}" height="${canvas.height}" align="center">${encodedRaster}</image>
<cut type="feed" />`
    );
}

function printerErrorMessage(result) {
    const code = (result && result.printerErrorCode) || "";
    if (code === "DeviceNotFound") {
        return overlayText(
            "The Epson printer was reached, but Device ID local_printer was not found.",
            "تم الوصول إلى طابعة Epson، لكن لم يتم العثور على Device ID local_printer."
        );
    }
    if (code === "EPTR_REC_EMPTY") {
        return overlayText("No paper was detected by the printer.", "لم تكتشف الطابعة وجود ورق.");
    }
    if (code) {
        return `${overlayText("Epson error code", "كود خطأ Epson")}: ${code}`;
    }
    return overlayText("The printer rejected the print job.", "رفضت الطابعة مهمة الطباعة.");
}

async function sendEposXmlToPrinter(eposXml, printer, signal = null) {
    let response;
    try {
        response = await fetch(getPrinterAddress(printer), {
            method: "POST",
            headers: { "Content-Type": "text/xml; charset=utf-8" },
            body: eposXml,
            signal,
        });
    } catch (error) {
        if (error?.name === "AbortError") {
            throw new PrintCancelledError();
        }
        let message = overlayText("Could not reach the Epson printer.", "تعذر الوصول إلى طابعة Epson.");
        if (window.location.protocol === "https:") {
            message += ` ${overlayText(
                "Open this printer address once in the same browser and accept its certificate",
                "افتح عنوان الطابعة مرة واحدة في نفس المتصفح ووافق على الشهادة"
            )}: ${getPrinterBaseUrl(printer)}`;
        }
        throw new Error(`${message} (${normalizeMessage(error)})`);
    }
    const body = await response.text();
    const parsedBody = new DOMParser().parseFromString(body, "application/xml");
    const eposResponse = parsedBody.querySelector("response");
    const result = {
        ok: response.ok,
        successful: eposResponse ? eposResponse.getAttribute("success") === "true" : false,
        printerErrorCode: eposResponse ? eposResponse.getAttribute("code") || "" : "",
    };
    if (!result.ok || !result.successful) {
        throw new Error(printerErrorMessage(result));
    }
}

async function fetchLabelHtml(url, signal = null) {
    const response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        signal,
    });
    if (!response.ok) {
        throw new Error(
            overlayText(
                "Could not load the laundry label template.",
                "تعذر تحميل قالب ملصق المغسلة."
            )
        );
    }
    return await response.text();
}

function waitForBrowserFrame(frameWindow) {
    return new Promise((resolve) => {
        frameWindow.requestAnimationFrame(() => frameWindow.requestAnimationFrame(resolve));
    });
}

async function waitForFrameDocument(iframe) {
    const frameWindow = iframe.contentWindow;
    const frameDocument = iframe.contentDocument;
    if (!frameWindow || !frameDocument) {
        throw new Error(
            overlayText("Could not prepare the print frame.", "تعذر تجهيز إطار الطباعة.")
        );
    }

    if (frameDocument.readyState !== "complete") {
        await Promise.race([
            new Promise((resolve) => {
                frameWindow.addEventListener("load", resolve, { once: true });
            }),
            new Promise((resolve) => window.setTimeout(resolve, 5000)),
        ]);
    }

    if (frameDocument.fonts?.ready) {
        await Promise.race([
            frameDocument.fonts.ready.catch(() => undefined),
            new Promise((resolve) => window.setTimeout(resolve, 4000)),
        ]);
    }

    await waitForBrowserFrame(frameWindow);
}

async function mountLabelPages(html) {
    const iframe = document.createElement("iframe");
    iframe.className = "o_laundry_epos_print_frame";
    iframe.setAttribute("aria-hidden", "true");
    iframe.setAttribute("tabindex", "-1");
    iframe.style.cssText = [
        "position:fixed",
        "left:-10000px",
        "top:0",
        "width:80mm",
        "height:1200px",
        "border:0",
        "opacity:0",
        "pointer-events:none",
        "z-index:-1",
    ].join(";");
    document.body.appendChild(iframe);

    const frameDocument = iframe.contentDocument;
    if (!frameDocument) {
        iframe.remove();
        throw new Error(
            overlayText("Could not prepare the print frame.", "تعذر تجهيز إطار الطباعة.")
        );
    }

    frameDocument.open();
    frameDocument.write(html);
    frameDocument.close();
    await waitForFrameDocument(iframe);

    const pages = [...frameDocument.querySelectorAll(".laundry-label-page")];
    if (!pages.length) {
        iframe.remove();
        throw new Error(
            overlayText(
                "No laundry labels were found in the print template.",
                "لم يتم العثور على ملصقات مغسلة داخل قالب الطباعة."
            )
        );
    }

    const head =
        frameDocument.head ||
        frameDocument.documentElement.insertBefore(
            frameDocument.createElement("head"),
            frameDocument.body
        );
    const overrides = frameDocument.createElement("style");
    overrides.textContent = `
        html,
        body {
            margin: 0 !important;
            width: 80mm !important;
            min-width: 80mm !important;
            max-width: 80mm !important;
            overflow: visible !important;
            background: #fff !important;
        }
        .laundry-label-page {
            margin: 0 !important;
            background: #fff !important;
            break-after: auto !important;
            page-break-after: auto !important;
        }
        .laundry-label-card {
            box-shadow: none !important;
        }
    `;
    head.appendChild(overrides);

    await waitForFrameDocument(iframe);

    return {
        frame: iframe,
        root: frameDocument.body,
        pages,
    };
}

async function waitForImages(root) {
    const images = [...root.querySelectorAll("img")];
    await Promise.all(
        images.map((image) => {
            if (image.complete && image.naturalWidth !== 0) {
                return Promise.resolve();
            }
            return new Promise((resolve, reject) => {
                image.addEventListener("load", resolve, { once: true });
                image.addEventListener("error", reject, { once: true });
            });
        })
    );
}

async function renderPageCanvas(page, printerDotWidth, fontEmbedCSS) {
    const rect = page.getBoundingClientRect();
    const width = Math.ceil(rect.width || page.scrollWidth);
    const height = Math.ceil(page.scrollHeight || rect.height);
    const options = {
        backgroundColor: "#ffffff",
        includeQueryParams: true,
        pixelRatio: 2,
        width,
        height,
    };
    if (typeof fontEmbedCSS === "string") {
        // Inlining the web fonts is done once for the whole batch instead of
        // being recomputed for every single label.
        options.fontEmbedCSS = fontEmbedCSS;
    }
    const canvas = await toCanvas(page, options);
    return scaleCanvasToPrinterWidth(canvas, printerDotWidth);
}

async function preparePagePayload(page, printerDotWidth, fontEmbedCSS) {
    const canvas = await renderPageCanvas(page, printerDotWidth, fontEmbedCSS);
    return canvasToEposXml(canvas);
}

async function getBatchFontEmbedCSS(root) {
    try {
        return await getFontEmbedCSS(root, { includeQueryParams: true });
    } catch (error) {
        console.warn(error);
        return undefined;
    }
}

async function recordLabels(orm, method, ids, batchReference, errorMessage = "") {
    if (!ids.length) {
        return;
    }
    const args =
        method === "record_browser_print_failure"
            ? [ids, errorMessage, batchReference]
            : [ids, batchReference];
    await orm.call("pos.laundry.label", method, args);
}

export async function printLaundryLabelsDirect(env, action) {
    printOverlayLocaleContext = getOverlayLocaleContext(env);
    const params = action.params || {};
    const services = env?.services || {};
    const orm = services.orm;
    const notification = getNotification(env);
    const labelIds = (params.label_ids || []).map((id) => Number(id)).filter(Boolean);
    const totalCount = Math.max(1, labelIds.length);
    const batchReference =
        params.batch_reference ||
        (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `${Date.now()}`);
    let mounted = null;
    let activeController = null;
    let timeoutId = null;
    let timedOut = false;
    const reusableOverlay = params.print_overlay || params._printOverlay || null;
    const overlay =
        reusableOverlay &&
        typeof reusableOverlay.update === "function" &&
        typeof reusableOverlay.onCancel === "function" &&
        typeof reusableOverlay.close === "function"
            ? reusableOverlay
            : createPrintOverlay();
    const removeCancelListener = overlay.onCancel(() => {
        if (activeController) {
            activeController.abort();
        }
    });
    const maxWaitMs = Number(params.max_wait_ms);
    const hasMaxWait = Number.isFinite(maxWaitMs) && maxWaitMs > 0;

    const stopPrinting = async (printedLabelIds = []) => {
        await recordLabels(
            orm,
            "record_browser_print_success",
            printedLabelIds,
            batchReference
        ).catch(console.error);
        overlay.update({
            status: overlayText("Printing stopped", "تم إيقاف الطباعة"),
            message: overlayText(
                "The job was stopped; remaining labels were not sent.",
                "تم إيقاف المهمة؛ لم يتم إرسال الملصقات المتبقية."
            ),
            state: "cancelled",
        });
        notification.add(_t("Printing stopped."), {
            type: "warning",
        });
        return getNextAction(params);
    };

    const failTimedOutPrint = async (printedLabelIds = []) => {
        const message = getPrintTimeoutMessage();
        const remainingIds = labelIds.filter((id) => !printedLabelIds.includes(id));
        await recordLabels(
            orm,
            "record_browser_print_success",
            printedLabelIds,
            batchReference
        ).catch(console.error);
        await recordLabels(
            orm,
            "record_browser_print_failure",
            remainingIds,
            batchReference,
            message
        ).catch(console.error);
        overlay.update({
            status: overlayText("Print failed", "فشلت الطباعة"),
            message: overlayText("Details: %s", "التفاصيل: %s", message),
            progress: 100,
            state: "failed",
        });
        notification.add(_t("Could not send labels to the printer: %s", message), {
            type: "danger",
            sticky: true,
        });
        return getNextAction(params);
    };

    const throwIfTimedOut = () => {
        if (timedOut) {
            throw new Error(getPrintTimeoutMessage());
        }
    };

    try {
        if (hasMaxWait) {
            timeoutId = window.setTimeout(() => {
                timedOut = true;
                if (activeController) {
                    activeController.abort();
                }
            }, maxWaitMs);
        }
        overlay.update({
            status: overlayText("Loading label template", "تحميل قالب الملصق"),
            message: overlayText("Preparing the print layout.", "يتم تجهيز شكل الطباعة."),
            progress: 8,
        });
        activeController = new AbortController();
        const html = await fetchLabelHtml(params.html_url, activeController.signal);
        activeController = null;
        throwIfTimedOut();
        overlay.throwIfCancelled();
        overlay.update({
            status: overlayText("Preparing images and QR", "تجهيز الصور ورمز QR"),
            message: overlayText(
                "Checking images and QR before printing.",
                "يتم فحص الصور ورمز QR قبل الطباعة."
            ),
            progress: 16,
        });
        mounted = await mountLabelPages(html);
        const fontEmbedPromise = getBatchFontEmbedCSS(mounted.root);
        await waitForImages(mounted.root);
        const fontEmbedCSS = await fontEmbedPromise;
        throwIfTimedOut();
        overlay.throwIfCancelled();

        const printedLabelIds = [];
        const pages = mounted.pages;
        const totalPages = pages.length || totalCount;
        // The next label is rendered and converted while the current one is
        // still travelling to the printer, so both stages overlap.
        const preparePage = (index) => {
            const promise = preparePagePayload(
                pages[index],
                params.printer_dot_width,
                fontEmbedCSS
            );
            promise.catch(() => {});
            return { index, promise };
        };
        const prepareNextPage = (index) =>
            index < pages.length && !overlay.isCancelled() ? preparePage(index) : null;
        let prepared = null;
        for (let index = 0; index < pages.length; index++) {
            throwIfTimedOut();
            overlay.throwIfCancelled();
            const page = pages[index];
            const current = index + 1;
            const labelId = Number(page.dataset.labelId) || labelIds[index];
            try {
                overlay.update({
                    status: overlayText("Preparing label", "تجهيز الملصق"),
                    message: overlayText(
                        "Converting the label for the thermal printer.",
                        "يتم تحويل الملصق للطابعة الحرارية."
                    ),
                    progress: 18 + (current / totalPages) * 42,
                    current,
                    total: totalPages,
                });
                if (!prepared || prepared.index !== index) {
                    prepared = preparePage(index);
                }
                const eposXml = await prepared.promise;
                throwIfTimedOut();
                overlay.throwIfCancelled();
                prepared = prepareNextPage(index + 1);
                overlay.update({
                    status: overlayText("Sending to printer", "إرسال للطابعة"),
                    message: overlayText("Sending the label now.", "جاري إرسال الملصق الآن."),
                    progress: 60 + (current / totalPages) * 32,
                    current,
                    total: totalPages,
                });
                activeController = new AbortController();
                await sendEposXmlToPrinter(eposXml, params.printer, activeController.signal);
                activeController = null;
                if (labelId) {
                    printedLabelIds.push(labelId);
                }
            } catch (error) {
                activeController = null;
                if (timedOut) {
                    return await failTimedOutPrint(printedLabelIds);
                }
                if (isPrintCancelled(error) || overlay.isCancelled()) {
                    return await stopPrinting(printedLabelIds);
                }
                const message = normalizeMessage(error);
                const remainingIds = labelIds.filter((id) => !printedLabelIds.includes(id));
                await recordLabels(
                    orm,
                    "record_browser_print_success",
                    printedLabelIds,
                    batchReference
                ).catch(console.error);
                await recordLabels(
                    orm,
                    "record_browser_print_failure",
                    remainingIds,
                    batchReference,
                    message
                ).catch(console.error);
                overlay.update({
                    status: overlayText("Print failed", "فشلت الطباعة"),
                    message: overlayText("Details: %s", "التفاصيل: %s", message),
                    progress: 100,
                    state: "failed",
                });
                notification.add(
                    _t("Could not send labels to the printer: %s", message),
                    { type: "danger", sticky: true }
                );
                return getNextAction(params);
            }
        }

        try {
            throwIfTimedOut();
            overlay.throwIfCancelled();
            overlay.update({
                status: overlayText("Updating print history", "تحديث سجل الطباعة"),
                message: overlayText(
                    "Saving the print result in Odoo.",
                    "يتم حفظ نتيجة الطباعة في أودو."
                ),
                progress: 96,
            });
            await recordLabels(orm, "record_browser_print_success", printedLabelIds, batchReference);
        } catch (error) {
            if (timedOut) {
                return await failTimedOutPrint(printedLabelIds);
            }
            if (isPrintCancelled(error) || overlay.isCancelled()) {
                return await stopPrinting(printedLabelIds);
            }
            overlay.update({
                status: overlayText("Printed with notice", "تمت الطباعة مع تنبيه"),
                message: overlayText(
                    "Labels were sent, but the history update needs review.",
                    "تم إرسال الملصقات، لكن تحديث السجل يحتاج مراجعة."
                ),
                progress: 100,
                state: "warning",
            });
            notification.add(
                _t(
                    "Labels were printed, but Odoo could not update the print history: %s",
                    normalizeMessage(error)
                ),
                { type: "danger", sticky: true }
            );
            return getNextAction(params);
        }
        overlay.update({
            status: overlayText("Labels sent", "تم إرسال الملصقات"),
            message: overlayText(
                "Labels were sent to print successfully.",
                "تم إرسال الملصقات للطباعة بنجاح."
            ),
            progress: 100,
            state: "done",
        });
        notification.add(_t("Labels were sent to print."), { type: "success" });
        return getNextAction(params);
    } catch (error) {
        activeController = null;
        if (timedOut) {
            return await failTimedOutPrint();
        }
        if (isPrintCancelled(error) || overlay.isCancelled()) {
            return await stopPrinting();
        }
        const message = normalizeMessage(error);
        await recordLabels(
            orm,
            "record_browser_print_failure",
            labelIds,
            batchReference,
            message
        ).catch(console.error);
        overlay.update({
            status: overlayText("Could not prepare printing", "تعذر تجهيز الطباعة"),
            message: overlayText("Details: %s", "التفاصيل: %s", message),
            progress: 100,
            state: "failed",
        });
        notification.add(_t("Laundry label printing failed: %s", message), {
            type: "danger",
            sticky: true,
        });
        return getNextAction(params);
    } finally {
        if (timeoutId) {
            window.clearTimeout(timeoutId);
        }
        removeCancelListener();
        activeController = null;
        if (mounted && mounted.frame) {
            mounted.frame.remove();
        } else if (mounted && mounted.root) {
            mounted.root.remove();
        }
        await overlay.close();
        printOverlayLocaleContext = null;
    }
}

registry.category("actions").add("pos_laundry_receipt.print_laundry_labels", printLaundryLabelsDirect);

if (typeof window !== "undefined") {
    window.posLaundryPrintLabelsDirect = printLaundryLabelsDirect;
    window.posLaundryCreatePrintOverlay = createReusablePrintOverlay;
}
