(() => {
  "use strict";

  const COLORS = {
    ruling: "#4f9dff",
    official: "#62d0ff",
    opposition: "#ff5f7e",
    party: "#ff7a59",
    media: "#ffd36b",
    watchdog: "#6ed8b5",
    business: "#b98cff",
    civic: "#7eb4ff",
    regions: "#9ed26b",
    event: "#93a4b8",
    person: "#9ec8ff",
    organization: "#d8e2f0",
    unknown: "#aeb8c5",
  };

  const FAMILY_ORDER = ["official", "ruling", "party", "opposition", "media", "watchdog", "business", "regions", "person", "organization", "event", "unknown"];

  function requestedSceneMode() {
    try {
      const params = new URLSearchParams(window.location.search);
      const mode = (params.get("mode") || "").trim().toLowerCase();
      if (mode === "3d" || mode === "2d") return mode;
      const stored = window.localStorage.getItem("thiezer.sceneMode");
      return stored === "3d" ? "3d" : "2d";
    } catch {
      return "2d";
    }
  }

  function requestedWebGL3D() {
    try {
      const params = new URLSearchParams(window.location.search);
      return (params.get("renderer") || "").trim().toLowerCase() === "webgl";
    } catch {
      return false;
    }
  }

  const state = {
    graphLayer: "core",
    requestedSceneMode: requestedSceneMode(),
    sceneMode: requestedSceneMode(),
    layoutMode: "political-map",
    inspectorMode: "entity",
    graphView: null,
    graphMode: "pending",
    workbenchMode: "graph",
    selectedNodeId: null,
    selectedLinkId: null,
    lastEntityId: null,
    lastRelationId: null,
    hoveredNodeId: null,
    hoveredLinkId: null,
    familyFilter: "all",
    latestGraphLayers: { core: null },
    graph: { nodes: [], links: [], stats: {} },
    visibleNodes: [],
    visibleLinks: [],
    nodeById: new Map(),
    linkById: new Map(),
    relationTypes: [],
    latestSuggestions: { suggested_nodes: [], suggested_queries: [] },
    runtime: null,
    safety: null,
    flows: [],
    lastDiffRunId: "",
    latestResearchRun: null,
    latestResearchEvents: [],
    latestResearchEventTs: 0,
    latestResearchEventCount: 0,
    researchDrawerTab: "summary",
    showLatestChangesOnly: false,
    runHighlights: { nodeIds: new Set(), linkIds: new Set(), expiresAt: 0, reason: "" },
    layoutCenter: { x: 0, y: 0, z: 0 },
    layoutRadius: 0,
    orbit3DLite: { yaw: -0.55, pitch: 0.34, zoom: 1, panX: 0, panY: 0, dispose: null },
  };

  const el = {
    graph: document.getElementById("graph"),
    status: document.getElementById("graph-status"),
    entityCount: document.getElementById("entity-count"),
    relationCount: document.getElementById("relation-count"),
    eventCount: document.getElementById("event-count"),
    issueCount: document.getElementById("issue-count"),
    search: document.getElementById("search"),
    layoutMode: document.getElementById("layout-mode"),
    typeFilter: document.getElementById("type-filter"),
    linkFilter: document.getElementById("link-filter"),
    resetCamera: document.getElementById("reset-camera"),
    legend: document.getElementById("legend"),
    searchResults: document.getElementById("search-results"),
    detailName: document.getElementById("detail-name"),
    detailMeta: document.getElementById("detail-meta"),
    detailSummary: document.getElementById("detail-summary"),
    detailHistoryTitle: document.getElementById("detail-history-title"),
    detailPerspectivesTitle: document.getElementById("detail-perspectives-title"),
    detailActivityTitle: document.getElementById("detail-activity-title"),
    detailLinksTitle: document.getElementById("detail-links-title"),
    detailRelationsTitle: document.getElementById("detail-relations-title"),
    detailProvenanceTitle: document.getElementById("detail-provenance-title"),
    detailTags: document.getElementById("detail-tags"),
    detailHeroLinks: document.getElementById("detail-hero-links"),
    detailHistory: document.getElementById("detail-history"),
    detailPerspectives: document.getElementById("detail-perspectives"),
    detailActivity: document.getElementById("detail-activity"),
    detailLinks: document.getElementById("detail-links"),
    detailRelations: document.getElementById("detail-relations"),
    detailProvenance: document.getElementById("detail-provenance"),
    detailActions: document.getElementById("detail-actions"),
    detailSuggestions: document.getElementById("detail-suggestions"),
    inspectorEntityTab: document.getElementById("inspector-entity-tab"),
    inspectorRelationTab: document.getElementById("inspector-relation-tab"),
    inspectorModeCopy: document.getElementById("inspector-mode-copy"),
    commandModelMode: document.getElementById("command-model-mode"),
    commandModelInfo: document.getElementById("command-model-info"),
    commandInput: document.getElementById("command-input"),
    commandRun: document.getElementById("command-run"),
    graphModePanel: document.getElementById("graph-mode-panel"),
    researchModePanel: document.getElementById("research-mode-panel"),
    researchEntity: document.getElementById("research-entity"),
    researchTarget: document.getElementById("research-target"),
    researchDateFrom: document.getElementById("research-date-from"),
    researchDateTo: document.getElementById("research-date-to"),
    researchBudget: document.getElementById("research-budget"),
    researchSourcePriority: document.getElementById("research-source-priority"),
    runtimeSignals: document.getElementById("runtime-signals"),
    flowRuns: document.getElementById("flow-runs"),
    sceneModeTitle: document.getElementById("scene-mode-title"),
    sceneWorkspaceLabel: document.getElementById("scene-workspace-label"),
    sceneModeCopy: document.getElementById("scene-mode-copy"),
    sceneMouseCopy: document.getElementById("scene-mouse-copy"),
    researchRunSummary: document.getElementById("research-run-summary"),
    researchRunActions: document.getElementById("research-run-actions"),
    researchRunTabs: document.getElementById("research-run-tabs"),
    researchPanelSummary: document.getElementById("research-panel-summary"),
    researchPanelViewed: document.getElementById("research-panel-viewed"),
    researchPanelAccepted: document.getElementById("research-panel-accepted"),
    researchPanelRejected: document.getElementById("research-panel-rejected"),
    researchPanelClaims: document.getElementById("research-panel-claims"),
    researchPanelDiff: document.getElementById("research-panel-diff"),
    researchPanelRaw: document.getElementById("research-panel-raw"),
    researchPanelEvents: document.getElementById("research-panel-events"),
  };

  function api(path, options = {}) {
    return fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    }).then(async (response) => {
      const text = await response.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        data = { ok: false, raw: text };
      }
      if (!response.ok) throw new Error(data.error || response.statusText || "Request failed");
      return data;
    });
  }

  function normalizeGraphPayload(payload) {
    if (!payload || typeof payload !== "object") return null;
    if (payload.graph && payload.graph.nodes && payload.graph.links) return payload;
    if (payload.nodes || payload.links) return { ok: true, graph: payload, legend: payload.legend || {} };
    if (Array.isArray(payload)) return normalizeKnowledgeGraphExport(payload);
    return null;
  }

  function normalizeKnowledgeGraphExport(rows) {
    if (!Array.isArray(rows) || !rows.length) return null;
    const nodes = rows.map((row) => ({
      id: String(row.id || "").trim(),
      name: String(row.label || row.id || "").trim(),
      category: String(row.category || "entity").trim(),
      subtype: String(row.category || "entity").trim(),
      summary: String(row.definition || "").trim(),
      long_description: String(row.long_description || "").trim(),
      tags: [String(row.category || "entity").trim(), row.depth != null ? `depth:${row.depth}` : ""].filter(Boolean),
      to: Array.isArray(row.to) ? row.to.map(String) : [],
      from: Array.isArray(row.from) ? row.from.map(String) : [],
      depth: Number(row.depth || 0),
      pagerank: Number(row._pagerank || 0),
      degree_centrality: Number(row._degree_centrality || 0),
      betweenness_centrality: Number(row._betweenness_centrality || 0),
      descendant_ratio: Number(row._descendant_ratio || 0),
      prerequisite_ratio: Number(row._prerequisite_ratio || 0),
      reachability_ratio: Number(row._reachability_ratio || 0),
      kind: String(row.category || "") === "event" ? "event" : "entity",
      public_safe: true,
    })).filter((node) => node.id);

    const byId = new Map(nodes.map((node) => [node.id, node]));
    const links = [];
    for (const row of rows) {
      const source = String(row.id || "").trim();
      for (const target of Array.isArray(row.to) ? row.to : []) {
        const targetId = String(target || "").trim();
        if (!source || !targetId || source === targetId || !byId.has(source) || !byId.has(targetId)) continue;
        links.push({
          id: `static:${source}:${targetId}`,
          from: source,
          to: targetId,
          relation_type: "static_link",
          status: "derived",
          confidence: 0.72,
          public_safe: true,
          visual_width: 0.95,
          visual_color: "#7b8a99",
          human_text: `${byId.get(source)?.name || source} → ${byId.get(targetId)?.name || targetId}`,
        });
      }
    }
    return {
      ok: true,
      graph: {
        nodes,
        links,
        entities: nodes.length,
        relations: links.length,
        event_nodes: nodes.filter((node) => node.kind === "event").length,
        context_kind: "static",
      },
      legend: { relation_types: ["static_link"] },
      static_export: true,
    };
  }

  function mergeGraphPayloads(staticPayload, corePayload) {
    if (!staticPayload) return corePayload || null;
    if (!corePayload) return staticPayload;
    const staticNodes = Array.isArray(staticPayload.graph?.nodes) ? staticPayload.graph.nodes : [];
    const staticLinks = Array.isArray(staticPayload.graph?.links) ? staticPayload.graph.links : [];
    const coreNodes = Array.isArray(corePayload.graph?.nodes) ? corePayload.graph.nodes : [];
    const coreLinks = Array.isArray(corePayload.graph?.links) ? corePayload.graph.links : [];
    const staticNodeById = new Map(staticNodes.map((node) => [String(node.id || ""), node]));
    const coreNodeById = new Map(coreNodes.map((node) => [String(node.id || ""), node]));
    const mergedNodeIds = new Set([...staticNodeById.keys(), ...coreNodeById.keys()]);
    const mergedNodes = Array.from(mergedNodeIds).map((id) => ({
      ...(staticNodeById.get(id) || {}),
      ...(coreNodeById.get(id) || {}),
    })).filter((node) => node.id);
    const mergedLinkById = new Map();
    for (const link of staticLinks) {
      const id = String(link.id || `${link.from || ""}:${link.to || ""}:${link.relation_type || ""}`);
      if (!id) continue;
      mergedLinkById.set(id, link);
    }
    for (const link of coreLinks) {
      const id = String(link.id || `${link.from || ""}:${link.to || ""}:${link.relation_type || ""}`);
      if (!id) continue;
      mergedLinkById.set(id, { ...(mergedLinkById.get(id) || {}), ...link });
    }
    const mergedLinks = Array.from(mergedLinkById.values()).filter((link) => link.from && link.to);
    return {
      ...staticPayload,
      ...corePayload,
      graph: {
        ...staticPayload.graph,
        ...corePayload.graph,
        nodes: mergedNodes,
        links: mergedLinks,
        entities: corePayload.graph?.entities ?? staticPayload.graph?.entities ?? mergedNodes.length,
        relations: corePayload.graph?.relations ?? staticPayload.graph?.relations ?? mergedLinks.length,
        event_nodes: corePayload.graph?.event_nodes ?? staticPayload.graph?.event_nodes ?? mergedNodes.filter((node) => node.kind === "event").length,
        context_kind: corePayload.graph?.context_kind || staticPayload.graph?.context_kind || "static",
      },
    };
  }

  function firstFocusableNodeIdFromResponse(response) {
    const focusIds = Array.isArray(response?.suggested_focus_nodes) ? response.suggested_focus_nodes : [];
    for (const value of focusIds) {
      const id = String(value || "").trim();
      if (id) return id;
    }
    const newNodes = Array.isArray(response?.graph_diff?.new_nodes) ? response.graph_diff.new_nodes : [];
    for (const item of newNodes) {
      const id = String(item?.id || "").trim();
      if (id) return id;
    }
    return "";
  }

  function setStatus(text, tone = "good") {
    el.status.textContent = text;
    const dot = el.status.parentElement.querySelector(".status-dot");
    if (dot) {
      dot.style.background = tone === "error" ? "#ff6483" : tone === "warn" ? "#ff8f70" : "#73d2b6";
    }
  }

  function researchStatusMeta(run = {}) {
    const accepted = Number(run.accepted_graph_changes || 0);
    const status = String(run.status || "").trim() || "unknown";
    if (status === "running" || status === "queued") return { text: "Research running...", tone: "warn" };
    if (status === "completed" && accepted > 0) return { text: "Research completed: graph updated.", tone: "good" };
    if (status === "completed") return { text: "Research completed: no graph changes admitted.", tone: "warn" };
    if (status === "completed_no_changes") return { text: "Research completed: no graph changes admitted.", tone: "warn" };
    if (status === "completed_with_warnings" && accepted > 0) return { text: "Research completed with warnings: graph updated.", tone: "warn" };
    if (status === "completed_with_warnings") return { text: "Research completed with warnings.", tone: "warn" };
    if (status === "failed_retryable") return { text: "Research failed: retryable.", tone: "warn" };
    if (status === "failed") return { text: "Research failed.", tone: "error" };
    if (status === "no_results") return { text: "Research finished: no useful sources found.", tone: "warn" };
    return { text: `Research status: ${status}.`, tone: "warn" };
  }

  function renderResearchDrawer() {
    const payload = state.latestResearchRun;
    const run = payload?.run || null;
    const tabs = {
      summary: el.researchPanelSummary,
      viewed: el.researchPanelViewed,
      accepted: el.researchPanelAccepted,
      rejected: el.researchPanelRejected,
      claims: el.researchPanelClaims,
      diff: el.researchPanelDiff,
      events: el.researchPanelEvents,
      raw: el.researchPanelRaw,
    };
    Object.entries(tabs).forEach(([key, container]) => {
      if (!container) return;
      container.classList.toggle("hidden", key !== state.researchDrawerTab);
    });
    document.querySelectorAll("[data-research-tab]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-research-tab") === state.researchDrawerTab);
    });
    if (!run) {
      renderList(el.researchRunSummary, [], (value) => value, "No research run recorded yet.");
      Object.values(tabs).forEach((container) => {
        if (container) container.innerHTML = '<div class="empty">No research trace yet.</div>';
      });
      el.researchRunActions.innerHTML = "";
      return;
    }
    const statusMeta = researchStatusMeta(run);
    if (run.status === "running" || run.status === "queued" || run.status === "failed" || run.status === "failed_retryable" || Number(run.accepted_graph_changes || 0) > 0) {
      const statusParts = [statusMeta.text];
      if (run.current_stage) statusParts.push(run.current_stage);
      if (run.current_entity_name) statusParts.push(run.current_entity_name);
      if (run.current_source_title) statusParts.push(run.current_source_title);
      setStatus(statusParts.join(" · "), statusMeta.tone);
    }
    const diff = run.graph_diff || {};
    const diffNamed = run.graph_diff_named || {};
    const diffCounts = [
      `new nodes ${Number((diff.new_node_ids || []).length)}`,
      `new edges ${Number((diff.new_edge_ids || []).length)}`,
      `updated nodes ${Number((diff.updated_node_ids || []).length)}`,
      `updated edges ${Number((diff.updated_edge_ids || []).length)}`,
    ].join(" · ");
    renderList(
      el.researchRunSummary,
      [
        `Status: ${run.status || "unknown"}`,
        `Run type: ${run.run_type || "unknown"}`,
        `Stage: ${run.current_stage || "n/a"}`,
        run.last_active_stage && run.last_active_stage !== run.current_stage ? `Last active stage: ${run.last_active_stage}` : null,
        `Model: ${run.resolved_model || run.selected_model || run.model_used || "n/a"}${run.selected_model && run.resolved_model && run.resolved_model !== run.selected_model ? ` · selected ${run.selected_model}` : ""}${run.fallback_used ? " · fallback used" : ""}`,
        `Search: ${run.search_provider || "unknown"}${run.internet_search_available === false ? " · unavailable" : ""}${run.limited_search_mode ? " · limited mode" : ""}`,
        `Target: ${(run.target_role || run.target_entity || "n/a")} · ${run.target_type || "relations"}${run.context_person ? ` · context ${run.context_person}` : ""}${run.date_from || run.date_to ? ` · ${run.date_from || "?"}–${run.date_to || "?"}` : ""}`,
        run.temporal_granularity ? `Temporal granularity: ${run.temporal_granularity}` : null,
        `Budget: ${run.budget_pages || "n/a"} pages · depth ${run.max_depth || "n/a"}`,
        `Search queries: ${Number(run.search_queries || 0)} · Model calls: ${Number(run.model_calls || 0)}`,
        `Items: done ${Number(run.counters?.done || 0)} · queued ${Number(run.counters?.queued || 0)} · failed ${Number(run.counters?.failed || 0)} · waiting ${Number(run.counters?.waiting || 0)}`,
        `Events: ${Number(run.event_count || state.latestResearchEvents.length || 0)}`,
        diffCounts,
        run.failure_explanation || "No failure diagnosis recorded.",
      ],
      (value) => escapeHtml(String(value)),
      "No research summary."
    );
    el.researchRunActions.innerHTML = "";
    const toggleBtn = document.createElement("button");
    toggleBtn.textContent = state.showLatestChangesOnly ? "Show all nodes" : "Show only new/updated";
    toggleBtn.disabled = !(diff.new_node_ids || []).length && !(diff.updated_node_ids || []).length;
    toggleBtn.onclick = () => {
      state.showLatestChangesOnly = !state.showLatestChangesOnly;
      renderResearchDrawer();
      refreshView();
    };
    const focusBtn = document.createElement("button");
    focusBtn.textContent = "Focus latest changes";
    focusBtn.disabled = toggleBtn.disabled;
    focusBtn.onclick = () => focusLatestChanges();
    el.researchRunActions.appendChild(toggleBtn);
    el.researchRunActions.appendChild(focusBtn);

    const renderTable = (rows, columns, emptyText) => {
      const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
      if (!values.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`;
      return `
        <div class="table-card">
          <table class="research-table">
            <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
            <tbody>
              ${values.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(String(row[column] ?? row[column.toLowerCase()] ?? row[column.replace(/ /g, "_").toLowerCase()] ?? ""))}</td>`).join("")}</tr>`).join("")}
            </tbody>
          </table>
        </div>`;
    };
    const renderUrlList = (items, emptyText) => items && items.length
      ? `<div class="list">${items.map((item) => {
          const url = typeof item === "string" ? item : (item.url || item.target_url || "");
          const label = typeof item === "string" ? item : (item.title || item.label || url);
          const status = typeof item === "string" ? "" : String(item.status || "");
          const reason = typeof item === "string" ? "" : String(item.reason || item.error || "");
          return `<div class="link-item"><a href="${escapeHtml(String(url))}" target="_blank" rel="noreferrer">${escapeHtml(String(label || url))}</a>${status || reason ? `<div class="muted">${escapeHtml([status, reason].filter(Boolean).join(" · "))}</div>` : ""}</div>`;
        }).join("")}</div>`
      : `<div class="empty">${escapeHtml(emptyText)}</div>`;
    const eventRows = state.latestResearchEvents.length ? state.latestResearchEvents : (run.events || []);
    const eventPayloadText = (event) => {
      const payload = event?.payload || {};
      return [
        payload.name || payload.label || payload.entity_name || payload.target_name || "",
        payload.url || payload.source_url || "",
        payload.evidence_quote || payload.snippet || payload.title || "",
      ].filter(Boolean).join(" · ");
    };
    const renderProcessTimeline = () => {
      const steps = [];
      steps.push({
        stage: "plan",
        title: run.query || "Research request",
        meta: [
          run.run_type || "",
          run.target_role || run.target_entity || "",
          `budget ${run.budget_pages || "n/a"} pages`,
        ].filter(Boolean).join(" · "),
        status: run.status || "running",
      });
      for (const block of run.search_hits || []) {
        steps.push({
          stage: "search",
          title: block?.query || "Search query",
          meta: `${block?.provider || run.search_provider || "search"} · ${(block?.results || []).length} results`,
          status: (block?.results || []).length ? "ok" : "warn",
        });
      }
      for (const source of (run.visited_sources || []).slice(0, 12)) {
        steps.push({
          stage: "open",
          title: source.title || source.url || "Visited source",
          meta: source.url || "",
          status: source.status || (source.reason ? "warn" : "ok"),
        });
      }
      for (const claim of (run.extracted_claim_items || []).slice(0, 10)) {
        steps.push({
          stage: "claim",
          title: claim.statement || [claim.subject_name, claim.relation_type, claim.object_name].filter(Boolean).join(" → ") || "Extracted claim",
          meta: claim.source_url || claim.evidence_quote || "",
          status: "ok",
        });
      }
      const changes = [
        ...(diffNamed.new_nodes || []).map((item) => ({ stage: "graph", title: item.name || item.id || "New node", meta: "new node", status: "ok" })),
        ...(diffNamed.updated_nodes || []).map((item) => ({ stage: "graph", title: item.name || item.id || "Updated node", meta: "updated node", status: "ok" })),
        ...(diffNamed.new_edges || []).map((item) => ({ stage: "graph", title: `${item.source_name || item.source_id || "source"} → ${item.target_name || item.target_id || "target"}`, meta: item.relation_type || "new edge", status: "ok" })),
        ...(diffNamed.updated_edges || []).map((item) => ({ stage: "graph", title: `${item.source_name || item.source_id || "source"} → ${item.target_name || item.target_id || "target"}`, meta: item.relation_type || "updated edge", status: "ok" })),
      ];
      steps.push(...changes.slice(0, 12));
      if (!steps.length) return '<div class="empty">No visible process steps recorded yet.</div>';
      return `<div class="process-timeline">${steps.slice(0, 40).map((step, index) => {
        const isActive = index === steps.length - 1 && ["running", "queued"].includes(String(run.status || ""));
        const tone = String(step.status || "").includes("fail") || String(step.status || "") === "error" ? "error" : String(step.status || "").includes("warn") || String(step.status || "") === "failed_fetch" ? "warn" : "ok";
        return `<div class="process-step ${isActive ? "active" : ""}">
          <div class="process-stage">${escapeHtml(step.stage)}</div>
          <div>
            <div class="process-title">${escapeHtml(step.title || "Step")}</div>
            ${step.meta ? `<div class="process-meta">${escapeHtml(step.meta)}</div>` : ""}
          </div>
          <div class="process-badge ${tone}">${escapeHtml(String(step.status || "ok"))}</div>
        </div>`;
      }).join("")}</div>`;
    };
    const renderEvidenceCards = (items, emptyText) => {
      const values = Array.isArray(items) ? items.filter(Boolean) : [];
      if (!values.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`;
      return `<div class="evidence-grid">${values.map((item) => {
        const title = item.statement || [item.subject_name, item.relation_type, item.object_name].filter(Boolean).join(" → ") || item.claim_type || "Claim";
        const meta = [item.claim_type || item.relation_type || "", item.source_url || ""].filter(Boolean).join(" · ");
        const quote = item.evidence_quote || item.quote || item.snippet || "";
        return `<div class="evidence-card">
          <div class="card-title">${escapeHtml(title)}</div>
          ${meta ? `<div class="card-meta">${escapeHtml(meta)}</div>` : ""}
          ${quote ? `<div class="quote">${escapeHtml(quote)}</div>` : ""}
        </div>`;
      }).join("")}</div>`;
    };
    const renderGraphChangeCards = () => {
      const changes = [
        ...(diffNamed.new_nodes || []).map((item) => ({ kind: "New node", title: item.name || item.id || "Node", meta: item.status || item.category || "" })),
        ...(diffNamed.updated_nodes || []).map((item) => ({ kind: "Updated node", title: item.name || item.id || "Node", meta: item.status || item.category || "" })),
        ...(diffNamed.new_edges || []).map((item) => ({ kind: "New edge", title: `${item.source_name || item.source_id || "source"} → ${item.target_name || item.target_id || "target"}`, meta: item.relation_type || "", quote: item.evidence_quote || "" })),
        ...(diffNamed.updated_edges || []).map((item) => ({ kind: "Updated edge", title: `${item.source_name || item.source_id || "source"} → ${item.target_name || item.target_id || "target"}`, meta: item.relation_type || "", quote: item.evidence_quote || "" })),
        ...(diffNamed.rejected_nodes || []).map((item) => ({ kind: "Rejected node", title: item.name || item.id || item.reason || "Rejected", meta: item.reason || "" })),
        ...(diffNamed.rejected_edges || []).map((item) => ({ kind: "Rejected edge", title: item.name || item.id || item.reason || "Rejected", meta: item.reason || "" })),
      ];
      if (!changes.length) return '<div class="empty">No graph changes recorded.</div>';
      return `<div class="graph-change-grid">${changes.map((item) => `<div class="graph-change-card">
        <div class="process-stage">${escapeHtml(item.kind)}</div>
        <div class="card-title">${escapeHtml(item.title)}</div>
        ${item.meta ? `<div class="card-meta">${escapeHtml(item.meta)}</div>` : ""}
        ${item.quote ? `<div class="quote">${escapeHtml(item.quote)}</div>` : ""}
      </div>`).join("")}</div>`;
    };

    const liveNow = [
      `Current stage: ${run.current_stage || "n/a"}`,
      `Current work item: ${run.current_work_item_type || "n/a"}`,
      `Current entity: ${run.current_entity_name || "n/a"}`,
      `Current source: ${run.current_source_title || "n/a"}${run.current_source_url ? ` · ${run.current_source_url}` : ""}`,
      `Current relation: ${run.current_relation_name || "n/a"}`,
      `Current claim: ${run.current_extracted_claim || "n/a"}`,
      `Current quote: ${run.current_extracted_quote || "n/a"}`,
      `Model: ${run.resolved_model || run.selected_model || run.model_used || "n/a"}${run.fallback_used ? " · fallback used" : ""}`,
      `Search: ${run.search_provider || "unknown"}${run.internet_search_available === false ? " · unavailable" : ""}${run.limited_search_mode ? " · limited mode" : ""}`,
      `Target: ${run.target_role || run.target_entity || "n/a"}${run.context_person ? ` · context ${run.context_person}` : ""}${run.date_from || run.date_to ? ` · ${run.date_from || "?"}–${run.date_to || "?"}` : ""}`,
      run.temporal_granularity ? `Temporal granularity: ${run.temporal_granularity}` : null,
      Array.isArray(run.years_checked) && run.years_checked.length ? `Years checked: ${run.years_checked.join(", ")}` : null,
      Array.isArray(run.roles_checked) && run.roles_checked.length ? `Roles checked: ${run.roles_checked.slice(0, 8).join(", ")}${run.roles_checked.length > 8 ? "…" : ""}` : null,
      Array.isArray(run.sources_checked) && run.sources_checked.length ? `Sources checked: ${run.sources_checked.slice(0, 8).join(", ")}${run.sources_checked.length > 8 ? "…" : ""}` : null,
      `Counts: search ${Number(run.search_queries || 0)} · model ${Number(run.model_calls || 0)} · waiting ${Number(run.counters?.waiting || 0)}`,
      `Events: ${Number(run.event_count || state.latestResearchEvents.length || 0)}`,
      run.failure_explanation || "No failure diagnosis recorded.",
    ];
    const searchRows = [];
    (run.search_hits || []).forEach((block) => {
      (block?.results || []).forEach((result) => {
        searchRows.push({
          query: block?.query || "",
          provider: block?.provider || "",
          title: result?.title || "",
          url: result?.url || "",
          snippet: result?.snippet || "",
          source: result?.source || "",
        });
      });
    });
    tabs.summary.innerHTML = `
      <div class="stacked-sections">
        <section class="trace-section">
          <h4>Visible LLM process</h4>
          ${renderProcessTimeline()}
        </section>
        <section class="trace-section">
          <h4>Now processing</h4>
          <div class="list">${liveNow.map((value) => `<div class="trace-item">${escapeHtml(String(value))}</div>`).join("")}</div>
        </section>
        <section class="trace-section">
          <h4>Search results</h4>
          ${renderTable(
            searchRows,
            ["query", "provider", "title", "url", "snippet"],
            run.limited_search_mode ? "Limited mode: external web search unavailable; using official seed URLs only." : "No search results recorded."
          )}
        </section>
        <section class="trace-section">
          <h4>Found entities</h4>
          ${renderTable(
            run.processed_entities || [],
            ["name", "type", "status", "source_url", "graph_action"],
            "No processed entities yet."
          )}
        </section>
        <section class="trace-section">
          <h4>Found relations</h4>
          ${renderTable(
            run.processed_relations || [],
            ["source_name", "relation_type", "target_name", "evidence_quote", "status"],
            "No processed relations yet."
          )}
        </section>
        <section class="trace-section">
          <h4>Visited websites</h4>
          ${renderTable(
            run.visited_sources || run.viewed_links || [],
            ["title", "url", "status", "reason"],
            run.limited_search_mode ? "Limited mode: external web search unavailable; using official seed URLs only." : "No visited links recorded."
          )}
        </section>
        <section class="trace-section">
          <h4>Extracted evidence</h4>
          ${renderEvidenceCards(run.extracted_claim_items || [], run.failure_explanation ? `No extracted claims because ${run.failure_explanation}.` : "No extracted claims recorded.")}
        </section>
        <section class="trace-section">
          <h4>Graph changes</h4>
          ${renderGraphChangeCards()}
          <div class="trace-item"><strong>Accepted / rejected graph changes</strong><div class="muted">${escapeHtml(`${run.accepted_graph_changes || 0} / ${run.rejected_graph_changes || 0}`)}</div></div>
          <div class="trace-item"><strong>Accepted change artifacts</strong><div class="muted">${escapeHtml(String(run.accepted_change_artifacts || 0))}</div></div>
          <div class="trace-item"><strong>Graph diff</strong><div class="muted">${escapeHtml(diffCounts)}</div></div>
          <div class="trace-item"><strong>Edge payloads</strong><div class="muted">${escapeHtml(String(run.edge_payload_count || 0))}</div></div>
        </section>
        <section class="trace-section">
          <h4>Coverage</h4>
          ${renderTable(
            [{
              years_checked: Array.isArray(run.years_checked) ? run.years_checked.join(", ") : "",
              roles_checked: Array.isArray(run.roles_checked) ? run.roles_checked.join(", ") : "",
              sources_checked: Array.isArray(run.sources_checked) ? run.sources_checked.join(", ") : "",
              confirmed_claims: String(run.confirmed_claims || 0),
              rejected_claims: String(run.rejected_claims || 0),
              unresolved_candidates: String(run.unresolved_candidates || 0),
            }],
            ["years_checked", "roles_checked", "sources_checked", "confirmed_claims", "rejected_claims", "unresolved_candidates"],
            "No coverage data recorded."
          )}
        </section>
        <section class="trace-section">
          <h4>Live events</h4>
          ${renderTable(
            eventRows.slice(-30).map((event) => ({
              event_type: event?.event_type || "",
              stage: event?.stage || "",
              item_id: event?.item_id || "",
              payload: eventPayloadText(event),
            })),
            ["event_type", "stage", "item_id", "payload"],
            "No live events recorded yet."
          )}
        </section>
      </div>`;
    tabs.viewed.innerHTML = renderUrlList(run.visited_sources || run.viewed_links || [], "No viewed links recorded.");
    tabs.accepted.innerHTML = renderUrlList(run.accepted_sources || [], run.failure_explanation ? `No accepted sources because ${run.failure_explanation}.` : "No accepted sources recorded.");
    tabs.rejected.innerHTML = renderUrlList(run.rejected_sources || [], run.failure_explanation ? `No rejected sources logged. Failure: ${run.failure_explanation}.` : "No rejected sources recorded.");
    tabs.claims.innerHTML = (run.extracted_claim_items || []).length
      ? renderEvidenceCards(run.extracted_claim_items || [], "No extracted claims recorded.")
      : `<div class="empty">${escapeHtml(run.failure_explanation ? `No extracted claims because ${run.failure_explanation}.` : "No extracted claims recorded.")}</div>`;
    tabs.diff.innerHTML = `
      <div class="list">
        ${renderGraphChangeCards()}
        <div class="trace-item"><strong>Accepted / rejected graph changes</strong><div class="muted">${escapeHtml(`${run.accepted_graph_changes || 0} / ${run.rejected_graph_changes || 0}`)}</div></div>
        <div class="trace-item"><strong>Accepted change artifacts</strong><div class="muted">${escapeHtml(String(run.accepted_change_artifacts || 0))}</div></div>
        <div class="trace-item"><strong>Graph diff</strong><div class="muted">${escapeHtml(diffCounts)}</div></div>
        <div class="trace-item"><strong>Edge payloads</strong><div class="muted">${escapeHtml(String(run.edge_payload_count || 0))}</div></div>
        <div class="trace-item"><strong>Failure reasons</strong><div class="muted">${escapeHtml((run.failure_reasons || []).join("; ") || "None")}</div></div>
      </div>`;
    if (tabs.events) {
      tabs.events.innerHTML = renderTable(
        eventRows.slice(-120).map((event) => ({
          event_type: event?.event_type || "",
          stage: event?.stage || "",
          item_id: event?.item_id || "",
          payload: eventPayloadText(event),
        })),
        ["event_type", "stage", "item_id", "payload"],
        "No live events recorded yet."
      );
    }
    tabs.raw.innerHTML = `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
  }

  function syncInspectorTabs() {
    if (el.inspectorEntityTab) el.inspectorEntityTab.classList.toggle("active", state.inspectorMode === "entity");
    if (el.inspectorRelationTab) el.inspectorRelationTab.classList.toggle("active", state.inspectorMode === "relation");
    if (el.inspectorModeCopy) {
      el.inspectorModeCopy.textContent = state.inspectorMode === "relation"
        ? "Relation inspector shows the last selected edge. Switch back to Entity to keep reading the last selected node dossier."
        : "Entity inspector stays pinned to the last selected node. Relation details are available in the adjacent tab.";
    }
  }

  function renderInspectorFromState() {
    if (state.inspectorMode === "relation" && state.lastRelationId && state.linkById.has(state.lastRelationId)) {
      renderLinkCard(state.linkById.get(state.lastRelationId));
      return;
    }
    if (state.lastEntityId && state.nodeById.has(state.lastEntityId)) {
      renderNodeCard(state.nodeById.get(state.lastEntityId));
      return;
    }
    if (state.lastRelationId && state.linkById.has(state.lastRelationId)) {
      renderLinkCard(state.linkById.get(state.lastRelationId));
      return;
    }
    renderEmptyInspector();
  }

  function updateSceneCopy() {
    if (state.sceneMode === "3d") {
      if (el.sceneWorkspaceLabel) el.sceneWorkspaceLabel.textContent = requestedWebGL3D() ? "3D orbit workspace" : "3D compatibility workspace";
      el.sceneModeTitle.textContent = "3D orbit";
      el.sceneModeCopy.textContent = "Orbit around the graph, inspect local structure, and read relation direction in space.";
      el.sceneMouseCopy.textContent = "Left drag: orbit. Wheel: zoom. Right drag or two-finger drag: pan. Click: inspect.";
      return;
    }
    if (el.sceneWorkspaceLabel) el.sceneWorkspaceLabel.textContent = "2D graph workspace";
    el.sceneModeTitle.textContent = "2D map";
    el.sceneModeCopy.textContent = "Read the whole network as a flat political map with clearer labels and relation lines.";
    el.sceneMouseCopy.textContent = "Left drag: pan. Wheel: zoom. Drag node: reposition. Click: inspect.";
  }

  function syncSceneButtons() {
    document.querySelectorAll("[data-view-mode]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-view-mode") === state.sceneMode);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function normalizeText(value) {
    return String(value || "").toLowerCase().replace(/[_\-\/]+/g, " ").replace(/\s+/g, " ").trim();
  }

  function getNodeFamily(node) {
    const text = normalizeText([node.category, node.subtype, node.name, ...(node.tags || [])].join(" "));
    if (text.includes("media")) return "media";
    if (text.includes("watchdog") || text.includes("civic")) return "watchdog";
    if (text.includes("business")) return "business";
    if (text.includes("opposition")) return "opposition";
    if (text.includes("party")) return "party";
    if (node.kind === "event" || text.includes("event")) return "event";
    if (node.category === "person") return "person";
    if (node.category === "organization") return "organization";
    if (node.category === "institution") return "official";
    if (node.category === "region" || node.category === "country" || text.includes("region")) return "regions";
    return "unknown";
  }

  function linkId(link) {
    return String(link.id || `${link.from}:${link.to}:${link.relation_type || "relation"}`);
  }

  function colorWithAlpha(hex, alpha) {
    const safe = Math.max(0, Math.min(1, alpha));
    const h = (hex || "#aeb8c5").replace("#", "");
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
    const n = parseInt(full, 16);
    const r = (n >> 16) & 255;
    const g = (n >> 8) & 255;
    const b = n & 255;
    return `rgba(${r}, ${g}, ${b}, ${safe})`;
  }

  function relationColor(type, relationClass = "") {
    const classMap = {
      institutional: "#62d0ff",
      membership: "#73d2b6",
      political_alignment: "#45d5c8",
      political_hierarchy: "#c7a7ff",
      business_relation: "#ff9f5c",
      financial_relation: "#b98cff",
      legal_relation: "#ffb36b",
      media_relation: "#ff8dc7",
      conflict_or_opposition: "#ff6483",
      event_co_participation: "#93a4b8",
      unknown_or_weak: "#7b8a99",
    };
    if (relationClass && classMap[relationClass]) return classMap[relationClass];
    const map = {
      opposes: "#ff6483",
      criticized_by: "#ff8f70",
      aligned_with: "#ffb36b",
      holds_office_in: "#62d0ff",
      part_of: "#7bd5c0",
      appointed_to: "#ffd36b",
      removed_from: "#ff8f70",
      member_of: "#86d2ff",
      funded_by: "#b98cff",
      investigated_by: "#9ed26b",
    };
    return map[type] || "#7b91a9";
  }

  function hashString(value) {
    let hash = 2166136261;
    const text = String(value || "");
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function hashUnit(value, salt = "") {
    return hashString(`${salt}:${value}`) / 4294967295;
  }

  const HASHISH_LABEL_RE = /^(?:[a-fA-F0-9]{8,}|[A-Z]?[a-fA-F0-9]{8,}[A-Za-z0-9]*|E[0-9A-Fa-f]{12,}[A-Za-z0-9]*)$/;

  function isRenderableGraphNode(raw) {
    const label = String(raw?.name || raw?.label || raw?.id || "").trim();
    const id = String(raw?.id || "").trim();
    if (!label) return false;
    if (HASHISH_LABEL_RE.test(label) || HASHISH_LABEL_RE.test(id)) return false;
    return true;
  }

  function buildVisualNode(raw) {
    const family = getNodeFamily(raw);
    const isHighlighted = state.runHighlights.nodeIds.has(String(raw.id || "")) && state.runHighlights.expiresAt > Date.now();
    const changeType = String(raw.change_type || "unchanged");
    return {
      ...raw,
      family,
      degree: Number(raw.degree || 0),
      color: isHighlighted ? "#ffd36b" : (raw.visual_color || COLORS[family] || COLORS.unknown),
      size: 4.2,
      isRunHighlight: isHighlighted,
      changeType,
      label: raw.name || raw.id,
      alwaysLabel: false,
      searchText: normalizeText([raw.id, raw.name, raw.summary, raw.category, raw.subtype, ...(raw.tags || [])].join(" ")),
    };
  }

  function buildVisualLink(raw) {
    const confidence = Math.max(0.15, Math.min(1, Number(raw.confidence ?? 0.6)));
    const isHighlighted = state.runHighlights.linkIds.has(String(linkId(raw) || "")) && state.runHighlights.expiresAt > Date.now();
    const relationClass = String(raw.relation_class || "").trim();
    const isDerived = String(raw.edge_kind || "") === "derived_relation" || raw.canonical === false;
    const changeType = String(raw.change_type || "unchanged");
    return {
      ...raw,
      id: linkId(raw),
      color: isHighlighted ? "#ffd36b" : (raw.visual_color || relationColor(raw.relation_type || "relation", relationClass)),
      width: (0.9 + confidence * (isDerived ? 1.0 : 1.6)) * ((isHighlighted || changeType === "new") ? 1.9 : changeType === "updated" ? 1.45 : 1),
      opacity: isHighlighted ? 0.92 : (isDerived ? 0.28 : 0.24 + confidence * 0.38),
      curvature: raw.curvature || 0.05,
      isRunHighlight: isHighlighted,
      isDerivedRelation: isDerived,
      changeType,
    };
  }

  function buildGraphData(payload) {
    const nodes = (payload.graph.nodes || []).filter(isRenderableGraphNode).map(buildVisualNode);
    const links = (payload.graph.links || []).map(buildVisualLink);
    const nodeMap = new Map(nodes.map((node) => [node.id, node]));

    for (const node of nodes) node.degree = 0;
    for (const link of links) {
      const source = nodeMap.get(link.from);
      const target = nodeMap.get(link.to);
      if (source) source.degree += 1;
      if (target) target.degree += 1;
    }
    for (const node of nodes) {
      node.size = Math.max(2.9, Math.min(14, 3.0 + Math.sqrt(node.degree) * 1.02 + (node.family === "event" ? 0.65 : 0)));
    }
    [...nodes]
      .sort((a, b) => (b.degree || 0) - (a.degree || 0))
      .slice(0, Math.min(10, nodes.length))
      .forEach((node) => {
        node.alwaysLabel = true;
      });
    for (const node of nodes) {
      const text = normalizeText([node.label, node.category, node.subtype, node.summary].join(" "));
      if (
        text.includes("pashinyan")
        || text.includes("government of armenia")
        || text.includes("national assembly")
        || text.includes("civil contract")
        || text.includes("prime minister")
      ) {
        node.alwaysLabel = true;
      }
    }

    state.graph = {
      nodes,
      links,
      stats: {
        entities: Number(payload.stats?.entities || payload.graph.entities?.length || nodes.length),
        relations: Number(payload.stats?.relations || payload.graph.relations?.length || links.length),
        event_nodes: Number(payload.stats?.event_nodes || payload.graph.event_nodes?.length || nodes.filter((node) => node.kind === "event").length),
      },
    };
    state.nodeById = nodeMap;
    state.linkById = new Map(links.map((link) => [link.id, link]));
    state.relationTypes = Array.isArray(payload.legend?.relation_types) ? payload.legend.relation_types : [];
  }

  function updateCounts() {
    el.entityCount.textContent = String(state.graph.stats.entities || state.graph.nodes.length || 0);
    el.relationCount.textContent = String(state.graph.stats.relations || state.graph.links.length || 0);
    el.eventCount.textContent = String(state.graph.stats.event_nodes || 0);
    const issues = Number(state.safety?.issues?.length || state.safety?.count || 0);
    el.issueCount.textContent = String(issues);
  }

  function setRunHighlights(payload) {
    const nodeIds = new Set(Array.isArray(payload?.node_ids) ? payload.node_ids.map((value) => String(value || "").trim()).filter(Boolean) : []);
    const linkIds = new Set(Array.isArray(payload?.link_ids) ? payload.link_ids.map((value) => String(value || "").trim()).filter(Boolean) : []);
    const ttlMs = Math.max(2000, Number(payload?.ttl_ms || 22000));
    state.runHighlights = {
      nodeIds,
      linkIds,
      expiresAt: Date.now() + ttlMs,
      reason: String(payload?.reason || "graph_update"),
    };
    window.clearTimeout(state.runHighlightsTimer);
    state.runHighlightsTimer = window.setTimeout(() => {
      state.runHighlights = { nodeIds: new Set(), linkIds: new Set(), expiresAt: 0, reason: "" };
      refreshWorkbenchLayers({ preserveSelection: true }).catch(() => {});
    }, ttlMs);
  }

  function focusLatestChanges() {
    const run = state.latestResearchRun?.run || {};
    const ids = [...(run.graph_diff?.new_node_ids || []), ...(run.graph_diff?.updated_node_ids || [])].map((value) => String(value || "").trim()).filter(Boolean);
    if (!ids.length) {
      setStatus("No graph diff to focus.", "warn");
      return;
    }
    const first = ids.find((id) => state.nodeById.has(id));
    if (first) {
      selectNode(first, { focus: true, refresh: true });
      setStatus("Focused latest graph changes.", "good");
    }
  }

  function populateFilters() {
    const typeValues = Array.from(new Set(state.graph.nodes.map((node) => node.category || node.family || "unknown"))).sort();
    const relValues = Array.from(new Set(state.graph.links.map((link) => link.relation_type || "relation"))).sort();
    const currentType = el.typeFilter.value || "all";
    const currentRel = el.linkFilter.value || "all";

    el.typeFilter.innerHTML = '<option value="all">All types</option>' + typeValues.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
    el.linkFilter.innerHTML = '<option value="all">All relations</option>' + relValues.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");

    if (typeValues.includes(currentType)) el.typeFilter.value = currentType;
    if (relValues.includes(currentRel)) el.linkFilter.value = currentRel;
  }

  function buildLegend() {
    const items = [
      ["all", "All families", COLORS.unknown],
      ["official", "Ruling / official", COLORS.official],
      ["opposition", "Opposition", COLORS.opposition],
      ["party", "Parties", COLORS.party],
      ["media", "Media", COLORS.media],
      ["watchdog", "Watchdog / civic", COLORS.watchdog],
      ["business", "Business", COLORS.business],
      ["regions", "Regions", COLORS.regions],
      ["event", "Events", COLORS.event],
    ];
    el.legend.innerHTML = items
      .map(([value, label, color]) => `<button type="button" class="legend-item filter-button ${state.familyFilter === value ? "active" : ""}" data-family-filter="${escapeHtml(value)}"><span class="legend-swatch" style="background:${color}"></span><span>${escapeHtml(label)}</span></button>`)
      .join("");
  }

  function matchesSearch(node, q) {
    if (!q) return true;
    return node.searchText.includes(q);
  }

  function computeVisibleGraph() {
    const q = normalizeText(el.search.value || "");
    const type = el.typeFilter.value || "all";
    const rel = el.linkFilter.value || "all";
    const latestDiff = state.latestResearchRun?.run?.graph_diff || {};
    const latestNodeIds = new Set([...(latestDiff.new_node_ids || []), ...(latestDiff.updated_node_ids || [])].map((value) => String(value || "").trim()).filter(Boolean));
    const latestEdgeIds = new Set([...(latestDiff.new_edge_ids || []), ...(latestDiff.updated_edge_ids || [])].map((value) => String(value || "").trim()).filter(Boolean));

    let nodes = state.graph.nodes.filter((node) => matchesSearch(node, q));
    if (state.familyFilter !== "all") nodes = nodes.filter((node) => (node.family || "unknown") === state.familyFilter);
    if (type !== "all") nodes = nodes.filter((node) => (node.category || node.family || "unknown") === type);
    if (state.showLatestChangesOnly) nodes = nodes.filter((node) => latestNodeIds.has(String(node.id || "").trim()));

    if (q) {
      const focusedIds = new Set(nodes.map((node) => node.id));
      for (const link of state.graph.links) {
        if (focusedIds.has(link.from)) focusedIds.add(link.to);
        if (focusedIds.has(link.to)) focusedIds.add(link.from);
      }
      nodes = state.graph.nodes.filter((node) => focusedIds.has(node.id));
      if (state.familyFilter !== "all") nodes = nodes.filter((node) => (node.family || "unknown") === state.familyFilter);
      if (type !== "all") nodes = nodes.filter((node) => (node.category || node.family || "unknown") === type);
    }

    const nodeIds = new Set(nodes.map((node) => node.id));
    let links = state.graph.links.filter((link) => nodeIds.has(link.from) && nodeIds.has(link.to));
    if (rel !== "all") links = links.filter((link) => (link.relation_type || "relation") === rel);
    if (state.showLatestChangesOnly) links = links.filter((link) => latestEdgeIds.has(String(link.id || "").trim()) || latestNodeIds.has(String(link.from || "").trim()) || latestNodeIds.has(String(link.to || "").trim()));

    state.visibleNodes = nodes;
    state.visibleLinks = links;
  }

  function seedDepth(nodes) {
    if (!Array.isArray(nodes) || !nodes.length) return;
    const familyDepth = {
      official: -320,
      ruling: -250,
      party: -110,
      opposition: 90,
      media: 220,
      watchdog: 280,
      business: 170,
      regions: 10,
      event: 340,
      person: 125,
      organization: 70,
      unknown: 0,
    };
    for (const node of nodes) {
      const base = familyDepth[node.family] ?? 0;
      const idScore = String(node.id || "")
        .split("")
        .reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
      const jitter = ((idScore % 41) - 20) * 12;
      const depth = Number.isFinite(node.z) ? node.z : base + jitter;
      node.z = depth;
      node.fz = depth;
    }
  }

  function familyAnchor3D(family, familyIndex, familyCount) {
    const familyBias = {
      official: { z: -360, y: -110 },
      ruling: { z: -280, y: -80 },
      party: { z: -120, y: -10 },
      opposition: { z: 130, y: 40 },
      media: { z: 310, y: 90 },
      watchdog: { z: 390, y: 120 },
      business: { z: 220, y: -40 },
      regions: { z: 10, y: -210 },
      person: { z: 170, y: 20 },
      organization: { z: 80, y: -20 },
      event: { z: 470, y: 190 },
      unknown: { z: 0, y: 0 },
    };
    const ringIndex = Math.max(0, familyIndex);
    const angle = (ringIndex / Math.max(1, familyCount)) * Math.PI * 2 - Math.PI / 2;
    const lift = Math.sin((ringIndex + 0.5) * 1.17) * 120;
    const bias = familyBias[family] || familyBias.unknown;
    return {
      x: Math.cos(angle) * 390,
      y: Math.sin(angle) * 235 + bias.y + lift,
      z: bias.z,
    };
  }

  function placeFamilyInSphere(items, anchor, family, scale = 1) {
    const golden = Math.PI * (3 - Math.sqrt(5));
    const count = Math.max(1, items.length);
    items.forEach((node, index) => {
      const t = count === 1 ? 0 : index / (count - 1);
      const yUnit = 1 - 2 * t;
      const radiusUnit = Math.sqrt(Math.max(0, 1 - yUnit * yUnit));
      const angle = index * golden + hashUnit(node.id, family) * Math.PI * 2;
      const degreeLift = Math.sqrt(Math.max(0, node.degree || 0));
      const shell = (70 + Math.min(170, count * 2.8) + degreeLift * 6) * scale;
      const jitter = 20 + hashUnit(node.id, "shell") * 34;
      node.x = anchor.x + Math.cos(angle) * radiusUnit * (shell + jitter);
      node.y = anchor.y + yUnit * shell * 0.82 + (hashUnit(node.id, "y") - 0.5) * 54;
      node.z = anchor.z + Math.sin(angle) * radiusUnit * (shell * 1.16 + jitter) + (hashUnit(node.id, "z") - 0.5) * 84;
      node.fx = node.x;
      node.fy = node.y;
      node.fz = node.z;
    });
  }

  function assignStableLayout(nodes, mode = "2d", layoutMode = state.layoutMode || "political-map") {
    if (!Array.isArray(nodes) || !nodes.length) return;
    const families = new Map();
    for (const family of FAMILY_ORDER) families.set(family, []);
    for (const node of nodes) {
      const family = node.family || "unknown";
      if (!families.has(family)) families.set(family, []);
      families.get(family).push(node);
    }

    const activeFamilies = [...families.entries()].filter(([, items]) => items.length);

    if (layoutMode === "political-map") {
      const rings = new Map([
        ["center", []],
        ["ministries", []],
        ["ministers", []],
        ["offices", []],
        ["institutions", []],
        ["parties", []],
        ["media", []],
        ["events", []],
        ["outer", []],
      ]);
      const ringForNode = (node) => {
        const text = normalizeText([node.label, node.category, node.subtype, node.summary].join(" "));
        if (text.includes("government of armenia")) return "center";
        if (text.includes("ministry of ")) return "ministries";
        if (node.category === "office" && text.includes("minister")) return "offices";
        if (node.category === "person" && (text.includes("minister") || text.includes("prime minister"))) return "ministers";
        if (text.includes("national assembly") || text.includes("parliament") || node.category === "institution") return "institutions";
        if (text.includes("party") || text.includes("faction")) return "parties";
        if (node.family === "media") return "media";
        if (node.family === "event") return "events";
        return "outer";
      };
      nodes.forEach((node) => rings.get(ringForNode(node)).push(node));
      const ringConfig = [
        ["center", 0, 0],
        ["ministries", 220, 0],
        ["ministers", 420, 80],
        ["offices", 310, -80],
        ["institutions", 620, 160],
        ["parties", 700, -120],
        ["media", 860, 220],
        ["events", 900, -250],
        ["outer", 980, 20],
      ];
      ringConfig.forEach(([ring, radius, zBase]) => {
        const items = rings.get(ring) || [];
        if (!items.length) return;
        if (ring === "center") {
          items.forEach((node, index) => {
            node.x = (index - (items.length - 1) / 2) * 90;
            node.y = 0;
            node.z = mode === "3d" ? zBase : 0;
            node.fx = node.x;
            node.fy = node.y;
            node.fz = node.z;
          });
          return;
        }
        items.sort((a, b) => (b.degree || 0) - (a.degree || 0));
        items.forEach((node, index) => {
          const angle = (index / Math.max(1, items.length)) * Math.PI * 2 - Math.PI / 2 + (hashUnit(node.id, ring) - 0.5) * 0.18;
          const localRadius = radius + (hashUnit(node.id, `${ring}:r`) - 0.5) * 70 + Math.sqrt(Math.max(0, node.degree || 0)) * 10;
          node.x = Math.cos(angle) * localRadius;
          node.y = Math.sin(angle) * (localRadius * 0.65);
          node.z = mode === "3d" ? zBase + (hashUnit(node.id, `${ring}:z`) - 0.5) * 120 : 0;
          node.fx = node.x;
          node.fy = node.y;
          node.fz = node.z;
        });
      });
      state.layoutCenter = { x: 0, y: 0, z: 0 };
      state.layoutRadius = mode === "3d" ? 1350 : 1120;
      return;
    }

    if (layoutMode === "radial") {
      const ringGap = mode === "3d" ? 82 : 112;
      const golden = Math.PI * (3 - Math.sqrt(5));
      nodes.forEach((node, index) => {
        const ring = Math.floor(index / 22);
        const radius = 90 + ring * ringGap;
        const angle = index * golden;
        node.x = Math.cos(angle) * radius;
        node.y = Math.sin(angle) * radius;
        node.z = mode === "3d" ? ((ring % 6) - 3) * 42 : 0;
        node.fx = node.x;
        node.fy = node.y;
        node.fz = node.z;
      });
      state.layoutCenter = { x: 0, y: 0, z: 0 };
      state.layoutRadius = 90 + Math.ceil(nodes.length / 22) * ringGap;
      return;
    }

    if (layoutMode === "hierarchical") {
      const byId = new Map(nodes.map((node) => [node.id, node]));
      const incoming = new Map(nodes.map((node) => [node.id, 0]));
      const outgoing = new Map(nodes.map((node) => [node.id, []]));
      for (const link of state.visibleLinks) {
        if (!byId.has(link.from) || !byId.has(link.to)) continue;
        incoming.set(link.to, (incoming.get(link.to) || 0) + 1);
        outgoing.get(link.from).push(link.to);
      }
      const depth = new Map(nodes.map((node) => [node.id, 0]));
      const queue = [];
      for (const node of nodes) {
        if ((incoming.get(node.id) || 0) === 0) queue.push(node.id);
      }
      let steps = 0;
      while (queue.length && steps < nodes.length * 6) {
        const current = queue.shift();
        steps += 1;
        const currentDepth = depth.get(current) || 0;
        for (const target of outgoing.get(current) || []) {
          if ((depth.get(target) || 0) < currentDepth + 1) depth.set(target, currentDepth + 1);
          incoming.set(target, Math.max(0, (incoming.get(target) || 0) - 1));
          if ((incoming.get(target) || 0) === 0) queue.push(target);
        }
      }
      const groups = new Map();
      for (const node of nodes) {
        const row = depth.get(node.id) || 0;
        if (!groups.has(row)) groups.set(row, []);
        groups.get(row).push(node);
      }
      const rows = [...groups.keys()].sort((a, b) => a - b);
      rows.forEach((row, rowIndex) => {
        const items = groups.get(row) || [];
        items.sort((a, b) => (b.degree || 0) - (a.degree || 0));
        items.forEach((node, index) => {
          const spread = 130;
          node.x = (index - (items.length - 1) / 2) * spread;
          node.y = rowIndex * 140 - (rows.length - 1) * 70;
          node.z = mode === "3d" ? (hashUnit(node.id, "hier") - 0.5) * 90 : 0;
          node.fx = node.x;
          node.fy = node.y;
          node.fz = node.z;
        });
      });
      state.layoutCenter = { x: 0, y: 0, z: 0 };
      state.layoutRadius = Math.max(420, rows.length * 150);
      return;
    }

    const anchorRadiusX = mode === "3d" ? 270 : 440;
    const anchorRadiusY = mode === "3d" ? 190 : 310;
    const golden = Math.PI * (3 - Math.sqrt(5));

    if (mode === "3d") {
      activeFamilies.forEach(([family, items], familyIndex) => {
        items.sort((a, b) => (b.degree || 0) - (a.degree || 0));
        const anchor = familyAnchor3D(family, familyIndex, activeFamilies.length);
        placeFamilyInSphere(items, anchor, family, activeFamilies.length > 8 ? 0.9 : 1);
      });
    } else {
    activeFamilies.forEach(([family, items], familyIndex) => {
      items.sort((a, b) => (b.degree || 0) - (a.degree || 0));
      const angle = (familyIndex / Math.max(1, activeFamilies.length)) * Math.PI * 2 - Math.PI / 2;
      const anchorX = Math.cos(angle) * anchorRadiusX;
      const anchorY = Math.sin(angle) * anchorRadiusY;
      const baseZ = mode === "3d" ? ({
        official: -260,
        ruling: -220,
        party: -120,
        opposition: 70,
        media: 200,
        watchdog: 240,
        business: 150,
        regions: 10,
        person: 110,
        organization: 60,
        event: 300,
        unknown: 0,
      }[family] ?? 0) : 0;

      items.forEach((node, index) => {
        const tier = Math.floor(index / 10);
        const radius = (mode === "3d" ? 16 : 30) + tier * (mode === "3d" ? 18 : 34) + (index % 10) * (mode === "3d" ? 4 : 9) + Math.sqrt(Math.max(0, node.degree || 0)) * (mode === "3d" ? 1.5 : 2.0);
        const localAngle = index * golden;
        const x = anchorX + Math.cos(localAngle) * radius;
        const y = anchorY + Math.sin(localAngle) * radius * 0.78;
        const z = mode === "3d" ? baseZ + ((index % 9) - 4) * 14 : 0;
        node.x = x;
        node.y = y;
        node.z = z;
        node.fx = x;
        node.fy = y;
        node.fz = z;
      });
    });
    }

    for (const node of nodes) {
      const centrality = Math.sqrt(Math.max(0, node.degree || 0));
      const pull = mode === "3d" ? Math.min(0.42, centrality / 26) : Math.min(0.93, centrality / 6);
      node.x *= 1 - pull;
      node.y *= 1 - pull * 0.9;
      node.z *= 1 - pull * 0.72;
      node.fx = node.x;
      node.fy = node.y;
      node.fz = node.z;
    }

    let minX = Infinity;
    let minY = Infinity;
    let minZ = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let maxZ = -Infinity;
    let weightSum = 0;
    let weightedX = 0;
    let weightedY = 0;
    let weightedZ = 0;
    for (const node of nodes) {
      const weight = 1 + Math.sqrt(Math.max(0, node.degree || 0));
      minX = Math.min(minX, node.x || 0);
      minY = Math.min(minY, node.y || 0);
      minZ = Math.min(minZ, node.z || 0);
      maxX = Math.max(maxX, node.x || 0);
      maxY = Math.max(maxY, node.y || 0);
      maxZ = Math.max(maxZ, node.z || 0);
      weightSum += weight;
      weightedX += (node.x || 0) * weight;
      weightedY += (node.y || 0) * weight;
      weightedZ += (node.z || 0) * weight;
    }
    const centerX = weightSum ? weightedX / weightSum : (minX + maxX) / 2;
    const centerY = weightSum ? weightedY / weightSum : (minY + maxY) / 2;
    const centerZ = weightSum ? weightedZ / weightSum : (minZ + maxZ) / 2;
    const scale = mode === "3d" ? 0.86 : 1.3;
    let maxAbsX = 0;
    let maxAbsY = 0;
    let maxAbsZ = 0;
    for (const node of nodes) {
      node.x = ((node.x || 0) - centerX) * scale;
      node.y = ((node.y || 0) - centerY) * scale;
      node.z = ((node.z || 0) - centerZ) * scale;
      node.fx = node.x;
      node.fy = node.y;
      node.fz = node.z;
      maxAbsX = Math.max(maxAbsX, Math.abs(node.x || 0));
      maxAbsY = Math.max(maxAbsY, Math.abs(node.y || 0));
      maxAbsZ = Math.max(maxAbsZ, Math.abs(node.z || 0));
    }
    state.layoutCenter = { x: 0, y: 0, z: 0 };
    state.layoutRadius = Math.max(maxAbsX, maxAbsY, maxAbsZ) + (mode === "3d" ? 350 : 140);
  }

  function selectedOrHoveredNode(node) {
    return node.id === state.selectedNodeId || node.id === state.hoveredNodeId || Boolean(node.isRunHighlight);
  }

  function selectedOrHoveredLink(link) {
    return link.id === state.selectedLinkId || link.id === state.hoveredLinkId || Boolean(link.isRunHighlight);
  }

  function destroyGraph() {
    try {
      if (state.orbit3DLite?.dispose) {
        state.orbit3DLite.dispose();
        state.orbit3DLite.dispose = null;
      }
      if (state.graphView?.pauseAnimation) state.graphView.pauseAnimation();
      const renderer = state.graphView?.renderer?.();
      if (renderer?.dispose) renderer.dispose();
      const controls = state.graphView?.controls?.();
      if (controls?.dispose) controls.dispose();
      if (state.graphView?._destructor) state.graphView._destructor();
    } catch (error) {
      console.warn("Graph destroy warning", error);
    }
    state.graphView = null;
    el.graph.innerHTML = "";
  }

  function centerGraphView(ms = 500) {
    if (!state.graphView) return;
    if (state.graphMode === "3d" && typeof state.graphView.cameraPosition === "function") {
      const target = state.layoutCenter || { x: 0, y: 0, z: 0 };
      const distance = Math.max(920, state.layoutRadius * 1.22);
      const controls = state.graphView.controls?.();
      if (controls?.target?.set) {
        controls.target.set(target.x || 0, target.y || 0, target.z || 0);
        controls.update?.();
      }
      state.graphView.cameraPosition({
        x: (target.x || 0) - distance * 0.15,
        y: (target.y || 0) + distance * 0.45,
        z: (target.z || 0) + distance * 1.0,
      }, target, ms);
      return;
    }
    if (
      ["2d", "3d-lite"].includes(state.graphMode)
      && typeof state.graphView.centerAt === "function"
      && typeof state.graphView.zoom === "function"
    ) {
      const rect = el.graph.getBoundingClientRect();
      const frame = Math.max(1, Math.min(rect.width || 1, rect.height || 1));
      const radius = Math.max(260, state.layoutRadius || 720);
      const zoom = state.graphMode === "3d-lite"
        ? Math.max(0.22, Math.min(1.8, frame / (radius * 1.55)))
        : Math.max(0.28, Math.min(1.6, frame / (radius * 2.15)));
      state.graphView.centerAt(0, 0, ms);
      state.graphView.zoom(zoom, ms);
      return;
    }
    if (typeof state.graphView.zoomToFit === "function") {
      state.graphView.zoomToFit(ms, 150);
    }
  }

  function make3DNodeObject(node) {
    const group = new THREE.Group();
    const size = Math.max(5.6, node.size * 0.84);
    const geometry = node.family === "event"
      ? new THREE.OctahedronGeometry(size, 0)
      : node.family === "official"
        ? new THREE.BoxGeometry(size * 1.2, size * 1.2, size * 1.2)
        : new THREE.SphereGeometry(size, 14, 14);

    const material = new THREE.MeshLambertMaterial({
      color: node.color,
      transparent: true,
      opacity: selectedOrHoveredNode(node) ? 1 : 0.92,
    });
    group.add(new THREE.Mesh(geometry, material));

    if (selectedOrHoveredNode(node)) {
      group.add(
        new THREE.Mesh(
          new THREE.SphereGeometry(size * 1.55, 14, 14),
          new THREE.MeshBasicMaterial({
            color: node.color,
            transparent: true,
            opacity: 0.16,
          })
        )
      );
    }

    if (selectedOrHoveredNode(node) || node.degree >= 12) {
      const label = String(node.label || node.id || "");
      if (label) {
        group.add(make3DLabel(label.length > 30 ? `${label.slice(0, 28)}...` : label, node.color, size));
      }
    }

    return group;
  }

  function make3DLabel(text, color, nodeSize) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    const fontSize = 34;
    ctx.font = `700 ${fontSize}px "IBM Plex Sans", "Segoe UI", sans-serif`;
    const width = Math.ceil(ctx.measureText(text).width + 34);
    canvas.width = Math.max(160, Math.min(640, width));
    canvas.height = 74;
    ctx.font = `700 ${fontSize}px "IBM Plex Sans", "Segoe UI", sans-serif`;
    ctx.fillStyle = "rgba(8, 14, 20, 0.84)";
    ctx.strokeStyle = colorWithAlpha(color, 0.72);
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.roundRect(2, 8, canvas.width - 4, canvas.height - 16, 8);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#ecf3f8";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 18, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
    const spriteScale = Math.min(150, Math.max(72, canvas.width * 0.18));
    sprite.scale.set(spriteScale, 34, 1);
    sprite.position.set(nodeSize + spriteScale * 0.55, nodeSize * 0.45, nodeSize * 0.25);
    return sprite;
  }

  function add3DDepthGuides(scene) {
    const grid = new THREE.GridHelper(1600, 16, 0x27384a, 0x172332);
    grid.name = "depth-floor";
    grid.position.y = -520;
    grid.material.transparent = true;
    grid.material.opacity = 0.32;
    scene.add(grid);

    const rearGrid = new THREE.GridHelper(1600, 16, 0x27384a, 0x172332);
    rearGrid.name = "depth-backplane";
    rearGrid.rotation.x = Math.PI / 2;
    rearGrid.position.z = -760;
    rearGrid.material.transparent = true;
    rearGrid.material.opacity = 0.18;
    scene.add(rearGrid);

    const axes = new THREE.AxesHelper(180);
    axes.name = "depth-axes";
    axes.position.set(-720, -500, -720);
    scene.add(axes);
  }

  function drawNodeLabel(node, ctx, globalScale) {
    if (node.changeType === "new" || node.changeType === "updated") {
      const haloRadius = Math.max(8, node.size * (node.changeType === "new" ? 2.1 : 1.7));
      ctx.save();
      ctx.beginPath();
      ctx.arc(node.x || 0, node.y || 0, haloRadius, 0, Math.PI * 2, false);
      ctx.strokeStyle = node.changeType === "new" ? "rgba(98, 208, 255, 0.78)" : "rgba(255, 204, 122, 0.72)";
      ctx.lineWidth = node.changeType === "new" ? 3.4 : 2.4;
      ctx.stroke();
      ctx.restore();
    }
    const show = selectedOrHoveredNode(node) || node.alwaysLabel || node.degree >= 10;
    if (!show) return;
    const label = node.label || node.id;
    if (!label) return;
    const fontSize = selectedOrHoveredNode(node) ? 15 : node.degree >= 14 ? 13 : 10.5;
    const text = label.length > 28 ? `${label.slice(0, 26)}...` : label;
    const x = node.x || 0;
    const y = node.y || 0;
    const radius = Math.max(5, node.size * 0.8);
    const scale = Math.max(0.75, Math.min(1.4, 1 / globalScale));

    ctx.save();
    ctx.font = `${fontSize * scale}px "IBM Plex Sans", sans-serif`;
    const width = ctx.measureText(text).width;
    const height = 18 * scale;
    const pad = 6 * scale;
    ctx.fillStyle = selectedOrHoveredNode(node) ? "rgba(8, 14, 20, 0.92)" : "rgba(8, 14, 20, 0.72)";
    ctx.strokeStyle = selectedOrHoveredNode(node) ? "rgba(134, 210, 255, 0.48)" : "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    const boxX = x + radius + 6;
    const boxY = y - height * 0.5;
    ctx.beginPath();
    ctx.roundRect(boxX, boxY, width + pad * 2, height, 8 * scale);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#ecf3f8";
    ctx.textBaseline = "middle";
    ctx.fillText(text, boxX + pad, y);
    ctx.restore();
  }

  function fallbackTo3DLite(message) {
    state.sceneMode = "3d";
    state.graphMode = "3d-lite";
    syncSceneButtons();
    updateSceneCopy();
    if (el.researchPanelSummary) {
      el.researchPanelSummary.innerHTML = `<div class="empty">${escapeHtml(message || "WebGL 3D could not start. Showing 3D compatibility view.")}</div>`;
    }
    setStatus("3D compatibility view: WebGL renderer was unavailable.", "warn");
    init3DLiteGraph();
  }

  function projected3DNode(node) {
    const rawX = Number(node.x || 0);
    const rawY = Number(node.y || 0);
    const rawZ = Number(node.z || 0);
    const yaw = Number(state.orbit3DLite?.yaw || 0);
    const pitch = Number(state.orbit3DLite?.pitch || 0);
    const zoom = Number(state.orbit3DLite?.zoom || 1);
    const panX = Number(state.orbit3DLite?.panX || 0);
    const panY = Number(state.orbit3DLite?.panY || 0);
    const cosY = Math.cos(yaw);
    const sinY = Math.sin(yaw);
    const cosP = Math.cos(pitch);
    const sinP = Math.sin(pitch);
    const x1 = rawX * cosY + rawZ * sinY;
    const z1 = -rawX * sinY + rawZ * cosY;
    const y2 = rawY * cosP - z1 * sinP;
    const z2 = rawY * sinP + z1 * cosP;
    const depth = Math.max(0.46, Math.min(1.45, 1 + z2 / 1800));
    const x = (x1 * depth + z2 * 0.14) * zoom + panX;
    const y = (y2 * depth - z2 * 0.08) * zoom + panY;
    return {
      ...node,
      rawX,
      rawY,
      rawZ,
      renderDepth: depth,
      x,
      y,
      fx: x,
      fy: y,
    };
  }

  function apply3DLiteProjection(nodes) {
    for (const node of nodes) {
      const projected = projected3DNode({ ...node, x: node.rawX, y: node.rawY, z: node.rawZ });
      node.x = projected.x;
      node.y = projected.y;
      node.fx = projected.x;
      node.fy = projected.y;
      node.renderDepth = projected.renderDepth;
    }
  }

  function fit3DLiteCamera(nodes) {
    if (!Array.isArray(nodes) || !nodes.length) return;
    state.orbit3DLite.zoom = 1;
    state.orbit3DLite.panX = 0;
    state.orbit3DLite.panY = 0;
    apply3DLiteProjection(nodes);
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const node of nodes) {
      minX = Math.min(minX, node.x || 0);
      minY = Math.min(minY, node.y || 0);
      maxX = Math.max(maxX, node.x || 0);
      maxY = Math.max(maxY, node.y || 0);
    }
    const rect = el.graph.getBoundingClientRect();
    const frameW = Math.max(320, (rect.width || 900) - 90);
    const frameH = Math.max(280, (rect.height || 700) - 110);
    const width = Math.max(1, maxX - minX);
    const height = Math.max(1, maxY - minY);
    state.orbit3DLite.zoom = Math.max(0.38, Math.min(1.18, Math.min(frameW / width, frameH / height) * 0.72));
    apply3DLiteProjection(nodes);
    minX = Infinity;
    minY = Infinity;
    maxX = -Infinity;
    maxY = -Infinity;
    for (const node of nodes) {
      minX = Math.min(minX, node.x || 0);
      minY = Math.min(minY, node.y || 0);
      maxX = Math.max(maxX, node.x || 0);
      maxY = Math.max(maxY, node.y || 0);
    }
    state.orbit3DLite.panX = -((minX + maxX) / 2);
    state.orbit3DLite.panY = -((minY + maxY) / 2);
    apply3DLiteProjection(nodes);
  }

  function init3DLiteGraph() {
    destroyGraph();
    computeVisibleGraph();
    assignStableLayout(state.visibleNodes, "3d", state.layoutMode);
    const nodes = state.visibleNodes.map((node) => ({
      ...node,
      rawX: Number(node.x || 0),
      rawY: Number(node.y || 0),
      rawZ: Number(node.z || 0),
    }));
    const links = state.visibleLinks.map((link) => ({ ...link }));
    fit3DLiteCamera(nodes);
    state.graphMode = "3d-lite";

    const canvas = document.createElement("canvas");
    canvas.style.display = "block";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.cursor = "grab";
    el.graph.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    let hoveredNode = null;
    let hoveredLink = null;
    let dragging = false;
    let dragMode = "rotate";
    let lastX = 0;
    let lastY = 0;
    let moved = false;

    const resizeCanvas = () => {
      const rect = el.graph.getBoundingClientRect();
      const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
      const width = Math.max(320, Math.floor(rect.width || 960));
      const height = Math.max(320, Math.floor(rect.height || 720));
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { width, height };
    };

    const projectAll = () => {
      apply3DLiteProjection(nodes);
      return new Map(nodes.map((node) => [node.id, node]));
    };

    const drawNode = (node, width, height) => {
        const x = width / 2 + (node.x || 0);
        const y = height / 2 + (node.y || 0);
        const depth = Number(node.renderDepth || 1);
        const radius = Math.max(2.5, node.size * 0.85 * depth);
        const active = selectedOrHoveredNode(node);
        ctx.save();
        ctx.beginPath();
        ctx.fillStyle = colorWithAlpha("#000000", 0.18);
        ctx.ellipse(x + radius * 0.8, y + radius * 0.9, radius * 1.2, radius * 0.52, 0, 0, Math.PI * 2);
        ctx.fill();
        const gradient = ctx.createRadialGradient(x - radius * 0.35, y - radius * 0.35, 1, x, y, radius);
        gradient.addColorStop(0, "#ffffff");
        gradient.addColorStop(0.18, colorWithAlpha(node.color, active ? 1 : 0.92));
        gradient.addColorStop(1, colorWithAlpha(node.color, active ? 0.72 : 0.48));
        ctx.beginPath();
        ctx.fillStyle = gradient;
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
        if (active) {
          ctx.strokeStyle = colorWithAlpha(node.color, 0.9);
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        if (active || node.alwaysLabel || node.degree >= 14) {
          const label = String(node.label || node.id || "");
          const text = label.length > 28 ? `${label.slice(0, 26)}...` : label;
          ctx.font = `${active ? 14 : 11}px "IBM Plex Sans", sans-serif`;
          const boxWidth = ctx.measureText(text).width + 12;
          const boxHeight = active ? 20 : 17;
          const boxX = x + radius + 7;
          const boxY = y - boxHeight / 2;
          ctx.fillStyle = active ? "rgba(8, 14, 20, 0.92)" : "rgba(8, 14, 20, 0.7)";
          ctx.strokeStyle = active ? colorWithAlpha(node.color, 0.75) : "rgba(255,255,255,0.08)";
          ctx.beginPath();
          ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 7);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = "#ecf3f8";
          ctx.textBaseline = "middle";
          ctx.fillText(text, boxX + 6, y);
        }
        ctx.restore();
    };

    const render = () => {
      const { width, height } = resizeCanvas();
      const nodeMap = projectAll();
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.strokeStyle = "rgba(134, 210, 255, 0.045)";
      ctx.lineWidth = 1;
      const gridStep = 64 * Math.max(0.6, state.orbit3DLite.zoom);
      const gridOffsetX = (width / 2 + state.orbit3DLite.panX) % gridStep;
      const gridOffsetY = (height / 2 + state.orbit3DLite.panY) % gridStep;
      for (let x = gridOffsetX; x < width; x += gridStep) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x + Math.sin(state.orbit3DLite.yaw) * 34, height);
        ctx.stroke();
      }
      for (let y = gridOffsetY; y < height; y += gridStep) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y + Math.sin(state.orbit3DLite.pitch) * 30);
        ctx.stroke();
      }
      ctx.restore();

      const sortedLinks = [...links].sort((a, b) => {
        const aDepth = ((nodeMap.get(a.from)?.renderDepth || 1) + (nodeMap.get(a.to)?.renderDepth || 1)) / 2;
        const bDepth = ((nodeMap.get(b.from)?.renderDepth || 1) + (nodeMap.get(b.to)?.renderDepth || 1)) / 2;
        return aDepth - bDepth;
      });
      for (const link of sortedLinks) {
        const source = nodeMap.get(link.from);
        const target = nodeMap.get(link.to);
        if (!source || !target) continue;
        const active = selectedOrHoveredLink(link);
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(width / 2 + (source.x || 0), height / 2 + (source.y || 0));
        ctx.lineTo(width / 2 + (target.x || 0), height / 2 + (target.y || 0));
        ctx.strokeStyle = colorWithAlpha(link.color, active ? 0.88 : Math.max(0.12, link.opacity * 0.78));
        ctx.lineWidth = active ? Math.max(2.6, link.width * 1.4) : Math.max(0.7, link.width * 0.75);
        ctx.stroke();
        ctx.restore();
      }

      const sortedNodes = [...nodes].sort((a, b) => (a.renderDepth || 1) - (b.renderDepth || 1));
      for (const node of sortedNodes) drawNode(node, width, height);
    };

    const findNodeAt = (clientX, clientY) => {
      const rect = canvas.getBoundingClientRect();
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      let best = null;
      let bestDistance = Infinity;
      for (const node of nodes) {
        const sx = rect.width / 2 + (node.x || 0);
        const sy = rect.height / 2 + (node.y || 0);
        const radius = Math.max(5, node.size * 1.2 * Number(node.renderDepth || 1));
        const dist = Math.hypot(x - sx, y - sy);
        if (dist <= radius + 8 && dist < bestDistance) {
          best = node;
          bestDistance = dist;
        }
      }
      return best;
    };

    const onPointerDown = (event) => {
      if (![0, 1, 2].includes(event.button)) return;
      dragging = true;
      moved = false;
      dragMode = event.button === 2 || event.shiftKey || event.altKey || event.metaKey ? "pan" : "rotate";
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.style.cursor = dragMode === "pan" ? "grabbing" : "move";
      canvas.setPointerCapture?.(event.pointerId);
      event.preventDefault();
    };
    const onPointerMove = (event) => {
      if (!dragging) {
        const node = findNodeAt(event.clientX, event.clientY);
        hoveredNode = node;
        state.hoveredNodeId = node ? node.id : null;
        canvas.style.cursor = node ? "pointer" : "grab";
        render();
        return;
      }
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      if (Math.abs(dx) + Math.abs(dy) > 1) moved = true;
      if (dragMode === "pan") {
        state.orbit3DLite.panX += dx;
        state.orbit3DLite.panY += dy;
      } else {
        state.orbit3DLite.yaw += dx * 0.008;
        state.orbit3DLite.pitch = Math.max(-1.22, Math.min(1.22, state.orbit3DLite.pitch + dy * 0.006));
      }
      setStatus(`3D camera: rotate ${Math.round(state.orbit3DLite.yaw * 57.3)}°, tilt ${Math.round(state.orbit3DLite.pitch * 57.3)}°. Shift/right drag pans.`, "warn");
      render();
      event.preventDefault();
    };
    const onPointerUp = (event) => {
      if (!dragging) return;
      dragging = false;
      canvas.style.cursor = "grab";
      if (!moved) {
        const node = findNodeAt(event.clientX, event.clientY);
        if (node) {
          selectNode(node.id, { focus: false, refresh: false });
          render();
        }
      }
      event.preventDefault();
    };
    const onWheel = (event) => {
      const before = state.orbit3DLite.zoom;
      const factor = Math.exp(-event.deltaY * 0.0012);
      state.orbit3DLite.zoom = Math.max(0.16, Math.min(3.2, before * factor));
      render();
      event.preventDefault();
    };
    const onDoubleClick = (event) => {
      state.orbit3DLite.yaw = -0.55;
      state.orbit3DLite.pitch = 0.34;
      fit3DLiteCamera(nodes);
      render();
      setStatus("3D camera refit. Left drag rotates, Shift/right drag pans, wheel zooms.", "warn");
      event.preventDefault();
    };
    const onContextMenu = (event) => event.preventDefault();
    const onResize = () => render();

    canvas.addEventListener("pointerdown", onPointerDown);
    canvas.addEventListener("pointermove", onPointerMove);
    canvas.addEventListener("pointerup", onPointerUp);
    canvas.addEventListener("pointercancel", onPointerUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });
    canvas.addEventListener("dblclick", onDoubleClick);
    canvas.addEventListener("contextmenu", onContextMenu);
    window.addEventListener("resize", onResize);

    state.graphView = {
      graphData() {
        render();
        return this;
      },
      refresh: render,
      centerAt(x = 0, y = 0) {
        state.orbit3DLite.panX = -Number(x || 0);
        state.orbit3DLite.panY = -Number(y || 0);
        render();
        return this;
      },
      zoom(value) {
        if (typeof value === "number") {
          state.orbit3DLite.zoom = Math.max(0.16, Math.min(3.2, value));
          render();
          return this;
        }
        return state.orbit3DLite.zoom;
      },
      pauseAnimation() {},
      _destructor() {
        canvas.removeEventListener("pointerdown", onPointerDown);
        canvas.removeEventListener("pointermove", onPointerMove);
        canvas.removeEventListener("pointerup", onPointerUp);
        canvas.removeEventListener("pointercancel", onPointerUp);
        canvas.removeEventListener("wheel", onWheel);
        canvas.removeEventListener("dblclick", onDoubleClick);
        canvas.removeEventListener("contextmenu", onContextMenu);
        window.removeEventListener("resize", onResize);
      },
    };

    render();
    setStatus("3D camera ready. Left drag rotates, Shift/right drag pans, wheel zooms, double-click fits.", "warn");
  }

  function initGraph() {
    destroyGraph();
    computeVisibleGraph();

    if (state.sceneMode === "3d" && !requestedWebGL3D()) {
      init3DLiteGraph();
      return;
    }

    if (state.sceneMode === "3d" && !window.ForceGraph3D) {
      fallbackTo3DLite("3D graph library is unavailable. Showing 3D compatibility view.");
      return;
    }

    if (state.sceneMode === "3d" && window.ForceGraph3D) {
      seedDepth(state.visibleNodes);
      assignStableLayout(state.visibleNodes, "3d", state.layoutMode);
      state.graphMode = "3d";
      try {
        state.graphView = window.ForceGraph3D({
          controlType: "orbit",
          rendererConfig: {
            antialias: true,
            alpha: true,
            powerPreference: "high-performance",
          },
        })(el.graph)
          .backgroundColor("#0b1117")
          .nodeId("id")
          .linkSource("from")
          .linkTarget("to")
          .showNavInfo(false)
          .enablePointerInteraction(true)
          .enableNodeDrag(false)
          .nodeResolution(16)
          .linkResolution(10)
          .nodeLabel((node) => `${node.label}${node.summary ? "\n" + node.summary : ""}`)
          .nodeVal((node) => node.size * (selectedOrHoveredNode(node) ? 1.25 : 1))
          .nodeColor((node) => colorWithAlpha(node.color, selectedOrHoveredNode(node) ? 1 : 0.9))
          .nodeThreeObject((node) => make3DNodeObject(node))
          .nodeThreeObjectExtend(true)
          .linkColor((link) => {
            const ctx = String(link.event_context || "");
            if (selectedOrHoveredLink(link)) return colorWithAlpha(link.color, 0.95);
            if (ctx === "conflict" || ctx === "political_crisis") return colorWithAlpha("#ef4444", 0.8);
            if (ctx === "dismissal") return colorWithAlpha("#f59e0b", 0.75);
            return colorWithAlpha(link.color, link.opacity);
          })
          .linkLabel((link) => link.human_text || link.natural_language_summary || link.label || "")
          .linkWidth((link) => selectedOrHoveredLink(link) ? Math.max(3.8, link.width * 2.2) : Math.max(1.6, link.width * 1.35))
          .linkOpacity(0.62)
          .linkCurvature((link) => selectedOrHoveredLink(link) ? 0.14 : 0.08)
          .linkDirectionalArrowLength((link) => selectedOrHoveredLink(link) ? 7 : 0)
          .linkDirectionalArrowRelPos(0.92)
          .linkDirectionalParticles((link) => selectedOrHoveredLink(link) ? 3 : 0)
          .linkDirectionalParticleWidth((link) => selectedOrHoveredLink(link) ? 3.2 : 0)
          .onNodeHover((node) => {
            state.hoveredNodeId = node ? node.id : null;
            refreshGraphStyles();
          })
          .onNodeClick((node) => {
            selectNode(node.id, { focus: true, refresh: false });
            refreshGraphStyles();
          })
          .onLinkHover((link) => {
            state.hoveredLinkId = link ? link.id : null;
            refreshGraphStyles();
          })
          .onLinkClick((link) => {
            selectLink(link.id, { refresh: false });
            refreshGraphStyles();
          });
      } catch (error) {
        console.error("3D graph init failed", error);
        fallbackTo3DLite(`3D graph failed to start: ${error.message || error}. Showing 3D compatibility view.`);
        return;
      }

      try {
        state.graphView.graphData({ nodes: state.visibleNodes, links: state.visibleLinks });
        state.graphView.cooldownTicks(0);
        const scene = state.graphView.scene?.();
        if (scene) {
          scene.add(new THREE.AmbientLight(0xffffff, 1.05));
          const key = new THREE.DirectionalLight(0xffffff, 0.7);
          key.position.set(220, 260, 280);
          scene.add(key);
          scene.fog = new THREE.Fog(0x0b1117, 760, 2600);
          add3DDepthGuides(scene);
        }
        const controls = state.graphView.controls?.();
        if (controls) {
        controls.enablePan = true;
        controls.enableRotate = true;
        controls.enableDamping = true;
          controls.dampingFactor = 0.08;
          controls.rotateSpeed = 0.85;
          controls.zoomSpeed = 0.95;
          controls.panSpeed = 0.9;
          controls.minDistance = 12;
          controls.maxDistance = 4200;
        controls.zoomSpeed = 1.15;
        controls.panSpeed = 1.05;
        controls.autoRotate = false;
        if (window.THREE?.MOUSE && controls.mouseButtons) {
          controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
          controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
        }
      }
        centerGraphView(800);
        window.setTimeout(() => centerGraphView(0), 120);
        window.setTimeout(() => centerGraphView(0), 900);
        setStatus(`3D orbit ready: ${state.visibleNodes.length} nodes. Drag to rotate, wheel to zoom.`, "good");
        return;
      } catch (error) {
        console.error("3D graph render failed", error);
        fallbackTo3DLite(`3D graph failed to render: ${error.message || error}. Showing 3D compatibility view.`);
        return;
      }
    }

    assignStableLayout(state.visibleNodes, "2d", state.layoutMode);
    state.graphMode = "2d";
    state.graphView = window.ForceGraph()(el.graph)
      .backgroundColor("#0b1117")
      .nodeId("id")
      .linkSource("from")
      .linkTarget("to")
      .enablePanInteraction(true)
      .enableZoomInteraction(true)
      .enableZoomPanInteraction(true)
      .enableNodeDrag(true)
      .minZoom(0.05)
      .maxZoom(18)
      .nodeLabel((node) => `${node.label}${node.summary ? "\n" + node.summary : ""}`)
      .nodeVal((node) => Math.max(1.8, node.size * (selectedOrHoveredNode(node) ? 0.88 : 0.64)))
      .nodeColor((node) => colorWithAlpha(node.color, selectedOrHoveredNode(node) ? 1 : 0.88))
      .linkColor((link) => {
        const ctx = String(link.event_context || "");
        if (selectedOrHoveredLink(link)) return colorWithAlpha(link.color, 0.95);
        if (ctx === "conflict" || ctx === "political_crisis") return colorWithAlpha("#ef4444", 0.75);
        if (ctx === "dismissal") return colorWithAlpha("#f59e0b", 0.7);
        return colorWithAlpha(link.color, link.opacity);
      })
      .linkLabel((link) => link.human_text || link.natural_language_summary || link.label || "")
      .linkWidth((link) => selectedOrHoveredLink(link) ? Math.max(2.6, link.width * 1.6) : Math.max(0.95, link.width * 1.0))
      .nodeCanvasObjectMode(() => "after")
      .nodeCanvasObject((node, ctx, globalScale) => drawNodeLabel(node, ctx, globalScale))
      .linkCanvasObjectMode(() => "after")
      .linkCanvasObject((link, ctx) => {
        const source = link.source;
        const target = link.target;
        if (!source || !target || typeof source !== "object" || typeof target !== "object") return;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(source.x || 0, source.y || 0);
        ctx.lineTo(target.x || 0, target.y || 0);
        ctx.strokeStyle = colorWithAlpha(link.color, selectedOrHoveredLink(link) ? 0.18 : 0.06);
        ctx.lineWidth = selectedOrHoveredLink(link) ? 4.6 : 1.8;
        ctx.stroke();
        if (link.changeType === "new" || link.changeType === "updated") {
          ctx.beginPath();
          ctx.setLineDash(link.changeType === "updated" ? [7, 5] : []);
          ctx.moveTo(source.x || 0, source.y || 0);
          ctx.lineTo(target.x || 0, target.y || 0);
          ctx.strokeStyle = link.changeType === "new" ? "rgba(98, 208, 255, 0.52)" : "rgba(255, 204, 122, 0.46)";
          ctx.lineWidth = link.changeType === "new" ? 3.2 : 2.4;
          ctx.stroke();
          ctx.setLineDash([]);
        }
        ctx.restore();
      })
      .linkCurvature((link) => selectedOrHoveredLink(link) ? 0.1 : 0.03)
      .linkDirectionalArrowLength((link) => selectedOrHoveredLink(link) ? 5.2 : 0)
      .linkDirectionalArrowRelPos(0.92)
      .linkDirectionalParticles((link) => selectedOrHoveredLink(link) ? 2 : 0)
      .linkDirectionalParticleWidth(2)
      .linkHoverPrecision(10)
      .onNodeHover((node) => {
        state.hoveredNodeId = node ? node.id : null;
        refreshGraphStyles();
      })
      .onNodeClick((node) => {
        selectNode(node.id, { focus: true, refresh: false });
        refreshGraphStyles();
      })
      .onLinkHover((link) => {
        state.hoveredLinkId = link ? link.id : null;
        refreshGraphStyles();
      })
      .onLinkClick((link) => {
          selectLink(link.id, { refresh: false });
          refreshGraphStyles();
      });

    state.graphView.graphData({ nodes: state.visibleNodes, links: state.visibleLinks });
    state.graphView.cooldownTicks(0);
    centerGraphView(800);
    window.setTimeout(() => centerGraphView(0), 120);
    window.setTimeout(() => centerGraphView(0), 900);
    setStatus(`2D map ready: ${state.visibleNodes.length} nodes. Drag to pan, click to inspect.`, "good");
  }

  function refreshGraphStyles() {
    if (!state.graphView) return;
    if (typeof state.graphView.refresh === "function") {
      state.graphView.refresh();
    } else if (typeof state.graphView.graphData === "function") {
      state.graphView.graphData({ nodes: state.visibleNodes, links: state.visibleLinks });
    }
  }

  function refreshView() {
    computeVisibleGraph();
    if (!state.graphView) {
      initGraph();
      return;
    }
    if (state.graphMode === "3d-lite") {
      init3DLiteGraph();
      return;
    }
    state.graphView.graphData({ nodes: state.visibleNodes, links: state.visibleLinks });
    refreshGraphStyles();
  }

  function focusNode(nodeId) {
    const node = state.nodeById.get(nodeId);
    if (!node || !state.graphView) return;

    if (state.graphMode === "3d" && typeof state.graphView.cameraPosition === "function") {
      state.graphView.cameraPosition(
        { x: node.x || 0, y: (node.y || 0) + 80, z: (node.z || 0) + 220 },
        { x: node.x || 0, y: node.y || 0, z: node.z || 0 },
        900
      );
      return;
    }
    if (typeof state.graphView.centerAt === "function") {
      state.graphView.centerAt(node.x || 0, node.y || 0, 800);
    }
    if (typeof state.graphView.zoom === "function") {
      state.graphView.zoom(4, 600);
    }
  }

  function clearSelection({ refresh = true } = {}) {
    state.selectedNodeId = null;
    state.selectedLinkId = null;
    state.lastEntityId = null;
    state.lastRelationId = null;
    renderEmptyInspector();
    if (refresh) refreshView();
  }

  function selectNode(nodeId, { focus = false, refresh = true } = {}) {
    const node = state.nodeById.get(nodeId);
    if (!node) return;
    state.selectedLinkId = null;
    state.selectedNodeId = nodeId;
    state.lastEntityId = nodeId;
    state.inspectorMode = "entity";
    syncInspectorTabs();
    renderNodeCard(node);
    if (refresh) refreshView();
    else refreshGraphStyles();
    if (focus) focusNode(nodeId);
    api(`/api/node/${encodeURIComponent(nodeId)}/card`)
      .then((payload) => {
        if (!payload?.card || state.selectedNodeId !== nodeId) return;
        node._entityCard = payload.card;
        renderNodeCard(node);
      })
      .catch(() => {});
  }

  function selectLink(linkId, { refresh = true } = {}) {
    const link = state.linkById.get(linkId);
    if (!link) return;
    state.selectedNodeId = null;
    state.selectedLinkId = linkId;
    state.lastRelationId = linkId;
    state.inspectorMode = "relation";
    syncInspectorTabs();
    renderLinkCard(link);
    if (refresh) refreshView();
    else refreshGraphStyles();
    api(`/api/relation/${encodeURIComponent(linkId)}/dossier`)
      .then((payload) => {
        if (!payload?.dossier || state.selectedLinkId !== linkId) return;
        link._dossier = payload.dossier;
        renderLinkCard(link);
      })
      .catch(() => {});
  }

  function renderPills(container, values) {
    container.innerHTML = "";
    const seen = new Set();
    for (const raw of values.filter(Boolean)) {
      const value = String(raw).trim();
      const key = normalizeText(value);
      if (!value || seen.has(key)) continue;
      seen.add(key);
      const pill = document.createElement("span");
      pill.className = "pill";
      pill.textContent = value;
      container.appendChild(pill);
    }
  }

  function normalizeUrlLabel(url) {
    try {
      return new URL(url).hostname.replace(/^www\./, "");
    } catch {
      return url;
    }
  }

  function renderLinksPills(container, items) {
    container.innerHTML = "";
    const deduped = [];
    const seen = new Set();
    for (const item of items) {
      const url = String(item?.url || "").trim();
      if (!url || seen.has(url)) continue;
      seen.add(url);
      deduped.push(item);
      if (deduped.length >= 4) break;
    }
    for (const item of deduped) {
      const link = document.createElement("a");
      link.className = "link-pill";
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = item.label || normalizeUrlLabel(item.url);
      container.appendChild(link);
    }
  }

  function renderList(container, items, formatter = (value) => value, emptyText = "No data.") {
    container.innerHTML = "";
    const values = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!values.length) {
      container.innerHTML = `<div class="empty">${escapeHtml(emptyText)}</div>`;
      return;
    }
    for (const item of values) {
      const div = document.createElement("div");
      div.className = "list-item";
      div.innerHTML = formatter(item);
      container.appendChild(div);
    }
  }

  function normalizeLinks(value) {
    if (Array.isArray(value)) {
      return value.filter((item) => item && item.url).map((item) => ({ label: item.label || "link", url: item.url }));
    }
    if (value && typeof value === "object") {
      return Object.entries(value)
        .filter(([, url]) => url)
        .map(([label, url]) => ({ label, url: String(url) }));
    }
    return [];
  }

  function splitLinks(node) {
    const base = normalizeLinks(node.links);
    const extra = (node.source_urls || []).filter(Boolean).map((url) => ({ label: "source", url }));
    const all = [...base, ...extra];
    const official = all.filter((item) => /(official|site|homepage|facebook|x|twitter|instagram|youtube|web)/i.test(`${item.label} ${item.url}`));
    const sources = all.filter((item) => !official.includes(item));
    return { official, sources };
  }

  function relationSentence(link) {
    if (link.semantic_summary) return String(link.semantic_summary);
    if (link.human_text) return String(link.human_text);
    const source = state.nodeById.get(link.from);
    const target = state.nodeById.get(link.to);
    return `${source?.name || link.from} — ${link.relation_type || "relation"} → ${target?.name || link.to}`;
  }

  function renderSuggestions(suggestions) {
    const items = [];
    for (const entry of suggestions?.suggested_nodes || []) {
      const id = typeof entry === "string" ? entry : entry?.id || entry?.node_id || entry?.name;
      if (!id) continue;
      items.push(`<button type="button" class="search-result" data-node-link="${escapeHtml(id)}">${escapeHtml(id)}</button>`);
    }
    for (const query of suggestions?.suggested_queries || []) {
      items.push(`<div class="list-item">${escapeHtml(query)}</div>`);
    }
    el.detailSuggestions.innerHTML = items.length ? items.join("") : '<div class="empty">No suggestions.</div>';
  }

  function renderNodeCard(node) {
    syncInspectorTabs();
    const links = splitLinks(node);
    const card = node._entityCard || node.entity_card || null;
    const profile = node.profile || {};
    const network = profile.network || profile.related_entities || {};
    const isPerson = node.category === "person";
    const historyTitle = isPerson ? "History / Biography" : "History / Functions";
    const perspectivesTitle = card ? "Current Roles / Functions" : "Perspectives";
    const timelineTitle = "Timeline";
    const evidenceTitle = "Evidence / Sources";
    const directTitle = "Direct Network";
    const indirectTitle = "Claims / Disputes";
    el.detailHistoryTitle.textContent = historyTitle;
    el.detailPerspectivesTitle.textContent = perspectivesTitle;
    el.detailActivityTitle.textContent = timelineTitle;
    el.detailLinksTitle.textContent = evidenceTitle;
    el.detailRelationsTitle.textContent = directTitle;
    el.detailProvenanceTitle.textContent = indirectTitle;
    const biography = Array.isArray(card?.biography_or_history) && card.biography_or_history.length
      ? card.biography_or_history
      : Array.isArray(profile.history_or_biography) && profile.history_or_biography.length
      ? profile.history_or_biography
      : [profile.neutral_analytic_summary || profile.overview || node.summary || ""];
    const perspectives = Array.isArray(card?.current_roles_or_functions) && card.current_roles_or_functions.length
      ? card.current_roles_or_functions.map((value) => ({ perspective_type: "role/function", summary: value }))
      : Array.isArray(node.perspectives) && node.perspectives.length
      ? node.perspectives
      : [];
    const timeline = Array.isArray(card?.timeline) && card.timeline.length
      ? card.timeline
      : Array.isArray(profile.timeline) && profile.timeline.length
      ? profile.timeline
      : (profile.notable_events || profile.actions || []);
    const evidence = Array.isArray(card?.source_links) && card.source_links.length
      ? card.source_links
      : Array.isArray(profile.evidence) && profile.evidence.length
      ? profile.evidence
      : (Array.isArray(profile.source_links) && profile.source_links.length ? profile.source_links : [...links.official, ...links.sources]);
    const directNetwork = Array.isArray(card?.direct_network) && card.direct_network.length
      ? card.direct_network
      : Array.isArray(network.direct) && network.direct.length
      ? network.direct
      : state.graph.links.filter((link) => link.from === node.id || link.to === node.id).slice(0, 24);
    const indirectNetwork = [
      ...(Array.isArray(card?.indirect_network) ? card.indirect_network.map((value) => ({ kind: "indirect_network", value })) : []),
      ...(Array.isArray(card?.evidence_summary) ? card.evidence_summary.map((value) => ({ kind: "evidence_summary", value })) : []),
      ...(Array.isArray(profile.dispute_flags) ? profile.dispute_flags.map((value) => ({ kind: "dispute_flag", value })) : []),
      ...(Array.isArray(profile.evidence_summary) ? profile.evidence_summary.map((value) => ({ kind: "evidence_summary", value })) : []),
    ];
    const quality = card?.profile_quality || profile.profile_quality || {};
    el.detailName.textContent = node.name || node.id;
    el.detailMeta.textContent = [node.category || "entity", node.subtype, node.family, quality.coverage ? `profile: ${quality.coverage}` : ""].filter(Boolean).join(" · ");
    el.detailSummary.textContent = card?.overview || profile.neutral_analytic_summary || profile.overview || node.summary || "No summary available.";
    renderPills(el.detailTags, [node.category, node.subtype, node.family, quality.coverage ? `profile:${quality.coverage}` : null, ...(quality.missing_sections || []).slice(0, 3), ...(profile.dispute_flags || []).slice(0, 2), ...(node.tags || []).slice(0, 6)]);
    renderLinksPills(el.detailHeroLinks, Array.isArray(card?.source_links) && card.source_links.length ? card.source_links : Array.isArray(profile.source_links) && profile.source_links.length ? profile.source_links : (links.official.length ? links.official : links.sources));

    renderList(el.detailHistory, biography, (value) => escapeHtml(String(value)), "No history block available.");
    renderList(
      el.detailPerspectives,
      perspectives,
      (value) => `<strong>${escapeHtml(String(value.perspective_type || value.source_group || "perspective"))}</strong><div class="muted">${escapeHtml(String(value.summary || ""))}</div>`,
      "No perspectives available."
    );
    renderList(
      el.detailActivity,
      timeline,
      (value) => typeof value === "string"
        ? escapeHtml(String(value))
        : `<strong>${escapeHtml(value.date || value.title || "Event")}</strong><div class="muted">${escapeHtml(value.summary || value.title || "")}</div>${value.url ? `<div class="muted"><a href="${escapeHtml(value.url)}" target="_blank" rel="noreferrer">${escapeHtml(normalizeUrlLabel(value.url))}</a></div>` : ""}`,
      "No timeline items are attached yet. Run Internet Research to improve this profile."
    );
    renderList(
      el.detailLinks,
      evidence,
      (value) => typeof value === "string"
        ? `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(value)}</a>`
        : `<div><a href="${escapeHtml(value.url)}" target="_blank" rel="noreferrer">${escapeHtml(value.title || value.label || value.domain || value.url)}</a></div><div class="muted">${escapeHtml([value.domain, value.source_type, value.date_if_known].filter(Boolean).join(" · "))}</div>`,
      "No source-backed evidence is attached to this profile yet."
    );

    renderList(
      el.detailRelations,
      directNetwork,
      (item) => {
        if (item && Object.prototype.hasOwnProperty.call(item, "entity_id")) {
          return `<strong>${escapeHtml(item.human_text || item.relation_type || "relation")}</strong>
            <div><strong>${escapeHtml(item.name || item.entity_id)}</strong></div>
            <div class="muted">confidence ${Number(item.confidence || 0).toFixed(2)}</div>
            ${item.source_link?.url ? `<div class="muted"><a href="${escapeHtml(item.source_link.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.source_link.domain || item.source_link.title || "source")}</a></div>` : ""}`;
        }
        const other = state.nodeById.get(item.from === node.id ? item.to : item.from);
        return `<strong>${escapeHtml(item.human_text || item.relation_type || "relation")}</strong>
          <div>${escapeHtml(item.from === node.id ? "to" : "from")} <strong>${escapeHtml(other?.name || (item.from === node.id ? item.to : item.from))}</strong></div>
          <div class="muted">confidence ${Number(item.confidence || 0).toFixed(2)}</div>
          ${item.evidence_quote ? `<div class="muted">${escapeHtml(item.evidence_quote)}</div>` : ""}`;
      },
      "No direct network entries are available yet. This profile is thin. Run Internet Research to improve it."
    );

    renderList(
      el.detailProvenance,
      indirectNetwork,
      (item) => item.kind === "indirect_network"
        ? `<strong>${escapeHtml(item.value?.via_name || item.value?.relation_type || "Indirect path")}</strong><div class="muted">${escapeHtml(item.value?.human_text || item.value?.name || item.value?.entity_id || "")}</div>`
        : item.kind === "dispute_flag"
        ? `<strong>Dispute flag</strong><div class="muted">${escapeHtml(String(item.value || ""))}</div>`
        : `<strong>Evidence summary</strong><div class="muted">${escapeHtml(String(item.value || ""))}</div>`,
      "No indirect network or evidence summary is available yet."
    );
    el.detailActions.innerHTML = "";

    const focusBtn = document.createElement("button");
    focusBtn.textContent = "Focus node";
    focusBtn.onclick = () => selectNode(node.id, { focus: true });

    el.detailActions.appendChild(focusBtn);
    renderSuggestions(state.latestSuggestions);
    if (state.runHighlights.nodeIds.has(String(node.id || "")) && state.runHighlights.expiresAt > Date.now()) {
      el.detailSuggestions.innerHTML = `<div class="list-item"><strong>New In This Run</strong><div class="muted">This node was added or updated by the latest workflow.</div></div>${el.detailSuggestions.innerHTML}`;
    }
  }

  function renderLinkCard(link) {
    syncInspectorTabs();
    const dossier = link._dossier || link.dossier || null;
    const sourceNode = state.nodeById.get(link.from);
    const targetNode = state.nodeById.get(link.to);
    const adjacentLinks = state.graph.links.filter((candidate) => {
      if (!candidate || candidate.id === link.id) return false;
      return candidate.from === link.from || candidate.to === link.from || candidate.from === link.to || candidate.to === link.to;
    }).slice(0, 8);

    const linkTitle = dossier?.relation_title || dossier?.short_label || link.short_label || link.human_text || "Relation";
    const linkSummary = dossier?.semantic_summary || link.semantic_summary || link.natural_language_summary || relationSentence(link);
    const eventCtx = link.event_context ? ` · ${link.event_context}` : "";
    const timeline = dossier?.timeline || link.timeline || {};
    const timelineStr = Array.isArray(timeline) ? "" : [timeline.start_date, timeline.end_date].filter(Boolean).join(" → ") || "";
    const modelAnalysis = link.model_analysis || {};
    const mechanismTags = Array.isArray(dossier?.mechanisms) ? dossier.mechanisms : Array.isArray(link.mechanism_tags) ? link.mechanism_tags : [];
    const basisPaths = Array.isArray(dossier?.derived_paths) && dossier.derived_paths.length ? dossier.derived_paths : Array.isArray(link.basis_paths) ? link.basis_paths : [];

    el.detailHistoryTitle.textContent = "Analysis";
    el.detailPerspectivesTitle.textContent = "Interpretation";
    el.detailActivityTitle.textContent = "Timeline";
    el.detailLinksTitle.textContent = "Evidence";
    el.detailRelationsTitle.textContent = "Adjacent Relations";
    el.detailProvenanceTitle.textContent = "Source Provenance";

    el.detailName.textContent = linkTitle;
    el.detailMeta.textContent = `${dossier?.relation_class || link.relation_class || "relation"} / ${dossier?.relation_type || link.relation_type || "relation"} · confidence ${Number(dossier?.confidence ?? link.confidence ?? 0).toFixed(2)}${(dossier?.canonical === false || link.canonical === false) ? " · derived, not canonical" : ""}${eventCtx}${timelineStr ? " · " + timelineStr : ""}`;
    el.detailSummary.textContent = linkSummary;
    renderPills(el.detailTags, [link.relation_class, link.relation_type, link.event_context, link.edge_kind, selectedOrHoveredLink(link) ? "active" : null, modelAnalysis.connection_strength, modelAnalysis.stability, ...mechanismTags].filter(Boolean));
    renderLinksPills(el.detailHeroLinks, link.source_url ? [{ label: "Relation source", url: link.source_url }] : []);

    // History → Model analysis interpretation
    const analysisItems = [];
    if (linkSummary) analysisItems.push(linkSummary);
    if (dossier?.role_from || dossier?.role_to || link.role_from || link.role_to) analysisItems.push(`Roles: ${sourceNode?.name || link.from} = ${dossier?.role_from || link.role_from || "source"}; ${targetNode?.name || link.to} = ${dossier?.role_to || link.role_to || "target"}.`);
    if (mechanismTags.length) analysisItems.push(`Mechanisms: ${mechanismTags.join(", ")}`);
    if (modelAnalysis.interpretation) analysisItems.push(modelAnalysis.interpretation);
    if (modelAnalysis.political_implication) analysisItems.push(`Political implication: ${modelAnalysis.political_implication}`);
    if (link.evidence_quote) analysisItems.push(link.evidence_quote);
    renderList(el.detailHistory, analysisItems.length ? analysisItems : [link.evidence_quote || ""], (value) => escapeHtml(String(value)), "No analysis available.");

    // Perspectives → Model analysis details
    const perspectiveItems = [];
    if (modelAnalysis.connection_strength) perspectiveItems.push(`Connection strength: ${modelAnalysis.connection_strength}`);
    if (modelAnalysis.stability) perspectiveItems.push(`Stability: ${modelAnalysis.stability}`);
    if (modelAnalysis.political_implication) perspectiveItems.push(`Political implication: ${modelAnalysis.political_implication}`);
    perspectiveItems.push(`Source: ${sourceNode?.name || link.from}`);
    perspectiveItems.push(`Target: ${targetNode?.name || link.to}`);
    if (link.canonical === false) perspectiveItems.push("This is a derived semantic relation built from canonical paths, not a separate canonical fact.");
    renderList(el.detailPerspectives, perspectiveItems, (value) => escapeHtml(String(value)), "No relation details.");

    // Timeline
    const timelineItems = [];
    if (Array.isArray(timeline)) {
      for (const item of timeline.slice(0, 8)) timelineItems.push(item);
    } else {
      if (timeline.start_date) timelineItems.push({ date: timeline.start_date, title: "Start", summary: `Relation active since ${timeline.start_date}` });
      if (timeline.end_date) timelineItems.push({ date: timeline.end_date, title: "End", summary: `Relation ended ${timeline.end_date}` });
    }
    if (link.event_context) timelineItems.push({ date: "", title: "Event context", summary: link.event_context });
    if (basisPaths.length) timelineItems.push({ date: "", title: "Basis path", summary: basisPaths.map((path) => Array.isArray(path) ? path.join(" → ") : (path.labels || path.node_ids || []).join(" → ")).join(" | ") });
    renderList(
      el.detailActivity,
      timelineItems,
      (value) => typeof value === "string"
        ? escapeHtml(String(value))
        : `<strong>${escapeHtml(value.date || value.title || "Event")}</strong><div class="muted">${escapeHtml(value.summary || value.title || "")}</div>`,
      "No timeline items."
    );

    // Evidence tab → structured evidence list
    const evidenceList = Array.isArray(dossier?.evidence) && dossier.evidence.length
      ? dossier.evidence
      : Array.isArray(link.evidence) && link.evidence.length
      ? link.evidence
      : (link.source_url ? [{ label: "Relation source", url: link.source_url, fact: link.evidence_quote || "" }] : []);
    renderList(
      el.detailLinks,
      evidenceList,
      (value) => typeof value === "string"
        ? `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(value)}</a>`
        : `<div>${value.url || value.source_url ? `<a href="${escapeHtml(value.url || value.source_url || "")}" target="_blank" rel="noreferrer">${escapeHtml(value.title || value.label || value.source_title || value.url || value.source_url || "source")}</a>` : `<strong>${escapeHtml(value.id || "Evidence")}</strong>`}</div>${value.fact || value.quote ? `<div class="muted">${escapeHtml(value.fact || value.quote)}</div>` : ""}`,
      "No evidence links."
    );

    renderList(
      el.detailRelations,
      adjacentLinks,
      (value) => {
        const other = value.from === link.from || value.from === link.to ? state.nodeById.get(value.to) : state.nodeById.get(value.from);
        return `<strong>${escapeHtml(value.human_text || value.relation_type || "relation")}</strong>
          <div>${escapeHtml(value.from === link.from || value.from === link.to ? "to" : "from")} <strong>${escapeHtml(other?.name || (value.from === link.from || value.from === link.to ? value.to : value.from))}</strong></div>
          <div class="muted">${escapeHtml(value.natural_language_summary || value.human_text || relationSentence(value))}</div>`;
      },
      "No adjacent relations."
    );
    renderList(
      el.detailProvenance,
      link.source_link ? [link.source_link] : [],
      (value) => `<strong>${escapeHtml(value.title || value.label || value.domain || "Source")}</strong>
        <div class="muted">${escapeHtml([value.domain, value.source_type, value.date_if_known].filter(Boolean).join(" · "))}</div>
        <div><a href="${escapeHtml(value.url)}" target="_blank" rel="noreferrer">${escapeHtml(value.url)}</a></div>`,
      "No indirect network item."
    );
    el.detailActions.innerHTML = "";

    const sourceBtn = document.createElement("button");
    sourceBtn.textContent = "Focus source";
    sourceBtn.onclick = () => selectNode(link.from, { focus: true });

    const targetBtn = document.createElement("button");
    targetBtn.textContent = "Focus target";
    targetBtn.onclick = () => selectNode(link.to, { focus: true });

    el.detailActions.appendChild(sourceBtn);
    el.detailActions.appendChild(targetBtn);
    renderList(el.detailSuggestions, [], (value) => escapeHtml(String(value)), "No suggestions.");
    if (state.runHighlights.linkIds.has(String(link.id || "")) && state.runHighlights.expiresAt > Date.now()) {
      el.detailSuggestions.innerHTML = `<div class="list-item"><strong>New In This Run</strong><div class="muted">This relation was added or updated by the latest workflow.</div></div>${el.detailSuggestions.innerHTML}`;
    }
  }

  function renderEmptyInspector() {
    syncInspectorTabs();
    el.detailHistoryTitle.textContent = "Biography";
    el.detailPerspectivesTitle.textContent = "Current Roles";
    el.detailActivityTitle.textContent = "Timeline";
    el.detailLinksTitle.textContent = "Evidence / Sources";
    el.detailRelationsTitle.textContent = "Direct Network";
    el.detailProvenanceTitle.textContent = "Indirect Network";
    el.detailName.textContent = "Select a node";
    el.detailMeta.textContent = "Click a node to inspect it or search to focus a match.";
    el.detailSummary.textContent = "The graph stays readable on load. Search or click a node to open its dossier.";
    el.detailTags.innerHTML = "";
    el.detailHeroLinks.innerHTML = "";
    renderList(el.detailHistory, [], (value) => value, "No history.");
    renderList(el.detailPerspectives, [], (value) => value, "No perspectives.");
    renderList(el.detailActivity, [], (value) => value, "No activity.");
    renderList(el.detailLinks, [], (value) => value, "No links.");
    renderList(el.detailRelations, [], (value) => value, "No relations.");
    renderList(el.detailProvenance, [], (value) => value, "No provenance.");
    el.detailActions.innerHTML = "";
    renderList(el.detailSuggestions, [], (value) => value, "No suggestions.");
  }

  function rebuildSearchResults(results) {
    if (!results.length) {
      const query = (el.search?.value || "").trim();
      el.searchResults.innerHTML = query ? '<div class="empty">No local graph matches.</div>' : '<div class="empty">Type to search the graph.</div>';
      return;
    }
    el.searchResults.innerHTML = results.map((item, index) => {
      const id = item.id || item.node_id || "";
      const title = item.name || item.label || id;
      const subtitle = item.summary || item.category || "";
      return `<div class="search-result" data-node-link="${escapeHtml(id)}" data-search-rank="${index}"><strong>${escapeHtml(title)}</strong><div class="muted">${escapeHtml(subtitle)}</div></div>`;
    }).join("");
  }

  function localSearchResults(query, limit = 10) {
    const q = normalizeText(query);
    if (!q) return [];
    return state.graph.nodes
      .filter((node) => matchesSearch(node, q))
      .sort((a, b) => {
        const aStarts = normalizeText(a.label || a.id).startsWith(q) ? 1 : 0;
        const bStarts = normalizeText(b.label || b.id).startsWith(q) ? 1 : 0;
        if (aStarts !== bStarts) return bStarts - aStarts;
        if ((a.degree || 0) !== (b.degree || 0)) return (b.degree || 0) - (a.degree || 0);
        return String(a.label || a.id).localeCompare(String(b.label || b.id));
      })
      .slice(0, limit)
      .map((node) => ({
        id: node.id,
        name: node.label || node.name || node.id,
        summary: node.summary || node.category || "",
        category: node.category || node.family || "entity",
      }));
  }

  function populateCommandModelSelector(payload) {
    const modes = Array.isArray(payload?.modes) ? payload.modes : [];
    el.commandModelMode.innerHTML = modes.map((mode) => `<option value="${escapeHtml(mode.id)}">${escapeHtml(mode.label || mode.id)}</option>`).join("");
    if (payload?.default_mode) el.commandModelMode.value = payload.default_mode;
    syncCommandModelInfo(payload);
  }

  function syncCommandModelInfo(payload = null) {
    const selectedId = el.commandModelMode?.value;
    const source = payload?.modes || Array.from(el.commandModelMode.options).map((option) => ({ id: option.value, label: option.textContent }));
    const found = source.find((entry) => entry.id === selectedId);
    el.commandModelInfo.textContent = found ? `${found.label || found.id}` : "Model selected.";
  }

  async function loadCommandModels() {
    try {
      const payload = await api("/api/models");
      populateCommandModelSelector(payload);
    } catch {
      const fallback = {
        modes: [
          { id: "auto", label: "Auto" },
          { id: "local/ollama", label: "Local / Ollama · gemma4:e4b" },
          { id: "openai/gpt-5.4-nano", label: "OpenAI / GPT-5.4 Nano" },
        ],
        default_mode: "local/ollama",
      };
      populateCommandModelSelector(fallback);
      el.commandModelInfo.textContent = "Model catalog unavailable. Using fallback modes.";
    }
  }

  async function refreshWorkbenchLayers({ preserveSelection = true } = {}) {
    const [staticPayload, corePayload, runtimePayload, safetyPayload, diffPayload, flowsPayload, latestResearchPayload] = await Promise.all([
      api("/knowledge_graph.json"),
      api("/api/graph/core"),
      api("/api/task-runtime"),
      api("/api/graph-safety"),
      api("/api/graph/diff/latest"),
      api("/api/flows?limit=8"),
      api("/api/research/runs/latest").catch(() => ({ ok: false })),
    ]);

    state.runtime = runtimePayload;
    state.safety = safetyPayload;
    state.flows = flowsPayload?.runs || [];
    state.latestResearchRun = latestResearchPayload?.ok ? latestResearchPayload : null;
    if (diffPayload?.run_id) state.lastDiffRunId = diffPayload.run_id;

    const staticGraph = normalizeGraphPayload(staticPayload);
    const core = normalizeGraphPayload(corePayload);
    if (staticGraph) state.latestGraphLayers.static = staticGraph;
    if (core) state.latestGraphLayers.core = core;
    const active = mergeGraphPayloads(staticGraph, core) || state.latestGraphLayers.core || state.latestGraphLayers.static || core || staticGraph;
    if (!active) throw new Error("No graph payload returned.");
    buildGraphData(active);

    if (!preserveSelection) {
      state.selectedNodeId = null;
      state.selectedLinkId = null;
      state.lastEntityId = null;
      state.lastRelationId = null;
    }
    if (state.selectedNodeId && !state.nodeById.has(state.selectedNodeId)) state.selectedNodeId = null;
    if (state.selectedLinkId && !state.linkById.has(state.selectedLinkId)) state.selectedLinkId = null;
    if (state.lastEntityId && !state.nodeById.has(state.lastEntityId)) state.lastEntityId = null;
    if (state.lastRelationId && !state.linkById.has(state.lastRelationId)) state.lastRelationId = null;

    updateCounts();
    populateFilters();
    buildLegend();
    updateRuntimeSignals();
    updateFlowRuns();
    renderResearchDrawer();
    renderInspectorFromState();
    refreshView();
  }

  function updateRuntimeSignals() {
    const items = [];
    if (state.runtime?.selected_workflow) items.push(`Workflow: ${state.runtime.selected_workflow}`);
    if (state.runtime?.assistant_summary) items.push(state.runtime.assistant_summary);
    if (state.runtime?.render_backend) items.push(`Backend: ${state.runtime.render_backend}`);
    if (state.safety?.summary) items.push(state.safety.summary);
    renderList(el.runtimeSignals, items, (value) => escapeHtml(String(value)), "No runtime signals.");
  }

  function updateFlowRuns() {
    renderList(
      el.flowRuns,
      state.flows || [],
      (run) => `<strong>${escapeHtml(run.title || run.task_type || "Flow")}</strong><div class="muted">${escapeHtml(run.status || "")}</div>`,
      "No recent flows."
    );
  }

  async function pollWorkbenchDiff() {
    try {
      const payload = await api("/api/graph/diff/latest");
      if (!payload?.run_id || payload.run_id === state.lastDiffRunId) return;
      await refreshWorkbenchLayers({ preserveSelection: true });
      setStatus(`Live graph update received for ${payload.task_type || "workflow"}.`, "good");
    } catch {
      // ignore polling failures
    }
  }

  async function pollResearchTrace() {
    try {
      const payload = await api("/api/research/runs/latest").catch(() => null);
      if (!payload?.ok || !payload.run) return;
      const previousRunId = state.latestResearchRun?.run?.run_id || "";
      const nextRunId = String(payload.run.run_id || payload.run_id || "");
      const previousStatus = state.latestResearchRun?.run?.status || state.latestResearchRun?.status || "";
      const nextStatus = payload.run.status || payload.status || "";
      const previousStage = state.latestResearchRun?.run?.current_stage || "";
      const nextStage = payload.run.current_stage || "";
      const previousEvents = Number(state.latestResearchRun?.run?.event_count || state.latestResearchRun?.event_count || 0);
      const nextEvents = Number(payload.run?.event_count || payload.event_count || 0);
      if (nextRunId && (nextRunId !== previousRunId || nextStatus !== previousStatus || nextStage !== previousStage || nextEvents !== previousEvents)) {
        state.latestResearchRun = payload;
        renderResearchDrawer();
      }
      if (nextRunId) {
        void pollResearchEvents(nextRunId);
      }
    } catch {
      // ignore polling failures
    }
  }

  async function pollResearchEvents(runId) {
    if (!runId) return;
    try {
      const payload = await api(`/api/research/runs/${encodeURIComponent(runId)}/events?after_ts=${state.latestResearchEventTs || 0}&limit=120`).catch(() => null);
      if (!payload?.ok || !Array.isArray(payload.events) || !payload.events.length) return;
      for (const event of payload.events) {
        if (Number(event.ts || 0) > state.latestResearchEventTs) {
          state.latestResearchEventTs = Number(event.ts || 0);
        }
      }
      state.latestResearchEvents = [...state.latestResearchEvents, ...payload.events].slice(-400);
      state.latestResearchEventCount = state.latestResearchEvents.length;
      if (state.latestResearchRun?.run) {
        state.latestResearchRun.run.event_count = state.latestResearchEventCount;
      }
      renderResearchDrawer();
    } catch {
      // ignore polling failures
    }
  }

  async function runCommandFromInput() {
    const command = el.commandInput.value.trim();
    if (!command) {
      setStatus("Enter a research query first.", "warn");
      return;
    }
    try {
      setStatus(`Running research: ${command}`, "warn");
      const response = await api("/api/research/run", {
        method: "POST",
        body: JSON.stringify({
          query: command,
          target_entity: el.researchEntity?.value?.trim() || "",
          target_type: el.researchTarget?.value || "relations",
          date_from: el.researchDateFrom?.value || "",
          date_to: el.researchDateTo?.value || "",
          budget_pages: Number(el.researchBudget?.value || 30),
          source_priority: el.researchSourcePriority?.value || "official,reliable_media,watchdogs",
        }),
      });
      const trace = response?.trace?.ok ? response.trace : response;
      state.latestResearchRun = trace?.ok ? trace : { ok: false };
      renderResearchDrawer();
      if (trace?.run?.graph_diff) {
        const highlightNodeIds = [...(trace.run.graph_diff.new_node_ids || []), ...(trace.run.graph_diff.updated_node_ids || [])];
        const highlightLinkIds = [...(trace.run.graph_diff.new_edge_ids || []), ...(trace.run.graph_diff.updated_edge_ids || [])];
        if (highlightNodeIds.length || highlightLinkIds.length) {
          setRunHighlights({ node_ids: highlightNodeIds, link_ids: highlightLinkIds, ttl_ms: 30000, reason: "latest_research_run" });
        }
      }
      await refreshWorkbenchLayers({ preserveSelection: true });
      const focusNodeId = String(trace?.run?.graph_diff?.new_node_ids?.[0] || trace?.run?.graph_diff?.updated_node_ids?.[0] || "").trim();
      if (focusNodeId && state.nodeById.has(focusNodeId)) {
        selectNode(focusNodeId, { focus: true });
        setStatus(`Updated graph and focused ${focusNodeId}.`, "good");
      }
    } catch (error) {
      setStatus(`Research failed: ${error.message}`, "error");
    }
  }

  function setWorkbenchMode(mode) {
    state.workbenchMode = mode === "research" ? "research" : "graph";
    document.querySelectorAll("[data-workbench-mode]").forEach((button) => {
      button.classList.toggle("active", button.getAttribute("data-workbench-mode") === state.workbenchMode);
    });
    el.graphModePanel?.classList.toggle("hidden", state.workbenchMode !== "graph");
    el.researchModePanel?.classList.toggle("hidden", state.workbenchMode !== "research");
    if (el.commandRun) el.commandRun.textContent = "Run research";
    setStatus(state.workbenchMode === "research" ? "Research Mode: internet workflow enabled." : "Graph Mode: local graph search only.", "good");
  }

  function setSceneMode(mode) {
    const nextMode = mode === "3d" ? "3d" : "2d";
    state.requestedSceneMode = nextMode;
    state.sceneMode = nextMode;
    try {
      window.localStorage.setItem("thiezer.sceneMode", nextMode);
    } catch {}
    syncSceneButtons();
    updateSceneCopy();
    initGraph();
  }

  function wireSearch() {
    let timer = 0;
    el.search.addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        const value = el.search.value.trim();
        refreshView();
        if (!value) {
          rebuildSearchResults([]);
          return;
        }
        try {
          const payload = await api(`/api/node/search?q=${encodeURIComponent(value)}&limit=10`);
          const effectiveResults = (payload.results && payload.results.length) ? payload.results : localSearchResults(value, 10);
          rebuildSearchResults(effectiveResults);
          const first = effectiveResults.find((item) => state.nodeById.has(item.id || item.node_id || ""));
          const firstId = String(first?.id || first?.node_id || "").trim();
          if (firstId && state.nodeById.has(firstId)) {
            selectNode(firstId, { focus: true, refresh: false });
          }
          if (effectiveResults.length && !(payload.results && payload.results.length)) {
            setStatus("Search completed from the loaded graph.", "good");
          } else {
            setStatus(payload.reranker_used ? "Search completed with rerank." : "Search completed.", "good");
          }
        } catch (error) {
          const fallbackResults = localSearchResults(value, 10);
          if (fallbackResults.length) {
            rebuildSearchResults(fallbackResults);
            const firstId = String(fallbackResults[0]?.id || "").trim();
            if (firstId && state.nodeById.has(firstId)) {
              selectNode(firstId, { focus: true, refresh: false });
            }
            setStatus("Search completed from the loaded graph.", "good");
            return;
          }
          el.searchResults.innerHTML = `<div class="empty">Search failed: ${escapeHtml(error.message)}</div>`;
        }
      }, 180);
    });
    el.search.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      const first = el.searchResults.querySelector("[data-node-link]");
      const id = first?.getAttribute("data-node-link");
      if (!id || !state.nodeById.has(id)) return;
      event.preventDefault();
      selectNode(id, { focus: true });
    });
  }

  function wireControls() {
    el.typeFilter.addEventListener("change", refreshView);
    el.linkFilter.addEventListener("change", refreshView);
    el.layoutMode?.addEventListener("change", () => {
      state.layoutMode = el.layoutMode.value || "political-map";
      initGraph();
    });
    el.resetCamera.addEventListener("click", () => {
      clearSelection({ refresh: true });
      centerGraphView(700);
      setStatus(state.graphMode === "3d-lite"
        ? `3D view refit: ${state.visibleNodes.length} nodes. Left drag rotates, Shift/right drag pans.`
        : `Loaded ${state.visibleNodes.length} nodes.`, "good");
    });

    el.commandRun.addEventListener("click", runCommandFromInput);
    el.commandInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        runCommandFromInput();
      }
    });
    el.commandModelMode?.addEventListener("change", () => syncCommandModelInfo());
    document.querySelectorAll("[data-workbench-mode]").forEach((button) => {
      button.addEventListener("click", () => setWorkbenchMode(button.getAttribute("data-workbench-mode") || "graph"));
    });
    document.querySelectorAll("[data-research-tab]").forEach((button) => {
      button.addEventListener("click", () => {
        state.researchDrawerTab = button.getAttribute("data-research-tab") || "summary";
        renderResearchDrawer();
      });
    });

    document.querySelectorAll("[data-view-mode]").forEach((button) => {
      button.addEventListener("click", () => setSceneMode(button.getAttribute("data-view-mode") || "2d"));
    });
    el.legend.addEventListener("click", (event) => {
      const target = event.target.closest("[data-family-filter]");
      if (!target) return;
      const value = target.getAttribute("data-family-filter") || "all";
      state.familyFilter = value;
      buildLegend();
      refreshView();
    });
    el.inspectorEntityTab?.addEventListener("click", () => {
      state.inspectorMode = "entity";
      syncInspectorTabs();
      renderInspectorFromState();
    });
    el.inspectorRelationTab?.addEventListener("click", () => {
      state.inspectorMode = "relation";
      syncInspectorTabs();
      renderInspectorFromState();
    });
    document.addEventListener("click", (event) => {
      const target = event.target.closest("[data-node-link]");
      if (!target) return;
      const id = target.getAttribute("data-node-link");
      if (!id || !state.nodeById.has(id)) return;
      selectNode(id, { focus: true });
    });
  }

  async function boot() {
    wireSearch();
    wireControls();
    if (el.layoutMode) el.layoutMode.value = state.layoutMode;
    syncSceneButtons();
    updateSceneCopy();
    renderEmptyInspector();
    buildLegend();
    rebuildSearchResults([]);
    setWorkbenchMode("graph");
    await loadCommandModels();
    syncInspectorTabs();
    await refreshWorkbenchLayers({ preserveSelection: false });
    renderEmptyInspector();
    centerGraphView(700);
    window.setInterval(() => {
      void pollWorkbenchDiff();
    }, 12000);
    window.setInterval(() => {
      void pollResearchTrace();
    }, 2000);
  }

  window.addEventListener("resize", () => centerGraphView(400));
  window.addEventListener("beforeunload", destroyGraph);
  window.addEventListener("DOMContentLoaded", () => {
    boot().catch((error) => {
      console.error(error);
      setStatus("Graph load error.", "error");
      if (el.researchPanelSummary) {
        el.researchPanelSummary.innerHTML = `<div class="empty">Viewer load failed: ${escapeHtml(error.message)}</div>`;
      }
    });
  });
})();
