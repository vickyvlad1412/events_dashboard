const DEBOUNCE_MS = 220;
const MIN_QUERY = 2;

function debounce(fn, wait) {
	let timer;
	return (...args) => {
		clearTimeout(timer);
		timer = setTimeout(() => fn(...args), wait);
	};
}

function el(tag, className, text) {
	const node = document.createElement(tag);
	if (className) {
		node.className = className;
	}
	if (text !== undefined && text !== null) {
		node.textContent = text;
	}
	return node;
}

function image(src) {
	const img = el("img");
	img.src = src;
	img.alt = "";
	img.loading = "lazy";
	return img;
}

async function fetchJson(url, signal) {
	const response = await fetch(url, {
		signal,
		headers: { Accept: "application/json" },
	});
	if (!response.ok) {
		const error = new Error(`Request failed with ${response.status}`);
		error.status = response.status;
		throw error;
	}
	return response.json();
}

function setupClock() {
	const target = document.querySelector("[data-clock]");
	const timeZone = document.body.dataset.timezone;
	if (!target || !timeZone) {
		return;
	}
	const date = new Intl.DateTimeFormat("en-GB", {
		timeZone,
		weekday: "long",
		day: "numeric",
		month: "long",
		year: "numeric",
	});
	const time = new Intl.DateTimeFormat("en-US", {
		timeZone,
		hour: "numeric",
		minute: "2-digit",
	});
	const update = () => {
		const now = new Date();
		target.textContent = `${date.format(now).replace(/^(\w+) /, "$1, ")} · ${time.format(now)}`;
	};
	update();
	setInterval(update, 30000);
}

function setupListKeyboard(input, getItems, onChoose, onClose) {
	let active = -1;
	const highlight = (index) => {
		const items = getItems();
		for (const [i, item] of items.entries()) {
			item.classList.toggle("is-active", i === index);
			item.setAttribute("aria-selected", i === index ? "true" : "false");
		}
		active = index;
		if (items[index]) {
			items[index].scrollIntoView({ block: "nearest" });
		}
	};
	input.addEventListener("keydown", (event) => {
		const items = getItems();
		if (event.key === "ArrowDown" && items.length) {
			event.preventDefault();
			highlight((active + 1) % items.length);
		} else if (event.key === "ArrowUp" && items.length) {
			event.preventDefault();
			highlight((active - 1 + items.length) % items.length);
		} else if (event.key === "Enter" && items[active]) {
			event.preventDefault();
			onChoose(items[active]);
		} else if (event.key === "Escape") {
			onClose();
		}
	});
	return () => {
		active = -1;
	};
}

function setupSearch() {
	const form = document.querySelector("[data-search]");
	if (!form) {
		return;
	}
	const input = form.querySelector("input[name=q]");
	const panel = form.querySelector("[data-search-results]");
	let controller;

	const close = () => {
		panel.hidden = true;
	};
	const items = () => Array.from(panel.querySelectorAll(".search-item"));
	const resetActive = setupListKeyboard(
		input,
		items,
		(item) => {
			window.location.href = item.href;
		},
		close,
	);

	const render = (query, data) => {
		panel.replaceChildren();
		resetActive();
		const addGroup = (label, entries, build) => {
			if (!entries.length) {
				return;
			}
			panel.append(el("div", "search-group", label));
			for (const entry of entries) {
				panel.append(build(entry));
			}
		};
		addGroup("Events", data.events.slice(0, 6), (event) => {
			const link = el("a", "search-item");
			link.href = `/category/${event.category_name}`;
			if (event.image_url) {
				link.append(image(event.image_url));
			}
			const text = el("span");
			text.append(el("span", null, event.title));
			text.append(
				el(
					"span",
					"search-item-sub",
					`${event.countdown} · ${event.subtitle || event.category_name}`,
				),
			);
			link.append(text);
			return link;
		});
		addGroup("Following", data.follows.slice(0, 4), (follow) => {
			const link = el("a", "search-item");
			link.href = "/following";
			if (follow.image_url) {
				link.append(image(follow.image_url));
			}
			link.append(el("span", null, follow.name));
			return link;
		});
		const all = el("a", "search-item");
		all.href = `/search?q=${encodeURIComponent(query)}`;
		all.append(el("span", "search-item-sub", `See all results for “${query}”`));
		if (!data.events.length && !data.follows.length) {
			panel.append(el("div", "search-empty", "No matches yet."));
		}
		panel.append(all);
		panel.hidden = false;
	};

	const run = debounce(async () => {
		const query = input.value.trim();
		if (controller) {
			controller.abort();
		}
		if (query.length < MIN_QUERY) {
			close();
			return;
		}
		controller = new AbortController();
		try {
			const data = await fetchJson(
				`/api/search?q=${encodeURIComponent(query)}`,
				controller.signal,
			);
			if (input.value.trim() === query) {
				render(query, data);
			}
		} catch (error) {
			if (error.name !== "AbortError") {
				panel.replaceChildren(
					el("div", "search-empty", "Search is unavailable right now."),
				);
				panel.hidden = false;
			}
		}
	}, DEBOUNCE_MS);

	input.addEventListener("input", run);
	input.addEventListener("focus", () => {
		if (panel.childElementCount && input.value.trim().length >= MIN_QUERY) {
			panel.hidden = false;
		}
	});
	document.addEventListener("click", (event) => {
		if (!form.contains(event.target)) {
			close();
		}
	});
}

