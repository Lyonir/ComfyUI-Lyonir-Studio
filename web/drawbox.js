import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

function parseState(value) {
    try {
        const data = JSON.parse(value);
        if (Array.isArray(data)) {
            const boxes = data.length === 4 && data.every(Number.isFinite)
                ? [{ id: 1, coords: data, color: "#ff303b", name: "" }] : [];
            return { version: 2, boxes, nextId: boxes.length + 1 };
        }
        if (data?.version === 2 && Array.isArray(data.boxes)) {
            const ids = new Set();
            const boxes = data.boxes.filter((box) => {
                if (!Number.isSafeInteger(box.id) || box.id < 1 || ids.has(box.id)) return false;
                if (!Array.isArray(box.coords) || box.coords.length !== 4 || !box.coords.every(Number.isFinite)) return false;
                ids.add(box.id);
                return true;
            }).map((box) => ({
                type: ["rect", "ellipse", "freehand"].includes(box.type) ? box.type : "rect",
                points: Array.isArray(box.points) ? box.points.filter((p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)).map((p) => p.map((v) => Math.max(0, Math.min(1, v)))) : [],
                width: Number.isFinite(box.width) && box.width > 0 ? Math.min(1, box.width) : 0.03,
                id: box.id, coords: box.coords.map((v) => Math.max(0, Math.min(1, v))),
                color: /^#[0-9a-f]{6}$/i.test(box.color) ? box.color : "#ff303b",
                name: typeof box.name === "string" ? box.name : "",
            }));
            return { version: 2, boxes, nextId: Math.max(1, Number.isSafeInteger(data.nextId) ? data.nextId : 1, ...boxes.map((box) => box.id + 1)) };
        }
    } catch {}
    return { version: 2, boxes: [], nextId: 1 };
}

