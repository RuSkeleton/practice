"use strict";

(function initializeAdminLiveUpdates() {
    const WS_URL = (
        window.location.protocol === "https:" ? "wss:" : "ws:"
    ) + "//" + window.location.host + "/ws/admin";

    const RECONNECT_DELAY_MS = 3000;
    const SLIDE_RELOAD_DEBOUNCE_MS = 100;

    let websocket = null;
    let reconnectTimer = null;
    let slideReloadTimer = null;
    let statusBoundaryTimer = null;
    let slidesLoadPromise = null;
    let stopped = false;
    let cachedSlides = [];

    const originalLoadSlides = loadSlides;
    const originalRenderSlides = renderSlides;

    // Объединяет одновременные причины обновления: начальную загрузку,
    // собственный CRUD и WebSocket-событие. В один момент выполняется
    // не более одного GET /api/slides.
    loadSlides = function loadSlidesDeduplicated() {
        if (slidesLoadPromise !== null) {
            return slidesLoadPromise;
        }

        slidesLoadPromise = Promise.resolve(originalLoadSlides());
        slidesLoadPromise = slidesLoadPromise.finally(function finishSlidesLoad() {
            slidesLoadPromise = null;
        });
        return slidesLoadPromise;
    };

    function scheduleNextStatusBoundary() {
        if (statusBoundaryTimer !== null) {
            window.clearTimeout(statusBoundaryTimer);
            statusBoundaryTimer = null;
        }

        const now = Date.now();
        let nextBoundary = null;

        for (const slide of cachedSlides) {
            const start = parseServerDate(slide.start_date).getTime();
            const end = parseServerDate(slide.end_date).getTime();

            if (!Number.isNaN(start) && start > now) {
                nextBoundary = nextBoundary === null
                    ? start
                    : Math.min(nextBoundary, start);
            }

            if (!Number.isNaN(end) && end > now) {
                nextBoundary = nextBoundary === null
                    ? end
                    : Math.min(nextBoundary, end);
            }
        }

        if (nextBoundary === null) return;

        statusBoundaryTimer = window.setTimeout(
            function refreshStatusesAtBoundary() {
                statusBoundaryTimer = null;
                originalRenderSlides(cachedSlides);
                scheduleNextStatusBoundary();
            },
            Math.max(50, nextBoundary - now + 50)
        );
    }

    // Сохраняет последнюю коллекцию и планирует локальную перерисовку
    // ровно на ближайшее начало/окончание показа. HTTP-запросов здесь нет.
    renderSlides = function renderSlidesWithLiveStatuses(slides) {
        cachedSlides = Array.isArray(slides) ? slides : [];
        originalRenderSlides(cachedSlides);
        scheduleNextStatusBoundary();
    };

    function scheduleSlidesReload(delayMs = SLIDE_RELOAD_DEBOUNCE_MS) {
        if (slideReloadTimer !== null) {
            window.clearTimeout(slideReloadTimer);
        }

        slideReloadTimer = window.setTimeout(function reloadSlidesAfterEvent() {
            slideReloadTimer = null;
            Promise.resolve(loadSlides()).catch(function ignoreHandledLoadError() {
                // loadSlides самостоятельно показывает ошибку в интерфейсе.
            });
        }, delayMs);
    }

    function sendMessage(message) {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) return;

        try {
            websocket.send(JSON.stringify(message));
        } catch (_) {
            // onclose запустит обычное переподключение.
        }
    }

    function scheduleReconnect() {
        if (stopped || reconnectTimer !== null) return;

        reconnectTimer = window.setTimeout(function reconnectAdminSocket() {
            reconnectTimer = null;
            connectAdminWebSocket();
        }, RECONNECT_DELAY_MS);
    }

    function connectAdminWebSocket() {
        if (stopped || !token) return;

        if (
            websocket &&
            (websocket.readyState === WebSocket.OPEN ||
                websocket.readyState === WebSocket.CONNECTING)
        ) {
            return;
        }

        try {
            websocket = new WebSocket(WS_URL);
        } catch (_) {
            scheduleReconnect();
            return;
        }

        websocket.onopen = function authenticateAdminSocket() {
            sendMessage({
                type: "authenticate",
                token: token
            });
        };

        websocket.onmessage = function handleAdminSocketMessage(event) {
            let message;

            try {
                message = JSON.parse(event.data);
            } catch (_) {
                return;
            }

            const type = String(message.type || "").toLowerCase();

            if (type === "ping") {
                sendMessage({
                    type: "pong",
                    client_time: new Date().toISOString()
                });
                return;
            }

            if (type === "authenticated") {
                // За время установки или reconnect могли произойти изменения.
                scheduleSlidesReload(0);
                return;
            }

            if (type === "slides_updated") {
                // WebSocket сообщает только о факте изменения.
                // Полная актуальная модель по-прежнему загружается через REST.
                scheduleSlidesReload();
                return;
            }

            if (type === "auth_failed") {
                stopped = true;
                clearAuthAndRedirect();
            }
        };

        websocket.onclose = function handleAdminSocketClose() {
            websocket = null;
            scheduleReconnect();
        };

        websocket.onerror = function handleAdminSocketError() {
            try {
                websocket.close();
            } catch (_) {
                scheduleReconnect();
            }
        };
    }

    document.addEventListener("visibilitychange", function handleVisibilityChange() {
        if (document.visibilityState !== "visible") return;

        // После сна вкладки или временного разрыва сразу сверяем данные.
        scheduleSlidesReload(0);
        scheduleNextStatusBoundary();
        connectAdminWebSocket();
    });

    window.addEventListener("beforeunload", function stopAdminLiveUpdates() {
        stopped = true;

        if (reconnectTimer !== null) {
            window.clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }

        if (slideReloadTimer !== null) {
            window.clearTimeout(slideReloadTimer);
            slideReloadTimer = null;
        }

        if (statusBoundaryTimer !== null) {
            window.clearTimeout(statusBoundaryTimer);
            statusBoundaryTimer = null;
        }

        if (websocket) {
            try {
                websocket.close(1000, "page_closed");
            } catch (_) {
                // Страница всё равно закрывается.
            }
        }
    });

    connectAdminWebSocket();
})();
