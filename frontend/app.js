const API_URL = "/api";
const tabBtns = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");
const createForm = document.getElementById("createForm");
const createResult = document.getElementById("createResult");
const alertsContainer = document.getElementById("alerts");
const campaignsList = document.getElementById("campaignsList");
const refreshBtn = document.getElementById("refreshCampaigns");
const campaignSearch = document.getElementById("campaignSearch");
const campaignCount = document.getElementById("campaignCount");
const themeToggle = document.getElementById("themeToggle");
const trafficSourceHint = document.getElementById("trafficSourceHint");
const domainHint = document.getElementById("domainHint");
const groupHint = document.getElementById("groupHint");
const retryDefaults = document.getElementById("retryDefaults");
let availableOffers = [];
let campaigns = [];
let renderGeneration = 0;
let offersLoaded = false;
let offersLoadError = null;
const preferredDefaults = { domainId: 1813, groupId: 10332, trafficSourceId: 836 };

function setTheme(theme, persist = true) {
    document.body.dataset.theme = theme;
    const isDark = theme === "dark";
    themeToggle.querySelector("span[aria-hidden]").textContent = isDark ? "☼" : "☾";
    themeToggle.querySelector(".theme-toggle-label").textContent = isDark ? "Светлая тема" : "Тёмная тема";
    themeToggle.setAttribute("aria-label", isDark ? "Включить светлую тему" : "Включить тёмную тему");
    if (persist) {
        try { localStorage.setItem("keitaro-theme", theme); } catch { /* Storage may be unavailable. */ }
    }
}

try { setTheme(localStorage.getItem("keitaro-theme") || "dark", false); } catch { setTheme("dark", false); }
themeToggle.addEventListener("click", () => setTheme(document.body.dataset.theme === "dark" ? "light" : "dark"));

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let body = {};
    try { body = await response.json(); } catch { /* response may be empty */ }
    if (!response.ok) {
        const message = body.detail || body.message || `Request failed (${response.status})`;
        throw new Error(message);
    }
    return body;
}

function showAlert(message, type = "info") {
    const alert = document.createElement("div");
    alert.className = `alert alert-${type}`;
    alert.textContent = message;
    alertsContainer.appendChild(alert);
    setTimeout(() => alert.remove(), 4500);
}

function showResult(title, data) {
    createResult.className = "result-box error";
    createResult.innerHTML = `<h3>${escapeHtml(title)}</h3><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
    createResult.hidden = false;
}

function populateSelect(selectId, items, valueField = null, labelField = null, emptyText = "-- Выберите --") {
    const select = document.getElementById(selectId);
    const rows = items || [];
    select.replaceChildren(new Option(rows.length ? "-- Выберите --" : emptyText, ""));
    for (const item of rows) {
        const value = valueField ? item?.[valueField] : item;
        const label = labelField ? `${value} — ${item?.[labelField] ?? ""}` : item;
        select.add(new Option(label, value));
    }
}

function populateOfferSelect(select, offers, searchTerm = "", placeholder = "Выберите оффер…") {
    const previousValue = select.value;
    const query = searchTerm.trim().replace(/^#/, "").toLocaleLowerCase();
    const filtered = query
        ? offers.filter((offer) => String(offer.id).toLocaleLowerCase().includes(query))
        : offers;
    const prompt = searchTerm.trim() ? "2. Выберите найденный оффер…" : placeholder;
    select.replaceChildren(new Option(filtered.length ? prompt : "По этому ID офферов не найдено", ""));
    for (const offer of filtered) {
        select.add(new Option(`${offer.name} · #${offer.id}`, offer.id));
    }
    if (filtered.some((offer) => String(offer.id) === previousValue)) select.value = previousValue;
    return filtered;
}

function selectPreferredValue(selectId, preferredId) {
    const select = document.getElementById(selectId);
    const option = [...select.options].find((item) => item.value === String(preferredId));
    if (!option) return false;
    select.value = option.value;
    return true;
}

