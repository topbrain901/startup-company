// Production server for a self-hosted machine (VPS): serves the output of `npm run build`.
//
// The built Worker reads SUPABASE_URL, SUPABASE_ANON_KEY and FASTAPI_URL at runtime, but Wrangler
// only loads variables from a `.dev.vars` file next to the built config, not from this project's
// `.env`. So this copies `.env` (plus any of those variables set in the process environment, e.g.
// by systemd) to dist/server/.dev.vars, then starts Wrangler.
//
//   HOST (default 127.0.0.1) and PORT (default 8787) choose where it listens. Keep 127.0.0.1 and put
//   an HTTPS reverse proxy (Caddy, nginx) in front: sign-in cookies are Secure in production builds.
import { spawn } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";
import { projectRoot } from "./sites-env.mjs";

const RUNTIME_KEYS = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "FASTAPI_URL"];
const serverDir = path.join(projectRoot, "dist", "server");
const config = path.join(serverDir, "wrangler.json");
if (!existsSync(config)) {
  console.error("No production build found. Run `npm run build` first.");
  process.exit(1);
}

const envFile = path.join(projectRoot, ".env");
const values = existsSync(envFile) ? parseEnv(readFileSync(envFile, "utf8")) : {};
for (const key of RUNTIME_KEYS) {
  if (process.env[key]) values[key] = process.env[key];
}
const missing = RUNTIME_KEYS.filter((key) => !values[key]);
if (missing.length) {
  console.error(`Missing ${missing.join(", ")}. Set them in ${envFile} (see .env.example).`);
  process.exit(1);
}
const quote = (value) => (/^[\w.:/@%+=,-]*$/.test(value) ? value : JSON.stringify(String(value)));
writeFileSync(
  path.join(serverDir, ".dev.vars"),
  Object.entries(values).map(([key, value]) => `${key}=${quote(value)}`).join("\n") + "\n",
  { mode: 0o600 },
);

const host = process.env.HOST || "127.0.0.1";
const port = process.env.PORT || "8787";
const child = spawn(
  process.execPath,
  [
    path.join(projectRoot, "node_modules", "wrangler", "bin", "wrangler.js"),
    "dev",
    "--config", config,
    "--local",
    "--persist-to", path.join(projectRoot, ".wrangler", "state"),
    "--ip", host,
    "--port", port,
    "--inspector-port", "0",
    ...process.argv.slice(2),
  ],
  { cwd: projectRoot, stdio: "inherit", env: process.env },
);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
