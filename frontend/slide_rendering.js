
﻿// =========================================================
// RENDER
// =========================================================

function createSlideNode(slide) {
    const safeSlide = slide || {};

    const canvas = document.createElement("section");
    canvas.className = "slide-canvas";
    canvas.setAttribute("aria-label", "Слайд " + safeSlide.id);
    applySlideBackground(canvas, safeSlide.background);

    for (const element of safeSlide.elements || []) {
        const node = renderElement(element);
        if (node) {
            canvas.appendChild(node);
        }
    }

    return canvas;
}

function renderSlide(slide, root) {
    if (!root) {
        console.error("renderSlide: root-контейнер не был передан")
        return null;
    }

    const canvas = createSlideNode(slide);

    root.innerHTML = ""; // Заменить на рекурсивный removeChild ??
    root.appendChild(canvas);

    scaleSlideCanvas(root, canvas);

    if (typeof hydrateRenderedImages == "function") {
        hydrateRenderedImages(canvas)
    }

    return canvas;
}

function scaleSlideCanvas(root, canvas) {
    const config = window.CONFIG || {};
    const canvasWidth = Number(config.CANVAS_WIDTH || 1920);
    const canvasHeight = Number(config.CANVAS_HEIGHT || 1080);

    const rootWidth = root.clientWidth || window.innerWidth;
    const rootHeight = root.clientHeight || window.innerHeight;

    const scale = Math.min(
        rootWidth / canvasWidth,
        rootHeight / canvasHeight
    );

    const left = Math.round((rootWidth - canvasWidth * scale) / 2);
    const top = Math.round((rootHeight - canvasHeight * scale) / 2);

    canvas.style.left = left + "px";
    canvas.style.top = top + "px";
    canvas.style.transform = "scale(" + scale + ")";
}

function renderElement(element) {
    const type = String(element.type || "text").toLowerCase();
    if (type === "text") return renderTextElement(element);
    if (type === "image") return renderImageElement(element);
    if (type === "chart" || type === "metric") return renderMetricElement(element);
    if (type === "badge") return renderBadgeElement(element);
    return renderTextElement({ ...element, value: element.value ?? "" });
}

function renderTextElement(element) {
    const node = document.createElement("div");
    node.className = "slide-element slide-text";
    applyRoleClass(node, element.role);
    applyTextAlignmentClasses(node, element.layout || {});
    node.textContent = String(element.value ?? element.text ?? "");
    applyLayout(node, element.layout, {
        width: 1200,
        height: 140,
        fontSize: 64,
        color: "#ffffff",
        fontWeight: 700
    });
    return node;
}

function renderImageElement(element) {
    const node = document.createElement("div");
    node.className = "slide-element slide-image-element";
    applyImageClasses(node, element.layout || {}, element.role);
    applyLayout(node, element.layout, { width: 800, height: 500 });

    const src = getImageElementSource(element);
    if (src) {
        const img = document.createElement("img");
        img.src = src;
        img.dataset.cacheSrc = toAbsoluteUrl(src);
        img.alt = String(element.alt || element.title || element.role || "Изображение");
        node.appendChild(img);
    }
    return node;
}

function renderMetricElement(element) {
    const chart = element.chart || element.metric || {};
    const chartType = String(chart.chartType || chart.type || "value").toLowerCase();

    if (chartType === "value" || (!chart.datasets && element.value !== undefined)) {
        return renderMetricValueElement(element);
    }

    const node = document.createElement("div");
    node.className = "slide-element slide-chart";
    applyRoleClass(node, element.role);
    applyLayout(node, element.layout, { width: 1200, height: 520 });

    const canvas = document.createElement("canvas");
    node.appendChild(canvas);
    window.requestAnimationFrame(() => drawChart(canvas, chart));
    return node;
}

function renderMetricValueElement(element) {
    const node = document.createElement("div");
    node.className = "slide-element metric-value";
    applyRoleClass(node, element.role);
    const chart = element.chart || element.metric || {};
    const value = element.value ?? chart.value ?? "—";
    const unit = chart.unit ? " " + chart.unit : "";
    node.textContent = String(value) + unit;
    applyLayout(node, element.layout, {
        width: 900,
        height: 220,
        fontSize: 150,
        color: "#d6ffe8",
        fontWeight: 800
    });
    return node;
}