async function loadDefaults() {
    offersLoaded = false;
    offersLoadError = null;
    retryDefaults.disabled = true;
    retryDefaults.textContent = "Загружаем…";
    try {
        const data = await requestJson(`${API_URL}/defaults`);
        availableOffers = data.offers || [];
        offersLoaded = true;
        const geoSelect = document.getElementById("geoCode");
        geoSelect.replaceChildren(new Option("-- Выберите страну --", ""));
        const regionNames = typeof Intl.DisplayNames === "function"
            ? new Intl.DisplayNames(["ru"], { type: "region" })
            : null;
        for (const code of data.geo_codes || []) {
            const countryName = regionNames?.of(code) || code;
            geoSelect.add(new Option(`${countryName} — ${code}`, code));
        }
        populateOfferSelect(document.getElementById("offerId"), availableOffers);
        populateSelect("domainId", data.domains, "id", "name");
        populateSelect("groupId", data.groups, "id", "name");
        populateSelect("trafficSourceId", data.traffic_sources, "id", "name", "Нет источников трафика");
        const defaultResults = Object.entries(preferredDefaults).map(([selectId, id]) => ({
            selectId,
            id,
            selected: selectPreferredValue(selectId, id),
        }));
        const hasDefault = (selectId) => defaultResults.find((item) => item.selectId === selectId)?.selected;
        domainHint.textContent = hasDefault("domainId")
            ? "По умолчанию выбран kylovoa.com (#1813). Можно выбрать другой домен."
            : "Домен kylovoa.com (#1813) не пришёл из Keitaro; можно выбрать доступный домен.";
        groupHint.textContent = hasDefault("groupId")
            ? "По умолчанию выбрана группа FORTESTS (#10332)."
            : "Группа FORTESTS (#10332) не пришла из Keitaro; проверьте справочник кампаний.";
        retryDefaults.hidden = defaultResults.every((item) => item.selected);
        trafficSourceHint.textContent = !data.traffic_sources?.length
            ? "В Keitaro пока нет источников трафика. Создайте источник в разделе Traffic Sources и обновите список."
            : hasDefault("trafficSourceId")
                ? "По умолчанию выбран FORTESTS (#836). Можно выбрать другой источник."
                : "Источник FORTESTS (#836) не пришёл из Keitaro. Выберите доступный источник или проверьте справочник в трекере.";
        const missingDefaults = defaultResults.filter((item) => !item.selected);
        if (missingDefaults.length) {
            console.warn("Preferred Keitaro defaults were not present in API response:", missingDefaults);
        }
    } catch (error) {
        offersLoadError = error.message;
        trafficSourceHint.textContent = `Не удалось загрузить справочники: ${error.message}`;
        retryDefaults.hidden = false;
        showAlert(`Не удалось загрузить справочники: ${error.message}`, "error");
    } finally {
        retryDefaults.disabled = false;
        retryDefaults.textContent = "↻ Обновить справочники";
        if (campaigns.length) renderCampaigns();
    }
}

retryDefaults.addEventListener("click", loadDefaults);

document.getElementById("offerIdSearch").addEventListener("input", (event) => {
    populateOfferSelect(document.getElementById("offerId"), availableOffers, event.currentTarget.value);
});

tabBtns.forEach((button) => button.addEventListener("click", () => {
    tabBtns.forEach((item) => item.classList.toggle("active", item === button));
    tabContents.forEach((section) => section.classList.toggle("active", section.id === button.dataset.tab));
    const isManage = button.dataset.tab === "manage";
    document.getElementById("pageBreadcrumb").textContent = isManage ? "Кампании" : "Создать кампанию";
    if (isManage && !campaigns.length) loadCampaigns();
}));

document.querySelectorAll("[data-open-tab]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(`.tab-btn[data-tab="${button.dataset.openTab}"]`)?.click();
}));

createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = createForm.querySelector('[type="submit"]');
    submit.disabled = true;
    submit.classList.add("is-loading");
    submit.textContent = "Создаём…";
    try {
        const payload = {
            name: document.getElementById("campaignName").value.trim(),
            geo: document.getElementById("geoCode").value,
            offer_id: Number(document.getElementById("offerId").value),
            domain_id: Number(document.getElementById("domainId").value) || null,
            group_id: Number(document.getElementById("groupId").value),
            traffic_source_id: Number(document.getElementById("trafficSourceId").value),
        };
        const result = await requestJson(`${API_URL}/campaigns`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        showAlert(`Кампания «${result.campaign_name}» создана`, "success");
        createForm.reset();
        populateOfferSelect(document.getElementById("offerId"), availableOffers);
        campaigns = [];
        createResult.hidden = true;
        document.querySelector('.tab-btn[data-tab="manage"]')?.click();
    } catch (error) {
        showResult("Не удалось создать кампанию", { error: error.message }, false);
        showAlert(error.message, "error");
    } finally {
        submit.disabled = false;
        submit.classList.remove("is-loading");
        submit.innerHTML = '<span>Создать кампанию</span><span aria-hidden="true">→</span>';
    }
});

async function loadCampaigns() {
    refreshBtn.disabled = true;
    refreshBtn.classList.add("is-loading");
    refreshBtn.textContent = "Загружаем…";
    campaignsList.innerHTML = '<div class="loading-state"><span class="loading"></span> Загружаем кампании из Keitaro…</div>';
    try {
        campaigns = await requestJson(`${API_URL}/campaigns`);
        renderCampaigns();
    } catch (error) {
        campaignsList.innerHTML = `<div class="empty-state error-state">Не удалось загрузить кампании: ${escapeHtml(error.message)}</div>`;
        campaignCount.textContent = "";
    } finally {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove("is-loading");
        refreshBtn.innerHTML = '<span aria-hidden="true">↻</span> Обновить';
    }
}

function renderCampaigns() {
    const generation = ++renderGeneration;
    const query = campaignSearch.value.trim().toLocaleLowerCase();
    const filtered = campaigns.filter((campaign) =>
        [campaign.name, campaign.alias, campaign.id, campaign.state].some((value) => String(value ?? "").toLocaleLowerCase().includes(query))
    );
    campaignCount.textContent = `Показано ${filtered.length} из ${campaigns.length}`;
    if (!filtered.length) {
        campaignsList.innerHTML = `<div class="empty-state">${campaigns.length ? "По вашему запросу ничего не найдено." : "В Keitaro пока нет кампаний."}</div>`;
        return;
    }
    campaignsList.replaceChildren();

    let next = 0;
    const workers = Array.from({ length: Math.min(5, filtered.length) }, async () => {
        while (next < filtered.length) {
            const index = next++;
            const card = await createCampaignCard(filtered[index]);
            if (generation !== renderGeneration) return;
            campaignsList.appendChild(card);
        }
    });
    Promise.all(workers).catch((error) => console.error("Campaign rendering failed", error));
}

function offerLabel(offerId) {
    const offer = availableOffers.find((item) => Number(item.id) === Number(offerId));
    return offer ? `${offer.name} · #${offerId}` : `Оффер #${offerId}`;
}

