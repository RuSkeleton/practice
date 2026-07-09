function getImageCacheConfig() {
    if (typeof CONFIG !== "undefined") return CONFIG;
    if (window.CONFIG) return window.CONFIG;

    return {
        IMAGE_CACHE_NAME: "digital_signage_images_v2"
    };
}

function getImageCacheState() {
    if (typeof state !== "undefined") return state;

    if (!window.__imageCacheState) {
        window.__imageCacheState = {
            serverOnline: true,
            objectUrls: []
        };
    }

    return window.__imageCacheState;
}

function getImageSourceForCache(element) {
    if (typeof getImageElementSource === "function") {
        return getImageElementSource(element);
    }

    return String(
        element.src ||
        element.url ||
        element.value ||
        (element.image && element.image.src) ||
        ""
    );
}

async function cacheImagesForSlides(slides) {
    if (!("caches" in window)) return;

    const config = getImageCacheConfig();
    const urls = collectImageUrlsFromSlides(slides).map(toAbsoluteUrl);

    if (urls.length === 0) return;

    try {
        const cache = await caches.open(config.IMAGE_CACHE_NAME);

        await Promise.all(urls.map(async url => {
            try {
                const response = await fetch(url, { cache: "reload" });
                if (response.ok) {
                    await cache.put(url, response.clone());
                }
            } catch (_) {}
        }));
    } catch (_) {}
}

function collectImageUrlsFromSlides(slides) {
    const urls = new Set();

    for (const slide of slides || []) {
        if (!slide) continue;

        if (
            slide.background &&
            String(slide.background.type).toLowerCase() === "image" &&
            slide.background.value
        ) {
            urls.add(String(slide.background.value));
        }

        for (const element of slide.elements || []) {
            if (String(element.type || "").toLowerCase() === "image") {
                const src = getImageSourceForCache(element);
                if (src) urls.add(src);
            }
        }
    }

    return [...urls];
}

async function pruneImageCacheForSlides(slides) {
    if (!("caches" in window)) return;

    const config = getImageCacheConfig();
    const neededUrls = new Set(
        collectImageUrlsFromSlides(slides).map(toAbsoluteUrl)
    );

    try {
        const cache = await caches.open(config.IMAGE_CACHE_NAME);
        const requests = await cache.keys();

        await Promise.all(requests.map(request => {
            if (neededUrls.has(request.url)) {
                return Promise.resolve(false);
            }

            return cache.delete(request);
        }));
    } catch (_) {}
}

async function getCachedImageUrl(src) {
    if (!("caches" in window) || !src) return "";

    const config = getImageCacheConfig();
    const runtimeState = getImageCacheState();

    try {
        const cache = await caches.open(config.IMAGE_CACHE_NAME);
        const response = await cache.match(toAbsoluteUrl(src));

        if (!response) return "";

        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);

        runtimeState.objectUrls.push(objectUrl);

        return objectUrl;
    } catch (_) {
        return "";
    }
}

async function hydrateRenderedImages(root) {
    const runtimeState = getImageCacheState();

    if (!root) {
        root =
            (window.DOM && window.DOM.slideRoot) ||
            document.getElementById("slideRoot") ||
            document.getElementById("preview-place");
    }

    if (!root) return;

    const images = [...root.querySelectorAll("img[data-cache-src]")];

    for (const img of images) {
        const cacheSrc = img.dataset.cacheSrc;

        img.onerror = async () => {
            const cachedUrl = await getCachedImageUrl(cacheSrc);

            if (cachedUrl && img.src !== cachedUrl) {
                img.src = cachedUrl;
            }
        };

        if (!runtimeState.serverOnline) {
            const cachedUrl = await getCachedImageUrl(cacheSrc);

            if (cachedUrl) {
                img.src = cachedUrl;
            }
        }
    }

    const backgrounds = [...root.querySelectorAll("[data-bg-cache-src]")];

    for (const node of backgrounds) {
        if (runtimeState.serverOnline) continue;

        const cachedUrl = await getCachedImageUrl(node.dataset.bgCacheSrc);

        if (cachedUrl) {
            node.style.backgroundImage = "url(" + JSON.stringify(cachedUrl) + ")";
        }
    }
}

function clearImageObjectUrls() {
    const runtimeState = getImageCacheState();

    for (const objectUrl of runtimeState.objectUrls) {
        URL.revokeObjectURL(objectUrl);
    }

    runtimeState.objectUrls = [];
}