function createDrawbox(node) {
    const boxWidget = node.widgets.find((widget) => widget.name === "box");
    boxWidget.type = "hidden";
    boxWidget.computeSize = () => [0, -4];

    const root = document.createElement("div");
    Object.assign(root.style, {
        width: "100%", height: "100%", display: "flex", flexDirection: "column",
        gap: "6px", minHeight: "180px", color: "#e3e3e3",
    });
    const status = document.createElement("div");
    Object.assign(status.style, { font: "12px system-ui", flexShrink: "0" });
    const viewport = document.createElement("div");
    Object.assign(viewport.style, {
        flex: "1", minHeight: "120px", overflow: "auto", display: "flex",
        alignItems: "center", justifyContent: "center",
    });
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 360;
    canvas.setAttribute("aria-label", "Drag a rectangle to select the mask");
    Object.assign(canvas.style, {
        display: "block", width: "100%", height: "auto", flexShrink: "0",
        touchAction: "none", cursor: "crosshair",
    });
    const toolbar = document.createElement("div");
    Object.assign(toolbar.style, { display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap", flexShrink: "0" });
    function button(label, title) {
        const element = document.createElement("button");
        element.type = "button";
        element.textContent = label;
        element.title = title;
        Object.assign(element.style, {
            border: "1px solid #62626b", borderRadius: "9px", padding: "5px 10px",
            background: "#303038", color: "#eee", cursor: "pointer", font: "12px system-ui",
        });
        toolbar.append(element);
        return element;
    }
    const undo = button("↶ Desfazer", "Desfazer a última alteração");
    const redo = button("↷ Refazer", "Refazer a última alteração");
    const clear = button("Limpar", "Remover todas as caixas");
    const color = document.createElement("input");
    color.type = "color";
    color.value = "#ff303b";
    color.title = "Cor das próximas caixas";
    color.setAttribute("aria-label", color.title);
    Object.assign(color.style, { width: "30px", height: "28px", padding: "0", border: "0", background: "transparent", cursor: "pointer" });
    const tool = document.createElement("select");
    tool.setAttribute("aria-label", "Ferramenta de desenho");
    for (const [value, label] of [["rect", "▭ Retângulo"], ["ellipse", "◯ Círculo"], ["freehand", "✎ Livre"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        tool.append(option);
    }
    tool.value = "rect";
    Object.assign(tool.style, { borderRadius: "8px", padding: "5px", background: "#303038", color: "#eee", border: "1px solid #62626b" });
    const brush = document.createElement("input");
    brush.type = "range";
    brush.min = "4";
    brush.max = "128";
    brush.step = "1";
    brush.value = "24";
    brush.title = "Espessura do desenho livre, em pixels da imagem";
    brush.setAttribute("aria-label", brush.title);
    Object.assign(brush.style, { width: "80px", display: "none" });
    tool.addEventListener("change", () => { brush.style.display = tool.value === "freehand" ? "block" : "none"; });
    toolbar.append(tool, color, brush);
    const list = document.createElement("div");
    Object.assign(list.style, { maxHeight: "120px", overflowY: "auto", flexShrink: "0", display: "flex", flexDirection: "column", gap: "4px" });
    viewport.append(canvas);
    root.append(toolbar, status, viewport, list);

    let state = parseState(boxWidget.value);
    const undoStack = [];
    const redoStack = [];
    let draft = null;

    let image = null;
    let pendingImage = null;
    let revision = 0;
    let start = null;
    let activePointer = null;
    let disposed = false;
    let currentUrl = "";
    let sourceKey = null;
    let executionPreview = null;

    function paint() {
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!image) return;
        ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
        for (const box of [...state.boxes, ...(draft ? [draft] : [])]) {
            const [x1, y1, x2, y2] = box.coords;
            const x = Math.min(x1, x2) * canvas.width;
            const y = Math.min(y1, y2) * canvas.height;
            const width = Math.abs(x2 - x1) * canvas.width;
            const height = Math.abs(y2 - y1) * canvas.height;
            ctx.fillStyle = box.color + "33";
            ctx.strokeStyle = box.color;
            ctx.lineWidth = 3;
            if (box.type === "freehand" && box.points?.length) {
                ctx.beginPath();
                ctx.moveTo(box.points[0][0] * canvas.width, box.points[0][1] * canvas.height);
                for (const point of box.points.slice(1)) ctx.lineTo(point[0] * canvas.width, point[1] * canvas.height);
                ctx.lineWidth = box.width * Math.min(canvas.width, canvas.height);
                ctx.lineCap = "round";
                ctx.lineJoin = "round";
                if (box.points.length === 1) {
                    ctx.arc(box.points[0][0] * canvas.width, box.points[0][1] * canvas.height, ctx.lineWidth / 2, 0, Math.PI * 2);
                    ctx.fillStyle = box.color;
                    ctx.fill();
                } else ctx.stroke();
            } else if (box.type === "ellipse") {
                ctx.beginPath();
                ctx.ellipse(x + width / 2, y + height / 2, width / 2, height / 2, 0, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
            } else {
                ctx.fillRect(x, y, width, height);
                ctx.strokeRect(x, y, width, height);
            }
            const label = String(box.id);
            ctx.font = "bold 12px system-ui";
            const radius = Math.max(9, ctx.measureText(label).width / 2 + 4);
            const cx = Math.max(radius, Math.min(canvas.width - radius, x));
            const cy = Math.max(radius, Math.min(canvas.height - radius, y));
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.fillStyle = box.color;
            ctx.fill();
            ctx.strokeStyle = "#222";
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.fillStyle = "#fff";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(label, cx, cy);
        }
    }

    function renderList() {
        list.replaceChildren();
        for (const box of state.boxes) {
            const row = document.createElement("div");
            Object.assign(row.style, { display: "flex", alignItems: "center", gap: "6px" });
            const number = document.createElement("span");
            number.textContent = String(box.id);
            Object.assign(number.style, { background: box.color, borderRadius: "12px", minWidth: "22px", textAlign: "center", font: "bold 12px system-ui" });
            const swatch = document.createElement("input");
            swatch.type = "color";
            swatch.value = box.color;
            swatch.title = "Cor da caixa " + box.id;
            swatch.setAttribute("aria-label", swatch.title);
            Object.assign(swatch.style, { width: "26px", height: "24px", padding: "0", border: "0" });
            swatch.addEventListener("change", () => {
                const next = structuredClone(state);
                next.boxes.find((item) => item.id === box.id).color = swatch.value;
                commit(next);
            });
            const name = document.createElement("input");
            name.type = "text";
            name.value = box.name;
            name.placeholder = "Nome da caixa " + box.id;
            name.setAttribute("aria-label", name.placeholder);
            Object.assign(name.style, { minWidth: "0", flex: "1", borderRadius: "6px", border: "1px solid #555", padding: "4px 6px", background: "#25252c", color: "#eee" });
            name.addEventListener("change", () => {
                const next = structuredClone(state);
                next.boxes.find((item) => item.id === box.id).name = name.value;
                commit(next);
            });
            row.append(number, swatch, name);
            list.append(row);
        }
    }

    function publish() {
        boxWidget.value = JSON.stringify(state);
        undo.disabled = undoStack.length === 0;
        redo.disabled = redoStack.length === 0;
        clear.disabled = state.boxes.length === 0;
        undo.style.opacity = undo.disabled ? "0.45" : "1";
        redo.style.opacity = redo.disabled ? "0.45" : "1";
        renderList();
        paint();
        app.graph?.setDirtyCanvas?.(true, true);
    }

    function commit(next) {
        if (JSON.stringify(next) === JSON.stringify(state)) return;
        undoStack.push(JSON.stringify(state));
        if (undoStack.length > 100) undoStack.shift();
        redoStack.length = 0;
        state = next;
        publish();
    }

    function finishDrag() {
        const pointer = activePointer;
        activePointer = null;
        start = null;
        draft = null;
        if (pointer !== null && canvas.hasPointerCapture(pointer)) canvas.releasePointerCapture(pointer);
    }

    function loadUrl(url) {
        if (url === currentUrl) return;
        currentUrl = url;
        finishDrag();
        const current = ++revision;
        image = null;
        if (pendingImage) {
            pendingImage.onload = null;
            pendingImage.onerror = null;
        }
        paint();
        status.textContent = url ? "Loading image…" : "Connect IMAGE. Run once if the source has no preview yet.";
        if (!url) return;
        const candidate = new Image();
        pendingImage = candidate;
        candidate.onload = () => {
            if (disposed || current !== revision) return;
            image = candidate;
            const scale = Math.min(1, 1024 / Math.max(image.naturalWidth, image.naturalHeight));
            canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
            canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
            status.textContent = image.naturalWidth + " × " + image.naturalHeight + " — drag to draw; white mask inside.";
            paint();
        };
        candidate.onerror = () => {
            if (disposed || current !== revision) return;
            status.textContent = "Could not load image. Select or upload it again.";
        };
        candidate.src = url;
    }

    function previewUrl(info) {
        if (!info?.filename) return "";
        const params = new URLSearchParams({
            filename: info.filename, subfolder: info.subfolder || "", type: info.type || "temp",
        });
        return api.apiURL("/view?" + params.toString());
    }

    function syncSource() {
        const graph = node.graph || app.graph;
        const input = node.inputs?.find((item) => item.name === "image");
        const link = graph?.links?.get?.(input?.link) || graph?.links?.[input?.link];
        const originId = link?.origin_id ?? (Array.isArray(link) ? link[1] : null);
        const key = input?.link == null ? null : String(input.link);
        if (sourceKey !== key) {
            sourceKey = key;
            executionPreview = null;
        }
        if (originId == null) {
            loadUrl("");
            return;
        }
        const origin = graph?.getNodeById?.(originId);
        const output = app.nodeOutputs?.[originId];
        // Native Load Image files are available before the first execution.
        const fileWidget = origin?.type === "LoadImage" || origin?.comfyClass === "LoadImage"
            ? origin.widgets?.find((widget) => widget.name === "image") : null;
        let url = "";
        if (fileWidget?.value) {
            let filename = String(fileWidget.value);
            let type = "input";
            const annotation = filename.match(/ \[(input|output|temp)\]$/);
            if (annotation) {
                type = annotation[1];
                filename = filename.slice(0, annotation.index);
            }
            url = previewUrl({ filename, type });
        }
        url ||= executionPreview || previewUrl(output?.images?.[0]);
        if (!url && origin?.imgs?.[0]?.src) url = origin.imgs[0].src;
        loadUrl(url);
    }

    function updateFromOutput(output) {
        const info = output?.lyonir_drawbox_preview?.[0];
        if (!info) return;
        executionPreview = previewUrl(info);
        loadUrl(executionPreview);
    }

    function point(event) {
        const rect = canvas.getBoundingClientRect();
        return [
            Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
            Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
        ];
    }

    function updateDraft(point) {
        if (draft.type !== "freehand") {
            draft.coords = [...start, ...point];
            return;
        }
        const last = draft.points[draft.points.length - 1];
        if (last[0] !== point[0] || last[1] !== point[1]) draft.points.push(point);
        draft.coords = [
            Math.min(draft.coords[0], point[0]), Math.min(draft.coords[1], point[1]),
            Math.max(draft.coords[2], point[0]), Math.max(draft.coords[3], point[1]),
        ];
    }

    canvas.addEventListener("pointerdown", (event) => {
        if (!image || event.button !== 0 || activePointer !== null) return;
        event.preventDefault();
        event.stopPropagation();
        start = point(event);
        activePointer = event.pointerId;
        canvas.setPointerCapture(event.pointerId);
        draft = { id: state.nextId, type: tool.value, coords: [...start, ...start], points: [start], width: Number(brush.value) / Math.min(image.naturalWidth, image.naturalHeight), color: color.value, name: "" };
        paint();
    });
    canvas.addEventListener("pointermove", (event) => {
        if (event.pointerId !== activePointer) return;
        event.preventDefault();
        event.stopPropagation();
        updateDraft(point(event));
        paint();
    });
    canvas.addEventListener("pointerup", (event) => {
        if (event.pointerId !== activePointer) return;
        event.stopPropagation();
        updateDraft(point(event));
        const box = draft;
        finishDrag();
        if (box.type === "freehand" || (box.coords[0] !== box.coords[2] && box.coords[1] !== box.coords[3])) {
            commit({ ...state, boxes: [...state.boxes, box], nextId: state.nextId + 1 });
        } else paint();
    });
    function cancel(event) {
        if (event.pointerId !== activePointer) return;
        finishDrag();
        paint();
    }
    canvas.addEventListener("pointercancel", cancel);
    canvas.addEventListener("lostpointercapture", cancel);
    clear.addEventListener("click", () => {
        finishDrag();
        commit({ version: 2, boxes: [], nextId: 1 });
    });
    undo.addEventListener("click", () => {
        finishDrag();
        if (!undoStack.length) return;
        redoStack.push(JSON.stringify(state));
        state = parseState(undoStack.pop());
        publish();
    });
    redo.addEventListener("click", () => {
        finishDrag();
        if (!redoStack.length) return;
        undoStack.push(JSON.stringify(state));
        state = parseState(redoStack.pop());
        publish();
    });
    for (const name of ["keydown", "keyup"]) {
        root.addEventListener(name, (event) => event.stopPropagation());
    }
    for (const name of ["pointerdown", "pointermove", "pointerup", "click", "dblclick"]) {
        root.addEventListener(name, (event) => event.stopPropagation());
    }
    publish();
    syncSource();
    const sourceTimer = setInterval(syncSource, 500);
    return {
        root, syncSource, updateFromOutput,
        restore() {
            finishDrag();
            state = parseState(boxWidget.value);
            undoStack.length = 0;
            redoStack.length = 0;
            publish();
            syncSource();
        },
        destroy() {
            disposed = true;
            clearInterval(sourceTimer);
            revision++;
            finishDrag();
            if (pendingImage) {
                pendingImage.onload = null;
                pendingImage.onerror = null;
            }
        },
    };
}

app.registerExtension({
    name: "LyonirStudio.Drawbox",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "Lyonir_Drawbox") return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            created?.apply(this, arguments);
            const editor = createDrawbox(this);
            this.__lyonirDrawbox = editor;
            this.addDOMWidget("lyonir_drawbox", "lyonir_drawbox", editor.root, {
                serialize: false, hideOnZoom: false,
                getMinHeight: () => 220, getHeight: () => 340,
            });
            this.setSize([Math.max(this.size[0], 380), Math.max(this.size[1], 450)]);
        };
        const configured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            configured?.apply(this, arguments);
            this.__lyonirDrawbox?.restore();
        };
        const executed = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            executed?.apply(this, arguments);
            this.__lyonirDrawbox?.updateFromOutput(message);
        };
        const removed = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this.__lyonirDrawbox?.destroy();
            removed?.apply(this, arguments);
        };
    },
});
