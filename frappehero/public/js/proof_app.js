// Copyright (c) 2026, Agilasoft and contributors
// For license information, please see license.txt

// The proof of payment web app. Amounts are plain text. Frappe's currency
// formatter returns a right-aligned div, which is why the desk page showed
// markup on a phone.

function esc(value) {
	return String(value == null ? "" : value)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function money(amount, currency) {
	const number = Number(amount);
	const value = Number.isFinite(number) ? number : 0;
	const digits = { minimumFractionDigits: 2, maximumFractionDigits: 2 };
	if (!currency) {
		return value.toLocaleString(undefined, digits);
	}
	try {
		return new Intl.NumberFormat(undefined, Object.assign({ style: "currency", currency: currency }, digits)).format(value);
	} catch (error) {
		return currency + " " + value.toFixed(2);
	}
}

function formatDate(value, dateFormat, withTime) {
	const raw = String(value || "").trim();
	if (!raw) {
		return "";
	}
	const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2})(?::\d{2})?)?/);
	if (!match) {
		return raw;
	}
	const tokens = { yyyy: match[1], mm: match[2], dd: match[3] };
	let date = String(dateFormat || "yyyy-mm-dd").toLowerCase();
	["yyyy", "mm", "dd"].forEach(function (token) {
		date = date.replace(token, tokens[token]);
	});
	if (withTime && match[4]) {
		return date + " " + match[4];
	}
	return date;
}

function serverMessage(data) {
	try {
		const rows = JSON.parse((data && data._server_messages) || "[]");
		const first = JSON.parse(rows[0]);
		return String(first.message || "").replace(/<[^>]*>/g, "").trim();
	} catch (error) {
		return "";
	}
}

function statusName(docstatus) {
	const status = Number(docstatus);
	if (status === 2) {
		return "Cancelled";
	}
	if (status === 1) {
		return "Submitted";
	}
	return "Draft";
}

function statusClass(docstatus) {
	const status = Number(docstatus);
	if (status === 2) {
		return "bad";
	}
	if (status === 1) {
		return "ok";
	}
	return "warn";
}

function proofHref(url) {
	const value = String(url || "");
	if (value.startsWith("/private/files/") || value.startsWith("/files/")) {
		return value;
	}
	return "";
}

function showInvoiceLine(row, allocatedCurrency) {
	if (!row || !row.invoice_currency) {
		return false;
	}
	if (row.invoice_currency !== allocatedCurrency) {
		return true;
	}
	return Math.abs(Number(row.invoice_amount || 0) - Number(row.allocated_amount || 0)) >= 0.0001;
}

function renderPendingHtml(rows, dateFormat) {
	if (!rows || !rows.length) {
		return '<p class="empty">Nothing is waiting on you.</p>';
	}
	return rows
		.map(function (row) {
			const party = row.party ? '<span class="meta">' + esc(row.party) + "</span>" : "";
			const date = formatDate(row.posting_date, dateFormat);
			const when = date ? '<span class="meta">' + esc(date) + "</span>" : "";
			return (
				'<button type="button" class="pay-card" data-action="open" data-name="' +
				esc(row.name) +
				'">' +
				'<span class="pay-card-text"><strong>' +
				esc(row.name) +
				"</strong>" +
				party +
				when +
				"</span>" +
				'<span class="pay-amount">' +
				esc(money(row.amount, row.currency)) +
				"</span></button>"
			);
		})
		.join("");
}

function renderDetailHtml(payment, dateFormat) {
	const references = payment.references || [];
	const referenceHtml = references.length
		? '<ul class="refs">' +
			references
				.map(function (row) {
					const invoice = showInvoiceLine(row, payment.allocated_currency)
						? '<p class="ref-invoice">Invoice ' + esc(money(row.invoice_amount, row.invoice_currency)) + "</p>"
						: "";
					return (
						"<li class=\"ref\"><p class=\"ref-name\">" +
						esc(row.reference_name) +
						'</p><p class="ref-type">' +
						esc(row.reference_doctype) +
						'</p><p class="ref-amount">' +
						esc(money(row.allocated_amount, payment.allocated_currency)) +
						"</p>" +
						invoice +
						"</li>"
					);
				})
				.join("") +
			"</ul>"
		: '<p class="empty">No references.</p>';
	const href = proofHref(payment.proof_of_payment);
	const proof = href
		? '<a class="btn ghost proof-link" href="' + esc(href) + '" target="_blank" rel="noopener">View proof</a>'
		: "";
	const uploaded = payment.proof_uploaded_by
		? '<p class="muted uploaded">Uploaded by ' +
			esc(payment.proof_uploaded_by) +
			(payment.proof_uploaded_on ? " · " + esc(formatDate(payment.proof_uploaded_on, dateFormat, true)) : "") +
			"</p>"
		: "";
	const facts = [
		["Posting date", formatDate(payment.posting_date, dateFormat)],
		["Payment type", payment.payment_type],
		["Mode of payment", payment.mode_of_payment],
		["Reference", payment.reference_no ? payment.reference_no + (payment.reference_date ? " · " + formatDate(payment.reference_date, dateFormat) : "") : ""],
		["Company", payment.company],
	]
		.filter(function (row) {
			return row[1];
		})
		.map(function (row) {
			return "<div><dt>" + esc(row[0]) + "</dt><dd>" + esc(row[1]) + "</dd></div>";
		})
		.join("");
	return (
		'<button type="button" class="back" data-action="back">Back</button>' +
		'<article class="detail-card">' +
		'<p class="hero-amount">' +
		esc(money(payment.amount, payment.currency)) +
		"</p>" +
		'<p class="pay-id">' +
		esc(payment.name) +
		"</p>" +
		'<div class="who"><p class="who-name">' +
		esc(payment.party_name || payment.party) +
		"</p>" +
		(payment.party_type ? '<p class="who-type">' + esc(payment.party_type) + "</p>" : "") +
		"</div>" +
		'<span class="chip ' +
		statusClass(payment.docstatus) +
		'">' +
		esc(statusName(payment.docstatus)) +
		"</span>" +
		'<dl class="facts">' +
		facts +
		"</dl>" +
		"<h3>References</h3>" +
		referenceHtml +
		"<h3>Proof</h3>" +
		proof +
		uploaded +
		"</article>"
	);
}

