import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    viewport: { width: 1440, height: 1100 },
    trace: "retain-on-failure",
    launchOptions: {
      args: [
        "--autoplay-policy=no-user-gesture-required",
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
      ],
    },
  },
  webServer: {
    command:
      ".venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8765",
    cwd: root,
    url: "http://127.0.0.1:8765/healthz",
    reuseExistingServer: false,
    timeout: 30_000,
    env: {
      FOLEYGRAPH_DATA_DIR: path.join(root, ".data", "e2e"),
      AZURE_STORAGE_ACCOUNT: "",
      AZURE_OPENAI_ENDPOINT: "",
      WORKSPACE_SECRET: "local-browser-tests-only",
    },
  },
});
