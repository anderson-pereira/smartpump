function errorMessage(payload, status) {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) return payload.detail.map((item) => item.msg).join("; ");
  return `Falha na API (HTTP ${status}).`;
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const payload = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(errorMessage(payload, response.status));
  return { payload, response };
}

function idempotencyKey() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
}

async function confirmedPost(path, body) {
  const confirmation = await request("/api/v1/control/confirmations", {
    method: "POST",
    body: JSON.stringify({ method: "POST", path, body }),
  });
  return request(path, {
    method: "POST",
    headers: {
      "X-Confirmation-Token": confirmation.payload.token,
      "Idempotency-Key": idempotencyKey(),
    },
    body: JSON.stringify(body),
  });
}

export async function getStatus() {
  return (await request("/api/v1/status")).payload;
}

export async function getRecipes() {
  return (await request("/api/v1/recipes")).payload;
}

export async function getSerialPorts() {
  return (await request("/api/v1/serial-ports")).payload.items;
}

export async function saveRecipe(recipe, definition) {
  if (recipe.persisted === false) {
    return (await request("/api/v1/recipes", {
      method: "POST",
      body: JSON.stringify({ id: recipe.id, recipe: definition }),
    })).payload;
  }
  return (await request(`/api/v1/recipes/${encodeURIComponent(recipe.id)}`, {
    method: "PUT",
    headers: { "If-Match": `"${recipe.revision}"` },
    body: JSON.stringify({ recipe: definition }),
  })).payload;
}

export async function deleteRecipe(recipe) {
  await request(`/api/v1/recipes/${encodeURIComponent(recipe.id)}`, {
    method: "DELETE",
    headers: { "If-Match": `"${recipe.revision}"` },
  });
}

export async function runRecipe(options) {
  return (await confirmedPost("/api/v1/runs", options)).payload;
}

export async function stopRun(runId) {
  return (await confirmedPost(`/api/v1/runs/${encodeURIComponent(runId)}/stop`, {
    reason: "Interrupção confirmada na interface Web",
  })).payload;
}

export async function pauseRun(runId) {
  return (await confirmedPost(`/api/v1/runs/${encodeURIComponent(runId)}/pause`, {
    reason: "Pausa solicitada na interface Web",
  })).payload;
}

export async function resumeRun(runId) {
  return (await confirmedPost(`/api/v1/runs/${encodeURIComponent(runId)}/resume`, {
    reason: "Retomada solicitada na interface Web",
  })).payload;
}

export async function manualCommand(action, parameters = {}) {
  return (await confirmedPost("/api/v1/control/commands", { action, parameters })).payload;
}

export async function connectDevice(device, port, baudRate = 9600) {
  return (await confirmedPost(`/api/v1/devices/${device}/connect`, {
    port,
    baud_rate: baudRate,
  })).payload;
}

export async function disconnectDevice(device) {
  return (await confirmedPost(`/api/v1/devices/${device}/disconnect`, {})).payload;
}

function nodeId(path, kind) {
  return `${kind}-${path.join("-")}`;
}

export function apiStepsToStructure(steps, path = []) {
  return steps.map((item, index) => {
    const itemPath = [...path, index + 1];
    if (Array.isArray(item.steps)) {
      return {
        id: nodeId(itemPath, "loop"),
        kind: "loop",
        label: item.name || `Loop ${index + 1}`,
        cycles: item.cycles ?? 1,
        flowRate: Object.hasOwn(item, "flow_rate_ml_min") ? item.flow_rate_ml_min : null,
        children: apiStepsToStructure(item.steps, itemPath),
      };
    }
    return {
      id: nodeId(itemPath, "step"),
      kind: "step",
      label: item.solution,
      channel: item.channel,
      solution: item.solution,
      durationMinutes: item.duration_minutes,
      flowRate: Object.hasOwn(item, "flow_rate_ml_min") ? item.flow_rate_ml_min : null,
    };
  });
}

function structureNodeToApi(node) {
  if (node.kind === "loop") {
    const value = {
      name: node.label,
      cycles: Number(node.cycles),
      steps: node.children.map(structureNodeToApi),
    };
    if (node.flowRate !== null && node.flowRate !== "") value.flow_rate_ml_min = Number(node.flowRate);
    return value;
  }
  const value = {
    channel: Number(node.channel),
    solution: node.solution,
    duration_minutes: Number(node.durationMinutes),
  };
  if (node.flowRate !== null && node.flowRate !== "") value.flow_rate_ml_min = Number(node.flowRate);
  return value;
}

export function structureToApiRecipe(recipe, structure) {
  const value = {
    schema_version: 1,
    name: recipe.name,
    description: recipe.description || "",
    cycles: Number(recipe.cycles || 1),
    steps: structure.map(structureNodeToApi),
  };
  if (recipe.flowRate !== null && recipe.flowRate !== "" && recipe.flowRate !== undefined) {
    value.flow_rate_ml_min = Number(recipe.flowRate);
  }
  return value;
}

export function apiRecipeToView(item) {
  return {
    id: item.id,
    name: item.name,
    description: item.description,
    revision: item.revision,
    revisionLabel: item.revision.slice(0, 8),
    steps: item.executable_steps,
    duration: item.cycles === null
      ? `${item.duration_minutes_per_cycle} min/ciclo`
      : `${item.duration_minutes_per_cycle * item.cycles} min`,
    cycles: item.cycles,
    flowRate: Object.hasOwn(item.recipe, "flow_rate_ml_min") ? item.recipe.flow_rate_ml_min : null,
    persisted: true,
    updatedAt: "Arquivo local",
  };
}
