import { app } from "/scripts/app.js";

const NODE_CLASS = "Lyonir_Sampler";
const DESIRED_ORDER = [
    "model",
    "conditioning",
    "negative",
    "latent",
    "video_vae",
    "audio_vae",
    "target_width",
    "target_height",
];

function slotName(slot) {
    // Prefer the declared socket name; reordering must never confuse SIGMAS
    // with an unrelated widget-linked input.
    if (slot?.name === "sigmas") return "sigmas";
    return slot?.widget?.name || slot?.name || "";
}

function getLink(graph, linkId) {
    if (!graph || linkId == null) return null;

    const stores = [graph.links, graph._links];
    for (const store of stores) {
        if (!store) continue;
        if (store instanceof Map) {
            const link = store.get(linkId);
            if (link) return link;
        } else if (Array.isArray(store)) {
            const direct = store[linkId];
            if (direct) return direct;
            const found = store.find((item) => item?.id === linkId || item?.[0] === linkId);
            if (found) return found;
        } else if (typeof store === "object") {
            const link = store[linkId] ?? store[String(linkId)];
            if (link) return link;
        }
    }
    return null;
}

function setTargetSlot(link, targetSlot) {
    if (!link) return;
    if (Array.isArray(link)) {
        // Serialized/legacy link: [id, origin_id, origin_slot, target_id, target_slot, type]
        if (link.length > 4) link[4] = targetSlot;
        return;
    }
    if ("target_slot" in link) link.target_slot = targetSlot;
}

function reorderSamplerInputs(node) {
    if (!Array.isArray(node?.inputs) || node.inputs.length < 2) return;

    const original = [...node.inputs];
    const rank = new Map(DESIRED_ORDER.map((name, index) => [name, index]));
    const known = [];
    const unknown = [];

    for (let index = 0; index < original.length; index++) {
        const input = original[index];
        const name = slotName(input);
        const desired = rank.get(name);
        if (desired == null) unknown.push({ input, index });
        else known.push({ input, index, desired });
    }

    known.sort((a, b) => a.desired - b.desired);
    unknown.sort((a, b) => a.index - b.index);
    const reordered = [...known.map((x) => x.input), ...unknown.map((x) => x.input)];

    const beforeNames = original.map(slotName);
    const afterNames = reordered.map(slotName);
    if (beforeNames.length === afterNames.length && beforeNames.every((name, i) => name === afterNames[i])) {
        return;
    }

    // Keep existing connections attached to the same named sockets when a loaded
    // workflow is re-laid out. Execution uses socket names, while legacy graph
    // links also retain a numeric target_slot that must follow the visual move.
    reordered.forEach((input, newIndex) => {
        if (input?.link == null) return;
        setTargetSlot(getLink(node.graph, input.link), newIndex);
    });

    node.inputs.splice(0, node.inputs.length, ...reordered);
    node.setDirtyCanvas?.(true, true);
}

// Keep the backend input schema unchanged. SIGMAS must remain a *native input*
// (no `input.widget` association): recent ComfyUI frontends delete socket
// descriptors that reference a widget they cannot find. The old custom anchor
// was not registered with the Vue widget store, so Manual Sigmas lost its port.
const STEP_WIDGETS = ["steps", "scheduler", "denoise"];
const LAYOUT_VERSION = 5;
const SIGMA_WIDGET_NAME = "sigmas";
const SIGMA_ROW_HEIGHT = 24;

// IMPORTANT: ComfyUI's Vue nodes draw plain inputs in the TOP sockets list.
// Changing slot.pos or getConnectionPos does not relocate that DOM row.
// To place SIGMAS beneath Sampling Mode, it must be a real widget-backed input,
// attached to a registered and ordered, non-serialized converted-widget row.
// This works with both the native/Vue widget grid and legacy LiteGraph canvas.

