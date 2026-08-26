/**
 * Police Command Center Dashboard Client Script
 * Connects to Member 3 FastAPI Backend & Fusion Engine
 */

const API_BASE = "";

document.addEventListener("DOMContentLoaded", () => {
  console.log("[Police Dashboard] Client initialized.");
  
  // Attach Event Listeners
  document.getElementById("btn-run-demo")?.addEventListener("click", runFullDemo);
  document.getElementById("btn-trigger-rfid")?.addEventListener("click", triggerRfidScan);
  document.getElementById("btn-refresh")?.addEventListener("click", refreshDashboard);

  // Initial Load
  refreshDashboard();

  // Auto Refresh polling every 4 seconds
  setInterval(refreshDashboard, 4000);
});

async function refreshDashboard() {
  await Promise.all([
    fetchIncidentDetails(),
    fetchEventFeed()
  ]);
}

async function fetchIncidentDetails() {
  try {
    const res = await fetch(`${API_BASE}/api/incidents/INC-000001`);
    if (!res.ok) {
      console.warn("Incident INC-000001 not found yet. Attempting demo trigger...");
      return;
    }
    const data = await res.json();
    renderIncident(data);
  } catch (err) {
    console.error("Error fetching incident details:", err);
  }
}

function renderIncident(data) {
  // Update Alert Banner
  document.getElementById("banner-incident-id").textContent = `INCIDENT ${data.incident_id}:`;
  document.getElementById("banner-incident-type").textContent = `${data.incident_type} DETECTED AT JUNCTION ${data.crash_junction}`;
  document.getElementById("banner-confidence").textContent = `${Math.round((data.confidence_score || 0.96) * 100)}%`;

  // Update Suspect Card
  document.getElementById("suspect-plate").textContent = data.suspect_plate || "KA05XY5678";
  document.getElementById("suspect-id").textContent = data.suspect_vehicle_id || "V002";
  document.getElementById("suspect-last-location").textContent = `JUNCTION ${data.last_known_location} (${getJunctionName(data.last_known_location)})`;
  
  if (data.summary_notes) {
    document.getElementById("suspect-reason").textContent = data.summary_notes;
  }

  // Update Route Timeline
  if (data.route_history && data.route_history.length > 0) {
    const routeStr = data.route_history.join(" → ");
    document.getElementById("route-path-text").textContent = routeStr;
    updateTimelineNodes(data.route_history, data.last_known_location);
  }

  // Render Evidence Breakdown Table
  if (data.evidence_items) {
    renderEvidenceTable(data.evidence_items);
  }
}

function getJunctionName(jId) {
  const map = {
    "J01": "North Entry",
    "J02": "Crash Junction",
    "J03": "East Bypass RFID Checkpoint",
    "J04": "Highway Exit Camera Checkpoint"
  };
  return map[jId] || "Checkpoint";
}

function updateTimelineNodes(routeHistory, lastKnownLocation) {
  const nodes = ["J01", "J02", "J03", "J04"];
  nodes.forEach(jId => {
    const nodeEl = document.getElementById(`node-${jId}`);
    if (!nodeEl) return;

    if (routeHistory.includes(jId)) {
      nodeEl.classList.add("node-active");
    }
  });
}

function renderEvidenceTable(evidenceItems) {
  const tbody = document.getElementById("evidence-table-body");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (evidenceItems.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:#8b9bb4;">No evidence items recorded yet.</td></tr>`;
    return;
  }

  evidenceItems.forEach(item => {
    const tr = document.createElement("tr");
    const simTime = item.details?.timestamp_sim ? `${item.details.timestamp_sim.toFixed(2)}s` : "N/A";
    const sourceTag = item.source === "member1" ? "Member 1 (IMU)" : item.source === "member2" ? "Member 2 (Vision/ANPR)" : "Member 3 (RFID)";
    
    tr.innerHTML = `
      <td><strong>${simTime}</strong></td>
      <td><span class="badge badge-info">${sourceTag}</span></td>
      <td><strong>${item.event_type}</strong></td>
      <td>${item.details?.junction_id || "J02"}</td>
      <td>${Math.round((item.confidence || 0.95) * 100)}%</td>
      <td>${item.description || "Evidence payload verified."}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function fetchEventFeed() {
  try {
    const res = await fetch(`${API_BASE}/api/events?limit=50`);
    if (!res.ok) return;
    const events = await res.json();
    renderEventFeed(events);
  } catch (err) {
    console.error("Error fetching event feed:", err);
  }
}

function renderEventFeed(events) {
  const feedList = document.getElementById("event-feed-list");
  const countBadge = document.getElementById("event-count-badge");
  if (!feedList) return;

  if (countBadge) {
    countBadge.textContent = `${events.length} EVENTS`;
  }

  feedList.innerHTML = "";

  if (events.length === 0) {
    feedList.innerHTML = `<div style="text-align:center; padding:20px; color:#8b9bb4;">No live events ingested yet. Click "Run Full Fusion Demo".</div>`;
    return;
  }

  events.reverse().forEach(evt => {
    const div = document.createElement("div");
    div.className = `feed-item ${evt.event_type}`;
    
    let desc = "";
    if (evt.event_type === "CRASH_DETECTED") {
      desc = `Impact Detected on Vehicle ${evt.vehicle_id} at ${evt.junction_id}`;
    } else if (evt.event_type === "COLLISION_PAIR_IDENTIFIED") {
      desc = `Collision Pair Identified: ${evt.payload_json?.vehicle_ids?.join(" & ")}`;
    } else if (evt.event_type === "ANPR_IDENTIFIED") {
      desc = `ANPR Plate Read: ${evt.plate_number} (Vehicle ${evt.vehicle_id})`;
    } else if (evt.event_type === "RFID_DETECTED") {
      desc = `Virtual RFID Tag ${evt.payload_json?.tag_id} scanned for ${evt.vehicle_id} (${evt.plate_number})`;
    } else if (evt.event_type === "VEHICLE_OBSERVED") {
      desc = `Camera Observation of ${evt.vehicle_id} (${evt.plate_number}) at ${evt.junction_id}`;
    }

    div.innerHTML = `
      <div class="feed-header">
        <span class="feed-title">${evt.event_type}</span>
        <span class="feed-time">t = ${evt.timestamp_sim.toFixed(2)}s</span>
      </div>
      <div class="feed-details">${desc}</div>
    `;
    feedList.appendChild(div);
  });
}

async function runFullDemo() {
  const btn = document.getElementById("btn-run-demo");
  if (btn) btn.disabled = true;
  
  try {
    const res = await fetch(`${API_BASE}/api/demo/run`, { method: "POST" });
    const data = await res.json();
    console.log("Demo execution result:", data);
    await refreshDashboard();
  } catch (err) {
    console.error("Error executing demo:", err);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function triggerRfidScan() {
  try {
    const res = await fetch(`${API_BASE}/api/rfid/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reader_id: "RFID_J03_R01",
        junction_id: "J03",
        vehicle_id: "V002",
        tag_id: "TAG_V002_99B",
        plate_number: "KA05XY5678",
        timestamp_sim: 125.10,
        distance_m: 5.0
      })
    });
    const data = await res.json();
    console.log("RFID trigger response:", data);
    await refreshDashboard();
  } catch (err) {
    console.error("Error triggering RFID:", err);
  }
}
