(function () {
    function closeAllSearchableSelects(exceptWrap = null) {
        document.querySelectorAll(".searchable-select-wrap.open").forEach((wrap) => {
            if (exceptWrap && wrap === exceptWrap) return;
            wrap.classList.remove("open");
        });
    }

    function ensureSearchableSelect(selectEl) {
        if (!selectEl || selectEl.dataset.searchableBound === "1") return;
        if (!selectEl.classList.contains("searchable-select")) return;

        const wrap = document.createElement("div");
        wrap.className = "searchable-select-wrap";

        const input = document.createElement("input");
        input.type = "text";
        input.className = "searchable-select-input";
        input.placeholder = selectEl.dataset.placeholder || "검색 또는 선택";

        const list = document.createElement("div");
        list.className = "searchable-select-list";

        selectEl.parentNode.insertBefore(wrap, selectEl);
        wrap.appendChild(input);
        wrap.appendChild(list);
        wrap.appendChild(selectEl);

        selectEl.style.display = "none";

        function renderOptions(filterText) {
            const keyword = String(filterText || "").toLowerCase().trim();
            const options = Array.from(selectEl.options || []);
            const currentValue = selectEl.value || "";

            list.innerHTML = "";

            options.forEach((opt) => {
                const value = String(opt.value || "");
                const text = String(opt.text || "");

                if (!value && !text) return;
                if (keyword && !text.toLowerCase().includes(keyword)) return;

                const item = document.createElement("button");
                item.type = "button";
                item.className = "searchable-select-item";
                if (value === currentValue) item.classList.add("active");
                item.textContent = text;
                item.addEventListener("mousedown", (e) => e.preventDefault());
                item.addEventListener("click", function (e) {
                    e.stopPropagation();
                    selectEl.value = value;
                    input.value = text;
                    wrap.classList.remove("open");
                    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
                });
                list.appendChild(item);
            });
        }

        function syncInputFromSelect() {
            const selected = selectEl.options[selectEl.selectedIndex];
            input.value = selected ? selected.text : "";
        }

        function openPanel() {
            closeAllSearchableSelects(wrap);
            wrap.classList.add("open");
            renderOptions(input.value);
        }

        input.addEventListener("focus", openPanel);
        input.addEventListener("click", function (e) {
            e.stopPropagation();
            openPanel();
        });
        input.addEventListener("input", function () {
            wrap.classList.add("open");
            renderOptions(input.value);
        });

        wrap.addEventListener("mousedown", function (e) {
            e.stopPropagation();
        });
        wrap.addEventListener("click", function (e) {
            e.stopPropagation();
        });

        selectEl.addEventListener("change", function () {
            syncInputFromSelect();
            renderOptions(input.value);
        });

        syncInputFromSelect();
        renderOptions("");

        selectEl.dataset.searchableBound = "1";
    }

    function initSearchableSelects(scope) {
        const root = scope || document;
        root.querySelectorAll("select.searchable-select").forEach(ensureSearchableSelect);
    }

    document.addEventListener("mousedown", function (e) {
        const target = e.target;
        if (!(target instanceof HTMLElement)) return;
        const currentWrap = target.closest(".searchable-select-wrap");
        closeAllSearchableSelects(currentWrap);
    });

    window.initFactsSearchableSelects = initSearchableSelects;
})();