function setSamplerWidgetHidden(widget, hidden) {
    if (!widget) return;
    const state = widget.__lyonirVisibilityState || (widget.__lyonirVisibilityState = {
        computeSize: widget.computeSize,
    });
    widget.hidden = hidden;
    widget.options ||= {};
    widget.options.hidden = hidden;
    if (hidden) {
        widget.computeSize = () => [0, -4];
    } else if (state.computeSize === undefined) {
        delete widget.computeSize;
    } else {
        widget.computeSize = state.computeSize;
    }
    for (const el of [widget.element, widget.inputEl]) {
        if (el?.style) el.style.display = hidden ? "none" : "";
    }
}

function ensureSigmaRowWidget(node) {
    let row = node.widgets?.find((widget) => widget.name === SIGMA_WIDGET_NAME);
    if (row) return row;
    // Register the placeholder via LiteGraph's widget API: merely setting
    // input.widget to a made-up name breaks ComfyUI's reactive Vue widgets.
    const definition = {
        name: SIGMA_WIDGET_NAME,
        label: "sigmas",
        type: "converted-widget",
        value: "",
        serialize: false, // Never shift workflow/clipboard widget positions.
        options: { serialize: false },
        computeSize: () => [0, SIGMA_ROW_HEIGHT],
        draw(ctx, node, width, y, height, lowQuality) {
            // Native/legacy canvas needs its own label. Vue renders the
            // InputSlot label automatically in this converted-widget row.
            if (!ctx || lowQuality) return;
            ctx.save?.();
            ctx.textAlign = "left";
            ctx.fillStyle = "#bdbdbd";
            ctx.font = "12px sans-serif";
            ctx.fillText?.("sigmas", 26, y + 17);
            ctx.restore?.();
        },
    };
    if (typeof node.addCustomWidget === "function") {
        row = node.addCustomWidget(definition);
    } else {
        // Fallback for older LiteGraph versions: keep a genuine widget entry.
        row = definition;
        node.widgets ||= [];
        node.widgets.push(row);
    }
    row.serialize = false;
    return row;
}

function arrangeSamplerWidgets(node) {
    if (!Array.isArray(node?.widgets)) return;
    if (!node.__lyonirOriginalWidgetOrder) {
        node.__lyonirOriginalWidgetOrder = node.widgets.map((w) => w.name)
            .filter((name) => name !== SIGMA_WIDGET_NAME);
    }
    const mode = node.widgets.find((w) => w.name === "sampling_mode");
    if (!mode) return;
    const anchor = ensureSigmaRowWidget(node);
    const stepWidgets = STEP_WIDGETS.map((name) => node.widgets.find((w) => w.name === name)).filter(Boolean);
    const moving = new Set([mode, anchor, ...stepWidgets]);
    const remaining = node.widgets.filter((w) => !moving.has(w));
    const noiseIndex = remaining.findIndex((w) => w.name === "noise");
    const insertion = noiseIndex >= 0 ? noiseIndex + 1 : 0;
    remaining.splice(insertion, 0, mode, anchor, ...stepWidgets);
    node.widgets.splice(0, node.widgets.length, ...remaining);
}

function getSigmaInputIndex(node) {
    return node.inputs?.findIndex((slot) => slotName(slot) === "sigmas") ?? -1;
}

function removeSigmaInput(node) {
    const index = getSigmaInputIndex(node);
    if (index < 0) return;
    const input = node.inputs[index];
    if (input?.link != null) {
        // Remember the origin during mode changes (without saving a broken
        // link into Basic Scheduler workflows).
        const link = getLink(node.graph, input.link);
        if (link && !Array.isArray(link)) {
            node.__lyonirStashedSigmaOrigin = { nodeId: link.origin_id, slot: link.origin_slot };
        } else if (Array.isArray(link)) {
            node.__lyonirStashedSigmaOrigin = { nodeId: link[1], slot: link[2] };
        }
        node.disconnectInput?.(index);
    }
    // Use LiteGraph's public removal API when possible. Raw array splicing
    // bypasses NodeSlots' reactive input-list updates in the Vue frontend.
    if (typeof node.removeInput === "function") {
        node.removeInput(index);
    } else {
        node.inputs.splice(index, 1);
        for (let i = index; i < node.inputs.length; i++) {
            if (node.inputs[i]?.link != null) {
                setTargetSlot(getLink(node.graph, node.inputs[i].link), i);
            }
        }
    }
}

