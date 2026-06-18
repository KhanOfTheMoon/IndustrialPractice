const API_BASE_URL = "http://127.0.0.1:8000";

let lastApiData = null;
let lastBestLimit = 20;

let currentRequestId = 0;
let currentAbortController = null;

function formatPrice(price) {
    if (price === null || price === undefined) {
        return "Нет данных";
    }

    return Number(price).toLocaleString("ru-RU") + " ₸";
}

function escapeHtml(text) {
    if (text === null || text === undefined) {
        return "";
    }

    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function sortOffers(offers, sortMode) {
    const sorted = [...offers];

    if (sortMode === "price_asc") {
        sorted.sort((a, b) => Number(a.price || 0) - Number(b.price || 0));
    }

    if (sortMode === "price_desc") {
        sorted.sort((a, b) => Number(b.price || 0) - Number(a.price || 0));
    }

    if (sortMode === "score_desc") {
        sorted.sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
    }

    return sorted;
}

function getSortLabel(sortMode) {
    if (sortMode === "price_asc") {
        return "сначала дешёвые";
    }

    if (sortMode === "price_desc") {
        return "сначала дорогие";
    }

    return "по выгодности";
}

function getSourceLabel(source) {
    if (source === "satu") {
        return "Satu.kz";
    }

    if (source === "dns") {
        return "DNS";
    }

    if (source === "all") {
        return "Satu.kz + DNS";
    }

    return source || "Не указан";
}

function getImageHtml(product) {
    if (!product.image_url) {
        return `
            <div class="product-image product-image-placeholder">
                Нет фото
            </div>
        `;
    }

    return `
        <img
            class="product-image"
            src="${escapeHtml(product.image_url)}"
            alt="${escapeHtml(product.title)}"
            onerror="this.outerHTML='<div class=&quot;product-image product-image-placeholder&quot;>Фото не загрузилось</div>'"
        >
    `;
}

function toggleSuppliers() {
    const block = document.getElementById("suppliersBlock");

    if (!block) {
        return;
    }

    if (block.style.display === "none") {
        block.style.display = "block";
    } else {
        block.style.display = "none";
    }
}

function validateInputs(query, startPage, endPage, bestLimit) {
    if (!query) {
        return "Введите название товара.";
    }

    if (!Number.isInteger(startPage) || startPage < 1) {
        return "Начальная страница должна быть не меньше 1.";
    }

    if (!Number.isInteger(endPage) || endPage < 1) {
        return "Конечная страница должна быть не меньше 1.";
    }

    if (endPage < startPage) {
        return "Конечная страница не может быть меньше начальной.";
    }

    if (endPage > 20) {
        return "Максимальная конечная страница — 20.";
    }

    if (!Number.isInteger(bestLimit) || bestLimit < 1 || bestLimit > 50) {
        return "Количество выгодных предложений должно быть от 1 до 50.";
    }

    return null;
}

function renderEmptyResult(data) {
    const resultDiv = document.getElementById("result");
    const selectedCategory = document.getElementById("categoryInput").value;
    const selectedSource = document.getElementById("sourceInput").value;

    resultDiv.innerHTML = `
        <div class="summary">
            <h2>Ничего не найдено</h2>
            <p>${escapeHtml(data.message || "Релевантные товары не найдены.")}</p>
            <p><b>Запрос:</b> ${escapeHtml(data.query)}</p>
            <p><b>Сайт:</b> ${escapeHtml(getSourceLabel(data.selected_source || selectedSource))}</p>
            <p><b>Категория:</b> ${escapeHtml(data.selected_category || selectedCategory)}</p>
            <p><b>Страницы:</b> ${data.start_page}-${data.end_page}</p>
            <p><b>Строгий поиск:</b> ${data.strict_title_match ? "Да" : "Нет"}</p>
            <p><b>Удаление выбросов:</b> ${data.remove_outliers ? "Да" : "Нет"}</p>
        </div>
    `;
}

function renderStatsBlock(data, stats, sortMode, selectedCategory, selectedSource, bestLimit) {
    return `
        <div class="summary">
            <h2>Результат анализа</h2>

            <p>
                <span class="badge">Запрос: ${escapeHtml(data.query)}</span>
                <span class="badge">Сайт: ${escapeHtml(getSourceLabel(data.selected_source || selectedSource))}</span>
                <span class="badge">Категория: ${escapeHtml(data.selected_category || selectedCategory)}</span>
                <span class="badge">Страницы: ${data.start_page}-${data.end_page}</span>
                <span class="badge">Строгий поиск: ${data.strict_title_match ? "Да" : "Нет"}</span>
                <span class="badge">Удаление выбросов: ${data.remove_outliers ? "Да" : "Нет"}</span>
                <span class="badge">Топ: ${data.best_limit || bestLimit}</span>
                <span class="badge">Сортировка: ${getSortLabel(sortMode)}</span>
            </p>

            <p><b>Найдено до удаления выбросов:</b> ${data.total_before_outlier_filter}</p>
            <p><b>Удалено как ценовые выбросы:</b> ${data.removed_as_outliers}</p>
            <p><b>Итоговое количество товаров:</b> ${data.total_found}</p>

            <div class="stats-grid">
                <div class="stat-card">
                    <b>Минимальная цена</b><br>
                    ${formatPrice(stats.min_price)}
                </div>
                <div class="stat-card">
                    <b>Максимальная цена</b><br>
                    ${formatPrice(stats.max_price)}
                </div>
                <div class="stat-card">
                    <b>Средняя цена</b><br>
                    ${formatPrice(stats.average_price)}
                </div>
                <div class="stat-card">
                    <b>Медианная цена</b><br>
                    ${formatPrice(stats.median_price)}
                </div>
            </div>

            <p>
                <b>Нормальный диапазон:</b>
                ${formatPrice(stats.normal_range.from)} — ${formatPrice(stats.normal_range.to)}
            </p>
        </div>
    `;
}

function renderSuppliersBlock(suppliers) {
    let html = `
        <div class="summary supplier-list">
            <h2>
                Поставщики
                <button class="secondary-button" type="button" onclick="toggleSuppliers()">Показать / скрыть</button>
            </h2>

            <div id="suppliersBlock" style="display: none;">
    `;

    if (!suppliers || suppliers.length === 0) {
        html += `<p>Нет данных по поставщикам.</p>`;
    } else {
        suppliers.forEach(supplier => {
            html += `
                <p>
                    <b>${escapeHtml(supplier.name || "Unknown")}</b> —
                    товаров: ${supplier.products_count},
                    средняя цена: ${formatPrice(supplier.average_price)},
                    диапазон: ${formatPrice(supplier.min_price)} — ${formatPrice(supplier.max_price)}
                </p>
            `;
        });
    }

    html += `
            </div>
        </div>
    `;

    return html;
}

function renderProductCard(product, index) {
    return `
        <div class="product">
            ${getImageHtml(product)}

            <div class="product-content">
                <h3>${index + 1}. ${escapeHtml(product.title)}</h3>

                <p class="price">${formatPrice(product.price)}</p>

                <p>
                    <b>Источник:</b> ${escapeHtml(getSourceLabel(product.source || "satu"))}
                </p>

                <p class="supplier">
                    <b>Поставщик:</b> ${escapeHtml(product.supplier || "Не указан")}
                </p>

                <p>
                    <b>Рейтинг:</b> ${product.rating ? product.rating : "Нет данных"}
                    |
                    <b>Отзывы:</b> ${product.reviews_count ? product.reviews_count : "Нет данных"}
                </p>

                <p>
                    <b>Страница источника:</b> ${product.source_page || "Не указана"}
                </p>

                <p>
                    <b>Наличие:</b> ${product.available ? "В наличии" : "Нет данных / не в наличии"}
                </p>

                <p class="score">
                    <b>Score:</b> ${product.score}
                </p>

                <p>
                    <b>Почему выбрано:</b> ${escapeHtml(product.reason)}
                </p>

                <p>
                    <a href="${escapeHtml(product.url)}" target="_blank" rel="noopener noreferrer">
                        Открыть товар
                    </a>
                </p>
            </div>
        </div>
    `;
}

function renderOffersBlock(offers) {
    let html = `<h2 class="offers-title">Самые выгодные предложения</h2>`;

    if (!offers || offers.length === 0) {
        html += `
            <div class="summary">
                <p>Выгодные предложения не найдены.</p>
            </div>
        `;

        return html;
    }

    offers.forEach((product, index) => {
        html += renderProductCard(product, index);
    });

    return html;
}

function renderResults(data) {
    const resultDiv = document.getElementById("result");
    const sortMode = document.getElementById("sortInput").value;
    const selectedCategory = document.getElementById("categoryInput").value;
    const selectedSource = document.getElementById("sourceInput").value;
    const bestLimit = lastBestLimit;

    if (data.total_found === 0) {
        renderEmptyResult(data);
        return;
    }

    const stats = data.price_stats;
    const sortedOffers = sortOffers(data.best_offers || [], sortMode);

    let html = "";

    html += renderStatsBlock(data, stats, sortMode, selectedCategory, selectedSource, bestLimit);
    html += renderSuppliersBlock(data.suppliers);
    html += renderOffersBlock(sortedOffers);

    resultDiv.innerHTML = html;
}

async function analyzeProduct() {
    const query = document.getElementById("queryInput").value.trim();
    const selectedSource = document.getElementById("sourceInput").value;
    const selectedCategory = document.getElementById("categoryInput").value;
    const startPage = Number(document.getElementById("startPageInput").value);
    const endPage = Number(document.getElementById("endPageInput").value);
    const bestLimit = Number(document.getElementById("bestLimitInput").value);
    const removeOutliers = document.getElementById("removeOutliersInput").checked;
    const strictTitleMatch = document.getElementById("strictTitleMatchInput").checked;

    const resultDiv = document.getElementById("result");
    const searchButton = document.getElementById("searchButton");

    const validationError = validateInputs(query, startPage, endPage, bestLimit);

    if (validationError) {
        resultDiv.innerHTML = `<div class="error">${validationError}</div>`;
        return;
    }

    // Увеличиваем ID актуального запроса
    currentRequestId += 1;
    const requestId = currentRequestId;

    // Отменяем предыдущий запрос, если он ещё выполняется
    if (currentAbortController) {
        currentAbortController.abort();
    }

    currentAbortController = new AbortController();

    resultDiv.innerHTML = `
        <div class="loading">
            Идёт поиск и анализ товаров. Если выбран DNS или несколько страниц, это может занять дольше.
        </div>
    `;

    if (searchButton) {
        searchButton.disabled = true;
        searchButton.textContent = "Ищу...";
    }

    const url =
        `${API_BASE_URL}/analyze?query=${encodeURIComponent(query)}` +
        `&selected_source=${encodeURIComponent(selectedSource)}` +
        `&selected_category=${encodeURIComponent(selectedCategory)}` +
        `&start_page=${encodeURIComponent(startPage)}` +
        `&end_page=${encodeURIComponent(endPage)}` +
        `&remove_outliers=${encodeURIComponent(removeOutliers)}` +
        `&strict_title_match=${encodeURIComponent(strictTitleMatch)}` +
        `&best_limit=${encodeURIComponent(bestLimit)}`;

    try {
        const response = await fetch(url, {
            signal: currentAbortController.signal,
        });

        const data = await response.json();

        // Если после этого запроса уже был отправлен новый — этот результат игнорируем
        if (requestId !== currentRequestId) {
            console.log("Ignored old response:", requestId);
            return;
        }

        console.log("API response:", data);

        if (data.error) {
            resultDiv.innerHTML = `<div class="error">${escapeHtml(data.error)}</div>`;
            return;
        }

        lastApiData = data;
        lastBestLimit = bestLimit;

        renderResults(data);

    } catch (error) {
        if (error.name === "AbortError") {
            console.log("Previous request was cancelled");
            return;
        }

        // Если ошибка пришла от старого запроса — игнорируем
        if (requestId !== currentRequestId) {
            return;
        }

        console.error(error);

        resultDiv.innerHTML = `
            <div class="error">
                Ошибка при запросе к backend. Проверь, что сервер запущен на http://127.0.0.1:8000
            </div>
        `;
    } finally {
        // Кнопку возвращаем только если это всё ещё актуальный запрос
        if (requestId === currentRequestId && searchButton) {
            searchButton.disabled = false;
            searchButton.textContent = "Найти";
        }
    }
}

document.getElementById("searchButton").addEventListener("click", analyzeProduct);

document.getElementById("sortInput").addEventListener("change", function () {
    if (lastApiData) {
        renderResults(lastApiData);
    }
});
