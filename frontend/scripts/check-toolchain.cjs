// Resolve Rollup from Vite: npm overrides may place it in Vite's node_modules.
const { createRequire } = require("node:module");
try {
  const fromVite = createRequire(require.resolve("vite/package.json"));
  const rollup = fromVite("rollup/package.json").version;
  fromVite("rollup");
  console.log(`Node ${process.versions.node}; Angular CLI ${require("@angular/cli/package.json").version}; Rollup ${rollup}: carga correcta.`);
} catch (error) {
  console.error("No se pudo cargar la herramienta de compilacion:", error.message);
  console.error("Revisa la instalacion con el lock del proyecto y, si aparece Application Control, la politica con TI.");
  process.exitCode = 1;
}