function renderBadgeElement(element) {
    const node = document.createElement("div");
    node.className = "slide-element slide-badge";
    applyRoleClass(node, element.role);
    node.textContent = String(element.value ?? element.text ?? "");
    applyLayout(node, element.layout, {
        width: 360,
        height: 70,
        fontSize: 30,
        color: "#ffffff",
        fontWeight: 700
    });
    return node;
}

function applySlideBackground(canvas, background) {
    canvas.classList.add("bg-default");
    if (!background) return;

    const type = String(background.type || "gradient").toLowerCase();
    const value = String(background.value || "default");

    if (type === "color" && isSafeCssColor(value)) {
        canvas.classList.remove("bg-default");
        canvas.style.background = value;
        return;
    }

    if (type === "image" && value) {
        canvas.classList.remove("bg-default");
        canvas.classList.add("bg-image");
        canvas.style.backgroundImage = "url(" + JSON.stringify(toAbsoluteUrl(value)) + ")";
        canvas.style.backgroundSize = "cover";
        canvas.style.backgroundPosition = "center";
        canvas.dataset.bgCacheSrc = toAbsoluteUrl(value);
        return;
    }

    if (type === "gradient") {
        const preset = sanitizeClassName(value);
        const knownPreset = ["default", "announcement", "urgent", "image", "greeting", "metric", "light"].includes(preset) ? preset : "default";
        canvas.classList.remove("bg-default");
        canvas.classList.add("bg-" + knownPreset);
    }
}

function applyLayout(node, layout = {}, defaults = {}) {
    const x = safeNumber(layout.x, defaults.x || 0);
    const y = safeNumber(layout.y, defaults.y || 0);
    const width = safeNumber(layout.width, defaults.width || 400);
    const height = safeNumber(layout.height, defaults.height || 100);

    node.style.left = x + "px";
    node.style.top = y + "px";
    node.style.width = width + "px";
    node.style.height = height + "px";
    node.style.zIndex = String(safeInteger(layout.zIndex, defaults.zIndex || 1));

    if (layout.fontSize !== undefined || defaults.fontSize !== undefined) node.style.fontSize = safeNumber(layout.fontSize, defaults.fontSize) + "px";
    if (layout.fontWeight !== undefined || defaults.fontWeight !== undefined) node.style.fontWeight = String(layout.fontWeight || defaults.fontWeight);
    if (layout.color !== undefined || defaults.color !== undefined) node.style.color = isSafeCssColor(layout.color) ? layout.color : defaults.color;
    if (layout.backgroundColor && isSafeCssColor(layout.backgroundColor)) node.style.backgroundColor = layout.backgroundColor;
    if (layout.borderColor && isSafeCssColor(layout.borderColor)) node.style.borderColor = layout.borderColor;
    if (layout.borderRadius !== undefined) node.style.borderRadius = safeNumber(layout.borderRadius, 0) + "px";
    if (layout.opacity !== undefined) node.style.opacity = String(Math.max(0, Math.min(1, safeNumber(layout.opacity, 1))));
    if (layout.lineHeight !== undefined) node.style.lineHeight = String(layout.lineHeight);
    if (layout.padding !== undefined) node.style.padding = safeNumber(layout.padding, 0) + "px";
}

function applyTextAlignmentClasses(node, layout) {
    const align = String(layout.textAlign || "center").toLowerCase();
    const valign = String(layout.verticalAlign || "middle").toLowerCase();
    node.classList.add(["left", "center", "right"].includes(align) ? "align-" + align : "align-center");
    node.classList.add(["top", "middle", "bottom"].includes(valign) ? "valign-" + valign : "valign-middle");
}

function applyImageClasses(node, layout, role) {
    const fit = String(layout.fit || "contain").toLowerCase();
    const shape = String(layout.shape || "").toLowerCase();
    if (["cover", "fill"].includes(fit)) node.classList.add("fit-" + fit);
    if (["rounded", "circle"].includes(shape)) node.classList.add("shape-" + shape);
    if (role === "photo" || role === "person_photo") node.classList.add("shape-circle", "shadow-soft");
    if (layout.shadow) node.classList.add("shadow-soft");
}

function applyRoleClass(node, role) {
    if (!role) return;
    const roleClass = sanitizeClassName(String(role));
    if (roleClass) node.classList.add("role-" + roleClass);
}

