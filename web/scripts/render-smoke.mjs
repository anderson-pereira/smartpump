import React from "react";
import { renderToString } from "react-dom/server";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  server: { middlewareMode: true },
});

try {
  const { App } = await vite.ssrLoadModule("/src/App.jsx");
  const html = renderToString(React.createElement(App));
  if (!html.includes("Smart") || !html.includes("Resumo da bancada")) {
    throw new Error("A tela principal não foi renderizada por completo.");
  }
  console.log("Renderização inicial do React concluída sem exceções.");
} finally {
  await vite.close();
}