function addSigmaInput(node) {
    const widget = ensureSigmaRowWidget(node);
    let index = getSigmaInputIndex(node);
    if (index < 0) {
        if (typeof node.addInput === "function") {
            node.addInput("sigmas", "SIGMAS");
        } else {
            node.inputs ||= [];
            node.inputs.push({ name: "sigmas", type: "SIGMAS", link: null });
        }
        index = getSigmaInputIndex(node);
    }
    if (index < 0) return;
    const slot = node.inputs[index];
    slot.name = "sigmas";
    slot.type = "SIGMAS";
    // A widget-backed input is displayed in the widget grid, not in the
    // top-level socket list. Both members are needed for contemporary
    // ComfyUI's reactive slot layout and its LiteGraph compatibility layer.
    slot.widget = { name: SIGMA_WIDGET_NAME };
    slot._widget = widget;
    slot.alwaysVisible = true;
    delete slot.pos; // Let the real widget row determine the connector Y.
    if (slot.label === "__lyonir_sigmas_position") delete slot.label;

    const origin = node.__lyonirStashedSigmaOrigin;
    if (origin && node.graph && typeof node.graph.getNodeById === "function") {
        const originNode = node.graph.getNodeById(origin.nodeId);
        if (originNode && typeof originNode.connect === "function") {
            try {
                originNode.connect(origin.slot, node, index);
                if (node.inputs[index]?.link != null) node.__lyonirStashedSigmaOrigin = null;
            } catch (error) {
                console.warn("Lyonir Sampler: could not restore SIGMAS connection", error);
            }
        }
    }
}

// LiteGraph WORKFLOW serialization is controlled by `widget.serialize`, *not*
// `widget.options.serialize`.  The latter controls API/prompt serialization.
// Treating `options.serialize === false` as a workflow omission shifted every
// value after the seed's control_after_generate widget on Ctrl+C/Ctrl+V.
function workflowWidgets(node) {
    return (node.widgets || []).filter((w) => w && w.serialize !== false);
}

function widgetValuesByName(node) {
    const named = Object.create(null);
    for (const widget of workflowWidgets(node)) {
        if (widget.name && widget.value !== undefined) named[widget.name] = widget.value;
    }
    return named;
}

function migrateSavedValues(node, info) {
    if (!Array.isArray(node?.widgets)) return;

    // New ComfyUI frontends provide widgets_values_named, which is independent
    // of how the frontend sorts or hides the node's controls.  Keep our own
    // named snapshot for copy/paste in older frontends as well.
    const fromFrontend = info?.widgets_values_named;
    const fromLyonir = info?.properties?.lyonir_sampler_widget_values_by_name;
    const named = fromFrontend && typeof fromFrontend === "object" && !Array.isArray(fromFrontend)
        ? fromFrontend
        : fromLyonir && typeof fromLyonir === "object" && !Array.isArray(fromLyonir)
            ? fromLyonir : null;
    if (named) {
        for (const widget of workflowWidgets(node)) {
            if (Object.prototype.hasOwnProperty.call(named, widget.name)) {
                widget.value = named[widget.name];
            }
        }
        return;
    }

    // For workflows saved by earlier pack versions that contain only a
    // positional array, use the historical *workflow* widget order. In
    // v3.5.26/27 the displayed widget order was already rearranged, whereas
    // older workflows used the Python schema order.
    const saved = info?.widgets_values;
    if (!saved || typeof saved.length !== "number") return;
    const serializedLayout = Number(info?.properties?.lyonir_sampler_layout_version || 0);
    const savedOrder = info?.properties?.lyonir_sampler_widget_order;
    const names = Array.isArray(savedOrder) && savedOrder.length
        ? savedOrder
        : serializedLayout >= 2
            ? workflowWidgets(node).map((w) => w.name)
            : (node.__lyonirOriginalWidgetOrder || []).filter(
                (name) => node.widgets.some((w) => w.name === name && w.serialize !== false));
    for (let i = 0; i < Math.min(saved.length, names.length); i++) {
        const widget = node.widgets.find((w) => w.name === names[i]);
        if (widget && widget.serialize !== false && saved[i] !== undefined) widget.value = saved[i];
    }
}

