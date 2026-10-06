import { app, ComfyApp } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_CLASS = "Lyonir_SaveImage";
const BASE_NODE_WIDTH = 300;
const BASE_NODE_HEIGHT = 420;
const BASE_THUMB_SIZE = 36;

function newHistoryId() {
    try {
        if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    } catch (_) {}
    return `lyonir-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function ensureHistoryIdentity(node, forceNew = false) {
    if (!node) return "";
    node.properties ??= {};
    let value = String(node.properties.lyonir_image_history_id || "").trim();
    if (forceNew || !value) {
        value = newHistoryId();
        node.properties.lyonir_image_history_id = value;
        node.graph?.setDirtyCanvas?.(true, true);
        node.graph?.change?.();
    }
    return value;
}

function dedupeHistoryIdentity(node) {
    const current = ensureHistoryIdentity(node);
    if (!current) return current;
    const nodes = node?.graph?._nodes || [];
    const duplicate = nodes.find((other) =>
        other && other !== node && other.type === NODE_CLASS &&
        String(other?.properties?.lyonir_image_history_id || "").trim() === current
    );
    return duplicate ? ensureHistoryIdentity(node, true) : current;
}

function imageUrl(info, cacheBust = true) {
    if (!info) return "";
    const params = new URLSearchParams();
    params.set("filename", info.filename || "");
    params.set("type", info.type || "output");
    params.set("subfolder", info.subfolder || "");
    if (cacheBust) params.set("t", String(Date.now()));
    return api.apiURL(`/view?${params.toString()}`);
}

function stopGraphGesture(e) {
    e.stopPropagation();
}

function getWidgetValue(node, name, fallback) {
    const widget = node?.widgets?.find?.((item) => item?.name === name);
    return widget?.value ?? fallback;
}

async function copyImageToClipboard(url) {
    if (!url) return;
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    let blob = await response.blob();

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
    const link = document.createElement("a");
    link.href = imageUrl(info, false);
    link.download = info.filename || "lyonir_image.png";
    link.rel = "noopener";
    document.body.append(link);
    link.click();
    link.remove();
}

function createGallery(node) {
    const root = document.createElement("div");
    Object.assign(root.style, {
        width: "100%",
        height: "100%",
        minWidth: "0",
        minHeight: "0",
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: "0",
        boxSizing: "border-box",
        border: "none",
        borderRadius: "0",
        color: "#e3e3e3",
        font: "12px Inter, system-ui, sans-serif",
        userSelect: "none",
        overflow: "hidden",
        outline: "none",
        boxShadow: "none",
        background: "transparent",
    });

    const previewWrap = document.createElement("div");
    Object.assign(previewWrap.style, {
        position: "relative",
        width: "100%",
        flex: "1 1 0",
        minHeight: "120px",
        overflow: "hidden",
        borderRadius: "0",
        border: "none",
        outline: "none",
        boxShadow: "none",
        cursor: "default",
        boxSizing: "border-box",
        background: "transparent",
    });

    const preview = document.createElement("img");
    preview.draggable = false;
    Object.assign(preview.style, {
        position: "absolute",
        inset: "0",
        width: "100%",
        height: "100%",
        minWidth: "0",
        minHeight: "0",
        maxWidth: "none",
        maxHeight: "none",
        objectFit: "contain",
        objectPosition: "center center",
        display: "none",
        border: "none",
        background: "transparent",
    });

    const toolbar = document.createElement("div");
    Object.assign(toolbar.style, {
        display: "flex",
        flex: "0 0 auto",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: "4px",
        minHeight: "18px",
        boxSizing: "border-box",
        background: "transparent",
    });

    const makeButton = (label) => {
        const button = document.createElement("button");
        button.textContent = label;
        Object.assign(button.style, {
            height: "18px",
            padding: "0 6px",
            borderRadius: "0",
            border: "none",
            outline: "none",
            boxShadow: "none",
            background: "transparent",
            color: "#e3e3e3",
            cursor: "pointer",
            font: "600 10px Inter, system-ui, sans-serif",
        });
        return button;
    };

    const refreshButton = makeButton("Refresh");
    const openButton = makeButton("Open");
    toolbar.append(refreshButton, openButton);

    const thumbs = document.createElement("div");
    Object.assign(thumbs.style, {
        display: "flex",
        flex: "0 0 auto",
        alignItems: "center",
        width: "100%",
        overflowX: "auto",
        overflowY: "hidden",
        padding: "1px 0 1px",
        boxSizing: "border-box",
        scrollbarWidth: "thin",
        background: "transparent",
    });

    const generationInfo = document.createElement("div");
    generationInfo.dataset.lyonirGenerationInfo = "1";
    Object.assign(generationInfo.style, {
        position: "relative", width: "100%", height: "40px", flex: "0 0 40px",
        boxSizing: "border-box", padding: "2px 6px", fontSize: "12px",
        lineHeight: "18px", color: "inherit", background: "transparent",
        overflow: "hidden", display: "none",
    });
    const seedRow = document.createElement("div");
    Object.assign(seedRow.style, { display: "flex", alignItems: "center", gap: "6px", height: "18px" });
    const seedLabel = document.createElement("span");
    Object.assign(seedLabel.style, { minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
    const copySeedButton = document.createElement("button");
    copySeedButton.type = "button";
    copySeedButton.textContent = "Copiar seed";
    copySeedButton.setAttribute("aria-label", "Copiar seed da imagem selecionada");
    Object.assign(copySeedButton.style, {
        flexShrink: "0", padding: "0 4px", fontSize: "11px", lineHeight: "16px",
        height: "18px", border: "1px solid #777", borderRadius: "3px",
        color: "inherit", background: "transparent", cursor: "pointer",
    });
    const resolutionLabel = document.createElement("div");
    seedRow.append(seedLabel, copySeedButton);
    generationInfo.append(seedRow, resolutionLabel);
    let copySeedTimer = null;
    let copySeedRevision = 0;

    function resetCopySeedFeedback() {
        copySeedRevision++;
        clearTimeout(copySeedTimer);
        copySeedButton.textContent = "Copiar seed";
    }

    for (const eventName of ["pointerdown", "pointermove", "pointerup", "dblclick", "contextmenu", "wheel"]) {
        copySeedButton.addEventListener(eventName, (event) => event.stopPropagation());
    }
    copySeedButton.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        const seeds = Array.isArray(selected?.generation_seeds) ? selected.generation_seeds : [];
        if (!seeds.length) return;
        resetCopySeedFeedback();
        const revision = copySeedRevision;
        // Keep seeds as strings: converting 64-bit seeds to JS Number loses digits.
        const text = seeds.map(String).join(", ");
        try {
            await navigator.clipboard.writeText(text);
            if (revision !== copySeedRevision) return;
            copySeedButton.textContent = "Copiado!";
        } catch (error) {
            if (revision !== copySeedRevision) return;
            copySeedButton.textContent = "Falhou";
            console.warn("[Lyonir Save Image] Could not copy seed", error);
        }
        copySeedTimer = setTimeout(() => {
            if (revision === copySeedRevision) copySeedButton.textContent = "Copiar seed";
        }, 1800);
    });

    function updateGenerationInfo(useLoadedSize = false) {
        resetCopySeedFeedback();
        generationInfo.style.display = selected ? "block" : "none";
        const seeds = Array.isArray(selected?.generation_seeds) ? selected.generation_seeds : [];
        copySeedButton.disabled = !seeds.length;
        copySeedButton.title = seeds.length ? "Copiar seed da imagem selecionada" : "Seed indisponível nesta imagem";
        if (!selected) { seedLabel.textContent = ""; resolutionLabel.textContent = ""; return; }
        const width = Number(selected.width) || (useLoadedSize ? preview.naturalWidth : 0);
        const height = Number(selected.height) || (useLoadedSize ? preview.naturalHeight : 0);
        const seedText = seeds.length ? seeds.join(", ") : "Unavailable";
        const sizeText = width && height ? `${width} × ${height}` : "Unavailable";
        seedLabel.textContent = `Seed: ${seedText}`;
        seedLabel.title = seedLabel.textContent;
        resolutionLabel.textContent = `Resolution: ${sizeText}`;
    }

    root.append(generationInfo, previewWrap, toolbar, thumbs);
    previewWrap.append(preview);

    let history = [];
    let selected = null;
    let thumbSize = BASE_THUMB_SIZE;
    let resizeObserver = null;

    function makeSurfaceTransparent(element) {
        if (!element?.style) return;
        element.style.setProperty("background", "transparent", "important");
        element.style.setProperty("background-color", "transparent", "important");
        element.style.setProperty("border", "none", "important");
        element.style.setProperty("outline", "none", "important");
        element.style.setProperty("box-shadow", "none", "important");
    }

    function syncNodeSurface() {
        for (const surface of [root, previewWrap, preview, toolbar, thumbs]) {
            makeSurfaceTransparent(surface);
        }
        const host = root.parentElement;
        if (host && host !== document.body && host !== document.documentElement) {
            makeSurfaceTransparent(host);
        }
    }

    function currentGallerySize() {
        const width = Math.max(1, Number(node?.size?.[0]) || BASE_NODE_WIDTH);
        const height = Math.max(1, Number(node?.size?.[1]) || BASE_NODE_HEIGHT);
        return { width, height };
    }

    function calculateScale() {
        const { width, height } = currentGallerySize();
        return Math.sqrt((width * height) / (BASE_NODE_WIDTH * BASE_NODE_HEIGHT));
    }

    function syncWidgetBounds() {
        root.style.width = "100%";
        root.style.height = "100%";
        root.style.minWidth = "0";
        root.style.minHeight = "0";
        root.style.maxWidth = "none";
        root.style.maxHeight = "none";
    }

    function syncLayout() {
        syncWidgetBounds();
        syncNodeSurface();

        const scale = Math.max(0.55, calculateScale());
        thumbSize = Math.max(22, Math.round(BASE_THUMB_SIZE * scale));
        const toolbarHeight = Math.max(18, Math.round(18 * Math.min(scale, 1.4)));

        toolbar.style.minHeight = `${toolbarHeight}px`;
        toolbar.style.height = `${toolbarHeight}px`;
        thumbs.style.height = `${thumbSize + 2}px`;
        thumbs.style.minHeight = `${thumbSize + 2}px`;
        thumbs.style.gap = "2px";
        root.style.gap = "2px";

        previewWrap.style.flex = "1 1 0";
        previewWrap.style.width = "100%";
        previewWrap.style.maxWidth = "none";
        previewWrap.style.maxHeight = "none";

        for (const button of thumbs.children) {
            button.style.flexBasis = `${thumbSize}px`;
            button.style.width = `${thumbSize}px`;
            button.style.height = `${thumbSize}px`;
            button.style.background = "transparent";
        }
    }

    function bindWidget(widget) {
        if (!widget) return;
        syncLayout();
    }

    function openSelected() {
        if (!selected) return;
        const url = imageUrl(selected, false);
        if (url) window.open(url, "_blank", "noopener,noreferrer");
    }

    async function copySelected() {
        if (!selected) return;
        try {
            await copyImageToClipboard(imageUrl(selected, false));
        } catch (error) {
            console.warn("[Lyonir Save Image] Copy Image failed", error);
        }
    }

    function saveSelected() {
        if (!selected) return;
        downloadImage(selected);
    }

    async function openMaskEditor(targetNode) {
        if (!selected || !targetNode) return;

        const img = new Image();
        img.src = imageUrl(selected, false);
        try { await img.decode?.(); } catch (_) {}

        const previousImgs = targetNode.imgs;
        const previousIndex = targetNode.imageIndex;
        const previousPreviewType = targetNode.previewMediaType;

        targetNode.imgs = [img];
        targetNode.imageIndex = 0;
        targetNode.previewMediaType = "image";

        try {
            ComfyApp.clipspace_return_node = targetNode;
            if (typeof ComfyApp.open_maskeditor === "function") {
                ComfyApp.open_maskeditor();
            }
        } finally {
            setTimeout(() => {
                targetNode.imgs = previousImgs;
                targetNode.imageIndex = previousIndex;
                targetNode.previewMediaType = previousPreviewType;
            }, 150);
        }
    }

    function showComfyNodeMenu(e) {
        if (!selected) return;
        e.preventDefault();
        e.stopPropagation();
        const canvas = app?.canvas;
        if (!canvas) return;
        try {
            canvas.adjustMouseEvent?.(e);
            canvas.processContextMenu?.(node, e);
        } catch (error) {
            console.warn("[Lyonir Save Image] Could not open ComfyUI context menu", error);
        }
    }

    function selectEntry(entry) {
        selected = entry || null;
        updateGenerationInfo();
        if (!selected) {
            preview.removeAttribute("src");
            preview.style.display = "none";
            renderThumbs();
            return;
        }
        const loadingEntry = selected;
        preview.onload = () => {
            if (selected !== loadingEntry) return;
            preview.style.display = "block";
            updateGenerationInfo(true);
        };
        preview.onerror = () => {
            preview.style.display = "none";
        };
        preview.src = imageUrl(selected);
        renderThumbs();
    }

    function renderThumbs() {
        syncNodeSurface();
        thumbs.replaceChildren();
        for (const entry of history) {
            const button = document.createElement("button");
            button.title = entry.filename || "Saved image";
            Object.assign(button.style, {
                flex: `0 0 ${thumbSize}px`,
                width: `${thumbSize}px`,
                height: `${thumbSize}px`,
                padding: "0",
                borderRadius: "3px",
                overflow: "hidden",
                border: selected?.filename === entry.filename && selected?.subfolder === entry.subfolder
                    ? "2px solid #e3e3e3"
                    : "none",
                background: "transparent",
                cursor: "pointer",
                boxSizing: "border-box",
            });
            const img = document.createElement("img");
            img.draggable = false;
            img.src = imageUrl(entry, false);
            Object.assign(img.style, {
                width: "100%",
                height: "100%",
                maxWidth: "none",
                maxHeight: "none",
                objectFit: "cover",
                display: "block",
                pointerEvents: "none",
                background: "transparent",
            });
            button.append(img);
            button.addEventListener("click", (e) => {
                stopGraphGesture(e);
                selectEntry(entry);
            });
            button.addEventListener("contextmenu", (e) => {
                selectEntry(entry);
                showComfyNodeMenu(e);
            });
            thumbs.append(button);
        }
        syncLayout();
    }

    function setHistory(items, preferCurrent = null) {
        history = Array.isArray(items) ? items.filter(Boolean) : [];
        const current = preferCurrent?.[0];
        const target = current || history[0] || null;
        if (target) {
            const matching = history.find((entry) =>
                entry?.filename === target?.filename && entry?.subfolder === target?.subfolder
            );
            selectEntry(matching || target);
        } else {
            selectEntry(null);
            renderThumbs();
        }
    }

    async function fetchHistory() {
        const historyId = dedupeHistoryIdentity(node);
        const nodeId = node?.id;
        if (nodeId == null || nodeId === -1) return;
        const limit = Math.max(4, Math.min(100, Number(getWidgetValue(node, "history_limit", 18)) || 18));
        const params = new URLSearchParams({ history_id: historyId, limit: String(limit) });
        try {
            const response = await fetch(api.apiURL(`/lyonir/save-image/history?${params.toString()}`), { cache: "no-store" });
            const data = await response.json();
            if (data?.ok && ensureHistoryIdentity(node) === historyId) setHistory(data.history || []);
        } catch (error) {
            console.warn("[Lyonir Save Image] history refresh failed", error);
        }
    }

    function updateFromOutput(output) {
        const items = output?.lyonir_gallery_history;
        const current = output?.lyonir_gallery_current;
        if (Array.isArray(items)) setHistory(items, current);
        else fetchHistory();
    }

    previewWrap.addEventListener("click", (e) => {
        // A normal left click must never open a browser tab. The preview is
        // intentionally passive; explicit image actions live in the ComfyUI
        // right-click menu (and the Open button below).
        stopGraphGesture(e);
    });
    previewWrap.addEventListener("contextmenu", showComfyNodeMenu);
    refreshButton.addEventListener("click", (e) => {
        stopGraphGesture(e);
        fetchHistory();
    });
    openButton.addEventListener("click", (e) => {
        stopGraphGesture(e);
        openSelected();
    });

    for (const target of [root, previewWrap, toolbar, thumbs]) {
        target.addEventListener("pointerdown", stopGraphGesture);
        target.addEventListener("wheel", stopGraphGesture, { passive: true });
    }

    if (globalThis.ResizeObserver) {
        resizeObserver = new ResizeObserver(() => syncLayout());
        resizeObserver.observe(root);
    }

    syncLayout();

    function destroy() {
        resetCopySeedFeedback();
        resizeObserver?.disconnect?.();
        resizeObserver = null;
    }

    return {
        root,
        fetchHistory,
        updateFromOutput,
        syncLayout,
        bindWidget,
        hasImage: () => Boolean(selected),
        openSelected,
        copySelected,
        saveSelected,
        openMaskEditor,
        destroy,
    };
}

app.registerExtension({
    name: "LyonirStudio.SaveImageGallery.Nodes7",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        if (nodeType.prototype.__lyonirSaveImageGalleryPatched) return;
        nodeType.prototype.__lyonirSaveImageGalleryPatched = true;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);
            ensureHistoryIdentity(this);
            const gallery = createGallery(this);
            this.__lyonirSaveImageGallery = gallery;

            const widget = this.addDOMWidget(
                "lyonir_save_image_gallery",
                "lyonir_save_image_gallery",
                gallery.root,
                {
                    serialize: false,
                    hideOnZoom: false,
                    margin: 0,
                    getMinHeight: () => 210,
                    getHeight: () => 280,
                    afterResize: () => gallery.syncLayout(),
                },
            );
            if (widget) {
                widget.serialize = false;
                gallery.bindWidget(widget);
            }

            const natural = this.computeSize?.();
            if (Array.isArray(natural) && natural.length >= 2) {
                this.setSize?.(natural);
            }
            setTimeout(() => gallery.syncLayout(), 0);
        };

        const originalGraphConfigured = nodeType.prototype.onGraphConfigured;
        nodeType.prototype.onGraphConfigured = function () {
            originalGraphConfigured?.apply(this, arguments);
            dedupeHistoryIdentity(this);
            this.properties ??= {};
            if (this.properties.lyonir_gallery_layout !== "3.4.4") {
                const w = Number(this.size?.[0]) || 0;
                const h = Number(this.size?.[1]) || 0;
                const legacyForced = Math.round(w) === 430 && Math.round(h) === 760;
                const runawayHeight = h > 1400;
                if (legacyForced || runawayHeight) {
                    const natural = this.computeSize?.();
                    if (Array.isArray(natural) && natural.length >= 2) this.setSize?.(natural);
                }
                this.properties.lyonir_gallery_layout = "3.4.4";
            }
            setTimeout(() => {
                this.__lyonirSaveImageGallery?.syncLayout();
                this.__lyonirSaveImageGallery?.fetchHistory();
            }, 0);
        };

        const originalClone = nodeType.prototype.clone;
        nodeType.prototype.clone = function () {
            const copy = originalClone?.apply(this, arguments);
            if (copy) ensureHistoryIdentity(copy, true);
            return copy;
        };
        const originalAdded = nodeType.prototype.onAdded;
        nodeType.prototype.onAdded = function () {
            originalAdded?.apply(this, arguments);
            setTimeout(() => dedupeHistoryIdentity(this), 0);
        };

        const originalExtraMenu = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            const inherited = originalExtraMenu?.apply(this, arguments);
            const gallery = this.__lyonirSaveImageGallery;
            const imageItems = gallery?.hasImage?.() ? [
                { content: "Open Image", callback: () => gallery.openSelected() },
                { content: "Copy Image", callback: () => gallery.copySelected() },
                { content: "Save Image", callback: () => gallery.saveSelected() },
                { content: "MaskEditor", callback: () => gallery.openMaskEditor(this) },
            ] : [];

            if (Array.isArray(inherited) && inherited.length) {
                return imageItems.length ? [...imageItems, null, ...inherited] : inherited;
            }
            return imageItems;
        };

        const originalExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalExecuted?.apply(this, arguments);
            this.__lyonirSaveImageGallery?.updateFromOutput(message);
            this.__lyonirSaveImageGallery?.syncLayout();
        };

        const originalRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this.__lyonirSaveImageGallery?.destroy?.();
            originalRemoved?.apply(this, arguments);
        };
    },
});