function getImageElementSource(element) {
    return String(element.src || element.url || element.value || (element.image && element.image.src) || "");
}

//  TODO: удалить после рефакторинга и перевести весь проект на
//   новую функцию. Старое имя сохранено для совместимости
function scaleCurrentCanvas(root) {
    const targetRoot =
        root ||
        (window.DOM && window.DOM.slideRoot) ||
        document.getElementById("slideRoot") ||
        document.getElementById("preview-place");

    if (!targetRoot) return;

    const canvas = targetRoot.querySelector(".slide-canvas");
    if (!canvas) return;

    scaleSlideCanvas(targetRoot, canvas);
}

function drawChart(canvas, chart) {
    if (!canvas || !chart) return;
    const width = canvas.clientWidth || (canvas.parentElement && canvas.parentElement.clientWidth) || 1;
    const height = canvas.clientHeight || (canvas.parentElement && canvas.parentElement.clientHeight) || 1;
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(width * scale));
    canvas.height = Math.max(1, Math.floor(height * scale));

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(scale, scale);
    const labels = Array.isArray(chart.labels) ? chart.labels : [];
    const dataset = Array.isArray(chart.datasets) && chart.datasets.length > 0 ? chart.datasets[0] : null;
    const data = dataset && Array.isArray(dataset.data) ? dataset.data.map(Number).filter(value => !Number.isNaN(value)) : [];
    const type = String(chart.chartType || chart.type || "bar").toLowerCase();

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(255,255,255,0.88)";
    ctx.strokeStyle = "rgba(255,255,255,0.72)";
    ctx.lineWidth = 3;
    ctx.font = "24px Segoe UI, sans-serif";

    if (data.length === 0) {
        ctx.fillText("Нет данных", 24, 42);
        return;
    }

    const padding = { left: 70, right: 32, top: 42, bottom: 74 };
    const chartWidth = Math.max(1, width - padding.left - padding.right);
    const chartHeight = Math.max(1, height - padding.top - padding.bottom);
    const max = Math.max(...data, 1);
    const min = Math.min(...data, 0);
    const range = Math.max(1, max - Math.min(0, min));
    const baseY = padding.top + chartHeight;

    ctx.strokeStyle = "rgba(255,255,255,0.25)";
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top);
    ctx.lineTo(padding.left, baseY);
    ctx.lineTo(width - padding.right, baseY);
    ctx.stroke();

    if (type === "line") drawLineChart(ctx, data, labels, padding, chartWidth, chartHeight, range, min, baseY);
    else drawBarChart(ctx, data, labels, padding, chartWidth, chartHeight, max, baseY);
}

function drawBarChart(ctx, data, labels, padding, chartWidth, chartHeight, max, baseY) {
    const gap = 18;
    const barWidth = Math.max(12, (chartWidth - gap * (data.length - 1)) / data.length);
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    ctx.textAlign = "center";

    data.forEach((value, index) => {
        const x = padding.left + index * (barWidth + gap);
        const h = Math.max(2, (value / max) * chartHeight);
        const y = baseY - h;
        roundRect(ctx, x, y, barWidth, h, 10);
        ctx.fill();
        ctx.fillText(String(labels[index] || ""), x + barWidth / 2, baseY + 36);
        ctx.fillText(String(value), x + barWidth / 2, y - 12);
    });
}

function drawLineChart(ctx, data, labels, padding, chartWidth, chartHeight, range, min, baseY) {
    const step = data.length > 1 ? chartWidth / (data.length - 1) : chartWidth;
    const points = data.map((value, index) => ({
        x: padding.left + index * step,
        y: baseY - ((value - Math.min(0, min)) / range) * chartHeight,
        value
    }));

    ctx.strokeStyle = "rgba(255,255,255,0.78)";
    ctx.beginPath();
    points.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();

    ctx.fillStyle = "rgba(255,255,255,0.88)";
    ctx.textAlign = "center";
    points.forEach((point, index) => {
        ctx.beginPath();
        ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillText(String(labels[index] || ""), point.x, baseY + 36);
        ctx.fillText(String(point.value), point.x, point.y - 14);
    });
}

function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
}

window.addEventListener("resize", function () {
    scaleCurrentCanvas();
})
