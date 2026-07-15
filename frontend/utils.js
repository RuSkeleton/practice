
﻿// =========================================================
// UTILS
// =========================================================

function parseDateMs(value) {
    if (!value) return null;
    const ms = Date.parse(value);
    return Number.isNaN(ms) ? null : ms;
}

function positiveModulo(value, divisor) {
    return ((value % divisor) + divisor) % divisor;
}

function safeNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : Number(fallback || 0);
}

function safeInteger(value, fallback) {
    const number = parseInt(value, 10);
    return Number.isFinite(number) ? number : Number(fallback || 0);
}

function sanitizeClassName(value) {
    return String(value || "")
        .toLowerCase()
        .replace(/[^a-zа-яё0-9_-]+/gi, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 48);
}

function isSafeCssColor(value) {
    if (typeof value !== "string") return false;
    return /^#[0-9a-f]{3,8}$/i.test(value) ||
        /^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}(\s*,\s*(0|1|0?\.\d+))?\s*\)$/i.test(value) ||
        /^[a-z]+$/i.test(value);
}

function toAbsoluteUrl(url) {
    try { return new URL(url, window.location.origin).href; }
    catch (_) { return String(url || ""); }
}

function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}
