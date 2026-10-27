import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  ArrowsClockwise,
  BookOpen,
  CaretDown,
  CaretRight,
  CaretUp,
  Check,
  CheckCircle,
  CirclesFour,
  Copy,
  Drop,
  FileText,
  Flask,
  FloppyDisk,
  Gauge,
  GearSix,
  Info,
  ListBullets,
  LockKey,
  Minus,
  Pause,
  PencilSimple,
  Play,
  Plug,
  Plus,
  Question,
  SlidersHorizontal,
  Stop,
  Trash,
  TreeStructure,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import {
  activeRecipe,
  channels,
  initialRecipes,
  initialRecipeStructures,
  serialPorts as demoSerialPorts,
} from "./demoData.js";
import {
  apiRecipeToView,
  apiStepsToStructure,
  connectDevice,
  deleteRecipe as deleteApiRecipe,
  disconnectDevice,
  getRecipes,
  getSerialPorts,
  getStatus,
  manualCommand,
  pauseRun,
  resumeRun,
  runRecipe,
  saveRecipe as saveApiRecipe,
  stopRun,
  structureToApiRecipe,
} from "./api.js";

const NAV_ITEMS = [
  { id: "operate", label: "Operar", caption: "Painel", icon: Play },
  { id: "recipes", label: "Receitas", caption: "Biblioteca", icon: FileText },
  { id: "devices", label: "Dispositivos", caption: "Conexões", icon: GearSix },
];

function revisionLabel(recipe) {
  return recipe?.revisionLabel ?? recipe?.revision ?? "—";
}

function createNodeId(kind) {
  const suffix = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${kind}-${suffix}`;
}

function createRecipeNode(kind) {
  if (kind === "loop") {
    return {
      id: createNodeId("loop"),
      kind: "loop",
      label: "Novo loop",
      cycles: 2,
      flowRate: null,
      children: [],
    };
  }
  return {
    id: createNodeId("step"),
    kind: "step",
    label: "Nova etapa",
    channel: 1,
    solution: channels[0].label,
    durationMinutes: 1,
    flowRate: null,
  };
}

function mapRecipeNodes(nodes, targetId, transform) {
  return nodes.map((node) => {
    if (node.id === targetId) return transform(node);
    if (node.kind !== "loop") return node;
    return { ...node, children: mapRecipeNodes(node.children, targetId, transform) };
  });
}

function appendRecipeNode(nodes, parentId, newNode) {
  if (parentId === null) return [...nodes, newNode];
  return mapRecipeNodes(nodes, parentId, (node) => ({
    ...node,
    children: [...node.children, newNode],
  }));
}

function removeRecipeNode(nodes, targetId) {
  return nodes
    .filter((node) => node.id !== targetId)
    .map((node) => node.kind === "loop"
      ? { ...node, children: removeRecipeNode(node.children, targetId) }
      : node);
}

function recipeStructureStats(nodes) {
  return nodes.reduce((total, node) => {
    if (node.kind === "step") {
      return {
        steps: total.steps + 1,
        durationMinutes: total.durationMinutes + Number(node.durationMinutes || 0),
      };
    }
    const childStats = recipeStructureStats(node.children);
    const cycles = Number(node.cycles || 1);
    return {
      steps: total.steps + childStats.steps * cycles,
      durationMinutes: total.durationMinutes + childStats.durationMinutes * cycles,
    };
  }, { steps: 0, durationMinutes: 0 });
}

function formatDuration(minutes) {
  if (minutes < 1) return `${Math.round(minutes * 60)} s`;
  if (Number.isInteger(minutes)) return `${minutes} min`;
  return `${minutes.toFixed(2).replace(".", ",")} min`;
}

function flattenRecipeStructure(nodes, inheritedFlowRate = null, loopPath = []) {
  const flattened = [];
  nodes.forEach((node) => {
    const effectiveFlowRate = node.flowRate === null || node.flowRate === ""
      ? inheritedFlowRate
      : Number(node.flowRate);
    if (node.kind === "step") {
      flattened.push({ ...node, effectiveFlowRate, loopPath });
      return;
    }
    const cycles = Number(node.cycles || 1);
    for (let iteration = 1; iteration <= cycles; iteration += 1) {
      flattened.push(...flattenRecipeStructure(
        node.children,
        effectiveFlowRate,
        [...loopPath, `${node.label} ${iteration}/${cycles}`],
      ));
    }
  });
  return flattened;
}

function recipeNodeContains(node, targetId) {
  if (node.id === targetId) return true;
  return node.kind === "loop" && node.children.some((child) => recipeNodeContains(child, targetId));
}

function findRecipeNode(nodes, targetId) {
  for (const node of nodes) {
    if (node.id === targetId) return node;
    if (node.kind === "loop") {
      const match = findRecipeNode(node.children, targetId);
      if (match) return match;
    }
  }
  return null;
}

function structureToRunMap(nodes, activeNodeId, activeLoopPath = []) {
  return nodes.map((node, index) => {
    if (node.kind === "step") {
      return {
        id: node.id,
        position: index + 1,
        kind: "step",
        label: node.label,
        meta: "1 etapa",
        active: node.id === activeNodeId,
        channel: node.channel,
        solution: node.solution,
        durationMinutes: Number(node.durationMinutes),
        flowRate: node.flowRate,
      };
    }
    const stats = recipeStructureStats(node.children);
    const repeats = Number(node.cycles || 1);
    const activeChildIndex = node.children.findIndex((child) => recipeNodeContains(child, activeNodeId));
    const loopPathEntry = activeLoopPath.find((entry) => entry.startsWith(`${node.label} `));
    const iterationMatch = loopPathEntry?.match(/(\d+)\/(\d+)$/);
    return {
      id: node.id,
      position: index + 1,
      kind: "loop",
      label: node.label,
      meta: `${stats.steps * repeats} etapas executáveis`,
      repeats,
      iteration: iterationMatch ? Number(iterationMatch[1]) : 1,
      active: recipeNodeContains(node, activeNodeId),
      durationMinutes: stats.durationMinutes * repeats,
      flowRate: node.flowRate,
      children: node.children.map((child, index) => ({
        id: child.id,
        kind: child.kind,
        label: child.label,
        duration: child.kind === "step" ? formatDuration(Number(child.durationMinutes)) : `${child.cycles} ciclos`,
        state: recipeNodeContains(child, activeNodeId)
          ? "active"
          : activeChildIndex >= 0 && index < activeChildIndex
            ? "done"
            : "pending",
      })),
    };
  });
}

function timelineEntries(items, activeIndex, maximumVisible) {
  if (items.length <= maximumVisible) {
    return items.map((item, index) => ({ type: "item", item, index }));
  }

  const middleSlots = Math.max(1, maximumVisible - 2);
  const maximumStart = Math.max(1, items.length - 1 - middleSlots);
  const start = Math.min(
    maximumStart,
    Math.max(1, activeIndex - Math.floor(middleSlots / 2)),
  );
  const end = Math.min(items.length - 1, start + middleSlots);
  const visibleIndexes = [0, ...Array.from({ length: end - start }, (_, offset) => start + offset), items.length - 1];
  const entries = [];

  visibleIndexes.forEach((index, position) => {
    const previous = visibleIndexes[position - 1];
    if (previous !== undefined && index - previous > 1) {
      entries.push({ type: "gap", hidden: index - previous - 1, key: `gap-${previous}-${index}` });
    }
    entries.push({ type: "item", item: items[index], index });
  });
  return entries;
}

function buildRunPresentation(recipe) {
  if (recipe.presentation) return recipe.presentation;
  const structure = recipe.structure ?? [];
  const flattened = flattenRecipeStructure(structure);
  const first = flattened[0];
  const firstRoot = structure[0];
  const duration = first ? Number(first.durationMinutes) : 0;
  return {
    map: structureToRunMap(structure, firstRoot?.id),
    current: first ? {
      title: first.label,
      description: first.solution,
      solution: first.solution,
      channel: Number(first.channel),
      flowRate: first.effectiveFlowRate ?? 0,
      direction: (first.effectiveFlowRate ?? 0) < 0 ? "Anti-horário" : "Horário",
      elapsed: "00:00",
      duration: duration < 1 ? `0:${String(Math.round(duration * 60)).padStart(2, "0")}` : `${Math.floor(duration)}:00`,
      progress: 0,
      cycleLabel: `1 de ${recipe.cycles ?? 1}`,
      breadcrumb: [`Ciclo principal 1/${recipe.cycles ?? 1}`, ...first.loopPath, "Etapa 1"],
    } : null,
    upcoming: flattened.slice(1, 4).map((step, index) => ({
      label: step.label,
      path: [...step.loopPath, `Etapa ${index + 2}`].join(" · "),
      duration: formatDuration(Number(step.durationMinutes)),
      solution: step.solution,
    })),
  };
}

function buildLivePresentation(recipe, structure, run) {
  const flattened = flattenRecipeStructure(structure);
  const stepIndex = Math.max(0, Number(run?.progress?.step ?? 1) - 1);
  const currentStep = flattened[stepIndex] ?? flattened[0];
  if (!currentStep) return buildRunPresentation({ ...recipe, structure });
  const completed = run?.state === "completed";
  const durationSeconds = Number(currentStep.durationMinutes) * 60;
  const remaining = Number(run?.progress?.remaining_step_seconds ?? durationSeconds);
  const progress = durationSeconds > 0
    ? Math.max(0, Math.min(100, Math.round((1 - remaining / durationSeconds) * 100)))
    : 0;
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = Math.round(durationSeconds % 60);
  return {
    map: structureToRunMap(
      structure,
      completed ? null : currentStep.id,
      currentStep.loopPath,
    ).map((item) => ({
      ...item,
      completed,
    })),
    current: {
      title: currentStep.label,
      description: currentStep.solution,
      solution: currentStep.solution,
      channel: Number(currentStep.channel),
      flowRate: Number(currentStep.effectiveFlowRate ?? 0),
      direction: Number(currentStep.effectiveFlowRate ?? 0) < 0 ? "Anti-horário" : "Horário",
      elapsed: completed ? `${minutes}:${String(seconds).padStart(2, "0")}` : "em andamento",
      duration: `${minutes}:${String(seconds).padStart(2, "0")}`,
      progress: completed ? 100 : progress,
      cycleLabel: `${run?.progress?.cycle ?? 1} de ${run?.requested_cycles ?? recipe.cycles ?? 1}`,
      breadcrumb: [
        `Ciclo principal ${run?.progress?.cycle ?? 1}/${run?.requested_cycles ?? recipe.cycles ?? 1}`,
        ...currentStep.loopPath,
        `Etapa ${stepIndex + 1}/${flattened.length}`,
      ],
    },
    upcoming: (completed ? [] : flattened.slice(stepIndex + 1, stepIndex + 4)).map((step, index) => ({
      label: step.label,
      path: [...step.loopPath, `Etapa ${stepIndex + index + 2}`].join(" · "),
      duration: formatDuration(Number(step.durationMinutes)),
      solution: step.solution,
    })),
  };
}

function IconButton({ label, children, className = "", ...props }) {
  return (
    <button className={`icon-button ${className}`} aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}

function AppHeader({ view, onNavigate, onOpenHelp }) {
  return (
    <header className="app-header">
      <button className="brand" onClick={() => onNavigate("operate")} aria-label="Ir para o painel operacional">
        <span className="brand-mark"><Drop weight="fill" /></span>
        <span>Smart<span>Pump</span></span>
      </button>

      <nav className="primary-nav" aria-label="Navegação principal">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? "is-active" : ""}`}
              onClick={() => onNavigate(item.id)}
              aria-current={view === item.id ? "page" : undefined}
            >
              <Icon weight={view === item.id ? "fill" : "regular"} />
              <span className="nav-copy"><strong>{item.label}</strong><small>{item.caption}</small></span>
            </button>
          );
        })}
      </nav>

      <div className="header-actions">
        <button className="help-link" onClick={onOpenHelp}><Question /> Ajuda</button>
        <span className="header-divider" />
        <button className="operator-menu"><span className="avatar">OP</span><span>Operador</span><CaretDown /></button>
      </div>
    </header>
  );
}

