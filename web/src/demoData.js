export const channels = [
  { id: 1, label: "Tampão A" },
  { id: 2, label: "Tampão B" },
  { id: 3, label: "H₂O" },
  { id: 4, label: "Etanol 10%" },
  { id: 5, label: "Etanol 50%" },
  { id: 6, label: "Etanol 100%" },
];

export const activeRecipe = {
  id: "ethanol-gradient",
  name: "Gradiente de etanol",
  revision: 8,
  state: "Em execução",
  startedAt: "10:14",
  duration: "24:00",
  map: [
    { id: "prepare", label: "Preparação", meta: "1 etapa", kind: "step" },
    {
      id: "wash",
      label: "Lavagem",
      meta: "3 etapas",
      repeats: 4,
      kind: "loop",
      active: true,
      iteration: 2,
      children: [
        { label: "H₂O", duration: "5 min", state: "done" },
        { label: "Etanol 10%", duration: "5 min", state: "active" },
        { label: "H₂O", duration: "5 min", state: "pending" },
      ],
    },
    { id: "pbs", label: "PBS", meta: "1 etapa", kind: "step" },
    {
      id: "gradient",
      label: "Gradiente",
      meta: "4 etapas",
      repeats: 2,
      kind: "loop",
      children: [
        { label: "Etanol 20%", duration: "5 min", state: "pending" },
        { label: "H₂O", duration: "5 min", state: "pending" },
        { label: "Etanol 50%", duration: "5 min", state: "pending" },
        { label: "H₂O", duration: "5 min", state: "pending" },
      ],
    },
    { id: "rinse", label: "Enxágue", meta: "1 etapa", kind: "step" },
  ],
  current: {
    title: "Etanol 10%",
    description: "Solução de etanol 10% em água",
    solution: "Etanol 10%",
    channel: 3,
    flowRate: 1,
    direction: "Horário",
    elapsed: "03:12",
    duration: "5:00",
    progress: 62,
    breadcrumb: ["Ciclo principal 1/2", "Lavagem 2/4", "Etapa 2/3"],
  },
  upcoming: [
    { label: "H₂O", path: "Lavagem 2/4 · Etapa 3/3", duration: "5 min" },
    { label: "H₂O", path: "Lavagem 3/4 · Etapa 1/3", duration: "5 min" },
    { label: "Etanol 10%", path: "Lavagem 3/4 · Etapa 2/3", duration: "5 min" },
  ],
};

export const initialRecipes = [
  {
    id: "ethanol-gradient",
    name: "Gradiente de etanol",
    description: "Exposição sequencial com lavagens intermediárias.",
    revision: 8,
    steps: 8,
    duration: "24 min",
    status: "Em execução",
    updatedAt: "Hoje 10:14",
  },
  {
    id: "channel-wash",
    name: "Lavagem do sistema",
    description: "Lavagem sequencial dos seis canais.",
    revision: 3,
    steps: 4,
    duration: "12 min",
    updatedAt: "Hoje 08:20",
  },
  {
    id: "column-balance",
    name: "Equilíbrio da coluna",
    description: "Preparação e estabilização antes do ensaio.",
    revision: 5,
    steps: 6,
    duration: "18 min",
    updatedAt: "Ontem 16:32",
  },
];

export const initialRecipeStructures = {
  "ethanol-gradient": [
    {
      id: "prepare",
      kind: "step",
      label: "Preparação",
      channel: 1,
      solution: "Tampão A",
      durationMinutes: 2,
      flowRate: 1,
    },
    {
      id: "wash",
      kind: "loop",
      label: "Lavagem",
      cycles: 4,
      flowRate: 1,
      children: [
        { id: "wash-water-in", kind: "step", label: "Entrada de água", channel: 3, solution: "H₂O", durationMinutes: 5, flowRate: null },
        { id: "wash-ethanol", kind: "step", label: "Etanol 10%", channel: 4, solution: "Etanol 10%", durationMinutes: 5, flowRate: null },
        { id: "wash-water-out", kind: "step", label: "Enxágue", channel: 3, solution: "H₂O", durationMinutes: 5, flowRate: null },
      ],
    },
    {
      id: "pbs",
      kind: "step",
      label: "PBS",
      channel: 2,
      solution: "Tampão B",
      durationMinutes: 4,
      flowRate: 0.8,
    },
    {
      id: "gradient",
      kind: "loop",
      label: "Gradiente",
      cycles: 2,
      flowRate: 1,
      children: [
        { id: "gradient-20", kind: "step", label: "Etanol 20%", channel: 4, solution: "Etanol 20%", durationMinutes: 5, flowRate: null },
        { id: "gradient-water-a", kind: "step", label: "Lavagem", channel: 3, solution: "H₂O", durationMinutes: 5, flowRate: null },
        { id: "gradient-50", kind: "step", label: "Etanol 50%", channel: 5, solution: "Etanol 50%", durationMinutes: 5, flowRate: null },
        { id: "gradient-water-b", kind: "step", label: "Lavagem final", channel: 3, solution: "H₂O", durationMinutes: 5, flowRate: null },
      ],
    },
    {
      id: "rinse",
      kind: "step",
      label: "Enxágue",
      channel: 3,
      solution: "H₂O",
      durationMinutes: 3,
      flowRate: 1,
    },
  ],
  "channel-wash": [
    {
      id: "wash-all-channels",
      kind: "loop",
      label: "Percorrer canais",
      cycles: 1,
      flowRate: 1,
      children: channels.map((channel) => ({
        id: `channel-wash-${channel.id}`,
        kind: "step",
        label: `Lavar canal ${channel.id}`,
        channel: channel.id,
        solution: channel.label,
        durationMinutes: 0.25,
        flowRate: null,
      })),
    },
  ],
  "column-balance": [
    { id: "balance-pbs", kind: "step", label: "Equilibrar com PBS", channel: 2, solution: "PBS", durationMinutes: 10, flowRate: 0.6 },
    { id: "balance-water", kind: "step", label: "Lavagem com água", channel: 3, solution: "H₂O", durationMinutes: 8, flowRate: 0.6 },
  ],
};

export const serialPorts = [
  { value: "COM3", label: "COM3 · Cavro Valve" },
  { value: "COM4", label: "COM4 · Ismatec ISM832" },
  { value: "COM7", label: "COM7 · USB Serial Device" },
];
