const $ = id => document.getElementById(id);

let allPlaces = [], visibleCount = 0;
const PAGE_SIZE = 50;
const SEARCH_TIMEOUT = 180000;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[c]));
}

function render() {
  const shown = allPlaces.slice(0, visibleCount);

  $("count").textContent = allPlaces.length;
  $("showing").textContent = shown.length;
  $("csvBtn").disabled = allPlaces.length === 0;
  $("xlsxBtn").disabled = allPlaces.length === 0;

  $("results").innerHTML = shown.length
    ? shown.map(p => `<tr>
        <td><strong>${esc(p.name)}</strong></td>
        <td>${esc(p.address || "Not listed")}</td>
        <td>${p.phone ? esc(p.phone) : "—"}</td>
        <td>${p.website
          ? `<a href="${esc(p.website)}" target="_blank" rel="noopener">Visit website</a>`
          : "—"}</td>
        <td>${esc(p.category || "—")}</td>
        <td><a href="${esc(p.map_url || "#")}" target="_blank" rel="noopener">View map</a></td>
      </tr>`).join("")
    : '<tr><td colspan="6" class="empty">No matching businesses found in this area.</td></tr>';

  $("moreBtn").hidden =
    visibleCount >= allPlaces.length || allPlaces.length === 0;
}

async function search() {
  // Agar pehli search chal rahi hai to doosri shuru na karein (Enter key se bhi)
  if ($("searchBtn").disabled) return;

  const keyword = $("keyword").value.trim();
  const location = $("location").value.trim();

  if (!keyword || !location) {
    $("status").textContent = "Category aur location dono enter karein.";
    return;
  }

  $("searchBtn").disabled = true;
  $("status").textContent = "Searching OpenStreetMap... Please wait.";
  $("state").textContent = "Searching";

  $("results").innerHTML =
    '<tr><td colspan="6" class="empty">Searching businesses... Please wait.</td></tr>';

  allPlaces = [];
  visibleCount = 0;
  render();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), SEARCH_TIMEOUT);

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        keyword,
        location,
        radius: Number($("radius").value)
      }),
      signal: controller.signal
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || `Server error: ${response.status}`);
    }

    allPlaces = data.places || [];
    visibleCount = Math.min(PAGE_SIZE, allPlaces.length);

    $("locationInfo").textContent =
      `Near ${data.location} · ${data.radius / 1000} km radius · maximum 500 results per search`;

    $("status").textContent =
      data.note || `Found ${allPlaces.length} businesses.`;

    $("state").textContent = "Complete";

    render();

  } catch (error) {
    let message = error.message;

    if (error.name === "AbortError") {
      message = `Search timeout: Server ne ${SEARCH_TIMEOUT / 1000} seconds mein response nahi diya. Dobara try karein.`;
    } else if (!navigator.onLine) {
      message = "Internet connection check karein.";
    }

    $("results").innerHTML =
      `<tr><td colspan="6" class="empty">${esc(message)}</td></tr>`;

    $("count").textContent = "0";
    $("showing").textContent = "0";
    $("status").textContent = message;
    $("state").textContent = "Error";

  } finally {
    clearTimeout(timeoutId);
    $("searchBtn").disabled = false;
  }
}

$("searchBtn").addEventListener("click", search);

$("moreBtn").addEventListener("click", () => {
  visibleCount = Math.min(
    visibleCount + PAGE_SIZE,
    allPlaces.length
  );
  render();
});

async function exportFile(kind) {
  if (!allPlaces.length) return;

  const button = kind === "csv" ? $("csvBtn") : $("xlsxBtn");
  button.disabled = true;

  try {
    const response = await fetch(`/api/export/${kind}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        places: allPlaces
      })
    });

    if (!response.ok) {
      throw new Error("Export failed. Please try again.");
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");

    a.href = url;
    a.download = `osm_business_leads.${kind}`;
    document.body.appendChild(a);
    a.click();
    a.remove();

    URL.revokeObjectURL(url);

  } catch (error) {
    $("status").textContent = error.message;

  } finally {
    button.disabled = false;
  }
}

$("csvBtn").addEventListener("click", () => exportFile("csv"));
$("xlsxBtn").addEventListener("click", () => exportFile("xlsx"));

$("keyword").addEventListener("keydown", e => {
  if (e.key === "Enter") search();
});

$("location").addEventListener("keydown", e => {
  if (e.key === "Enter") search();
});