function StatusStrip({
  runActive,
  runState,
  pumpRunning,
  flowRate,
  channel,
  runningRecipe,
  deviceStatus = { valve: {}, pump: {} },
}) {
  const channelLabel = channels.find((item) => item.id === channel)?.label ?? "—";
  const valveConnected = Boolean(deviceStatus.valve?.connected);
  const pumpConnected = Boolean(deviceStatus.pump?.connected);
  const recipeState = runState === "paused"
    ? "pausada"
    : runActive
      ? "em execução"
      : runState === "completed"
        ? "concluída"
        : runState === "stopped"
          ? "interrompida"
          : "pronta";
  return (
    <section className="status-strip" aria-label="Resumo da bancada">
      <div className="status-item">
        <span className="status-icon"><CirclesFour /></span>
        <div><strong>{valveConnected ? `Válvula · Canal ${channel}` : "Válvula · desconectada"}</strong><span>{valveConnected ? channelLabel : "Conecte em Dispositivos"}</span></div>
      </div>
      <div className="status-item">
        <span className="status-icon"><Gauge /></span>
        <div><strong>Bomba · {!pumpConnected ? "desconectada" : pumpRunning ? `${flowRate >= 0 ? "+" : ""}${flowRate.toFixed(2)} mL/min` : "parada"}</strong><span>{!pumpConnected ? "Conecte em Dispositivos" : pumpRunning ? "Operação confirmada" : "Pronta para iniciar"}</span></div>
      </div>
      <div className="status-item recipe-status">
        <span className="status-icon is-violet"><FileText /></span>
        <div><strong>Receita · {recipeState}</strong><span>{runningRecipe?.name ?? "Nenhuma receita carregada"} · revisão {revisionLabel(runningRecipe)}</span></div>
      </div>
    </section>
  );
}