function renderDockHtml(payment) {
	if (payment.can_upload) {
		return (
			'<p class="dock-note">' +
			(payment.proof_of_payment
				? "A new file replaces this one. JPEG, PNG, WebP, or PDF. 10 MB or smaller."
				: "JPEG, PNG, WebP, or PDF. 10 MB or smaller.") +
			"</p>" +
			'<div class="actions">' +
			'<button type="button" class="btn primary" data-action="photo">Take photo</button>' +
			'<button type="button" class="btn ghost" data-action="file">Choose file</button>' +
			"</div>"
		);
	}
	const note = Number(payment.docstatus) === 2 ? "This payment is cancelled." : "This payment is not assigned to you.";
	return '<p class="dock-note">' + note + "</p>";
}

function fileError(file) {
	const name = String((file && file.name) || "").split(/[/\\]/).pop();
	const extension = name.indexOf(".") >= 0 ? name.split(".").pop().toLowerCase() : "";
	if (["jpg", "jpeg", "png", "webp", "pdf"].indexOf(extension) < 0) {
		return "Use a JPEG, PNG, WebP, or PDF.";
	}
	if (!file.size) {
		return "That file is empty.";
	}
	if (file.size > 10 * 1024 * 1024) {
		return "The file must be 10 MB or smaller.";
	}
	return "";
}

