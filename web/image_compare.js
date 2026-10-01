import { app, ComfyApp } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASS = "Lyonir_ImageCompare";

function imageUrl(info, cacheBust = true) {
    if (!info) return "";
    const params = new URLSearchParams();
    params.set("filename", info.filename || "");
    params.set("type", info.type || "temp");
    params.set("subfolder", info.subfolder || "");
    if (cacheBust) params.set("t", String(Date.now()));
    return api.apiURL(`/view?${params.toString()}`);
}

function stopGraphGesture(e) {
    e.stopPropagation();
}

function makeSurfaceTransparent(element) {
    if (!element?.style) return;
    element.style.setProperty("background", "transparent", "important");
    element.style.setProperty("background-color", "transparent", "important");
    element.style.setProperty("border", "none", "important");
    element.style.setProperty("outline", "none", "important");
    element.style.setProperty("box-shadow", "none", "important");
}

async function copyImageToClipboard(url) {
    if (!url) return;
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let blob = await response.blob();

    // Chromium clipboard support is most reliable with PNG. Convert other
    // image formats through a canvas before writing them to the OS clipboard.
    if (blob.type !== "image/png") {
        const bitmap = await createImageBitmap(blob);
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close?.();
        blob = await new Promise((resolve, reject) => {
            canvas.toBlob((value) => value ? resolve(value) : reject(new Error("PNG conversion failed")), "image/png");
        });
    }

    if (!navigator.clipboard?.write || !globalThis.ClipboardItem) {
        throw new Error("Clipboard image API is unavailable in this browser");
    }
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

function downloadImage(info) {
    if (!info) return;
    const url = imageUrl(info, false);
    const link = document.createElement("a");
    link.href = url;
    link.download = info.filename || "lyonir_compare.png";
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
}

function createComparer(node) {
    const root = document.createElement("div");
    root.className = "lyonir-image-compare";
    Object.assign(root.style, {
        position: "relative",
        width: "100%",
        height: "100%",
        minHeight: "240px",
        overflow: "hidden",
        borderRadius: "0",
        background: "transparent",
        userSelect: "none",
        touchAction: "none",
        boxSizing: "border-box",
        border: "none",
    });

    const makeImg = () => {
        const img = document.createElement("img");
        img.draggable = false;
        Object.assign(img.style, {
            position: "absolute",
            inset: "0",
            width: "100%",
            height: "100%",
            objectFit: "contain",
            objectPosition: "center center",
            pointerEvents: "none",
            display: "none",
            background: "transparent",
        });
        return img;
    };

    const imageA = makeImg();
    const imageB = makeImg();
    imageB.style.clipPath = "inset(0 50% 0 0)";

    const divider = document.createElement("div");
    Object.assign(divider.style, {
        position: "absolute",
        top: "0",
        bottom: "0",
        left: "50%",
        width: "2px",
        transform: "translateX(-1px)",
        background: "rgba(255,255,255,0.96)",
        boxShadow: "0 0 0 1px rgba(0,0,0,0.28), 0 0 10px rgba(255,255,255,0.18)",
        pointerEvents: "none",
        display: "none",
        zIndex: "5",
    });

    const handle = document.createElement("div");
    handle.textContent = "↔";
    Object.assign(handle.style, {
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: "28px",
        height: "28px",
        borderRadius: "50%",
        display: "none",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,2,16,0.78)",
        border: "1px solid rgba(227,227,227,0.85)",
        color: "#e3e3e3",
        font: "16px Inter, system-ui, sans-serif",
        pointerEvents: "none",
        zIndex: "6",
    });

    const makeLabel = (text, side) => {
        const label = document.createElement("div");
        label.textContent = text;
        Object.assign(label.style, {
            position: "absolute",
            top: "8px",
            [side]: "8px",
            padding: "2px 6px",
            borderRadius: "4px",
            background: "rgba(0,2,16,0.64)",
            color: "#e3e3e3",
            font: "600 10px Inter, system-ui, sans-serif",
            pointerEvents: "none",
            zIndex: "7",
            display: "none",
        });
        return label;
    };

    const labelA = makeLabel("A", "left");
    const labelB = makeLabel("B", "right");

    root.append(imageA, imageB, divider, handle, labelA, labelB);

    let readyA = false;
    let readyB = false;
    let reveal = 0.5;
    let aInfo = null;
    let bInfo = null;
    let lastPointerRatio = 0.75;
    let resizeObserver = null;

    function syncSurface() {
        for (const surface of [root, imageA, imageB]) {
            makeSurfaceTransparent(surface);
        }
        const host = root.parentElement;
        if (host && host !== document.body && host !== document.documentElement) {
            makeSurfaceTransparent(host);
        }
    }

    function setReveal(value) {
        reveal = Math.max(0, Math.min(1, value));
        const pct = reveal * 100;
        imageB.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
        divider.style.left = `${pct}%`;
        handle.style.left = `${pct}%`;
    }

    function updateVisibility() {
        const ready = readyA && readyB;
        imageA.style.display = readyA ? "block" : "none";
        imageB.style.display = readyB ? "block" : "none";
        divider.style.display = ready ? "block" : "none";
        handle.style.display = ready ? "flex" : "none";
        labelA.style.display = ready ? "block" : "none";
        labelB.style.display = ready ? "block" : "none";
    }

    function loadImage(img, info, which) {
        if (!info) return;
        img.onload = () => {
            if (which === "a") readyA = true;
            else readyB = true;
            updateVisibility();
        };
        img.onerror = () => {
            if (which === "a") readyA = false;
            else readyB = false;
            updateVisibility();
        };
        img.src = imageUrl(info);
    }

    function updateFromOutput(output) {
        const a = output?.lyonir_compare_a?.[0];
        const b = output?.lyonir_compare_b?.[0];
        if (!a || !b) return;
        aInfo = a;
        bInfo = b;
        readyA = false;
        readyB = false;
        updateVisibility();
        loadImage(imageA, a, "a");
        loadImage(imageB, b, "b");
        setReveal(0.5);
    }

    function pointerRatio(e) {
        const rect = root.getBoundingClientRect();
        if (rect.width <= 0) return lastPointerRatio;
        return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    }

    function revealFromPointer(e) {
        if (!(readyA && readyB)) return;
        lastPointerRatio = pointerRatio(e);
        setReveal(lastPointerRatio);
    }

    function activeInfo() {
        if (readyA && readyB) {
            // Image B is the clipped overlay on the LEFT side of the divider;
            // image A is visible on the RIGHT side.
            return lastPointerRatio <= reveal ? bInfo : aInfo;
        }
        if (readyB) return bInfo;
        if (readyA) return aInfo;
        return aInfo || bInfo;
    }

    function openActive() {
        const info = activeInfo();
        if (!info) return;
        window.open(imageUrl(info, false), "_blank", "noopener,noreferrer");
    }

    async function copyActive() {
        const info = activeInfo();
        if (!info) return;
        try {
            await copyImageToClipboard(imageUrl(info, false));
        } catch (error) {
            console.warn("[Lyonir Image Compare] Copy Image failed", error);
        }
    }

    function saveActive() {
        downloadImage(activeInfo());
    }

    async function openMaskEditor(targetNode) {
        const info = activeInfo();
        if (!info || !targetNode) return;

        const img = new Image();
        img.src = imageUrl(info, false);
        try { await img.decode?.(); } catch (_) {}

        const previousImgs = targetNode.imgs;
        const previousIndex = targetNode.imageIndex;
        const previousPreviewType = targetNode.previewMediaType;

        targetNode.imgs = [img];
        targetNode.imageIndex = 0;
        targetNode.previewMediaType = "image";

        try {
            // Current ComfyUI still exposes this compatibility bridge while the
            // native command system transitions. It opens the same Mask Editor
            // used by normal Save/Preview Image nodes.
            ComfyApp.clipspace_return_node = targetNode;
            if (typeof ComfyApp.open_maskeditor === "function") {
                ComfyApp.open_maskeditor();
            }
        } finally {
            // Let the editor read the selected source first, then restore the
            // comparer so no second native preview appears on the node.
            setTimeout(() => {
                targetNode.imgs = previousImgs;
                targetNode.imageIndex = previousIndex;
                targetNode.previewMediaType = previousPreviewType;
            }, 150);
        }
    }

    root.addEventListener("pointermove", (e) => {
        stopGraphGesture(e);
        revealFromPointer(e);
    }, { passive: true });
    root.addEventListener("pointerdown", (e) => {
        stopGraphGesture(e);
        root.setPointerCapture?.(e.pointerId);
        revealFromPointer(e);
    });
    root.addEventListener("pointerup", (e) => {
        stopGraphGesture(e);
        root.releasePointerCapture?.(e.pointerId);
    });
    root.addEventListener("wheel", stopGraphGesture, { passive: true });

    // Do not swallow contextmenu here. Let ComfyUI open the node context menu;
    // we only remember which side of the comparer the user clicked.
    root.addEventListener("contextmenu", (e) => {
        lastPointerRatio = pointerRatio(e);
    });

    if (globalThis.ResizeObserver) {
        resizeObserver = new ResizeObserver(() => syncSurface());
        resizeObserver.observe(root);
    }

    syncSurface();

    function destroy() {
        resizeObserver?.disconnect?.();
        resizeObserver = null;
    }

    return {
        root,
        updateFromOutput,
        hasImage: () => Boolean(activeInfo()),
        openActive,
        copyActive,
        saveActive,
        openMaskEditor,
        destroy,
    };
}