function setupTypeahead(form) {
	const input = form.querySelector("[data-typeahead-input]");
	const hiddenId = form.querySelector("[data-typeahead-id]");
	const list = form.querySelector("[data-typeahead-list]");
	const { category, type } = form.dataset;
	let controller;

	const close = () => {
		list.hidden = true;
		input.setAttribute("aria-expanded", "false");
	};
	const open = () => {
		list.hidden = false;
		input.setAttribute("aria-expanded", "true");
	};
	const message = (text) => {
		list.replaceChildren(el("div", "typeahead-message", text));
		open();
	};
	const choose = (option) => {
		input.value = option.dataset.name;
		hiddenId.value = option.dataset.id;
		close();
		form.requestSubmit();
	};
	const options = () => Array.from(list.querySelectorAll(".typeahead-option"));
	const resetActive = setupListKeyboard(input, options, choose, close);

	const render = (results) => {
		resetActive();
		if (!results.length) {
			message("No matches. Press Follow to search anyway.");
			return;
		}
		list.replaceChildren();
		for (const result of results) {
			const option = el("button", "typeahead-option");
			option.type = "button";
			option.setAttribute("role", "option");
			option.setAttribute("aria-selected", "false");
			option.dataset.id = result.external_id;
			option.dataset.name = result.name;
			if (result.image_url) {
				option.append(image(result.image_url));
			}
			const text = el("span");
			text.append(el("span", "typeahead-name", result.name));
			if (result.detail) {
				text.append(el("span", "typeahead-detail", result.detail));
			}
			option.append(text);
			option.addEventListener("click", () => choose(option));
			list.append(option);
		}
		open();
	};

	const run = debounce(async () => {
		const query = input.value.trim();
		if (controller) {
			controller.abort();
		}
		if (query.length < MIN_QUERY) {
			close();
			return;
		}
		controller = new AbortController();
		message("Searching…");
		const params = new URLSearchParams({ category, type, q: query });
		try {
			const data = await fetchJson(`/api/suggest?${params}`, controller.signal);
			if (input.value.trim() === query) {
				render(data.results);
			}
		} catch (error) {
			if (error.name !== "AbortError") {
				message(
					"Suggestions are unavailable right now. Press Follow to search anyway.",
				);
			}
		}
	}, DEBOUNCE_MS);

	input.addEventListener("input", () => {
		hiddenId.value = "";
		run();
	});
	document.addEventListener("click", (event) => {
		if (!form.contains(event.target)) {
			close();
		}
	});
}

function setupMiniCalendar() {
	const root = document.querySelector("[data-mini-calendar]");
	if (!root) {
		return;
	}
	const grid = root.querySelector("[data-calendar-grid]");
	const label = root.querySelector("[data-month-label]");
	const colors = JSON.parse(root.dataset.colors || "{}");
	const weekdays = Array.from(grid.querySelectorAll(".mini-calendar-weekday"));
	const timeZone = document.body.dataset.timezone;
	let year = Number(root.dataset.year);
	let month = Number(root.dataset.month);
	let controller;

	const todayParts = () => {
		const parts = new Intl.DateTimeFormat("en-CA", {
			timeZone,
			year: "numeric",
			month: "numeric",
			day: "numeric",
		}).formatToParts(new Date());
		const value = (name) =>
			Number(parts.find((part) => part.type === name).value);
		return { year: value("year"), month: value("month"), day: value("day") };
	};

	const render = (days) => {
		const today = todayParts();
		const calendarHref = `/calendar?year=${year}&month=${month}`;
		const firstWeekday = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
		const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
		const cells = [...weekdays];
		for (let i = 0; i < firstWeekday; i += 1) {
			cells.push(el("span", "mini-calendar-day is-blank"));
		}
		for (let day = 1; day <= daysInMonth; day += 1) {
			const cell = el("a", "mini-calendar-day", String(day));
			cell.href = calendarHref;
			if (today.year === year && today.month === month && today.day === day) {
				cell.classList.add("is-today");
			}
			const dots = el("span", "mini-calendar-dots");
			for (const category of days[day] || []) {
				const dot = el("span", "dot");
				dot.style.setProperty("--dot", colors[category] || "#94a3b8");
				dots.append(dot);
			}
			cell.append(dots);
			cells.push(cell);
		}
		grid.replaceChildren(...cells);
		label.href = calendarHref;
		label.textContent = new Intl.DateTimeFormat("en-GB", {
			month: "long",
			year: "numeric",
			timeZone: "UTC",
		}).format(new Date(Date.UTC(year, month - 1, 1)));
	};

	for (const button of root.querySelectorAll("[data-cal-step]")) {
		button.addEventListener("click", async (event) => {
			event.preventDefault();
			const step = Number(button.dataset.calStep);
			const target = new Date(Date.UTC(year, month - 1 + step, 1));
			if (controller) {
				controller.abort();
			}
			controller = new AbortController();
			try {
				const data = await fetchJson(
					`/api/calendar?year=${target.getUTCFullYear()}&month=${target.getUTCMonth() + 1}`,
					controller.signal,
				);
				year = data.year;
				month = data.month;
				render(data.days);
			} catch (error) {
				if (error.name !== "AbortError") {
					window.location.href = button.href;
				}
			}
		});
	}
}