function updateSamplingMode(node, resize = true) {
    if (!Array.isArray(node?.widgets)) return;
    const modeWidget = node.widgets.find((w) => w.name === "sampling_mode");
    if (!modeWidget) return;
    // Saved v3.5.25 workflows used the label "Steps".
    if (modeWidget.value === "Steps" || modeWidget.value == null) modeWidget.value = "Basic Scheduler";
    const mode = modeWidget.value === "Manual Sigmas" ? "Manual Sigmas" : "Basic Scheduler";
    const manual = mode === "Manual Sigmas";

    for (const name of STEP_WIDGETS) {
        setSamplerWidgetHidden(node.widgets.find((w) => w.name === name), manual);
    }
    // The SIGMAS placeholder row is a real converted widget; it reserves a
    // row beneath Sampling Mode only while Manual Sigmas is selected.
    if (manual) {
        setSamplerWidgetHidden(ensureSigmaRowWidget(node), false);
        addSigmaInput(node);
    } else {
        removeSigmaInput(node);
        setSamplerWidgetHidden(ensureSigmaRowWidget(node), true);
    }
    if (node.__lyonirSamplingModeLast === mode) return;
    node.__lyonirSamplingModeLast = mode;
    if (resize && typeof node.computeSize === "function" && typeof node.setSize === "function") {
        const size = node.computeSize();
        if (Array.isArray(size) && Number.isFinite(size[1])) {
            node.setSize([Math.max(node.size?.[0] || 0, size[0] || 0), Math.max(60, size[1])]);
        }
    }
    node.setDirtyCanvas?.(true, true);
}

function installSamplingMode(node) {
    if (!Array.isArray(node?.widgets)) return;
    arrangeSamplerWidgets(node);
    const modeWidget = node.widgets.find((w) => w.name === "sampling_mode");
    if (!modeWidget) return;
    modeWidget.label = "Sampling Mode";
    if (!modeWidget.__lyonirModeCallbackWrapped) {
        const originalCallback = modeWidget.callback;
        modeWidget.callback = function () {
            const result = originalCallback?.apply(this, arguments);
            updateSamplingMode(node);
            return result;
        };
        modeWidget.__lyonirModeCallbackWrapped = true;
    }
    updateSamplingMode(node, false);
}

app.registerExtension({
    name: "LyonirStudio.SamplerInputLayout",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        if (nodeType.prototype.__lyonirSamplerLayoutPatched) return;
        nodeType.prototype.__lyonirSamplerLayoutPatched = true;

        // No getConnectionPos override is needed. The real widget-backed
        // SIGMAS input has the same position in Vue and LiteGraph renderers.

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);
            reorderSamplerInputs(this);
            installSamplingMode(this);
        };

        const originalConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = originalConfigure?.apply(this, arguments);
            migrateSavedValues(this, info);
            installSamplingMode(this);
            return result;
        };

        const originalGraphConfigured = nodeType.prototype.onGraphConfigured;
        nodeType.prototype.onGraphConfigured = function () {
            originalGraphConfigured?.apply(this, arguments);
            reorderSamplerInputs(this);
            installSamplingMode(this);
        };

        const originalSerialize = nodeType.prototype.onSerialize;
        nodeType.prototype.onSerialize = function (data) {
            const result = originalSerialize?.apply(this, arguments);
            if (data) {
                data.properties ||= {};
                data.properties.lyonir_sampler_layout_version = LAYOUT_VERSION;
                // Persist values and order explicitly for legacy ComfyUI
                // copy/paste implementations that restore positionally.
                // Modern LiteGraph also writes widgets_values_named itself.
                data.properties.lyonir_sampler_widget_values_by_name = widgetValuesByName(this);
                data.properties.lyonir_sampler_widget_order = workflowWidgets(this).map((w) => w.name);
                data.widgets_values_named = {
                    ...(data.widgets_values_named || {}),
                    ...widgetValuesByName(this),
                };
            }
            return result;
        };

    },
});
