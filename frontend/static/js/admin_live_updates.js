"use strict";

(function initializeAdminLiveUpdates() {
    const WS_URL = (
        window.location.protocol === "https:" ? "wss:" : "ws:"
    ) + "//" + window.location.host + "/ws/admin";

    const RECONNECT_DELAY_MS = 3000;
    const RELOAD_DEBOUNCE_MS = 100;

    let websocket = null;
    let reconnectTimer = null;
    let slideReloadTimer = null;
    let screenReloadTimer = null;
    let userReloadTimer = null;
    let statusBoundaryTimer = null;
    let slidesLoadPromise = null;
    let screensLoadPromise = null;
    let usersLoadPromise = null;
    let stopped = false;
    let socketRole = "";
    let cachedSlides = [];

    const originalLoadSlides = loadSlides;
    const originalLoadScreens = loadScreens;
    const originalLoadUsers = loadUsers;
    const originalRenderSlides = renderSlides;

    function parseDateForStatus(value) {
        if (typeof parseServerDate === "function") {
            return parseServerDate(value);
        }
        return new Date(value);
    }

    function wrapDeduplicatedLoad(originalLoad, getPromise, setPromise) {
        return function deduplicatedLoad() {
            const activePromise = getPromise();
            if (activePromise !== null) {
                return activePromise;
            }

            let nextPromise = Promise.resolve(originalLoad());
            setPromise(nextPromise);

            nextPromise = nextPromise.finally(function finishLoad() {
                setPromise(null);
            });
            setPromise(nextPromise);
            return nextPromise;
        };
    }

    // Одновременные причины обновления объединяются. Например, собственный
    // CRUD-запрос и WebSocket-событие не запускают два параллельных GET.
    loadSlides = wrapDeduplicatedLoad(
        originalLoadSlides,
        function getSlidesPromise() { return slidesLoadPromise; },
        function setSlidesPromise(value) { slidesLoadPromise = value; }
    );

    loadScreens = wrapDeduplicatedLoad(
        originalLoadScreens,
        function getScreensPromise() { return screensLoadPromise; },
        function setScreensPromise(value) { screensLoadPromise = value; }
    );

    loadUsers = wrapDeduplicatedLoad(
        originalLoadUsers,
        function getUsersPromise() { return usersLoadPromise; },
        function setUsersPromise(value) { usersLoadPromise = value; }
    );

    function scheduleNextStatusBoundary() {
        if (statusBoundaryTimer !== null) {
            window.clearTimeout(statusBoundaryTimer);
            statusBoundaryTimer = null;
        }

        const now = Date.now();
        let nextBoundary = null;

        for (const slide of cachedSlides) {
            const start = parseDateForStatus(slide.start_date).getTime();
            const end = parseDateForStatus(slide.end_date).getTime();

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

    // Начало и окончание показа меняют статус слайда без изменения БД.
    // Поэтому интерфейс перерисовывается локально на ближайшей границе дат.
    renderSlides = function renderSlidesWithLiveStatuses(slides) {
        cachedSlides = Array.isArray(slides) ? slides : [];
        originalRenderSlides(cachedSlides);
        scheduleNextStatusBoundary();
    };

    function scheduleReload(timerName, callback, delayMs = RELOAD_DEBOUNCE_MS) {
        let currentTimer = null;

        if (timerName === "slides") currentTimer = slideReloadTimer;
        if (timerName === "screens") currentTimer = screenReloadTimer;
        if (timerName === "users") currentTimer = userReloadTimer;

        if (currentTimer !== null) {
            window.clearTimeout(currentTimer);
        }

        const timer = window.setTimeout(function reloadAfterEvent() {
            if (timerName === "slides") slideReloadTimer = null;
            if (timerName === "screens") screenReloadTimer = null;
            if (timerName === "users") userReloadTimer = null;

            Promise.resolve(callback()).catch(function ignoreHandledLoadError() {
                // Существующие load-функции сами отображают ошибки в интерфейсе.
            });
        }, delayMs);

        if (timerName === "slides") slideReloadTimer = timer;
        if (timerName === "screens") screenReloadTimer = timer;
        if (timerName === "users") userReloadTimer = timer;
    }

    function scheduleSlidesReload(delayMs = RELOAD_DEBOUNCE_MS) {
        scheduleReload("slides", loadSlides, delayMs);
    }

    function scheduleScreensReload(delayMs = RELOAD_DEBOUNCE_MS) {
        scheduleReload("screens", loadScreens, delayMs);
    }

    function canLoadUsers() {
        return socketRole === "admin";
    }

    function scheduleUsersReload(delayMs = RELOAD_DEBOUNCE_MS) {
        if (!canLoadUsers()) return;
        scheduleReload("users", loadUsers, delayMs);
    }

    function sendMessage(message) {
        if (!websocket || websocket.readyState !== WebSocket.OPEN) return;

        try {
            websocket.send(JSON.stringify(message));
        } catch (_) {
            // onclose запустит обычное переподключение.
        }
    }

    function redirectToLogin() {
        if (typeof clearAuthAndRedirect === "function") {
            clearAuthAndRedirect();
            return;
        }

        localStorage.removeItem("token");
        window.location.href = "/main.html";
    }

    function scheduleReconnect() {
        if (stopped || reconnectTimer !== null) return;

        reconnectTimer = window.setTimeout(function reconnectAdminSocket() {
            reconnectTimer = null;
            connectAdminWebSocket();
        }, RECONNECT_DELAY_MS);
    }

    function synchronizeAllVisibleData() {
        scheduleSlidesReload(0);
        scheduleScreensReload(0);
        scheduleUsersReload(0);
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
                socketRole = String(message.role || "").toLowerCase();

                // За время установки соединения или reconnect могли произойти
                // изменения. Выполняется одна сверка, а не polling.
                synchronizeAllVisibleData();
                return;
            }

            if (type === "slides_updated") {
                scheduleSlidesReload();
                return;
            }

            if (type === "screens_updated") {
                scheduleScreensReload();
                return;
            }

            if (type === "users_updated") {
                scheduleUsersReload();
                return;
            }

            if (type === "auth_failed") {
                stopped = true;
                redirectToLogin();
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

        // Браузер мог приостановить вкладку или WebSocket. После возвращения
        // выполняется одна сверка и восстанавливается соединение.
        synchronizeAllVisibleData();
        scheduleNextStatusBoundary();
        connectAdminWebSocket();
    });

    window.addEventListener("beforeunload", function stopAdminLiveUpdates() {
        stopped = true;

        for (const timer of [
            reconnectTimer,
            slideReloadTimer,
            screenReloadTimer,
            userReloadTimer,
            statusBoundaryTimer
        ]) {
            if (timer !== null) {
                window.clearTimeout(timer);
            }
        }

        reconnectTimer = null;
        slideReloadTimer = null;
        screenReloadTimer = null;
        userReloadTimer = null;
        statusBoundaryTimer = null;

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
