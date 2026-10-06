import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { applyTextReplacements } from "/scripts/utils.js";

// ComfyUI production builds expose core frontend exports through window.comfyAPI.
// Do not import the legacy /extensions/core/widgetInputs.js shim: modern ComfyUI
// intentionally warns on that path and may remove it in a future frontend release.
const setWidgetConfig = globalThis?.comfyAPI?.widgetInputs?.setWidgetConfig ?? null;

const NODE_CLASS = "Lyonir_SaveVideo";
const HISTORY_LIMIT = 12;
const BASE_NODE_WIDTH = 320;
const BASE_NODE_HEIGHT = 520;
const BASE_THUMB_SIZE = 32;
const THUMB_MIN_SIZE = 24;
const THUMB_MAX_SIZE = 96;
const THUMB_SLIDER_HEIGHT = 18;
function newHistoryId() {
    try {
        if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    } catch (_) {}
    return `lyonir-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function ensureHistoryIdentity(node, forceNew = false) {
    if (!node) return "";
    node.properties ??= {};
    let value = String(node.properties.lyonir_history_id || "").trim();
    if (forceNew || !value) {
        value = newHistoryId();
        node.properties.lyonir_history_id = value;
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
        String(other?.properties?.lyonir_history_id || "").trim() === current
    );
    return duplicate ? ensureHistoryIdentity(node, true) : current;
}

function chainCallback(object, property, callback) {
    if (!object) return;
    if (property in object && object[property]) {
        const original = object[property];
        object[property] = function () {
            const result = original.apply(this, arguments);
            return callback.apply(this, arguments) ?? result;
        };
    } else {
        object[property] = callback;
    }
}

function stopGraphGesture(event) {
    event.stopPropagation();
}

function mediaUrl(info, mode = "master", cacheBust = false) {
    if (!info) return "";
    let filename = info.filename;
    let subfolder = info.subfolder;
    let type = info.type || "output";
    if (mode === "thumb" && info.thumb_filename) {
        filename = info.thumb_filename;
        subfolder = info.thumb_subfolder;
        type = info.thumb_type || type;
    } else if (mode === "playback" && info.preview_filename) {
        filename = info.preview_filename;
        subfolder = info.preview_subfolder;
        type = info.preview_type || "output";
    }
    if (!filename) return "";
    const params = new URLSearchParams({
        filename: filename || "",
        subfolder: subfolder || "",
        type: type || "output",
    });
    if (cacheBust) params.set("t", String(Date.now()));
    return api.apiURL(`/lyonir/save-video/media?${params.toString()}`);
}

function makeTransparent(element) {
    if (!element?.style) return;
    element.style.setProperty("background", "transparent", "important");
    element.style.setProperty("background-color", "transparent", "important");
    element.style.setProperty("border", "none", "important");
    element.style.setProperty("outline", "none", "important");
    element.style.setProperty("box-shadow", "none", "important");
}

function addDateFormatting(nodeType) {
    chainCallback(nodeType.prototype, "onNodeCreated", function () {
        const widget = this.widgets?.find?.((w) => w.name === "filename_prefix");
        if (!widget) return;
        widget.serializeValue = () => applyTextReplacements(app, widget.value);
    });
}

function addVAEParity(nodeType) {
    chainCallback(nodeType.prototype, "onConnectionsChange", function (contype, slot, isConnected, linkInfo) {
        if (contype !== globalThis.LiteGraph?.INPUT) return;
        const changed = this.inputs?.[slot];
        if (changed?.name !== "vae") return;
        const imagesInput = this.inputs?.find?.((input) => input.name === "images");
        if (!imagesInput) return;
        if (isConnected && linkInfo) {
            if (imagesInput.type === "IMAGE") this.disconnectInput?.(this.inputs.indexOf(imagesInput));
            imagesInput.type = "LATENT";
        } else {
            if (imagesInput.type === "LATENT") this.disconnectInput?.(this.inputs.indexOf(imagesInput));
            imagesInput.type = "IMAGE";
        }
        this.graph?.setDirtyCanvas?.(true, true);
    });
}

function addFormatWidgets(nodeType, nodeData) {
    const formats = nodeData?.input?.required?.format?.[1]?.formats || {};

    function installFormatWidgetManager(node) {
        if (!node || node.__lyonirFormatWidgetManagerInstalled) return;
        const formatWidget = node.widgets?.find?.((widget) => widget.name === "format");
        if (!formatWidget) return;

        node.__lyonirFormatWidgetManagerInstalled = true;
        const formatWidgetIndex = node.widgets.indexOf(formatWidget) + 1;
        let formatWidgetsCount = 0;

        function rebuildFormatWidgets(value) {
            const definitions = formats?.[value] || [];
            const newWidgets = [];

            for (const definition of definitions) {
                if (!Array.isArray(definition) || definition.length < 2) continue;
                let widgetType = definition?.[2]?.widgetType ?? definition[1];
                if (Array.isArray(widgetType)) widgetType = "COMBO";
                const constructor = app.widgets?.[widgetType];
                if (!constructor) {
                    console.warn(`[Lyonir Save Video] Missing widget constructor ${widgetType}`);
                    continue;
                }
                constructor(node, definition[0], definition.slice(1), app);
                const widget = node.widgets.pop();
                if (!widget) continue;
                widget.config = definition.slice(1);
                newWidgets.push(widget);
            }

            const removed = node.widgets.splice(formatWidgetIndex, formatWidgetsCount, ...newWidgets);
            const newNames = new Set(newWidgets.map((widget) => widget.name));
            for (const widget of removed) {
                widget?.onRemove?.();
                if (newNames.has(widget.name)) continue;
                const inputIndex = node.inputs?.findIndex?.((input) => input.name === widget.name) ?? -1;
                if (inputIndex >= 0) node.removeInput?.(inputIndex);
            }

            for (const widget of newWidgets) {
                const existing = node.inputs?.find?.((input) => input.name === widget.name);
                if (existing) {
                    setWidgetConfig?.(existing, widget.config);
                } else {
                    node.addInput?.(widget.name, widget.config[0], { widget: { name: widget.name } });
                    const input = node.inputs?.find?.((item) => item.name === widget.name);
                    if (input) setWidgetConfig?.(input, widget.config);
                }
            }

            formatWidgetsCount = newWidgets.length;
            const natural = node.computeSize?.();
            if (Array.isArray(natural) && natural.length >= 2) {
                node.setSize?.([Math.max(node.size?.[0] || 0, natural[0]), Math.max(node.size?.[1] || 0, natural[1])]);
            }
            node.graph?.setDirtyCanvas?.(true, true);
        }

        node.__lyonirRebuildFormatWidgets = rebuildFormatWidgets;

        const originalCallback = formatWidget.callback;
        formatWidget.callback = function (value) {
            const result = originalCallback?.apply(this, arguments);
            rebuildFormatWidgets(value);
            return result;
        };

        // Build the default format fields for newly-created nodes. During workflow
        // restore, configure() below will rebuild again using the SAVED format
        // before LiteGraph reapplies positional widget values.
        rebuildFormatWidgets(formatWidget.value);
    }

    chainCallback(nodeType.prototype, "onNodeCreated", function () {
        installFormatWidgetManager(this);
    });

    // Critical reload fix (v3.5.11): LiteGraph restores widgets_values by array
    // position. Format-specific VHS widgets (e.g. ProRes `profile`) must therefore
    // exist BEFORE the base configure() consumes the saved array. Otherwise a
    // saved value such as `4444` shifts into Lyonir's `bit_depth` widget.
    if (!nodeType.prototype.__lyonirDynamicConfigureRestoreInstalled) {
        nodeType.prototype.__lyonirDynamicConfigureRestoreInstalled = true;
        const originalConfigure = nodeType.prototype.configure;
        nodeType.prototype.configure = function (info) {
            try {
                installFormatWidgetManager(this);

                let savedFormat = info?.widgets_values_named?.format;
                if (!savedFormat && Array.isArray(info?.widgets_values)) {
                    const formatIndex = this.widgets?.findIndex?.((widget) => widget.name === "format") ?? -1;
                    if (formatIndex >= 0) savedFormat = info.widgets_values[formatIndex];
                }

                if (savedFormat && formats?.[savedFormat]) {
                    this.__lyonirRebuildFormatWidgets?.(savedFormat);
                }
            } catch (error) {
                console.warn("[Lyonir Save Video] pre-configure dynamic widget restore failed", error);
            }

            const result = originalConfigure?.apply(this, arguments);

            // Modern ComfyUI also stores name-addressed values. Re-apply those
            // after base configure as a second guard against future widget-order
            // changes. This intentionally does not invoke callbacks again.
            try {
                const named = info?.widgets_values_named;
                if (named && typeof named === "object") {
                    const savedFormat = named.format;
                    if (savedFormat && formats?.[savedFormat]) {
                        this.__lyonirRebuildFormatWidgets?.(savedFormat);
                    }
                    for (const [name, value] of Object.entries(named)) {
                        const widget = this.widgets?.find?.((item) => item.name === name);
                        if (widget) widget.value = value;
                    }
                }

                // Safety net for older positional-only workflows: if an invalid
                // profile value ever lands in bit_depth, rebuild the saved format
                // once more and replay the positional values against the now-correct
                // widget order.
                const bitDepthWidget = this.widgets?.find?.((item) => item.name === "bit_depth");
                const validBitDepths = new Set(["Auto (format)", "8-bit", "10-bit", "12-bit", "16-bit"]);
                if (bitDepthWidget && !validBitDepths.has(String(bitDepthWidget.value))) {
                    let savedFormat = info?.widgets_values_named?.format;
                    if (!savedFormat && Array.isArray(info?.widgets_values)) {
                        const formatIndex = this.widgets?.findIndex?.((widget) => widget.name === "format") ?? -1;
                        if (formatIndex >= 0) savedFormat = info.widgets_values[formatIndex];
                    }
                    if (savedFormat && formats?.[savedFormat]) {
                        this.__lyonirRebuildFormatWidgets?.(savedFormat);
                        if (Array.isArray(info?.widgets_values)) {
                            const serializableWidgets = (this.widgets || []).filter((widget) => widget?.serialize !== false);
                            for (let i = 0; i < info.widgets_values.length && i < serializableWidgets.length; i++) {
                                serializableWidgets[i].value = info.widgets_values[i];
                            }
                        }
                    }
                }
            } catch (error) {
                console.warn("[Lyonir Save Video] post-configure named widget restore failed", error);
            }

            // History identity is stored only in node.properties. It is never a
            // visible widget, but remains serialized with the workflow.
            try { ensureHistoryIdentity(this); } catch (_) {}
            return result;
        };
    }
}

function createGallery(node) {
    const root = document.createElement("div");
    Object.assign(root.style, {
        width: "100%",
        height: "100%",
        minWidth: "0",
        minHeight: "0",
        display: "block",
        padding: "0",
        boxSizing: "border-box",
        overflow: "hidden",
        userSelect: "none",
    });

    const previewWrap = document.createElement("div");
    // Participate in VideoHelperSuite's native preview ecosystem. VHS Sync Preview
    // scans .vhs_preview containers, so using the same class makes sync work both
    // ways: VHS -> Lyonir and Lyonir -> VHS.
    previewWrap.className = "vhs_preview lyonir_save_video_preview";
    Object.assign(previewWrap.style, {
        position: "relative",
        width: "100%",
        height: "auto",
        minHeight: "0",
        overflow: "hidden",
        boxSizing: "border-box",
        margin: "0",
        padding: "0",
    });

    const video = document.createElement("video");
    video.controls = false;
    video.loop = true;
    video.muted = true;
    video.autoplay = true;
    video.className = "VHS_loopedvideo";
    video.playsInline = true;
    video.preload = "metadata";
    video.dataset.lyonirSaveVideo = "1";
    Object.assign(video.style, {
        position: "relative",
        width: "100%",
        height: "auto",
        maxWidth: "100%",
        objectFit: "contain",
        display: "none",
        cursor: "default",
        margin: "0",
        padding: "0",
    });

    // Match VideoHelperSuite: audio is always muted when the pointer is not over
    // the video. The user's Mute/Unmute Preview preference only takes effect
    // while hovering the preview.
    let previewMutedPreference = false;
    let previewPointerInside = false;
    try {
        const setting = app?.ui?.settings?.getSettingValue?.("VHS.DefaultMute");
        if (typeof setting === "boolean") previewMutedPreference = setting;
    } catch (_) {}
    video.muted = true;
    video.addEventListener("mouseenter", () => {
        previewPointerInside = true;
        video.muted = previewMutedPreference;
    });
    video.addEventListener("mouseleave", () => {
        previewPointerInside = false;
        video.muted = true;
    });

    const image = document.createElement("img");
    image.draggable = false;
    Object.assign(image.style, {
        position: "relative",
        width: "100%",
        height: "auto",
        maxWidth: "100%",
        objectFit: "contain",
        display: "none",
        margin: "0",
        padding: "0",
    });

    video.addEventListener("loadedmetadata", () => {
        updateGenerationInfo(true);
        if (video.videoWidth > 0 && video.videoHeight > 0) {
            setPreviewAspectRatio(video.videoWidth / video.videoHeight, true);
        }
    });

    image.addEventListener("load", () => {
        updateGenerationInfo(true);
        if (image.naturalWidth > 0 && image.naturalHeight > 0) {
            setPreviewAspectRatio(image.naturalWidth / image.naturalHeight, true);
        }
    });

    const placeholder = document.createElement("div");
    Object.assign(placeholder.style, {
        width: "100%",
        height: "0",
        display: "block",
        pointerEvents: "none",
        margin: "0",
        padding: "0",
    });

    previewWrap.append(video, image, placeholder);

    const historyStrip = document.createElement("div");
    Object.assign(historyStrip.style, {
        width: "100%",
        flex: "0 0 auto",
        display: "flex",
        alignItems: "center",
        gap: "3px",
        overflowX: "auto",
        overflowY: "hidden",
        padding: "1px 0 2px",
        boxSizing: "border-box",
        scrollbarWidth: "thin",
    });

    const thumbControl = document.createElement("div");
    Object.assign(thumbControl.style, {
        width: "100%",
        height: `${THUMB_SLIDER_HEIGHT}px`,
        minHeight: `${THUMB_SLIDER_HEIGHT}px`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "0",
        margin: "0",
        boxSizing: "border-box",
        overflow: "hidden",
    });

    const thumbSlider = document.createElement("input");
    thumbSlider.type = "range";
    thumbSlider.min = String(THUMB_MIN_SIZE);
    thumbSlider.max = String(THUMB_MAX_SIZE);
    thumbSlider.step = "2";
    thumbSlider.title = "Thumbnail size";
    thumbSlider.setAttribute("aria-label", "Thumbnail size");
    Object.assign(thumbSlider.style, {
        width: "92px",
        maxWidth: "42%",
        height: "14px",
        margin: "0",
        padding: "0",
        cursor: "ew-resize",
        accentColor: "#e3e3e3",
        opacity: "0.82",
    });
    thumbControl.append(thumbSlider);

    const generationInfo = document.createElement("div");
    generationInfo.dataset.lyonirGenerationInfo = "1";
    Object.assign(generationInfo.style, {
        position: "relative", width: "100%", height: "40px",
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
    copySeedButton.setAttribute("aria-label", "Copiar seed do vídeo selecionado");
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
            console.warn("[Lyonir Save Video] Could not copy seed", error);
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
        copySeedButton.title = seeds.length ? "Copiar seed do vídeo selecionado" : "Seed indisponível neste vídeo";
        if (!selected) { seedLabel.textContent = ""; resolutionLabel.textContent = ""; return; }
        const width = Number(selected.width) || (useLoadedSize ? (selected.is_image ? image.naturalWidth : video.videoWidth) : 0);
        const height = Number(selected.height) || (useLoadedSize ? (selected.is_image ? image.naturalHeight : video.videoHeight) : 0);
        const seedText = seeds.length ? seeds.join(", ") : "Unavailable";
        const sizeText = width && height ? `${width} × ${height}` : "Unavailable";
        seedLabel.textContent = `Seed: ${seedText}`;
        seedLabel.title = seedLabel.textContent;
        resolutionLabel.textContent = `Resolution: ${sizeText}`;
    }

    root.append(generationInfo, previewWrap, historyStrip, thumbControl);

    node.properties ??= {};
    let history = [];
    let selected = null;
    let thumbSize = Math.max(THUMB_MIN_SIZE, Math.min(THUMB_MAX_SIZE, Number(node.properties.lyonir_thumbnail_size) || BASE_THUMB_SIZE));
    thumbSlider.value = String(thumbSize);
    let resizeObserver = null;
    let hiddenPreview = false;
    let previewAspectRatio = null;

    function syncSurface() {
        for (const element of [root, previewWrap, video, image, placeholder, historyStrip, thumbControl]) makeTransparent(element);
        const host = root.parentElement;
        if (host && host !== document.body && host !== document.documentElement) makeTransparent(host);
    }

    function currentScale() {
        const width = Math.max(1, Number(node?.size?.[0]) || BASE_NODE_WIDTH);
        return Math.max(0.75, width / BASE_NODE_WIDTH);
    }

    function selectedAspectRatio() {
        if (Number.isFinite(previewAspectRatio) && previewAspectRatio > 0) return previewAspectRatio;
        const width = Number(selected?.width) || 0;
        const height = Number(selected?.height) || 0;
        if (width > 0 && height > 0) return width / height;
        return null;
    }

    function historyHeight() {
        const strip = history.length ? thumbSize + 5 : 0;
        return strip + THUMB_SLIDER_HEIGHT;
    }

    // Match VideoHelperSuite's Video Combine sizing model: the preview height is
    // derived from the current node WIDTH and the media aspect ratio. This makes
    // the actual video grow proportionally when the user widens the node instead
    // of leaving a fixed-height preview floating in empty node space.
    function computeWidgetSize(width) {
        const widgetWidth = Math.max(1, Number(width) || Number(node?.size?.[0]) || BASE_NODE_WIDTH);
        const ratio = selectedAspectRatio();
        const stripHeight = historyHeight() + (selected ? 40 : 0);
        if (hiddenPreview) return [widgetWidth, stripHeight || -4];
        if (!selected || !ratio) return [widgetWidth, stripHeight || -4];

        const nodeWidth = Math.max(1, Number(node?.size?.[0]) || widgetWidth);
        let previewHeight = (nodeWidth - 20) / ratio + 10;
        if (!(previewHeight > 0)) previewHeight = 0;
        // Same width-driven sizing model as VHS. The history strip is deliberately
        // tiny and added underneath; it never competes with the main preview.
        return [widgetWidth, previewHeight + stripHeight];
    }

    function fitNodeHeightToPreview() {
        try {
            const computed = node?.computeSize?.([node?.size?.[0], node?.size?.[1]]);
            if (Array.isArray(computed) && computed.length >= 2 && computed[1] > 0) {
                node.setSize?.([node.size[0], computed[1]]);
            }
            node?.graph?.setDirtyCanvas?.(true, true);
        } catch (error) {
            console.warn("[Lyonir Save Video] proportional preview fit failed", error);
        }
    }

    function setPreviewAspectRatio(value, shouldFit = true) {
        const ratio = Number(value);
        if (!(ratio > 0) || !Number.isFinite(ratio)) return;
        const changed = !previewAspectRatio || Math.abs(previewAspectRatio - ratio) > 0.0001;
        previewAspectRatio = ratio;
        syncLayout();
        if (changed && shouldFit) fitNodeHeightToPreview();
    }

    function syncLayout() {
        syncSurface();
        root.style.width = "100%";
        root.style.height = "auto";
        // Thumbnail scale is user-controlled. It is intentionally independent of
        // node width so resizing the node continues to behave exactly like v3.5.7.
        thumbSize = Math.max(THUMB_MIN_SIZE, Math.min(THUMB_MAX_SIZE, Number(thumbSlider.value) || BASE_THUMB_SIZE));
        historyStrip.style.display = history.length ? "flex" : "none";
        historyStrip.style.height = history.length ? `${thumbSize + 3}px` : "0px";
        historyStrip.style.minHeight = history.length ? `${thumbSize + 3}px` : "0px";
        previewWrap.style.display = hiddenPreview ? "none" : "block";
        previewWrap.style.height = hiddenPreview ? "0" : "auto";
        previewWrap.style.minHeight = "0";
        for (const button of historyStrip.children) {
            button.style.width = `${thumbSize}px`;
            button.style.height = `${thumbSize}px`;
            button.style.flexBasis = `${thumbSize}px`;
        }
    }

    function pauseCurrent() {
        try { video.pause(); } catch (_) {}
    }

    function openSelected() {
        const url = mediaUrl(selected, "master", false);
        if (url) window.open(url, "_blank", "noopener,noreferrer");
    }

    function saveSelected() {
        const url = mediaUrl(selected, "master", false);
        if (!url) return;
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = selected?.filename || "video";
        anchor.style.display = "none";
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
    }

    async function copyOutputPath() {
        if (!selected?.fullpath) return;
        try {
            await navigator.clipboard.writeText(selected.fullpath);
        } catch (error) {
            console.warn("[Lyonir Save Video] could not copy output filepath", error);
        }
    }

    function saveWorkflowImage() {
        if (!selected?.workflow_filename) return;
        const params = new URLSearchParams({
            filename: selected.workflow_filename,
            subfolder: selected.workflow_subfolder || "",
            type: selected.workflow_type || selected.type || "output",
        });
        const anchor = document.createElement("a");
        anchor.href = api.apiURL(`/lyonir/save-video/media?${params.toString()}`);
        anchor.download = selected.workflow_filename;
        anchor.style.display = "none";
        document.body.append(anchor);
        anchor.click();
        anchor.remove();
    }

    function syncAllPreviews() {
        // Same contract used by VideoHelperSuite's own "Sync preview": restart
        // every media element inside a .vhs_preview container. Since the Lyonir
        // preview itself carries that class, either node can sync the other.
        const seen = new Set();
        for (const container of document.getElementsByClassName("vhs_preview")) {
            for (const child of container.children) {
                if (child.tagName === "VIDEO") {
                    if (seen.has(child)) continue;
                    seen.add(child);
                    try { child.currentTime = 0; } catch (_) {}
                } else if (child.tagName === "IMG" && child.src) {
                    try { child.src = child.src; } catch (_) {}
                }
            }
        }
        // Compatibility fallback for an older Lyonir preview that may still be
        // mounted in a workflow tab before a full page refresh.
        for (const element of document.querySelectorAll('video[data-lyonir-save-video="1"]')) {
            if (seen.has(element)) continue;
            try { element.currentTime = 0; } catch (_) {}
        }
    }

    function metadataLabel() {
        if (!selected) return "";
        const width = Number(selected.width) || Number(video.videoWidth) || Number(image.naturalWidth) || 0;
        const height = Number(selected.height) || Number(video.videoHeight) || Number(image.naturalHeight) || 0;
        const fps = Number(selected.frame_rate) || 0;
        let frames = Number(selected.frame_count) || 0;
        if (!frames && selected.duration && fps) frames = Math.round(Number(selected.duration) * fps);
        const parts = [];
        if (width && height) parts.push(`${width}x${height}`);
        if (fps) parts.push(`@${Number.isInteger(fps) ? fps : fps.toFixed(2)}fps`);
        if (frames) parts.push(`${frames}frames`);
        return parts.join("");
    }

    function menuBefore() {
        if (!selected) return [];
        const items = [];
        const meta = metadataLabel();
        if (meta) items.push({ content: meta, disabled: true });
        items.push(
            { content: "Open preview", callback: openSelected },
            { content: "Save preview", callback: saveSelected },
        );
        return items;
    }

    function menuAfter() {
        if (!selected) return [];
        const items = [];
        if (selected?.fullpath) items.push({ content: "Copy output filepath", callback: copyOutputPath });
        if (selected?.workflow_filename) items.push({ content: "Save workflow image", callback: saveWorkflowImage });
        if (!selected?.is_image) {
            items.push(
                { content: video.paused ? "Resume preview" : "Pause preview", callback: () => video.paused ? video.play().catch(() => {}) : video.pause() },
                { content: hiddenPreview ? "Show preview" : "Hide preview", callback: () => { hiddenPreview = !hiddenPreview; syncLayout(); } },
                { content: "Sync preview", callback: syncAllPreviews },
                {
                    content: previewMutedPreference ? "Unmute Preview" : "Mute Preview",
                    callback: () => {
                        previewMutedPreference = !previewMutedPreference;
                        // Outside hover it remains muted by design, exactly like VHS.
                        video.muted = previewPointerInside ? previewMutedPreference : true;
                    },
                },
            );
        }
        return items;
    }

    // Exactly the same bridge used by VideoHelperSuite previews: the DOM preview
    // forwards the context-menu event to ComfyUI's canvas so the *real* node menu
    // appears, including rgthree/Manager/standard node actions.
    function openNativeNodeMenu(event) {
        if (!selected) return;
        event.preventDefault();
        try {
            if (typeof app?.canvas?._mousedown_callback === "function") {
                return app.canvas._mousedown_callback(event);
            }
            app?.canvas?.adjustMouseEvent?.(event);
            return app?.canvas?.processContextMenu?.(node, event);
        } catch (error) {
            console.warn("[Lyonir Save Video] native context menu failed", error);
        }
    }

    function renderHistory() {
        historyStrip.replaceChildren();
        for (const entry of history) {
            const button = document.createElement("button");
            const active = selected?.filename === entry.filename && selected?.subfolder === entry.subfolder && selected?.type === entry.type;
            button.title = entry.filename || "Saved video";
            Object.assign(button.style, {
                flex: `0 0 ${thumbSize}px`,
                width: `${thumbSize}px`,
                height: `${thumbSize}px`,
                padding: "0",
                overflow: "hidden",
                borderRadius: "3px",
                border: active ? "2px solid #e3e3e3" : "1px solid rgba(227,227,227,0.18)",
                background: "transparent",
                cursor: "pointer",
                boxSizing: "border-box",
            });
            const thumb = document.createElement("img");
            thumb.draggable = false;
            thumb.src = mediaUrl(entry, "thumb", false) || mediaUrl(entry, "playback", false);
            Object.assign(thumb.style, {
                width: "100%",
                height: "100%",
                objectFit: "cover",
                display: "block",
                pointerEvents: "none",
            });
            button.append(thumb);
            button.addEventListener("click", (e) => { stopGraphGesture(e); selectEntry(entry); });
            button.addEventListener("dblclick", (e) => { stopGraphGesture(e); selected = entry; openSelected(); });
            button.addEventListener("contextmenu", (e) => {
                selected = entry;
                selectEntry(entry);
                openNativeNodeMenu(e);
            });
            historyStrip.append(button);
        }
        syncLayout();
    }

    function selectEntry(entry) {
        pauseCurrent();
        selected = entry || null;
        updateGenerationInfo();
        previewAspectRatio = null;
        if (selected?.width && selected?.height) {
            const ratio = Number(selected.width) / Number(selected.height);
            if (ratio > 0 && Number.isFinite(ratio)) previewAspectRatio = ratio;
        }
        video.removeAttribute("src");
        video.removeAttribute("poster");
        image.removeAttribute("src");
        video.style.display = "none";
        image.style.display = "none";
        placeholder.style.display = selected ? "none" : "block";

        if (selected) {
            if (selected.is_image) {
                image.src = mediaUrl(selected, "master", true);
                image.style.display = "block";
            } else {
                const poster = mediaUrl(selected, "thumb", false);
                if (poster) video.poster = poster;
                video.src = mediaUrl(selected, "playback", true);
                video.style.display = "block";
                try { video.load(); } catch (_) {}
            }
        }
        renderHistory();
    }

    function setHistory(items, preferCurrent = null) {
        history = Array.isArray(items) ? items.filter(Boolean) : [];
        const current = Array.isArray(preferCurrent) ? preferCurrent[0] : preferCurrent;
        const target = current || history[0] || null;
        if (!target) return selectEntry(null);
        const match = history.find((entry) =>
            entry.filename === target.filename && entry.subfolder === target.subfolder && entry.type === target.type
        );
        selectEntry(match || target);
    }

    async function fetchHistory() {
        const historyId = ensureHistoryIdentity(node);
        if (!historyId) return;
        const params = new URLSearchParams({ history_id: historyId, limit: String(HISTORY_LIMIT) });
        try {
            const response = await fetch(api.apiURL(`/lyonir/save-video/history?${params.toString()}`), { cache: "no-store" });
            const data = await response.json();
            if (data?.ok) setHistory(data.history || []);
        } catch (error) {
            console.warn("[Lyonir Save Video] history refresh failed", error);
        }
    }

    function updateFromOutput(message) {
        const items = message?.lyonir_video_gallery_history;
        const current = message?.lyonir_video_gallery_current;
        if (Array.isArray(items)) {
            setHistory(items, current);
            return;
        }
        fetchHistory();
    }

    previewWrap.addEventListener("contextmenu", openNativeNodeMenu, true);
    previewWrap.addEventListener("pointerdown", (event) => {
        if (!selected) return;
        event.preventDefault();
        return app?.canvas?._mousedown_callback?.(event);
    }, true);
    previewWrap.addEventListener("mousewheel", (event) => {
        if (!selected) return;
        event.preventDefault();
        return app?.canvas?._mousewheel_callback?.(event);
    }, true);
    previewWrap.addEventListener("pointermove", (event) => {
        if (!selected) return;
        event.preventDefault();
        return app?.canvas?._mousemove_callback?.(event);
    }, true);
    previewWrap.addEventListener("pointerup", (event) => {
        if (!selected) return;
        event.preventDefault();
        return app?.canvas?._mouseup_callback?.(event);
    }, true);
    historyStrip.addEventListener("wheel", (event) => event.stopPropagation(), { passive: true });

    for (const eventName of ["pointerdown", "pointermove", "pointerup", "click", "dblclick", "contextmenu", "wheel"]) {
        thumbSlider.addEventListener(eventName, (event) => event.stopPropagation());
    }
    thumbSlider.addEventListener("input", () => {
        thumbSize = Math.max(THUMB_MIN_SIZE, Math.min(THUMB_MAX_SIZE, Number(thumbSlider.value) || BASE_THUMB_SIZE));
        node.properties ??= {};
        node.properties.lyonir_thumbnail_size = thumbSize;
        syncLayout();
        fitNodeHeightToPreview();
    });

    if (globalThis.ResizeObserver) {
        resizeObserver = new ResizeObserver(syncLayout);
        resizeObserver.observe(root);
    }
    syncLayout();

    function destroy() {
        resetCopySeedFeedback();
        pauseCurrent();
        video.removeAttribute("src");
        image.removeAttribute("src");
        try { video.load(); } catch (_) {}
        resizeObserver?.disconnect?.();
        resizeObserver = null;
    }

    return {
        root,
        fetchHistory,
        updateFromOutput,
        syncLayout,
        computeWidgetSize,
        fitNodeHeightToPreview,
        destroy,
        hasSelection: () => !!selected,
        menuBefore,
        menuAfter,
    };
}

app.registerExtension({
    name: "LyonirStudio.SaveVideo.VideoCombineHistoryResponsive",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        if (nodeType.prototype.__lyonirVideoCombineHistoryStable) return;
        nodeType.prototype.__lyonirVideoCombineHistoryStable = true;

        addDateFormatting(nodeType);
        addFormatWidgets(nodeType, nodeData);
        addVAEParity(nodeType);

        chainCallback(nodeType.prototype, "onNodeCreated", function () {
            // Never allow preview/history UI to abort node creation. This was the
            // regression in 3.5.0: an exception inside preview initialization made
            // the Library item visible but clicking it failed to insert the node.
            try {
                ensureHistoryIdentity(this);
                const gallery = createGallery(this);
                this.__lyonirSaveVideoGallery = gallery;
                const widget = this.addDOMWidget(
                    "videopreview",
                    "videopreview",
                    gallery.root,
                    {
                        serialize: false,
                        hideOnZoom: false,
                        margin: 0,
                        afterResize: () => gallery.syncLayout(),
                    },
                );
                if (widget) {
                    widget.serialize = false;
                    // Same core behavior as VHS Video Combine: the preview widget's
                    // height follows node width / media aspect ratio. The history
                    // strip is simply added underneath that proportional preview.
                    widget.computeSize = function (width) {
                        const size = gallery.computeWidgetSize(width);
                        this.computedHeight = size[1] > 0 ? size[1] + 10 : 0;
                        return size;
                    };
                }

                this.properties ??= {};
                this.properties.lyonir_video_combine_parity = "3.5.13";
                const natural = this.computeSize?.();
                if (Array.isArray(natural) && natural.length >= 2) this.setSize?.(natural);
                setTimeout(() => {
                    gallery.syncLayout();
                    gallery.fitNodeHeightToPreview?.();
                }, 0);
            } catch (error) {
                console.error("[Lyonir Save Video] preview/history initialization failed; node kept usable", error);
                this.__lyonirSaveVideoGallery = null;
            }
        });

        // Add VHS-style preview commands to ComfyUI's native node context menu.
        // We mutate the provided options array rather than replacing the menu, so
        // normal ComfyUI and rgthree items remain exactly available.
        chainCallback(nodeType.prototype, "getExtraMenuOptions", function (canvas, options) {
            const gallery = this.__lyonirSaveVideoGallery;
            if (!gallery?.hasSelection?.() || !Array.isArray(options)) return;
            const before = gallery.menuBefore?.() || [];
            const after = gallery.menuAfter?.() || [];
            if (before.length) options.unshift(...before);
            if (after.length) {
                let insertAt = options.findIndex((item) => item?.content === "Reload Node");
                if (insertAt < 0) insertAt = options.length;
                options.splice(insertAt, 0, ...after, null);
            }
        });

        function proportionalHeightForWidth(node, width) {
            const targetWidth = Math.max(BASE_NODE_WIDTH, Number(width) || BASE_NODE_WIDTH);
            // computeSize asks every widget (including videopreview) for its natural
            // height. The preview widget itself derives media height from node width.
            const previousWidth = node.size?.[0];
            if (node.size) node.size[0] = targetWidth;
            let computed = null;
            try {
                computed = node.computeSize?.([targetWidth, Number(node?.size?.[1]) || BASE_NODE_HEIGHT]);
            } finally {
                if (node.size && previousWidth != null) node.size[0] = previousWidth;
            }
            const height = Array.isArray(computed) ? Number(computed[1]) : 0;
            return height > 0 ? height : Math.max(BASE_NODE_HEIGHT, Number(node?.size?.[1]) || BASE_NODE_HEIGHT);
        }

        chainCallback(nodeType.prototype, "onNodeCreated", function () {
            if (this.__lyonirProportionalSetSizeInstalled) return;
            this.__lyonirProportionalSetSizeInstalled = true;
            const originalSetSize = this.setSize?.bind(this);
            if (!originalSetSize) return;

            this.setSize = (requested) => {
                if (!requested) return;
                const width = Math.max(BASE_NODE_WIDTH, Number(requested[0]) || Number(this.size?.[0]) || BASE_NODE_WIDTH);
                if (this.__lyonirProportionalSetSizeGuard) {
                    return originalSetSize([width, Number(requested[1]) || Number(this.size?.[1]) || BASE_NODE_HEIGHT]);
                }
                this.__lyonirProportionalSetSizeGuard = true;
                try {
                    // First commit width so the Video-Combine-style preview can compute
                    // against the new horizontal size, then immediately normalize height.
                    originalSetSize([width, Number(requested[1]) || Number(this.size?.[1]) || BASE_NODE_HEIGHT]);
                    const height = proportionalHeightForWidth(this, width);
                    originalSetSize([width, height]);
                    this.__lyonirSaveVideoGallery?.syncLayout?.();
                    this.graph?.setDirtyCanvas?.(true, true);
                    return this.size;
                } finally {
                    this.__lyonirProportionalSetSizeGuard = false;
                }
            };
        });

        // During an active LiteGraph resize gesture, mutate the candidate size itself.
        // This makes horizontal dragging visibly grow downward in the same gesture,
        // rather than only correcting after the user releases the mouse.
        chainCallback(nodeType.prototype, "onResize", function (size) {
            if (!size || this.__lyonirProportionalSetSizeGuard) return;
            const width = Math.max(BASE_NODE_WIDTH, Number(size[0]) || Number(this.size?.[0]) || BASE_NODE_WIDTH);
            size[0] = width;
            size[1] = proportionalHeightForWidth(this, width);
            this.__lyonirSaveVideoGallery?.syncLayout?.();
        });

        chainCallback(nodeType.prototype, "onGraphConfigured", function () {
            setTimeout(() => {
                // Clones must not share a gallery identity. On normal reload the
                // serialized UUID is unique and remains unchanged.
                dedupeHistoryIdentity(this);
                this.__lyonirSaveVideoGallery?.syncLayout?.();
                const width = Math.max(BASE_NODE_WIDTH, Number(this.size?.[0]) || BASE_NODE_WIDTH);
                this.setSize?.([width, this.size?.[1]]);
                this.__lyonirSaveVideoGallery?.fetchHistory?.();
            }, 0);
        });

        chainCallback(nodeType.prototype, "onAdded", function () {
            setTimeout(() => dedupeHistoryIdentity(this), 0);
        });

        chainCallback(nodeType.prototype, "onExecuted", function (message) {
            this.__lyonirSaveVideoGallery?.updateFromOutput?.(message);
            this.__lyonirSaveVideoGallery?.syncLayout?.();
        });

        chainCallback(nodeType.prototype, "onRemoved", function () {
            this.__lyonirSaveVideoGallery?.destroy?.();
        });
    },
});
