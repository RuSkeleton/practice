
"use strict";

const VIRTUAL_CANVAS_WIDTH = 1920;
const VIRTUAL_CANVAS_HEIGHT = 1080;

const editor_canvas = document.getElementById("editor-canvas");

const editor_state = {
    selected_element_id: null,

    slide: {
        width: VIRTUAL_CANVAS_WIDTH,
        height: VIRTUAL_CANVAS_HEIGHT,
        background_color: "#ffffff",

        elements: [
            {
                id: "decoration-top",
                type: "shape",
                variant: "circle-top",
                x: 1480,
                y: -190,
                width: 880,
                height: 880,
                z_index: 0
            },

            {
                id: "decoration-bottom",
                type: "shape",
                variant: "circle-bottom",
                x: -190,
                y: 760,
                width: 720,
                height: 720,
                z_index: 0
            },

            {
                id: "headline-card",
                type: "text",
                x: 230,
                y: 205,
                width: 1080,
                height: 330,

                title: "Будущий заголовок слайда",
                content:
                    "Это временный текстовый блок. Позже его можно будет " +
                    "выделять, перемещать, изменять по размеру и " +
                    "редактировать прямо на холсте.",

                title_font_size: 64,
                content_font_size: 30,
                z_index: 1
            },

            {
                id: "accent-card",
                type: "shape",
                variant: "accent",
                x: 1400,
                y: 620,
                width: 340,
                height: 340,
                z_index: 1
            }
        ]
    }
};

function virtual_to_percent(value, total_size) {
    return `${(value / total_size) * 100}%`;
}

function get_canvas_scale() {
    return editor_canvas.clientWidth / 1920;
}

function get_element_by_id(id) {
    return editor_state.slide.elements.find(e => e.id === id);
}

function create_element_shell(element) {
    const element_node = document.createElement("div");

    element_node.classList.add("slide-element");

    element_node.dataset.elementId = element.id;
    element_node.dataset.elementType = element.type;

    element_node.style.left = virtual_to_percent(
        element.x,
        VIRTUAL_CANVAS_WIDTH
    );

    element_node.style.top = virtual_to_percent(
        element.y,
        VIRTUAL_CANVAS_HEIGHT
    );

    element_node.style.width = virtual_to_percent(
        element.width,
        VIRTUAL_CANVAS_WIDTH
    );

    element_node.style.height = virtual_to_percent(
        element.height,
        VIRTUAL_CANVAS_HEIGHT
    );

    element_node.style.zIndex = String(element.z_index);

    if (element.id === editor_state.selected_element_id) {
        element_node.classList.add("is-selected");
    }

    element_node.addEventListener("click", (event) => {
        event.stopPropagation();

        editor_state.selected_element_id = element.id;
        render_slide();
    });

    return element_node;
}

function create_text_element(element, canvas_scale) {
    const element_node = create_element_shell(element);

    element_node.classList.add("slide-text-element");

    const title_node = document.createElement("h1");

    title_node.classList.add("slide-text-element-title");
    title_node.textContent = element.title;

    title_node.style.fontSize =
        `${element.title_font_size * canvas_scale}px`;

    const content_node = document.createElement("p");

    content_node.classList.add("slide-text-element-content");
    content_node.textContent = element.content;

    content_node.style.fontSize =
        `${element.content_font_size * canvas_scale}px`;

    element_node.append(title_node, content_node);

    return element_node;
}

function create_shape_element(element) {
    const element_node = create_element_shell(element);

    element_node.classList.add("slide-shape-element");
    element_node.classList.add(
        `slide-shape-element--${element.variant}`
    );

    return element_node;
}

function create_slide_element(element, canvas_scale) {
    switch (element.type) {
        case "text":
            return create_text_element(element, canvas_scale);

        case "shape":
            return create_shape_element(element);

        default:
            console.warn(
                `Неизвестный тип элемента: ${element.type}`
            );

            return null;
    }
}

function render_slide() {
    const safe_zone = editor_canvas.querySelector(
        ".editor-canvas-safe-zone"
    );

    editor_canvas
        .querySelectorAll(".slide-element")
        .forEach((element_node) => {
            element_node.remove();
        });

    editor_canvas.style.backgroundColor =
        editor_state.slide.background_color;

    const canvas_scale = get_canvas_scale();

    const sorted_elements = [...editor_state.slide.elements].sort(
        (first_element, second_element) =>
            first_element.z_index - second_element.z_index
    );

    sorted_elements.forEach((element) => {
        const element_node = create_slide_element(
            element,
            canvas_scale
        );

        if (element_node !== null) {
            editor_canvas.insertBefore(element_node, safe_zone);
        }
    });
}

editor_canvas.addEventListener("click", () => {
    editor_state.selected_element_id = null;
    render_slide();
});

const canvas_resize_observer = new ResizeObserver(() => {
    render_slide();
});

canvas_resize_observer.observe(editor_canvas);

render_slide();