async function createCampaignCard(campaign) {
    const card = document.createElement("article");
    card.className = "campaign-card";
    card.dataset.campaignId = campaign.id;
    card.innerHTML = `<div class="campaign-heading"><div><h3>${escapeHtml(campaign.name)}</h3><div class="alias">${escapeHtml(campaign.alias || "Без alias")}</div></div><span class="status-badge">${escapeHtml(campaign.state || "неизвестно")}</span></div><div class="campaign-meta"><span>ID <strong>${escapeHtml(campaign.id)}</strong></span><span>${escapeHtml(campaign.type || "Кампания")}</span><span>Создана ${escapeHtml(campaign.created_at ? new Date(campaign.created_at).toLocaleDateString("ru-RU") : "—")}</span></div><div class="stream-list-heading"><strong>Потоки</strong><span class="stream-total">Загружаем…</span></div><div class="stream-list"><div class="loading-state"><span class="loading"></span> Загружаем потоки…</div></div>`;
    const streamList = card.querySelector(".stream-list");
    try {
        const data = await requestJson(`${API_URL}/campaigns/${encodeURIComponent(campaign.id)}/offers`);
        if (data.pending_changes) card.classList.add("pending-changes");
        if (!data.streams?.length) {
            card.querySelector(".stream-total").textContent = "0 / 2";
            card.querySelector(".stream-total").classList.add("stream-count-warning");
            streamList.innerHTML = '<div class="stream-empty">Keitaro не вернул потоки для этой кампании.</div>';
            return card;
        }
        const count = card.querySelector(".stream-total");
        count.textContent = data.streams.length === 2 ? "2 потока" : `${data.streams.length} / 2`;
        if (data.streams.length !== 2) count.classList.add("stream-count-warning");
        if (data.pending_changes) {
            const actionBar = document.createElement("div");
            actionBar.className = "draft-action-bar";
            actionBar.innerHTML = `<span>Изменения · ${data.pending_count}. Закреплённые доли сохранятся, остаток распределится поровну.</span><button class="btn btn-apply" type="button">Отправить в Keitaro</button>`;
            actionBar.querySelector("button").addEventListener("click", (event) => applyCampaignDraft(campaign.id, event.currentTarget));
            card.append(actionBar);
        }
        streamList.replaceChildren(...data.streams.map((stream) => renderStream(campaign, stream)));
    } catch (error) {
        streamList.innerHTML = `<div class="stream-error"><strong>Не удалось загрузить потоки</strong><p>${escapeHtml(error.message)}</p><button class="btn btn-quiet retry-streams">Повторить</button></div>`;
        streamList.querySelector(".retry-streams").addEventListener("click", async (event) => {
            event.currentTarget.disabled = true;
            event.currentTarget.classList.add("is-loading");
            const replacement = await createCampaignCard(campaign);
            card.replaceWith(replacement);
        });
    }
    return card;
}