function RecipeMap({ recipeMap, currentStep, runState, onOpenLoop, onOpenStructure }) {
  const trackRef = useRef(null);
  const locatedActiveIndex = recipeMap.findIndex((item) => item.active);
  const activeIndex = locatedActiveIndex >= 0
    ? locatedActiveIndex
    : recipeMap.length > 0 && recipeMap.every((item) => item.completed)
      ? recipeMap.length
      : 0;
  const activeItem = recipeMap[Math.min(activeIndex, recipeMap.length - 1)] ?? recipeMap[0];
  const [selectedId, setSelectedId] = useState(activeItem?.id ?? null);
  const [maximumVisible, setMaximumVisible] = useState(11);
  const selectedItem = recipeMap.find((item) => item.id === selectedId) ?? activeItem;
  const activeLoop = recipeMap.find((item) => item.kind === "loop" && item.active);

  useEffect(() => {
    if (activeItem?.id) setSelectedId(activeItem.id);
  }, [activeItem?.id]);

  useEffect(() => {
    const target = trackRef.current;
    if (!target || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      setMaximumVisible(width < 480 ? 5 : width < 720 ? 7 : width < 980 ? 9 : 11);
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  const entries = timelineEntries(recipeMap, activeIndex, maximumVisible);
  const selectedIndex = Math.max(0, recipeMap.findIndex((item) => item.id === selectedItem?.id));
  const selectItem = (item) => {
    if (item.kind === "loop") {
      onOpenLoop(item.id);
      return;
    }
    setSelectedId(item.id);
  };

  const selectedDescription = selectedItem?.kind === "loop"
    ? `${selectedItem.meta} · ${selectedItem.repeats} ${selectedItem.repeats === 1 ? "ciclo" : "ciclos"} · ${formatDuration(selectedItem.durationMinutes ?? 0)}`
    : `Canal ${selectedItem?.channel ?? "—"} · ${formatDuration(selectedItem?.durationMinutes ?? 0)}${selectedItem?.flowRate === null || selectedItem?.flowRate === undefined ? " · vazão herdada" : ` · ${Number(selectedItem.flowRate).toFixed(2).replace(".", ",")} mL/min`}`;

  return (
    <section className="recipe-map" aria-labelledby="recipe-map-title">
      <div className="section-heading compact">
        <div className="map-heading-copy">
          <h2 id="recipe-map-title">Mapa da receita</h2>
          <span>{selectedItem?.kind === "loop" ? "Grupo" : "Etapa"} {selectedIndex + 1} de {recipeMap.length}</span>
        </div>
        <button className="text-link" onClick={onOpenStructure}>Ver estrutura completa <ArrowRight /></button>
      </div>

      <div className="timeline-track" role="list" ref={trackRef} aria-label={`Receita com ${recipeMap.length} itens principais`}>
        {entries.map((entry) => entry.type === "gap" ? (
          <span className="timeline-gap" key={entry.key} role="listitem" aria-label={`${entry.hidden} itens ocultos`}>
            <strong>…</strong><small>+{entry.hidden}</small>
          </span>
        ) : (
          <div className="timeline-segment" key={entry.item.id} role="listitem">
            <button
              className={`timeline-node ${entry.item.kind === "loop" ? "is-loop" : ""} ${entry.item.active ? "is-active" : ""} ${selectedItem?.id === entry.item.id ? "is-selected" : ""} ${entry.item.completed || entry.index < activeIndex ? "is-done" : ""}`}
              onClick={() => selectItem(entry.item)}
              aria-label={`${entry.item.kind === "loop" ? "Abrir detalhes do loop" : "Etapa"} ${entry.index + 1} de ${recipeMap.length}: ${entry.item.label}`}
              aria-current={entry.item.active ? "step" : undefined}
              aria-haspopup={entry.item.kind === "loop" ? "dialog" : undefined}
            >
              <span className="timeline-marker">
                {entry.item.completed || entry.index < activeIndex ? <Check weight="bold" /> : entry.index + 1}
                {entry.item.kind === "loop" && <small>×{entry.item.repeats}</small>}
              </span>
              <span className="timeline-tooltip" role="tooltip">
                <strong>{entry.item.label}</strong>
                <small>{entry.item.kind === "loop" ? entry.item.meta : `Canal ${entry.item.channel ?? "—"} · ${formatDuration(entry.item.durationMinutes ?? 0)}`}</small>
              </span>
            </button>
          </div>
        ))}
      </div>

      {selectedItem && selectedItem.kind !== "loop" && (
        <div className="timeline-selection" aria-live="polite">
          <span className="timeline-selection-icon"><Flask /></span>
          <div><strong>{selectedItem.label}</strong><span>{selectedDescription}</span></div>
          <em>{selectedItem.active ? "Atual" : selectedItem.completed || selectedIndex < activeIndex ? "Concluída" : "Programada"}</em>
        </div>
      )}

      {activeLoop && (
        <div className="active-loop-card" aria-live="polite">
          <div className="active-loop-heading">
            <span className="timeline-selection-icon"><ArrowsClockwise /></span>
            <div>
              <span className="eyebrow">Loop {runState === "paused" ? "pausado" : "em execução"}</span>
              <strong>{activeLoop.label}</strong>
              <small>Ciclo {activeLoop.iteration ?? 1} de {activeLoop.repeats} · {activeLoop.children.length} itens internos</small>
            </div>
            <button className="small-outline violet" onClick={() => onOpenLoop(activeLoop.id)}>Ver detalhes</button>
          </div>
          {(() => {
            const internalIndex = Math.max(0, activeLoop.children.findIndex((step) => step.state === "active"));
            const internalStep = activeLoop.children[internalIndex] ?? activeLoop.children[0];
            return internalStep ? (
              <div className="active-loop-current">
                <span className="step-number">{internalIndex + 1}</span>
                <div><small>Etapa interna {internalIndex + 1} de {activeLoop.children.length}</small><strong>{currentStep?.title ?? internalStep.label}</strong></div>
                <em>{currentStep?.duration ?? internalStep.duration}</em>
              </div>
            ) : null;
          })()}
          <div
            className={`loop-steps ${activeLoop.children.length > 6 ? "is-scrollable" : ""}`}
            style={{ "--loop-step-count": activeLoop.children.length }}
          >
            {activeLoop.children.map((step, index) => (
              <div className={`loop-step is-${step.state}`} key={`${step.label}-${index}`}>
                <span className="step-number">{step.state === "done" ? <Check weight="bold" /> : index + 1}</span>
                <strong>{step.label}</strong>
                <small>{step.duration}</small>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function CurrentStep({ current, runActive }) {
  if (!current) {
    return <section className="current-step is-stopped"><h2>Receita sem etapas executáveis</h2><p>Adicione ao menos uma etapa antes de iniciar.</p></section>;
  }
  return (
    <section className={`current-step ${runActive ? "" : "is-stopped"}`}>
      <div className="current-step-head">
        <div>
          <div className="breadcrumbs" aria-label="Posição atual na receita">
            {current.breadcrumb.map((item, index) => (
              <span key={item}>{item}{index < current.breadcrumb.length - 1 && <CaretRight />}</span>
            ))}
          </div>
          <h2>{current.title}</h2>
          <p>{current.description}</p>
        </div>
      </div>

      <div className="step-metrics">
        <div className="metric"><Drop /><span>Solução<strong>{current.solution}</strong></span></div>
        <div className="metric"><CirclesFour /><span>Canal<strong>Canal {current.channel}</strong></span></div>
        <div className="metric"><Gauge /><span>Vazão<strong>+{current.flowRate.toFixed(2)} mL/min</strong></span></div>
        <div className="metric"><ArrowsClockwise /><span>Sentido<strong>{current.direction}</strong></span></div>
      </div>

      <div className="progress-row">
        <div className="time-stat"><span>Tempo decorrido na etapa</span><strong>{current.elapsed} <small>/ {current.duration}</small></strong></div>
        <div className="progress-stat">
          <span>Progresso da etapa</span><strong>{current.progress}%</strong>
          <div className="progress-track"><span style={{ width: `${current.progress}%` }} /></div>
        </div>
        <div className="cycle-stat"><span>Ciclo principal</span><strong>{current.cycleLabel ?? "1 de 2"}</strong><small>{current.breadcrumb.slice(1).join(" · ") || "Etapa inicial"}</small></div>
      </div>
    </section>
  );
}

function RecipeExecutionControls({ runState, runActive, canStart, onStart, onPause, onResume, onStop }) {
  const paused = runState === "paused";
  const changing = runState === "starting" || runState === "stopping";
  return (
    <div className="recipe-run-controls" aria-label="Controles da receita">
      {!runActive && (
        <button className="launch-action" onClick={onStart} disabled={!canStart}>
          <Play weight="fill" /> Iniciar receita
        </button>
      )}
      {runActive && !paused && (
        <button className="secondary-action" onClick={onPause} disabled={changing}>
          <Pause weight="fill" /> Pausar
        </button>
      )}
      {runActive && paused && (
        <button className="launch-action" onClick={onResume}>
          <Play weight="fill" /> Retomar
        </button>
      )}
      {runActive && (
        <button className="outline-danger" onClick={onStop} disabled={runState === "stopping"}>
          <Stop weight="fill" /> Parar receita
        </button>
      )}
    </div>
  );
}

function ManualControls({ runActive, channel, setChannel, flowRate, setFlowRate, direction, setDirection, pumpRunning, setPumpRunning, notify, onManualCommand }) {
  const blocked = runActive;
  const adjustFlow = (amount) => setFlowRate((current) => Math.round((current + amount) * 100) / 100);
  const execute = async (action, parameters, success) => {
    try {
      await onManualCommand(action, parameters);
      notify(success);
    } catch (error) {
      notify(error.message);
    }
  };
  return (
    <aside className="manual-panel" aria-labelledby="manual-title">
      <div className="manual-title"><SlidersHorizontal /><h2 id="manual-title">Comandos da bancada</h2></div>
      {blocked && (
        <div className="blocked-notice"><LockKey /><div><strong>Comandos manuais bloqueados</strong><p>Existe uma receita em execução. Para evitar conflitos, os comandos da bancada estão desabilitados.</p><button onClick={() => notify("A execução mantém posse exclusiva dos dispositivos até ser interrompida.")}>Ver por que <ArrowRight /></button></div></div>
      )}

      <fieldset disabled={blocked}>
        <legend className="sr-only">Controles manuais da bancada</legend>
        <div className="manual-control-group">
          <span className="manual-group-label">Selecionar válvula (canal)</span>
          <div className="channel-grid">
            {channels.map((item) => (
              <button key={item.id} className={channel === item.id ? "is-selected" : ""} onClick={() => execute("valve.select_channel", { channel: item.id }, `Canal ${item.id} selecionado.`)}>
                <strong>{item.id}</strong><span>{item.label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="manual-control-group">
          <label className="manual-group-label">Vazão da bomba (mL/min)</label>
          <div className="flow-input">
            <IconButton label="Diminuir vazão" onClick={() => adjustFlow(-0.1)}><Minus /></IconButton>
            <output>{flowRate >= 0 ? "+" : ""}{flowRate.toFixed(2)}</output>
            <IconButton label="Aumentar vazão" onClick={() => adjustFlow(0.1)}><Plus /></IconButton>
          </div>
        </div>

        <div className="manual-control-group">
          <span className="manual-group-label">Sentido de rotação</span>
          <div className="direction-toggle">
            <button className={direction === "clockwise" ? "is-selected" : ""} onClick={() => setDirection("clockwise")}><ArrowsClockwise /> Horário</button>
            <button className={direction === "counterclockwise" ? "is-selected" : ""} onClick={() => setDirection("counterclockwise")}><ArrowsClockwise className="flip-horizontal" /> Anti-horário</button>
          </div>
        </div>

        <div className="manual-actions">
          <button className="primary-action" onClick={() => execute("pump.set_flow_rate", { flow_rate_ml_min: direction === "counterclockwise" ? -Math.abs(flowRate) : Math.abs(flowRate) }, "Bomba iniciada com a vazão configurada.")} disabled={pumpRunning}><Play weight="fill" /> Iniciar bomba</button>
          <button className="danger-action" onClick={() => execute("pump.stop", {}, "Bomba parada.")} disabled={!pumpRunning}><Stop weight="fill" /> Parar bomba</button>
          <button className="secondary-action" onClick={() => execute("valve.home", {}, "Válvula referenciada no canal 1.")}><CirclesFour /> Referenciar válvula</button>
        </div>
      </fieldset>
    </aside>
  );
}

function OperateView(props) {
  const presentation = buildRunPresentation(props.runningRecipe);
  const [consultedLoopId, setConsultedLoopId] = useState(null);
  const consultedLoop = consultedLoopId
    ? findRecipeNode(props.runningRecipe.structure ?? [], consultedLoopId)
    : null;
  return (
    <>
      <StatusStrip {...props} />
      <main className="dashboard-shell">
        <section className="execution-card">
          <header className="execution-header">
            <div className="recipe-title"><span className="title-icon"><Flask /></span><div><h1>{props.runningRecipe.name}</h1><p>Execução atual · revisão {revisionLabel(props.runningRecipe)}</p></div></div>
            <div className="execution-side">
              <div className="run-meta">
                <span className={`run-badge ${props.runState === "paused" ? "is-paused" : props.runActive ? "" : "is-stopped"}`}>
                  {props.runState === "paused" ? <Pause weight="fill" /> : props.runActive ? <Play weight="fill" /> : <Stop weight="fill" />}
                  {props.runState === "paused" ? "Pausada" : props.runActive ? "Em execução" : props.runState === "completed" ? "Concluída" : "Pronta para iniciar"}
                </span>
                <span>Início&nbsp; {props.runningRecipe.startedAt ?? "—"}</span>
                <span>Duração total {props.runningRecipe.duration}</span>
              </div>
              <RecipeExecutionControls
                runState={props.runState}
                runActive={props.runActive}
                canStart={props.runningRecipe.persisted !== false && presentation.map.length > 0}
                onStart={props.onStartRun}
                onPause={props.onPauseRun}
                onResume={props.onResumeRun}
                onStop={props.onStopRun}
              />
            </div>
          </header>
          <CurrentStep current={presentation.current} runActive={props.runActive} />
          <RecipeMap
            recipeMap={presentation.map}
            currentStep={presentation.current}
            runState={props.runState}
            onOpenLoop={setConsultedLoopId}
            onOpenStructure={props.onOpenStructure}
          />
        </section>
        <ManualControls {...props} />
      </main>
      {consultedLoop?.kind === "loop" && (
        <LoopDetailsModal loop={consultedLoop} onClose={() => setConsultedLoopId(null)} />
      )}
    </>
  );
}

function RecipesView({
  recipes,
  setRecipes,
  structures,
  setStructures,
  notify,
  runActive,
  runningRecipe,
  onNavigate,
  onLoadRecipe,
  onSaveRecipe,
  onDeleteRecipe,
}) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(recipes[0]?.id);
  const [creating, setCreating] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [nodeEditor, setNodeEditor] = useState(null);
  const selected = recipes.find((recipe) => recipe.id === selectedId) ?? recipes[0];
  const visible = recipes.filter((recipe) => recipe.name.toLowerCase().includes(query.toLowerCase()));
  const selectedStructure = selected ? structures[selected.id] ?? [] : [];
  const selectedStats = recipeStructureStats(selectedStructure);

  const updateSelected = (changes) => {
    setRecipes((items) => items.map((item) => item.id === selected.id ? { ...item, ...changes } : item));
  };

  const applyStructure = (nodes, message) => {
    const stats = recipeStructureStats(nodes);
    setStructures((current) => ({ ...current, [selected.id]: nodes }));
    updateSelected({ steps: stats.steps, duration: formatDuration(stats.durationMinutes), updatedAt: "Agora" });
    notify(message);
  };

  const openNodeEditor = ({ mode, kind, parentId = null, node = null }) => {
    setNodeEditor({
      sessionId: createNodeId("editor"),
      mode,
      kind: node?.kind ?? kind,
      parentId,
      node: node ?? createRecipeNode(kind),
    });
  };

  const saveNode = (node) => {
    const nextNodes = nodeEditor.mode === "add"
      ? appendRecipeNode(selectedStructure, nodeEditor.parentId, node)
      : mapRecipeNodes(selectedStructure, node.id, () => node);
    applyStructure(nextNodes, nodeEditor.mode === "add" ? "Item adicionado à receita." : "Item da receita atualizado.");
    setNodeEditor(null);
  };

  const deleteNode = () => {
    applyStructure(removeRecipeNode(selectedStructure, nodeEditor.node.id), "Item removido da receita.");
    setNodeEditor(null);
  };

  const createRecipe = (event) => {
    event.preventDefault();
    const name = draftName.trim();
    if (!name) return;
    const id = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "receita"}-${Date.now()}`;
    const recipe = { id, name, description: "Nova receita", revision: "rascunho", revisionLabel: "rascunho", persisted: false, cycles: 1, flowRate: 1, steps: 0, duration: "0 s", updatedAt: "Agora" };
    setRecipes((items) => [recipe, ...items]);
    setStructures((current) => ({ ...current, [id]: [] }));
    setSelectedId(id);
    setDraftName("");
    setCreating(false);
    notify("Receita criada como rascunho.");
  };

  const duplicateSelected = () => {
    const copy = { ...selected, id: `${selected.id}-copia-${Date.now()}`, name: `${selected.name} — cópia`, revision: "rascunho", revisionLabel: "rascunho", persisted: false, status: undefined, updatedAt: "Agora" };
    setRecipes((items) => [copy, ...items]);
    setStructures((current) => ({ ...current, [copy.id]: structuredClone(selectedStructure) }));
    setSelectedId(copy.id);
    notify("Receita duplicada.");
  };

  const deleteSelected = async () => {
    if (selected.status === "Em execução") {
      notify("A receita em execução não pode ser excluída.");
      return;
    }
    try {
      if (selected.persisted !== false) await onDeleteRecipe(selected);
    } catch (error) {
      notify(error.message);
      return;
    }
    const remaining = recipes.filter((item) => item.id !== selected.id);
    setRecipes(remaining);
    setStructures((current) => {
      const next = { ...current };
      delete next[selected.id];
      return next;
    });
    setSelectedId(remaining[0]?.id);
    notify("Receita excluída.");
  };

  const saveSelected = async () => {
    if (selectedStats.steps === 0) {
      notify("Adicione ao menos uma etapa antes de salvar.");
      return;
    }
    try {
      const saved = await onSaveRecipe(selected, selectedStructure);
      updateSelected(saved);
      notify("Nova revisão salva no arquivo local.");
    } catch (error) {
      notify(error.message);
    }
  };

  return (
    <main className="page-shell">
      <header className="page-heading">
        <div><span className="eyebrow">Biblioteca</span><h1>Receitas</h1><p>Crie, revise e organize protocolos sem alterar uma execução em andamento.</p></div>
        <button className="primary-action compact-action" onClick={() => setCreating(true)}><Plus /> Nova receita</button>
      </header>

      {creating && (
        <form className="inline-create" onSubmit={createRecipe}>
          <label>Nome da nova receita<input autoFocus value={draftName} onChange={(event) => setDraftName(event.target.value)} placeholder="Ex.: Lavagem final" /></label>
          <button className="primary-action" type="submit"><Check /> Criar rascunho</button>
          <button className="secondary-action" type="button" onClick={() => setCreating(false)}><X /> Cancelar</button>
        </form>
      )}

      <div className="library-layout">
        <aside className="recipe-library">
          <label className="search-field"><ListBullets /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar receitas" /></label>
          <div className="recipe-list">
            {visible.map((recipe) => (
              <button key={recipe.id} className={selected?.id === recipe.id ? "is-selected" : ""} onClick={() => setSelectedId(recipe.id)}>
                <span className="list-icon"><Flask /></span>
                <span><strong>{recipe.name}</strong><small>Rev. {revisionLabel(recipe)} · {recipe.steps} etapas · {recipe.duration}</small></span>
                {recipe.status && <em>{recipe.status}</em>}
                <CaretRight />
              </button>
            ))}
          </div>
        </aside>

        {selected ? (
          <section className="recipe-editor">
            <header className="editor-head">
              <div><span className="eyebrow">Receita selecionada · revisão {revisionLabel(selected)}</span><h2>{selected.name}</h2></div>
              <div className="editor-actions">
                <button className="secondary-action" onClick={duplicateSelected}><Copy /> Duplicar</button>
                <button className="secondary-action destructive-text" onClick={deleteSelected}><Trash /> Excluir</button>
                <button className="primary-action" onClick={saveSelected}><FloppyDisk /> Salvar revisão</button>
                {runActive && runningRecipe?.id === selected.id ? (
                  <button className="launch-action" onClick={() => onNavigate("operate")}><Gauge /> Acompanhar execução</button>
                ) : runActive ? (
                  <button className="launch-action" disabled title="Pare a execução atual antes de carregar outra receita"><LockKey /> Execução em andamento</button>
                ) : (
                  <button
                    className="launch-action"
                    onClick={() => onLoadRecipe(selected, selectedStructure)}
                    disabled={selectedStats.steps === 0 || selected.persisted === false}
                    title={selected.persisted === false ? "Salve a receita antes de carregá-la" : selectedStats.steps === 0 ? "Adicione uma etapa antes de carregar" : undefined}
                  >
                    <Gauge /> Carregar em Operar
                  </button>
                )}
              </div>
            </header>
            <div className="editor-form-grid">
              <label>Nome<input value={selected.name} onChange={(event) => updateSelected({ name: event.target.value })} /></label>
              <label>Ciclos<input type="number" min="1" value={selected.cycles ?? 1} onChange={(event) => updateSelected({ cycles: Number(event.target.value) })} /></label>
              <label className="span-two">Descrição<textarea value={selected.description} onChange={(event) => updateSelected({ description: event.target.value })} /></label>
              <label>Vazão padrão (mL/min)<input type="number" step="0.1" value={selected.flowRate ?? ""} onChange={(event) => updateSelected({ flowRate: event.target.value === "" ? null : Number(event.target.value) })} /></label>
              <label>Modo da bomba<select defaultValue="controlled"><option value="controlled">Controlada</option><option value="external">Externa</option><option value="disabled">Desativada</option></select></label>
            </div>

            <div className="editor-structure">
              <div className="section-heading"><div><span className="eyebrow">Estrutura hierárquica</span><h2>Etapas e loops</h2></div><div><button className="small-outline" onClick={() => openNodeEditor({ mode: "add", kind: "step" })}><Plus /> Etapa</button><button className="small-outline violet" onClick={() => openNodeEditor({ mode: "add", kind: "loop" })}><ArrowsClockwise /> Loop</button></div></div>
              <p className="structure-hint">A vazão em branco é herdada do nível superior. Loops podem conter etapas e outros loops.</p>
              {selectedStructure.length > 0 ? (
                <div className="editor-tree-list">
                  {selectedStructure.map((node, index) => (
                    <EditableRecipeNode
                      key={node.id}
                      node={node}
                      index={index}
                      depth={0}
                      onEdit={(selectedNode) => openNodeEditor({ mode: "edit", node: selectedNode })}
                      onAdd={(kind, parentId) => openNodeEditor({ mode: "add", kind, parentId })}
                    />
                  ))}
                </div>
              ) : (
                <div className="empty-structure">
                  <TreeStructure />
                  <strong>A receita ainda não possui itens</strong>
                  <span>Adicione uma etapa simples ou comece por um loop.</span>
                  <div><button className="small-outline" onClick={() => openNodeEditor({ mode: "add", kind: "step" })}><Plus /> Adicionar etapa</button><button className="small-outline violet" onClick={() => openNodeEditor({ mode: "add", kind: "loop" })}><ArrowsClockwise /> Adicionar loop</button></div>
                </div>
              )}
            </div>
          </section>
        ) : <section className="empty-state"><Flask /><h2>Nenhuma receita</h2><p>Crie a primeira receita para começar.</p></section>}
      </div>
      {nodeEditor && (
        <RecipeNodeDialog
          key={nodeEditor.sessionId}
          editor={nodeEditor}
          onClose={() => setNodeEditor(null)}
          onSave={saveNode}
          onDelete={nodeEditor.mode === "edit" ? deleteNode : null}
        />
      )}
    </main>
  );
}

function EditableRecipeNode({ node, index, depth, onEdit, onAdd }) {
  const isLoop = node.kind === "loop";
  const inheritedFlow = node.flowRate === null || node.flowRate === "";
  const meta = isLoop
    ? `${node.cycles} ${node.cycles === 1 ? "ciclo" : "ciclos"} · ${node.children.length} ${node.children.length === 1 ? "item" : "itens"} · ${inheritedFlow ? "vazão herdada" : `${Number(node.flowRate).toFixed(2).replace(".", ",")} mL/min`}`
    : `Canal ${node.channel} · ${node.solution} · ${formatDuration(Number(node.durationMinutes))} · ${inheritedFlow ? "vazão herdada" : `${Number(node.flowRate).toFixed(2).replace(".", ",")} mL/min`}`;

  return (
    <div className="editor-tree-item" style={{ "--tree-depth": depth }}>
      <div className={`editor-node ${isLoop ? "is-loop" : ""}`}>
        <span className="drag-index">{index + 1}</span>
        {isLoop ? <ArrowsClockwise /> : <Flask />}
        <span className="node-summary"><strong>{node.label}{isLoop ? ` ×${node.cycles}` : ""}</strong><small>{meta}</small></span>
        <div className="node-actions">
          {isLoop && <button className="text-link" onClick={() => onAdd("step", node.id)}><Plus /> Etapa interna</button>}
          {isLoop && <button className="text-link violet-text" onClick={() => onAdd("loop", node.id)}><ArrowsClockwise /> Loop interno</button>}
          <button className="text-link" onClick={() => onEdit(node)}><PencilSimple /> Editar</button>
        </div>
      </div>
      {isLoop && (
        <div className="editor-children">
          {node.children.length > 0 ? node.children.map((child, childIndex) => (
            <EditableRecipeNode
              key={child.id}
              node={child}
              index={childIndex}
              depth={depth + 1}
              onEdit={onEdit}
              onAdd={onAdd}
            />
          )) : <div className="empty-loop"><Info /> Loop vazio — adicione uma etapa ou outro loop.</div>}
        </div>
      )}
    </div>
  );
}

function RecipeNodeDialog({ editor, onClose, onSave, onDelete }) {
  const [draft, setDraft] = useState(() => ({
    ...editor.node,
    flowRate: editor.node.flowRate ?? "",
  }));
  const isLoop = editor.kind === "loop";

  const setField = (field, value) => setDraft((current) => ({ ...current, [field]: value }));
  const submit = (event) => {
    event.preventDefault();
    onSave(isLoop
      ? {
          ...draft,
          cycles: Number(draft.cycles),
          flowRate: draft.flowRate === "" ? null : Number(draft.flowRate),
          children: draft.children ?? [],
        }
      : {
          ...draft,
          channel: Number(draft.channel),
          durationMinutes: Number(draft.durationMinutes),
          flowRate: draft.flowRate === "" ? null : Number(draft.flowRate),
        });
  };

  const title = `${editor.mode === "add" ? "Adicionar" : "Editar"} ${isLoop ? "loop" : "etapa"}`;
  return (
    <Modal
      title={title}
      icon={isLoop ? ArrowsClockwise : Flask}
      onClose={onClose}
      footer={
        <>
          {onDelete && <button className="secondary-action destructive-text modal-delete" type="button" onClick={onDelete}><Trash /> Excluir</button>}
          <button className="secondary-action" type="button" onClick={onClose}>Cancelar</button>
          <button className="primary-action" type="submit" form="recipe-node-form"><Check /> {editor.mode === "add" ? "Adicionar" : "Aplicar alterações"}</button>
        </>
      }
    >
      <form id="recipe-node-form" className="node-editor-form" onSubmit={submit}>
        <label>Nome exibido<input autoFocus required value={draft.label} onChange={(event) => setField("label", event.target.value)} /></label>
        {isLoop ? (
          <>
            <label>Repetições<input required type="number" min="1" step="1" value={draft.cycles} onChange={(event) => setField("cycles", event.target.value)} /></label>
            <label className="span-two">Vazão do loop (mL/min)<input type="number" step="0.01" value={draft.flowRate} onChange={(event) => setField("flowRate", event.target.value)} placeholder="Herdar vazão do nível superior" /><small>Deixe em branco para herdar. Etapas internas ainda podem sobrescrever este valor.</small></label>
          </>
        ) : (
          <>
            <label>Solução<input required value={draft.solution} onChange={(event) => setField("solution", event.target.value)} /></label>
            <label>Canal<select value={draft.channel} onChange={(event) => setField("channel", event.target.value)}>{channels.map((channel) => <option value={channel.id} key={channel.id}>Canal {channel.id} · {channel.label}</option>)}</select></label>
            <label>Duração (minutos)<input required type="number" min="0.01" step="0.01" value={draft.durationMinutes} onChange={(event) => setField("durationMinutes", event.target.value)} /></label>
            <label>Vazão (mL/min)<input type="number" step="0.01" value={draft.flowRate} onChange={(event) => setField("flowRate", event.target.value)} placeholder="Herdar vazão" /><small>Valores positivos giram no sentido horário; negativos, no anti-horário; zero para a bomba.</small></label>
          </>
        )}
      </form>
    </Modal>
  );
}

function StartRecipeDialog({
  recipe,
  structure,
  runActive,
  runningRecipe,
  pumpRunning,
  onClose,
  onGoToRun,
  onStart,
}) {
  const [pumpMode, setPumpMode] = useState("controlled");
  const [startStoppedPump, setStartStoppedPump] = useState(true);
  const [cycles, setCycles] = useState(recipe.cycles ?? 1);
  const stats = recipeStructureStats(structure);

  if (runActive) {
    return (
      <Modal
        title="Já existe uma execução em andamento"
        icon={WarningCircle}
        onClose={onClose}
        footer={<><button className="secondary-action" onClick={onClose}>Voltar</button><button className="primary-action" onClick={onGoToRun}><Gauge /> Acompanhar execução</button></>}
      >
        <p className="modal-intro">Para preservar o controle exclusivo da bomba e da válvula, interrompa a execução atual antes de iniciar outra receita.</p>
        <div className="active-run-conflict">
          <span className="run-badge"><Play weight="fill" /> Em execução</span>
          <div><strong>{runningRecipe.name}</strong><span>Revisão {runningRecipe.revision} · iniciada às {runningRecipe.startedAt ?? "10:14"}</span></div>
        </div>
        <p className="conflict-next">A receita <strong>{recipe.name}</strong> permanece selecionada na biblioteca e não será alterada.</p>
      </Modal>
    );
  }

  return (
    <Modal
      title="Confirmar início da receita"
      icon={Play}
      onClose={onClose}
      wide
      footer={<><button className="secondary-action" onClick={onClose}>Cancelar</button><button className="launch-action" onClick={() => onStart({ pumpMode, startStoppedPump, cycles: Number(cycles) })}><Play weight="fill" /> Confirmar início</button></>}
    >
      <div className="start-recipe-layout">
        <section className="start-summary">
          <span className="eyebrow">Receita selecionada</span>
          <h3>{recipe.name}</h3>
          <p>{recipe.description}</p>
          <dl>
            <div><dt>Revisão</dt><dd>{revisionLabel(recipe)}</dd></div>
            <div><dt>Etapas executáveis</dt><dd>{stats.steps}</dd></div>
            <div><dt>Duração por ciclo</dt><dd>{formatDuration(stats.durationMinutes)}</dd></div>
          </dl>
        </section>

        <form className="start-options" onSubmit={(event) => event.preventDefault()}>
          <label>Número de ciclos<input type="number" min="1" step="1" value={cycles} onChange={(event) => setCycles(event.target.value)} /></label>
          <fieldset>
            <legend>Controle da bomba</legend>
            <label className={`choice-card ${pumpMode === "controlled" ? "is-selected" : ""}`}><input type="radio" name="pump-mode" value="controlled" checked={pumpMode === "controlled"} onChange={(event) => setPumpMode(event.target.value)} /><span><strong>Controlada pela receita</strong><small>Aplica vazão, sentido e parada definidos em cada etapa.</small></span></label>
            <label className={`choice-card ${pumpMode === "external" ? "is-selected" : ""}`}><input type="radio" name="pump-mode" value="external" checked={pumpMode === "external"} onChange={(event) => setPumpMode(event.target.value)} /><span><strong>Bomba externa</strong><small>A aplicação movimenta apenas a válvula e não conhece o estado da bomba.</small></span></label>
            <label className={`choice-card ${pumpMode === "disabled" ? "is-selected" : ""}`}><input type="radio" name="pump-mode" value="disabled" checked={pumpMode === "disabled"} onChange={(event) => setPumpMode(event.target.value)} /><span><strong>Sem bomba</strong><small>Executa os tempos e trocas de canal sem bombeamento controlado.</small></span></label>
          </fieldset>

          {pumpMode === "controlled" && !pumpRunning && (
            <div className="pump-start-question">
              <WarningCircle />
              <div><strong>A bomba está parada</strong><p>Deseja ligá-la quando a receita iniciar?</p></div>
              <label className="switch-choice"><input type="checkbox" checked={startStoppedPump} onChange={(event) => setStartStoppedPump(event.target.checked)} /><span>{startStoppedPump ? "Sim, ligar" : "Não ligar"}</span></label>
            </div>
          )}
        </form>
      </div>
      <div className="start-warning"><Info /> A execução usará uma cópia imutável da revisão {revisionLabel(recipe)}. Edições posteriores não alterarão este ciclo.</div>
    </Modal>
  );
}

function DevicesView({ notify, serialPorts, deviceStatus, onDeviceConnection }) {
  const [valvePort, setValvePort] = useState(serialPorts[0]?.value ?? "");
  const [pumpPort, setPumpPort] = useState(serialPorts[1]?.value ?? serialPorts[0]?.value ?? "");
  const [refreshing, setRefreshing] = useState(false);

  const refresh = () => {
    setRefreshing(true);
    window.setTimeout(() => { setRefreshing(false); notify("Portas seriais atualizadas."); }, 650);
  };

  return (
    <main className="page-shell devices-page">
      <header className="page-heading">
        <div><span className="eyebrow">Configuração</span><h1>Dispositivos</h1><p>Escolha portas seriais e gerencie as conexões sem acessar os drivers diretamente.</p></div>
        <button className="secondary-action compact-action" onClick={refresh} disabled={refreshing}><ArrowClockwise className={refreshing ? "is-spinning" : ""} /> {refreshing ? "Atualizando" : "Atualizar portas"}</button>
      </header>

      <div className="device-grid">
        <DeviceCard
          icon={CirclesFour}
          name="Válvula Cavro"
          description="Seleção automática dos canais 1 a 6"
          port={valvePort}
          setPort={setValvePort}
          connected={Boolean(deviceStatus.valve?.connected)}
          serialPorts={serialPorts}
          toggle={() => onDeviceConnection("valve", valvePort, Boolean(deviceStatus.valve?.connected))}
        />
        <DeviceCard
          icon={Gauge}
          name="Bomba Ismatec"
          description="Vazão, rotação e partida/parada"
          port={pumpPort}
          setPort={setPumpPort}
          connected={Boolean(deviceStatus.pump?.connected)}
          serialPorts={serialPorts}
          toggle={() => onDeviceConnection("pump", pumpPort, Boolean(deviceStatus.pump?.connected))}
        />
      </div>

      <section className="ports-panel">
        <div className="section-heading"><div><span className="eyebrow">Detectadas pelo sistema</span><h2>Portas seriais disponíveis</h2></div><span className="count-badge">{serialPorts.length} portas</span></div>
        {serialPorts.map((port, index) => (
          <div className="port-row" key={port.value}><Plug /><strong>{port.value}</strong><span>{port.label.split(" · ")[1]}</span><em>{index < 2 ? "Em uso" : "Disponível"}</em></div>
        ))}
      </section>
    </main>
  );
}

function DeviceCard({ icon: Icon, name, description, port, setPort, connected, toggle, serialPorts = demoSerialPorts }) {
  return (
    <section className="device-card">
      <header><span className="device-icon"><Icon /></span><div><h2>{name}</h2><p>{description}</p></div><span className={`device-state ${connected ? "is-connected" : ""}`}>{connected ? <CheckCircle weight="fill" /> : <WarningCircle />}{connected ? "Conectada" : "Desconectada"}</span></header>
      <label>Porta serial<select value={port} onChange={(event) => setPort(event.target.value)} disabled={connected}>{serialPorts.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
      <label>Baud rate<select defaultValue="9600" disabled={connected}><option>9600</option><option>19200</option><option>38400</option></select></label>
      <div className="device-observation"><span className={`status-dot ${connected ? "" : "is-muted"}`} /><span><strong>{connected ? "Pronta" : "Sem comunicação"}</strong><small>{connected ? `Observação recente em ${port}` : "Conecte para consultar o dispositivo"}</small></span></div>
      <button className={connected ? "outline-danger" : "primary-action"} onClick={toggle}>{connected ? <><Stop /> Desconectar</> : <><Plug /> Conectar</>}</button>
    </section>
  );
}

function Modal({ title, icon: Icon = Info, children, onClose, footer, wide = false }) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className={`modal ${wide ? "is-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <header><span className="modal-icon"><Icon /></span><h2 id="modal-title">{title}</h2><IconButton label="Fechar" onClick={onClose}><X /></IconButton></header>
        <div className="modal-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </section>
    </div>
  );
}

function StructureTreeNode({ node, index, depth = 0 }) {
  const isLoop = node.kind === "loop";
  const [open, setOpen] = useState(depth < 2);
  const RowElement = isLoop ? "button" : "div";
  const childStats = isLoop ? recipeStructureStats(node.children) : null;
  const description = isLoop
    ? `${node.cycles} ${node.cycles === 1 ? "ciclo" : "ciclos"} · ${childStats.steps * Number(node.cycles || 1)} etapas executáveis`
    : `Canal ${node.channel} · ${formatDuration(Number(node.durationMinutes))}${node.flowRate === null || node.flowRate === "" ? " · vazão herdada" : ` · ${Number(node.flowRate).toFixed(2).replace(".", ",")} mL/min`}`;

  return (
    <div className={`structure-tree-item ${isLoop ? "is-loop" : ""}`} style={{ "--structure-depth": depth }}>
      <RowElement
        className="structure-tree-row"
        onClick={isLoop ? () => setOpen((value) => !value) : undefined}
        aria-expanded={isLoop ? open : undefined}
      >
        <span className="structure-index">{index + 1}</span>
        <span className="structure-kind">{isLoop ? <ArrowsClockwise /> : <Flask />}</span>
        <span className="structure-copy"><strong>{node.label}</strong><small>{description}</small></span>
        {isLoop && (open ? <CaretUp /> : <CaretDown />)}
      </RowElement>
      {isLoop && open && (
        <div className="structure-tree-children">
          {node.children.map((child, childIndex) => (
            <StructureTreeNode key={child.id} node={child} index={childIndex} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function LoopDetailsModal({ loop, onClose }) {
  const childStats = recipeStructureStats(loop.children);
  const cycles = Number(loop.cycles || 1);
  const flowLabel = loop.flowRate === null || loop.flowRate === ""
    ? "Herdada do nível superior"
    : `${Number(loop.flowRate).toFixed(2).replace(".", ",")} mL/min`;
  return (
    <Modal
      title={`Detalhes do loop · ${loop.label}`}
      icon={ArrowsClockwise}
      onClose={onClose}
      wide
      footer={<button className="primary-action" onClick={onClose}>Fechar</button>}
    >
      <p className="modal-intro">Visualização consultiva da sequência. Alterações continuam disponíveis somente na Biblioteca de receitas.</p>
      <div className="loop-modal-summary">
        <div><span>Repetições</span><strong>{cycles}</strong></div>
        <div><span>Etapas executáveis</span><strong>{childStats.steps * cycles}</strong></div>
        <div><span>Duração total</span><strong>{formatDuration(childStats.durationMinutes * cycles)}</strong></div>
        <div><span>Vazão do loop</span><strong>{flowLabel}</strong></div>
      </div>
      <section className="loop-modal-structure" aria-label={`Estrutura do loop ${loop.label}`}>
        <div className="section-heading compact"><div><span className="eyebrow">Sequência interna</span><h2>Etapas e loops aninhados</h2></div><span className="loop-modal-count">{loop.children.length} itens diretos</span></div>
        <div className="structure-tree-list">
          {loop.children.map((node, index) => (
            <StructureTreeNode key={node.id} node={node} index={index} />
          ))}
        </div>
      </section>
    </Modal>
  );
}

function StructureModal({ onClose, recipe }) {
  const structure = recipe.structure ?? [];
  const stats = recipeStructureStats(structure);
  return (
    <Modal title="Estrutura completa da receita" icon={TreeStructure} onClose={onClose} wide>
      <p className="modal-intro">Os loops permanecem agrupados; a execução percorre suas etapas internas sem duplicá-las no mapa principal.</p>
      <div className="structure-tree">
        <div className="tree-root"><FileText /><strong>{recipe.name}</strong><span>{stats.steps} etapas · {recipe.cycles ?? 1} ciclos principais</span></div>
        <div className="structure-tree-list">
          {structure.map((node, index) => (
            <StructureTreeNode node={node} index={index} key={node.id} />
          ))}
        </div>
      </div>
    </Modal>
  );
}

function HelpModal({ onClose }) {
  return (
    <Modal title="Ajuda operacional" icon={BookOpen} onClose={onClose}>
      <div className="help-topics">
        <article><strong>Controle da receita</strong><p>Pause para continuar do mesmo ponto depois. Pare quando quiser encerrar definitivamente a execução atual.</p></article>
        <article><strong>Loops da receita</strong><p>O mapa mostra cada loop uma única vez. Abra o grupo para consultar as etapas e a iteração atual.</p></article>
        <article><strong>Controle manual</strong><p>Fica bloqueado enquanto uma receita está executando ou pausada. Pare a receita para liberar os comandos.</p></article>
      </div>
    </Modal>
  );
}

export function App() {
  const [view, setView] = useState("operate");
  const [runActive, setRunActive] = useState(true);
  const [runState, setRunState] = useState("running");
  const [pumpRunning, setPumpRunning] = useState(true);
  const [flowRate, setFlowRate] = useState(1);
  const [direction, setDirection] = useState("clockwise");
  const [channel, setChannel] = useState(3);
  const [recipes, setRecipes] = useState(initialRecipes);
  const [recipeStructures, setRecipeStructures] = useState(() => structuredClone(initialRecipeStructures));
  const [availablePorts, setAvailablePorts] = useState(demoSerialPorts);
  const [deviceStatus, setDeviceStatus] = useState({ valve: { connected: true }, pump: { connected: true } });
  const [currentRunId, setCurrentRunId] = useState(null);
  const [runningRecipe, setRunningRecipe] = useState(() => ({
    ...initialRecipes[0],
    structure: structuredClone(initialRecipeStructures[initialRecipes[0].id]),
    presentation: activeRecipe,
    startedAt: activeRecipe.startedAt,
    cycles: 2,
  }));
  const [modal, setModal] = useState(null);
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  const loadedRecipeId = useRef(initialRecipes[0].id);

  const notify = (message) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  };

  const applyStatus = (status) => {
    const run = status.run;
    const active = ["starting", "running", "paused", "stopping"].includes(run?.state);
    const belongsToLoadedRecipe = run?.recipe_id === loadedRecipeId.current;
    setRunActive(active);
    setRunState(run && belongsToLoadedRecipe ? run.state : active ? run.state : "idle");
    setCurrentRunId(active ? run.id : null);
    if (typeof status.pump?.running === "boolean") setPumpRunning(status.pump.running);
    else if (!status.pump?.connected) setPumpRunning(false);
    if (status.valve?.channel) setChannel(Number(status.valve.channel));
    else if (!status.valve?.connected) setChannel(null);
    setDeviceStatus({ valve: status.valve, pump: status.pump });

    if (run && (active || belongsToLoadedRecipe)) {
      setRunningRecipe((current) => {
        const recipe = recipes.find((item) => item.id === run.recipe_id) ?? current;
        const structure = recipeStructures[run.recipe_id] ?? current.structure ?? [];
        return {
          ...recipe,
          structure,
          cycles: run.requested_cycles,
          startedAt: run.started_at
            ? new Date(run.started_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
            : current.startedAt,
          presentation: buildLivePresentation(recipe, structure, run),
        };
      });
    }
  };

  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const [catalog, status, ports] = await Promise.all([
          getRecipes(),
          getStatus(),
          getSerialPorts(),
        ]);
        if (disposed) return;
        const loadedRecipes = catalog.items.map(apiRecipeToView);
        const loadedStructures = Object.fromEntries(
          catalog.items.map((item) => [item.id, apiStepsToStructure(item.recipe.steps)]),
        );
        if (loadedRecipes.length > 0) {
          setRecipes(loadedRecipes);
          setRecipeStructures(loadedStructures);
          const first = loadedRecipes[0];
          const loaded = loadedRecipes.find((item) => item.id === status.run?.recipe_id) ?? first;
          const loadedStructure = loadedStructures[loaded.id] ?? [];
          loadedRecipeId.current = loaded.id;
          setRunningRecipe({
            ...loaded,
            structure: loadedStructure,
            cycles: status.run?.requested_cycles ?? loaded.cycles,
            startedAt: status.run?.started_at
              ? new Date(status.run.started_at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
              : "—",
            ...(status.run ? { presentation: buildLivePresentation(loaded, loadedStructure, status.run) } : {}),
          });
        }
        setAvailablePorts(ports.map((port) => ({
          value: port.device,
          label: `${port.device} · ${port.description || "Dispositivo serial"}`,
        })));
        applyStatus(status);
        if (status.alerts?.[0]) notify(status.alerts[0].message);
      } catch (error) {
        if (!disposed) notify(`API indisponível; exibindo demonstração local. ${error.message}`);
      }
    };
    load();
    return () => { disposed = true; };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(async () => {
      try {
        applyStatus(await getStatus());
      } catch {
        // A última leitura válida permanece visível durante uma falha transitória.
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [recipes, recipeStructures]);

  const stopCurrentRecipe = async () => {
    try {
      if (!currentRunId) return;
      const run = await stopRun(currentRunId);
      setRunState(run.state);
      setModal(null);
      notify("Parada da receita solicitada.");
    } catch (error) {
      notify(error.message);
    }
  };

  const pauseCurrentRecipe = async () => {
    if (!currentRunId) return;
    try {
      const run = await pauseRun(currentRunId);
      setRunState(run.state);
      notify("Receita pausada. O tempo da etapa foi congelado.");
    } catch (error) {
      notify(error.message);
    }
  };

  const resumeCurrentRecipe = async () => {
    if (!currentRunId) return;
    try {
      const run = await resumeRun(currentRunId);
      setRunState(run.state);
      notify("Execução retomada.");
    } catch (error) {
      notify(error.message);
    }
  };

  const loadRecipeForOperation = (recipe, structure) => {
    const snapshot = structuredClone(structure);
    const stats = recipeStructureStats(snapshot);
    loadedRecipeId.current = recipe.id;
    setRunningRecipe({
      ...recipe,
      structure: snapshot,
      cycles: recipe.cycles ?? 1,
      startedAt: "—",
      duration: formatDuration(stats.durationMinutes * Number(recipe.cycles ?? 1)),
    });
    setRunState("idle");
    setView("operate");
    notify(`Receita carregada: ${recipe.name}.`);
  };

  const startRecipe = async (recipe, structure, options) => {
    if (recipe.persisted === false) {
      notify("Salve a receita antes de iniciar.");
      return false;
    }
    let run;
    try {
      run = await runRecipe({
        recipe_id: recipe.id,
        recipe_revision: recipe.revision,
        pump_mode: options.pumpMode,
        cycles: options.cycles,
        start_stopped_pump: options.startStoppedPump,
      });
    } catch (error) {
      notify(error.message);
      return false;
    }
    const snapshot = structuredClone(structure);
    const steps = flattenRecipeStructure(snapshot);
    const firstStep = steps[0];
    const stats = recipeStructureStats(snapshot);
    const now = new Date();
    const startedAt = now.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    loadedRecipeId.current = recipe.id;
    setRunningRecipe({
      ...recipe,
      structure: snapshot,
      presentation: undefined,
      cycles: options.cycles,
      pumpMode: options.pumpMode,
      startedAt,
      duration: formatDuration(stats.durationMinutes * options.cycles),
    });
    setRunActive(true);
    setRunState(run.state ?? "starting");
    setCurrentRunId(run.id);
    if (firstStep) {
      setChannel(Number(firstStep.channel));
      if (firstStep.effectiveFlowRate !== null) {
        setFlowRate(Number(firstStep.effectiveFlowRate));
        setDirection(Number(firstStep.effectiveFlowRate) < 0 ? "counterclockwise" : "clockwise");
      }
    }
    if (options.pumpMode === "controlled") {
      setPumpRunning(pumpRunning || options.startStoppedPump);
    } else if (options.pumpMode === "disabled") {
      setPumpRunning(false);
    }
    setView("operate");
    notify(`Receita iniciada: ${recipe.name}.`);
    return true;
  };

  const executeManualCommand = async (action, parameters) => {
    const status = await manualCommand(action, parameters);
    applyStatus(status);
  };

  const persistRecipe = async (recipe, structure) => {
    const saved = await saveApiRecipe(recipe, structureToApiRecipe(recipe, structure));
    return apiRecipeToView(saved);
  };

  const removeRecipe = async (recipe) => {
    await deleteApiRecipe(recipe);
  };

  const changeDeviceConnection = async (device, port, connected) => {
    try {
      const status = connected
        ? await disconnectDevice(device)
        : await connectDevice(device, port);
      applyStatus(status);
      notify(connected ? "Dispositivo desconectado com segurança." : "Dispositivo conectado.");
    } catch (error) {
      notify(error.message);
    }
  };

  const stopModal = modal === "stop" ? (
      <Modal
        title="Parar execução da receita"
        icon={WarningCircle}
        onClose={() => setModal(null)}
        footer={<><button className="secondary-action" onClick={() => setModal(null)}>Cancelar</button><button className="danger-action" onClick={stopCurrentRecipe}><Stop weight="fill" /> Parar receita</button></>}
      >
        <p className="modal-intro">A execução será encerrada e não poderá ser retomada deste ponto. Se a bomba estiver sob controle da receita, ela será parada. A válvula permanecerá no canal {channel}.</p>
        <div className="confirmation-summary"><span><FileText /> Execução</span><strong>{runningRecipe.name} · revisão {revisionLabel(runningRecipe)}</strong><span><Gauge /> Bomba</span><strong>{pumpRunning ? "Em movimento" : "Parada"}</strong></div>
      </Modal>
    ) : null;

  return (
    <div className="app-frame">
      <AppHeader view={view} onNavigate={setView} onOpenHelp={() => setModal("help")} />
      {view === "operate" && (
        <OperateView
          key={runningRecipe.id}
          runActive={runActive}
          runState={runState}
          pumpRunning={pumpRunning}
          setPumpRunning={setPumpRunning}
          flowRate={flowRate}
          setFlowRate={setFlowRate}
          direction={direction}
          setDirection={setDirection}
          channel={channel}
          setChannel={setChannel}
          deviceStatus={deviceStatus}
          runningRecipe={runningRecipe}
          onStopRun={() => setModal("stop")}
          onStartRun={() => setModal("start")}
          onPauseRun={pauseCurrentRecipe}
          onResumeRun={resumeCurrentRecipe}
          onOpenStructure={() => setModal("structure")}
          onManualCommand={executeManualCommand}
          notify={notify}
        />
      )}
      {view === "recipes" && <RecipesView recipes={recipes} setRecipes={setRecipes} structures={recipeStructures} setStructures={setRecipeStructures} notify={notify} runActive={runActive} runningRecipe={runningRecipe} onNavigate={setView} onLoadRecipe={loadRecipeForOperation} onSaveRecipe={persistRecipe} onDeleteRecipe={removeRecipe} />}
      {view === "devices" && <DevicesView notify={notify} serialPorts={availablePorts} deviceStatus={deviceStatus} onDeviceConnection={changeDeviceConnection} />}

      {modal === "help" && <HelpModal onClose={() => setModal(null)} />}
      {modal === "structure" && <StructureModal recipe={runningRecipe} onClose={() => setModal(null)} />}
      {modal === "start" && (
        <StartRecipeDialog
          recipe={runningRecipe}
          structure={runningRecipe.structure ?? []}
          runActive={runActive}
          runningRecipe={runningRecipe}
          pumpRunning={pumpRunning}
          onClose={() => setModal(null)}
          onGoToRun={() => setModal(null)}
          onStart={async (options) => {
            const started = await startRecipe(runningRecipe, runningRecipe.structure ?? [], options);
            if (started) setModal(null);
          }}
        />
      )}
      {stopModal}
      {toast && <div className="toast" role="status"><CheckCircle weight="fill" /> {toast}</div>}
    </div>
  );
}