function setupActionMenus() {
	const menus = Array.from(document.querySelectorAll("details.actions"));
	for (const menu of menus) {
		menu.addEventListener("toggle", () => {
			if (!menu.open) {
				return;
			}
			for (const other of menus) {
				if (other !== menu) {
					other.open = false;
				}
			}
		});
	}
	document.addEventListener("click", (event) => {
		for (const menu of menus) {
			if (menu.open && !menu.contains(event.target)) {
				menu.open = false;
			}
		}
	});
	document.addEventListener("keydown", (event) => {
		if (event.key === "Escape") {
			for (const menu of menus) {
				menu.open = false;
			}
		}
	});
}

const SYNC_POLL_MS = 2000;
const SYNC_MAX_WAIT_MS = 10 * 60 * 1000;

function setupSync() {
	const form = document.querySelector("[data-sync]");
	if (!form) {
		return;
	}
	const button = form.querySelector("button");
	const spinner = form.querySelector(".spinner");
	const label = form.querySelector("[data-sync-label]");
	const status = form.querySelector("[data-sync-status]");
	let polling = false;

	const setBusy = (busy) => {
		button.disabled = busy;
		spinner.hidden = !busy;
		label.textContent = busy ? "Syncing…" : "Sync now";
	};

	const poll = async (startedAt) => {
		if (polling) {
			return;
		}
		polling = true;
		setBusy(true);
		status.textContent = "";
		while (Date.now() - startedAt < SYNC_MAX_WAIT_MS) {
			await new Promise((resolve) => setTimeout(resolve, SYNC_POLL_MS));
			try {
				const state = await fetchJson("/api/sync");
				if (!state.running) {
					status.textContent = "Updated";
					window.location.reload();
					return;
				}
			} catch {
				status.textContent = "Still syncing…";
			}
		}
		polling = false;
		setBusy(false);
		status.textContent = "Sync is taking a while. Refresh later.";
	};

	form.addEventListener("submit", async (event) => {
		event.preventDefault();
		if (polling) {
			return;
		}
		setBusy(true);
		try {
			const response = await fetch("/api/sync", {
				method: "POST",
				headers: { Accept: "application/json" },
			});
			if (!response.ok) {
				throw new Error(`Request failed with ${response.status}`);
			}
			poll(Date.now());
		} catch {
			setBusy(false);
			status.textContent = "Couldn't start the sync.";
		}
	});

	if (form.dataset.syncing === "true") {
		poll(Date.now());
	}
}

function setupCarousel(root) {
	const track = root.querySelector("[data-carousel-track]");
	const prev = root.querySelector("[data-carousel-prev]");
	const next = root.querySelector("[data-carousel-next]");
	const dots = Array.from(root.querySelectorAll("[data-carousel-dot]"));
	const slides = Array.from(track.children);
	if (slides.length < 2) {
		return;
	}

	const current = () =>
		Math.round(track.scrollLeft / Math.max(track.clientWidth, 1));
	const goTo = (index) => {
		const target = Math.max(0, Math.min(slides.length - 1, index));
		track.scrollTo({
			left: slides[target].offsetLeft - track.offsetLeft,
			behavior: "smooth",
		});
	};
	const update = () => {
		const index = current();
		prev.disabled = index <= 0;
		next.disabled = index >= slides.length - 1;
		for (const [i, dot] of dots.entries()) {
			dot.classList.toggle("is-active", i === index);
			dot.setAttribute("aria-current", i === index ? "true" : "false");
		}
	};

	prev.addEventListener("click", () => goTo(current() - 1));
	next.addEventListener("click", () => goTo(current() + 1));
	for (const dot of dots) {
		dot.addEventListener("click", () => goTo(Number(dot.dataset.carouselDot)));
	}
	root.addEventListener("keydown", (event) => {
		if (event.key === "ArrowLeft") {
			goTo(current() - 1);
		} else if (event.key === "ArrowRight") {
			goTo(current() + 1);
		}
	});
	track.addEventListener("scroll", debounce(update, 80));
	window.addEventListener("resize", debounce(update, 150));
	update();
}

document.addEventListener("DOMContentLoaded", () => {
	setupClock();
	setupSearch();
	for (const form of document.querySelectorAll("[data-typeahead]")) {
		setupTypeahead(form);
	}
	setupMiniCalendar();
	setupActionMenus();
	setupSync();
	for (const carousel of document.querySelectorAll("[data-carousel]")) {
		setupCarousel(carousel);
	}
});