function renderStream(campaign, stream) {
    const editable = Boolean(stream.can_edit);
    const streamOffers = Array.isArray(stream.offers) ? stream.offers : [];
    const isEmpty = streamOffers.length === 0;
    const hasPendingChanges = Boolean(stream.has_pending_changes);
    const section = document.createElement("section");
    section.className = `stream ${editable ? "" : "readonly"}${isEmpty ? " empty-stream" : ""}${hasPendingChanges ? " has-draft" : ""}`;
    const offers = streamOffers.map((offer) => {
        const row = document.createElement("div");
        const pending = offer.draft_action;
        row.className = `offer-row${pending ? ` offer-${pending}` : ""}${offer.state === "disabled" ? " offer-disabled" : ""}`;
        const share = offer.share !== undefined && offer.share !== null ? `<span class="offer-share">${escapeHtml(offer.share)}%</span>` : "";
        const status = pending === "remove" ? '<span class="change-label">Будет удалён</span>' : pending === "add" ? '<span class="change-label added">Добавится</span>' : pending === "missing" ? '<span class="change-label">Удалён в Keitaro</span>' : offer.state === "disabled" ? '<span class="change-label">Отключён</span>' : "";
        const canPin = editable && pending !== "remove" && pending !== "missing" && offer.state !== "disabled";
        const pinControl = canPin
            ? `<button class="pin-offer${offer.pinned ? " is-pinned" : ""}" type="button" aria-pressed="${Boolean(offer.pinned)}" title="${offer.pinned ? `Закреплено: ${offer.pinned_share ?? offer.share}%` : "Закрепить текущую долю"}"><span aria-hidden="true">📌</span> ${offer.pinned ? "Закреплено" : "Закрепить"}</button>`
            : "";
        const action = pending === "remove" || pending === "missing"
            ? '<button class="restore-offer" type="button">Вернуть</button>'
            : editable ? `<button class="remove-offer" type="button">${pending === "add" ? "Отменить" : "Убрать"}</button>` : "";
        row.innerHTML = `<span class="offer-title">${escapeHtml(offerLabel(offer.offer_id))}</span>${share}${status}${pinControl}${action}`;
        if (editable && (pending === "remove" || pending === "missing")) row.querySelector(".restore-offer")?.addEventListener("click", () => restoreStagedOffer(campaign.id, stream.stream_id, offer.offer_id));
        else if (editable) row.querySelector(".remove-offer")?.addEventListener("click", () => removeOffer(campaign.id, stream.stream_id, offer.offer_id));
        row.querySelector(".pin-offer")?.addEventListener("click", () => toggleOfferPin(campaign.id, stream.stream_id, offer.offer_id, Number(offer.share || 0), Boolean(offer.pinned)));
        return row;
    });
    const emptyMessage = stream.schema === "redirect"
        ? "Редиректный поток · без офферов"
        : editable ? "Офферов пока нет · добавьте первый" : "В потоке пока нет офферов";
    section.innerHTML = `<div class="stream-header"><div><h4>${escapeHtml(stream.stream_name || `Поток ${stream.stream_id}`)}</h4><span class="stream-type">${escapeHtml(stream.schema || "неизвестно")} · ${escapeHtml(stream.type || "")}</span></div><span class="stream-badge">${hasPendingChanges ? "Есть изменения" : editable ? "Можно редактировать" : "Только просмотр"}</span></div><div class="offer-list${isEmpty ? " is-empty" : ""}">${isEmpty ? `<span class="stream-empty">${escapeHtml(emptyMessage)}</span>` : ""}</div>${editable ? '<div class="offer-controls"><div class="offer-picker"><label class="offer-search-help">1. Введите ID, чтобы отфильтровать список</label><input class="offer-id-search" type="search" placeholder="Например, 18001" inputmode="numeric" autocomplete="off" aria-label="Шаг 1. Введите ID оффера"><label class="offer-search-help">2. Выберите оффер из списка</label><select aria-label="Шаг 2. Выберите оффер"><option value="">Выберите оффер…</option></select></div><button class="btn btn-success" type="button">Добавить в черновик</button></div>' : ""}`;
    if (offers.length) section.querySelector(".offer-list").replaceChildren(...offers);
    if (editable) {
        const select = section.querySelector("select");
        const search = section.querySelector(".offer-id-search");
        const existing = new Set(streamOffers.map((offer) => Number(offer.offer_id)));
        const addableOffers = availableOffers.filter((item) => !existing.has(Number(item.id)));
        const refreshOfferOptions = () => {
            const filtered = populateOfferSelect(select, addableOffers, search.value);
            if (!offersLoaded) select.options[0].textContent = offersLoadError
                ? "Не удалось загрузить список офферов"
                : "Загружаем список офферов…";
            else if (!availableOffers.length) select.options[0].textContent = "В Keitaro нет офферов";
            else if (!addableOffers.length) select.options[0].textContent = "Все офферы уже в этом потоке";
            else if (search.value && !filtered.length) select.options[0].textContent = "Офферы по этому ID не найдены";
        };
        refreshOfferOptions();
        const button = section.querySelector(".offer-controls button");
        button.disabled = true;
        button.title = !offersLoaded
            ? offersLoadError ? "Не удалось загрузить справочник офферов" : "Справочник офферов ещё загружается"
            : !addableOffers.length ? "Нет офферов для добавления в этот поток" : "Сначала выберите оффер";
        select.addEventListener("change", () => {
            button.disabled = !select.value;
            button.title = select.value ? "Добавить выбранный оффер в черновик" : "Сначала выберите оффер";
        });
        search.addEventListener("input", () => {
            refreshOfferOptions();
            button.disabled = !select.value;
            button.title = select.value ? "Добавить выбранный оффер в черновик" : "Сначала выберите оффер";
        });
        button.addEventListener("click", () => select.value && addOffer(campaign.id, Number(select.value), stream.stream_id, button));
    }
    return section;
}