app.registerExtension({
    name: "LyonirStudio.ImageCompare.Nodes4",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        if (nodeType.prototype.__lyonirImageComparePatched) return;
        nodeType.prototype.__lyonirImageComparePatched = true;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);

            const viewer = createComparer(this);
            this.__lyonirComparer = viewer;

            const widget = this.addDOMWidget(
                "lyonir_image_compare_viewer",
                "lyonir_image_compare",
                viewer.root,
                {
                    serialize: false,
                    hideOnZoom: false,
                    margin: 0,
                    getMinHeight: () => 210,
                    getMaxHeight: () => 4000,
                    getHeight: () => 280,
                },
            );
            if (widget) widget.serialize = false;

            const natural = this.computeSize?.();
            if (Array.isArray(natural) && natural.length >= 2) this.setSize?.(natural);
        };

        // Add the same image-specific context actions users get on Save Image.
        // The selected side is whichever image is underneath the last pointer
        // position in the A/B comparer.
        const originalExtraMenu = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            const result = originalExtraMenu?.apply(this, arguments);
            const viewer = this.__lyonirComparer;
            if (Array.isArray(options) && viewer?.hasImage?.()) {
                const imageItems = [
                    { content: "Open Image", callback: () => viewer.openActive() },
                    { content: "Copy Image", callback: () => viewer.copyActive() },
                    { content: "Save Image", callback: () => viewer.saveActive() },
                    { content: "MaskEditor", callback: () => viewer.openMaskEditor(this) },
                    null,
                ];
                options.unshift(...imageItems);
            }
            return result;
        };

        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalExecuted?.apply(this, arguments);
            this.__lyonirComparer?.updateFromOutput(message);
        };

        const originalRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this.__lyonirComparer?.destroy?.();
            originalRemoved?.apply(this, arguments);
        };
    },
});