function boot(config) {
	if (!config || !config.permitted || !document.getElementById("app")) {
		return;
	}
	const root = document.getElementById("app");
	const home = document.getElementById("home");
	const detail = document.getElementById("detail");
	const detailBody = document.getElementById("detail-body");
	const detailDock = document.getElementById("detail-dock");
	const pending = document.getElementById("pending");
	const input = document.getElementById("payment-id");
	const camera = document.getElementById("camera");
	const video = camera.querySelector("video");
	const toast = document.getElementById("toast");
	const photoInput = document.getElementById("photo-input");
	const fileInput = document.getElementById("file-input");
	const dateFormat = config.dateFormat;
	let payment = null;
	let busy = false;
	let scanning = false;
	let stream = null;
	let scanTimer = null;
	let detector = null;
	let scanFormats = ["qr_code", "code_128"];
	let toastTimer = null;

	function showToast(message) {
		toast.textContent = message;
		toast.hidden = !message;
		clearTimeout(toastTimer);
		if (message) {
			toastTimer = setTimeout(function () {
				toast.hidden = true;
			}, 4200);
		}
	}

	async function call(method, args) {
		let response;
		try {
			response = await fetch("/api/method/" + method, {
				method: "POST",
				credentials: "same-origin",
				headers: {
					Accept: "application/json",
					"Content-Type": "application/json",
					"X-Frappe-CSRF-Token": config.csrf,
				},
				body: JSON.stringify(args || {}),
			});
		} catch (error) {
			throw new Error("The network request failed.");
		}
		const data = await response.json().catch(function () {
			return {};
		});
		if (!response.ok) {
			throw new Error(serverMessage(data) || "Something went wrong.");
		}
		return data.message;
	}

	function showHome() {
		detail.hidden = true;
		home.hidden = false;
		window.scrollTo(0, 0);
	}

	function showDetail() {
		detailBody.innerHTML = renderDetailHtml(payment, dateFormat);
		detailDock.innerHTML = renderDockHtml(payment);
		home.hidden = true;
		detail.hidden = false;
		window.scrollTo(0, 0);
	}

	async function loadPending() {
		const rows = (await call("frappehero.finance_desk.proof.list_pending")) || [];
		pending.innerHTML = renderPendingHtml(rows, dateFormat);
	}

	async function lookup(raw) {
		const name = String(raw || "").trim();
		if (!name) {
			showToast("Enter a Payment Entry.");
			return;
		}
		if (busy) {
			return;
		}
		busy = true;
		try {
			payment = await call("frappehero.finance_desk.proof.get_payment", { name: name });
			input.value = payment.name || name;
			showDetail();
		} catch (error) {
			showToast(error.message || "Something went wrong.");
		} finally {
			busy = false;
		}
	}

	function readFile(file) {
		return new Promise(function (resolve, reject) {
			const reader = new FileReader();
			reader.onload = function () {
				resolve(reader.result);
			};
			reader.onerror = function () {
				reject(new Error("That file could not be read."));
			};
			reader.readAsDataURL(file);
		});
	}

	async function upload(file) {
		if (!file || !payment) {
			return;
		}
		const error = fileError(file);
		if (error) {
			showToast(error);
			return;
		}
		if (busy) {
			return;
		}
		busy = true;
		try {
			const filedata = await readFile(file);
			payment = await call("frappehero.finance_desk.proof.attach_proof", {
				name: payment.name,
				filename: file.name,
				filedata: filedata,
			});
			showDetail();
			showToast("Proof saved");
			loadPending().catch(function () {});
		} catch (error) {
			showToast(error.message || "That file could not be read.");
		} finally {
			busy = false;
		}
	}

	function prepareScan() {
		const button = root.querySelector("[data-action=scan]");
		if (!button) {
			return;
		}
		if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
			button.hidden = true;
			return;
		}
		if (typeof BarcodeDetector.getSupportedFormats !== "function") {
			return;
		}
		BarcodeDetector.getSupportedFormats()
			.then(function (formats) {
				const wanted = ["qr_code", "code_128"].filter(function (format) {
					return formats.indexOf(format) >= 0;
				});
				if (!wanted.length) {
					button.hidden = true;
					return;
				}
				scanFormats = wanted;
			})
			.catch(function () {
				button.hidden = true;
			});
	}

	function stopScan() {
		scanning = false;
		clearTimeout(scanTimer);
		if (stream) {
			stream.getTracks().forEach(function (track) {
				track.stop();
			});
			stream = null;
		}
		video.srcObject = null;
		camera.hidden = true;
	}

	async function detect() {
		if (!scanning) {
			return;
		}
		try {
			const codes = await detector.detect(video);
			const value = codes && codes[0] && codes[0].rawValue;
			if (value) {
				stopScan();
				input.value = value;
				lookup(value);
				return;
			}
		} catch (error) {
			// One missed frame leaves the camera open.
		}
		scanTimer = setTimeout(detect, 250);
	}

	async function startScan() {
		if (scanning) {
			return;
		}
		camera.hidden = false;
		try {
			stream = await navigator.mediaDevices.getUserMedia({
				video: { facingMode: { ideal: "environment" } },
				audio: false,
			});
		} catch (error) {
			stopScan();
			showToast("The camera is not available. Type the Payment Entry instead.");
			return;
		}
		video.srcObject = stream;
		try {
			await video.play();
		} catch (error) {
			stopScan();
			showToast("The camera is not available. Type the Payment Entry instead.");
			return;
		}
		try {
			detector = new BarcodeDetector({ formats: scanFormats });
		} catch (error) {
			try {
				detector = new BarcodeDetector({ formats: ["qr_code"] });
			} catch (ignored) {
				stopScan();
				showToast("This browser cannot scan a code. Type the Payment Entry instead.");
				return;
			}
		}
		scanning = true;
		detect();
	}

	root.addEventListener("click", function (event) {
		const button = event.target.closest("[data-action]");
		if (!button || busy) {
			return;
		}
		const action = button.dataset.action;
		if (action === "open") {
			input.value = button.dataset.name || "";
			lookup(button.dataset.name);
		} else if (action === "back") {
			showHome();
			loadPending().catch(function (error) {
				showToast(error.message);
			});
		} else if (action === "scan") {
			startScan();
		} else if (action === "close-scan") {
			stopScan();
		} else if (action === "photo") {
			photoInput.click();
		} else if (action === "file") {
			fileInput.click();
		}
	});
	document.getElementById("lookup-form").addEventListener("submit", function (event) {
		event.preventDefault();
		lookup(input.value);
	});
	photoInput.addEventListener("change", function () {
		const file = photoInput.files && photoInput.files[0];
		photoInput.value = "";
		upload(file);
	});
	fileInput.addEventListener("change", function () {
		const file = fileInput.files && fileInput.files[0];
		fileInput.value = "";
		upload(file);
	});
	window.addEventListener("pagehide", stopScan);
	prepareScan();
	loadPending().catch(function (error) {
		showToast(error.message);
	});
}

const proofApi = {
	esc: esc,
	money: money,
	formatDate: formatDate,
	serverMessage: serverMessage,
	renderPendingHtml: renderPendingHtml,
	renderDetailHtml: renderDetailHtml,
	renderDockHtml: renderDockHtml,
	fileError: fileError,
};

if (typeof window !== "undefined") {
	window.frappeheroProof = proofApi;
	const start = function () {
		boot(window.PROOF_APP);
	};
	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", start);
	} else {
		start();
	}
}

if (typeof module !== "undefined" && module.exports) {
	module.exports = proofApi;
}