async function addOffer(campaignId, offerId, streamId, button) {
    button.disabled = true;
    button.classList.add("is-loading");
    try {
        await requestJson(`${API_URL}/campaigns/${campaignId}/offers?offer_id=${offerId}&stream_id=${streamId}`, { method: "POST" });
        showAlert(`Оффер #${offerId} добавлен в черновик. В Keitaro пока не отправлен.`, "success");
        await refreshCampaignCard(campaignId);
    } catch (error) {
        showAlert(`Не удалось добавить оффер: ${error.message}`, "error");
        button.disabled = false;
        button.classList.remove("is-loading");
    }
}

async function removeOffer(campaignId, streamId, offerId) {
    try {
        await requestJson(`${API_URL}/campaigns/${campaignId}/offers/${offerId}?stream_id=${streamId}`, { method: "DELETE" });
        showAlert(`${offerLabel(offerId)} отмечен к удалению. Изменение пока только в черновике.`, "info");
        await refreshCampaignCard(campaignId);
    } catch (error) {
        showAlert(`Не удалось удалить оффер: ${error.message}`, "error");
    }
}

async function restoreStagedOffer(campaignId, streamId, offerId) {
    try {
        const result = await requestJson(`${API_URL}/campaigns/${campaignId}/offers/${offerId}/restore?stream_id=${streamId}`, { method: "POST" });
        showAlert(result.action === "add_staged"
            ? `${offerLabel(offerId)} добавлен в черновик. Отправьте изменения, чтобы вернуть его в Keitaro.`
            : `${offerLabel(offerId)} возвращён в поток. Черновое удаление отменено.`, "success");
        await refreshCampaignCard(campaignId);
    } catch (error) {
        showAlert(`Не удалось вернуть оффер: ${error.message}`, "error");
    }
}

async function toggleOfferPin(campaignId, streamId, offerId, share, isPinned) {
    try {
        const url = `${API_URL}/campaigns/${campaignId}/streams/${streamId}/offers/${offerId}/pin`;
        await requestJson(url, isPinned
            ? { method: "DELETE" }
            : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ share }) });
        showAlert(isPinned ? `Доля оффера #${offerId} откреплена.` : `Доля ${share}% для оффера #${offerId} закреплена.`, "success");
        await refreshCampaignCard(campaignId);
    } catch (error) {
        showAlert(`Не удалось изменить закрепление: ${error.message}`, "error");
    }
}

async function applyCampaignDraft(campaignId, button) {
    button.disabled = true;
    button.classList.add("is-loading");
    button.textContent = "Отправляем…";
    try {
        const result = await requestJson(`${API_URL}/campaigns/${campaignId}/offers/apply`, { method: "POST" });
        showAlert(`Изменения отправлены в Keitaro. Обновлено потоков: ${result.updated_streams ?? 0}.`, "success");
        await refreshCampaignCard(campaignId);
    } catch (error) {
        button.disabled = false;
        button.classList.remove("is-loading");
        button.textContent = "Повторить отправку";
        showAlert(`Не удалось применить изменения: ${error.message}`, "error");
    }
}

async function refreshCampaignCard(campaignId) {
    const campaign = campaigns.find((item) => Number(item.id) === Number(campaignId));
    const oldCard = campaignsList.querySelector(`[data-campaign-id="${CSS.escape(String(campaignId))}"]`);
    if (!campaign || !oldCard) return;
    oldCard.classList.add("is-refreshing");
    try {
        const newCard = await createCampaignCard(campaign);
        oldCard.replaceWith(newCard);
    } catch (error) {
        oldCard.classList.remove("is-refreshing");
        showAlert(`Не удалось обновить кампанию: ${error.message}`, "error");
    }
}

refreshBtn.addEventListener("click", loadCampaigns);
campaignSearch.addEventListener("input", renderCampaigns);
document.addEventListener("DOMContentLoaded", loadDefaults);
document.addEventListener("DOMContentLoaded", loadCampaigns);
document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.querySelector('.tab-btn[data-tab="manage"]').click();
        campaignSearch.focus();
    }
});
