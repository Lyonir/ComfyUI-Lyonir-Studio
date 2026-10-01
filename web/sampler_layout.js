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

app.registerExtension({
    name: "LyonirStudio.SamplerInputLayout",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        if (nodeType.prototype.__lyonirSamplerLayoutPatched) return;
        nodeType.prototype.__lyonirSamplerLayoutPatched = true;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            originalCreated?.apply(this, arguments);
            // Safe for freshly-created nodes before they have connections.
            reorderSamplerInputs(this);
        };

        const originalGraphConfigured = nodeType.prototype.onGraphConfigured;
        nodeType.prototype.onGraphConfigured = function () {
            originalGraphConfigured?.apply(this, arguments);
            // Also migrate already-saved Lyonir Sampler nodes after their links load.
            reorderSamplerInputs(this);
        };
    },
});
