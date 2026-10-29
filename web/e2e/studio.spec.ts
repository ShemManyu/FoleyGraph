import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { Project } from "../src/types";

async function demo(page: Page): Promise<Project> {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Coffee ritual", exact: true })
    .click();
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith("/api/demo") && item.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  const result = await response;
  expect(result.ok()).toBeTruthy();
  await expect(page.getByLabel("Scene name")).toHaveValue("Slow mornings");
  return (await result.json()) as Project;
}

test("the default demo opens real people footage with a chat-first workspace", async ({
  page,
}) => {
  await enableDirectorInterface(page);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "People & style", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  const response = page.waitForResponse(
    (item) =>
      item.url().endsWith("/api/demo?scene=style") &&
      item.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  const result = await response;
  expect(result.ok()).toBeTruthy();
  const scene = (await result.json()) as Project;
  expect(scene.media.filename).toBe("weekend-style.mp4");
  await expect(page.getByLabel("Scene name")).toHaveValue("Weekend, remixed");
  await expect(page.locator("video")).toHaveJSProperty("videoHeight", 960);
  await expect(
    page.getByRole("button", {
      name: "Make the left outfit terracotta",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.locator(".timeline")).toBeHidden();
});

test("returning visitors are not sent back into the retired illustrated demo", async ({
  page,
}) => {
  const response = await page.request.post("/api/demo");
  const saved = (await response.json()) as Project;
  const legacy = {
    ...saved,
    name: "My saved first reel",
    source_credit: "",
    media: { ...saved.media, filename: "the-tiny-crossing.mp4" },
    analysis_note:
      "Original illustrated demo with hand-authored tracks and cues.",
  };
  await page.route("**/api/projects", (route) =>
    route.fulfill({
      json: [
        {
          id: legacy.id,
          name: legacy.name,
          duration: legacy.media.duration,
          updated_at: legacy.updated_at,
          objects: legacy.objects.length,
          cues: legacy.cues.length,
        },
      ],
    }),
  );
  await page.route(`**/api/projects/${saved.id}`, (route) =>
    route.fulfill({ json: legacy }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Try the demo", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Reel conversation" }),
  ).toHaveCount(0);
  await expect(page.locator(".reel-cover")).toHaveAttribute(
    "src",
    "/style-poster.jpg",
  );
  await page.getByRole("button", { name: "Your reels", exact: true }).click();
  await expect(
    page.getByRole("button", { name: /^My saved first reel/ }),
  ).toBeVisible();
  expect(
    (await (await page.request.get(`/api/projects/${saved.id}`)).json()).id,
  ).toBe(saved.id);
});

async function editResponse(page: Page, suffix: string): Promise<Project> {
  const response = await page.waitForResponse(
    (item) => item.url().endsWith(suffix) && item.request().method() === "POST",
  );
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as Project;
}

async function enableDirectorInterface(page: Page) {
  await page.route("**/api/config", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      json: {
        ...(await response.json()),
        ai_available: true,
        voice_available: true,
      },
    });
  });
}

async function openAdvancedTools(page: Page) {
  await page.getByRole("button", { name: "More reel options" }).click();
  await page
    .getByRole("button", { name: "Advanced tools", exact: true })
    .click();
}

test("the portrait reel starts simple, with detailed editing available on demand", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const before = await demo(page);
  expect(before.media.height / before.media.width).toBeCloseTo(16 / 9);
  await expect(
    page.getByRole("region", { name: "Reel conversation" }),
  ).toBeVisible();
  await expect(page.locator(".objects-panel")).toBeHidden();
  await expect(page.locator(".inspector-panel")).toBeHidden();
  await expect(page.locator(".timeline")).toBeHidden();
  await expect(page.locator(".tracking-box")).toHaveCount(0);
  expect(await page.locator("button:visible").count()).toBeLessThanOrEqual(15);
  await expect(
    page.getByRole("button", { name: "Fine-tune", exact: true }),
  ).toHaveCount(0);
  await openAdvancedTools(page);
  await expect(page.locator(".timeline")).toBeVisible();

  const afterPromise = editResponse(page, "/edit");
  await page.getByLabel("Sound material").selectOption("metal");
  const after = await afterPromise;
  expect(after.cues.filter((cue) => cue.object_id !== "pour")).toEqual(
    before.cues.filter((cue) => cue.object_id !== "pour"),
  );
  expect(after.cues.map((cue) => cue.time)).toEqual(
    before.cues.map((cue) => cue.time),
  );
  expect(
    after.cues
      .filter((cue) => cue.object_id === "pour")
      .every((cue) => cue.asset_id === "metal-movement"),
  ).toBeTruthy();

  const undoPromise = editResponse(page, "/undo");
  await page.getByRole("button", { name: "Undo last edit" }).click();
  expect((await undoPromise).cues).toEqual(before.cues);
  await page
    .getByRole("button", { name: /^Coffee pour movement at/ })
    .first()
    .click();
  const original = before.cues[0];
  const earlier = editResponse(page, "/edit");
  await page.locator(".frame-buttons button").first().click();
  expect((await earlier).cues[0].time).toBeCloseTo(
    original.time - 1 / before.media.fps,
  );

  await page.getByRole("button", { name: "Back to chat", exact: true }).click();
  await expect(page.locator(".timeline")).toBeHidden();
  const position = await page
    .locator("video")
    .evaluate((video) => (video as HTMLVideoElement).currentTime);
  await page.getByRole("button", { name: "Play scene" }).click();
  await expect(page.getByRole("button", { name: "Pause scene" })).toBeVisible();
  await expect
    .poll(() =>
      page
        .locator("video")
        .evaluate((video) => (video as HTMLVideoElement).currentTime),
    )
    .toBeGreaterThan(position + 0.3);
  await page.getByRole("button", { name: "Pause scene" }).click();
  expect(errors).toEqual([]);
});

test("mobile chat has room for conversation, resolves edits, and supports undo without setup", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await enableDirectorInterface(page);
  const before = await demo(page);
  await expect(page.getByLabel("Current reel")).toHaveText("Slow mornings");
  await expect(page.getByLabel("Scene name")).toBeHidden();
  await expect(page.getByLabel("Sound material")).toBeHidden();
  const preview = await page.locator(".video-surround").boundingBox();
  const chat = await page
    .getByRole("log", { name: "Conversation" })
    .boundingBox();
  expect(chat!.height).toBeGreaterThan(preview!.height);
  await page.getByRole("button", { name: "Enlarge preview" }).click();
  const enlarged = await page.locator(".video-surround").boundingBox();
  expect(enlarged!.height).toBeGreaterThan(preview!.height + 100);
  await expect(
    page.getByRole("button", { name: "Speak a direction" }),
  ).toBeVisible();
  let selected: string | null = "not called";
  const statusUrl = `/api/jobs/${"a".repeat(32)}`;
  let polls = 0;
  let complete = false;
  let result: { project: Project; message: string };
  await page.route("**/direct", async (route) => {
    expect(route.request().headers().prefer).toBe("respond-async");
    const body = route.request().postDataJSON() as {
      revision: number;
      object_id: string | null;
      instruction: string;
    };
    selected = body.object_id;
    const edited = await page.request.post(`/api/projects/${before.id}/edit`, {
      data: {
        revision: body.revision,
        object_id: "cup",
        operations: [{ type: "gain", value: -3 }],
      },
    });
    expect(edited.ok()).toBeTruthy();
    result = {
      project: (await edited.json()) as Project,
      message: "The cup is 3 dB quieter. Your pour and cafe air are unchanged.",
    };
    await route.fulfill({
      status: 202,
      json: { status: "processing", status_url: statusUrl },
    });
  });
  await page.route(`**${statusUrl}`, (route) => {
    polls += 1;
    return route.fulfill({
      json: complete
        ? { status: "completed", result }
        : { status: "processing" },
    });
  });
  await expect(
    page.getByRole("group", { name: "Choose a sound to edit" }),
  ).toHaveCount(0);
  await page.getByLabel("Edit direction").fill("Make the cup a little quieter");
  await expect(
    page.getByRole("button", { name: "Speak a direction" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Enlarge preview" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Send direction" }).click();
  await expect.poll(() => polls).toBeGreaterThan(0);
  await expect(page.getByLabel("Edit direction")).toBeDisabled();
  await expect(
    page.locator(".chat-message.assistant").last(),
  ).not.toContainText("3 dB quieter");
  complete = true;
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "3 dB quieter",
  );
  expect(selected).toBeNull();
  await expect(page.getByLabel("Try a direction")).toHaveCount(0);
  await expect(page.getByLabel("Edit direction")).toHaveValue("");
  const current = (await (
    await page.request.get(`/api/projects/${before.id}`)
  ).json()) as Project;
  expect(current.objects.filter((object) => object.id !== "cup")).toEqual(
    before.objects.filter((object) => object.id !== "cup"),
  );
  expect(current.cues).toEqual(before.cues);

  await page.reload();
  await expect(page.getByLabel("Scene name")).toHaveValue("Slow mornings");
  await expect(page.locator(".chat-message.user")).toContainText(
    "Make the cup a little quieter",
  );
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "3 dB quieter",
  );
  await page.getByLabel("Edit direction").fill("Undo that");
  const undone = editResponse(page, "/undo");
  await page.getByRole("button", { name: "Send direction" }).click();
  expect((await undone).objects).toEqual(before.objects);
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "last change is undone",
  );

  await page.getByRole("button", { name: "More reel options" }).click();
  await page.getByRole("button", { name: "Your reels", exact: true }).click();
  await page.getByRole("button", { name: "Try the demo", exact: true }).click();
  await expect(page.locator(".chat-message.user")).toHaveCount(0);
  await expect(page.locator(".chat-message.assistant")).toHaveCount(1);
});

test("a failed chat edit stays in the conversation without pretending it was applied", async ({
  page,
}) => {
  await enableDirectorInterface(page);
  const before = await demo(page);
  await page.route("**/direct", (route) =>
    route.fulfill({
      status: 503,
      json: { detail: "The director is temporarily unavailable." },
    }),
  );
  await page.getByLabel("Edit direction").fill("Make the pour softer");
  await page.getByRole("button", { name: "Send direction" }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "I couldn't make that change.",
  );
  await expect(page.getByLabel("Edit direction")).toHaveValue(
    "Make the pour softer",
  );
  const unchanged = (await (
    await page.request.get(`/api/projects/${before.id}`)
  ).json()) as Project;
  expect(unchanged.revision).toBe(before.revision);
  expect(unchanged.cues).toEqual(before.cues);
  await page.unroute("**/direct");
  const statusUrl = `/api/jobs/${"b".repeat(32)}`;
  await page.route("**/direct", (route) =>
    route.fulfill({
      status: 202,
      json: { status: "processing", status_url: statusUrl },
    }),
  );
  await page.route(`**${statusUrl}`, (route) =>
    route.fulfill({
      json: {
        status: "failed",
        error: "This color edit took too long. Try a shorter clip.",
        error_status: 422,
      },
    }),
  );
  await page.getByLabel("Edit direction").fill("Make the cup blue");
  await page.getByRole("button", { name: "Send direction" }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "I couldn't make that change. This color edit took too long.",
  );
  await expect(page.getByLabel("Edit direction")).toHaveValue(
    "Make the cup blue",
  );
  const afterFailure = (await (
    await page.request.get(`/api/projects/${before.id}`)
  ).json()) as Project;
  expect(afterFailure).toEqual(unchanged);
});

test("a new clip receives its first sound pass from chat without a separate setup panel", async ({
  page,
}) => {
  await enableDirectorInterface(page);
  const initial = await demo(page);
  const source = await page.request.get(
    `/api/projects/${initial.id}/source.mp4`,
  );
  const uploaded = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/projects") &&
      response.request().method() === "POST",
  );
  await page.getByLabel("Upload video file").setInputFiles({
    name: "My coffee film.mp4",
    mimeType: "video/mp4",
    buffer: await source.body(),
  });
  const scene = (await (await uploaded).json()) as Project;
  let brief = "";
  await page.route("**/direct", async (route) => {
    brief = (route.request().postDataJSON() as { instruction: string })
      .instruction;
    const boundResponse = await page.request.post(
      `/api/projects/${scene.id}/objects`,
      {
        data: {
          revision: scene.revision,
          name: "Coffee cup",
          profile: "water",
          box: { time: 0, x: 0.2, y: 0.5, width: 0.5, height: 0.3 },
        },
      },
    );
    const bound = (await boundResponse.json()) as Project;
    const proposed = await page.request.post(`/api/projects/${scene.id}/cues`, {
      data: {
        revision: bound.revision,
        object_id: bound.objects[0].id,
        kind: "movement",
        time: 1,
      },
    });
    await route.fulfill({
      json: {
        project: await proposed.json(),
        message: "Your first sound pass is ready.",
      },
    });
  });
  await expect(page.getByLabel("Scene name")).toHaveValue("My coffee film");
  await expect(page.locator(".objects-panel")).toBeHidden();
  await page
    .getByLabel("Edit direction")
    .fill("Warm, quiet coffee sounds, no music.");
  await page.getByRole("button", { name: "Send direction" }).click();
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "first sound pass is ready",
  );
  const updated = (await (
    await page.request.get(`/api/projects/${scene.id}`)
  ).json()) as Project;
  expect(updated.objects[0].name).toBe("Coffee cup");
  expect(updated.cues).toHaveLength(1);
  await expect(page.locator(".objects-panel")).toBeHidden();
  expect(brief).toBe("Warm, quiet coffee sounds, no music.");
  await expect(page.locator(".chat-message.assistant").last()).toContainText(
    "first sound pass is ready.",
  );
});

test("recordings are usable from chat, with a portrait export and editable bundle", async ({
  page,
}) => {
  const initial = await demo(page);
  const source = await page.request.get("/api/samples/glass-impact.wav");
  const assetResponse = page.waitForResponse(
    (item) =>
      item.url().endsWith("/assets") && item.request().method() === "POST",
  );
  await page.getByLabel("Import audio file").setInputFiles({
    name: "Desk tap.wav",
    mimeType: "audio/wav",
    buffer: await source.body(),
  });
  expect((await assetResponse).ok()).toBeTruthy();
  await expect(page.locator(".chat-attachment")).toHaveCount(1);
  const assignedPromise = editResponse(page, "/edit");
  await page
    .locator(".chat-attachment")
    .getByRole("button", { name: "Use on Coffee pour", exact: true })
    .click();
  const assigned = await assignedPromise;
  const customId = assigned.assets.at(-1)!.id;
  expect(
    assigned.cues
      .filter((cue) => cue.object_id === "pour")
      .every((cue) => cue.asset_id === customId),
  ).toBeTruthy();

  await page.getByLabel("Add your own sound").click();
  await page
    .getByRole("button", { name: "Record a sound", exact: true })
    .click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(page.getByRole("button", { name: "Save take" })).toBeVisible();
  await page.waitForTimeout(1000);
  const recordedResponse = page.waitForResponse(
    (item) =>
      item.url().endsWith("/assets") && item.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Save take" }).click();
  expect((await recordedResponse).ok()).toBeTruthy();
  await expect(page.locator(".chat-attachment")).toHaveCount(2);
  const rendering = page.waitForResponse(
    (item) =>
      item.url().endsWith("/exports") && item.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Share reel" }).click();
  expect((await rendering).ok()).toBeTruthy();
  await expect(
    page.getByText("Your reel is ready.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Download reel/ })).toBeVisible();
  await page
    .getByText("Keep the project files and sound layers", { exact: true })
    .click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /Complete scene bundle/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/bundle\.zip$/);
  const path = await download.path();
  expect(path).not.toBeNull();
  const data = await readFile(path!);
  expect(data.subarray(0, 2).toString()).toBe("PK");
  await page.getByRole("button", { name: "Close dialog" }).click();
  const restoredResponse = page.waitForResponse((item) =>
    item.url().endsWith("/api/projects/import"),
  );
  await page.getByLabel("Import project bundle").setInputFiles({
    name: "My scene.zip",
    mimeType: "application/zip",
    buffer: data,
  });
  const restored = await restoredResponse;
  expect(restored.ok(), await restored.text()).toBeTruthy();
  const scene = (await restored.json()) as Project;
  expect(scene.cues).toEqual(assigned.cues);
  expect(scene.assets).toHaveLength(initial.assets.length + 2);
  expect(scene.media.height / scene.media.width).toBeCloseTo(16 / 9);
  await expect(page.getByLabel("Scene name")).toHaveValue("Slow mornings");
});

test("manual point binding remains available and the simple view fits mobile", async ({
  page,
}) => {
  const initial = await demo(page);
  const clip = await page.request.get(`/api/projects/${initial.id}/source.mp4`);
  const uploadResponse = page.waitForResponse(
    (item) =>
      item.url().endsWith("/api/projects") &&
      item.request().method() === "POST",
  );
  await page.getByLabel("Upload video file").setInputFiles({
    name: "My original film.mp4",
    mimeType: "video/mp4",
    buffer: await clip.body(),
  });
  const uploaded = (await (await uploadResponse).json()) as Project;
  await expect(page.getByLabel("Scene name")).toHaveValue("My original film");
  await openAdvancedTools(page);
  await page.getByRole("button", { name: "Bind an object" }).click();
  const rectangle = await page.locator(".video-stage").boundingBox();
  expect(rectangle).not.toBeNull();
  const boundPromise = editResponse(page, "/objects");
  await page.mouse.move(
    rectangle!.x + rectangle!.width * 0.15,
    rectangle!.y + rectangle!.height * 0.3,
  );
  await page.mouse.down();
  await page.mouse.move(
    rectangle!.x + rectangle!.width * 0.4,
    rectangle!.y + rectangle!.height * 0.8,
    { steps: 10 },
  );
  await page.mouse.up();
  const bound = await boundPromise;
  expect(bound.objects).toHaveLength(1);
  expect(bound.cues).toHaveLength(0);
  expect(bound.objects[0].keyframes[0].x).toBeCloseTo(0.15);
  const cuePromise = editResponse(page, "/cues");
  await page.getByRole("button", { name: "Add cue", exact: true }).click();
  expect((await cuePromise).cues).toHaveLength(1);
  await page.getByRole("button", { name: "Back to chat", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Scene video")).toBeVisible();
  await expect(page.getByLabel("Edit direction")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  const composer = await page.getByLabel("Edit direction").boundingBox();
  const send = await page
    .getByRole("button", { name: "Send direction" })
    .boundingBox();
  expect(composer!.y).toBeGreaterThan(0);
  expect(send!.y + send!.height).toBeLessThanOrEqual(844);
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight),
  ).toBeLessThanOrEqual(845);
  await page.setViewportSize({ width: 390, height: 520 });
  await page.getByLabel("Edit direction").focus();
  await expect
    .poll(async () => {
      const bounds = await page
        .getByRole("button", { name: "Send direction" })
        .boundingBox();
      return bounds!.y + bounds!.height;
    })
    .toBeLessThanOrEqual(520);
  const current = await page.request.get(`/api/projects/${uploaded.id}`);
  expect(((await current.json()) as Project).cues).toHaveLength(1);
});

test("mobile Instagram and WhatsApp actions share the actual MP4 from a fresh tap", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    const shared: {
      type: string;
      size: number;
      header: string;
      active: boolean;
    }[] = [];
    Object.assign(window, { sharedVideos: shared });
    Object.defineProperty(navigator, "canShare", {
      value: (data: ShareData) => data.files?.[0]?.type === "video/mp4",
    });
    Object.defineProperty(navigator, "share", {
      value: async (data: ShareData) => {
        const active = navigator.userActivation.isActive;
        const file = data.files![0];
        shared.push({
          type: file.type,
          size: file.size,
          header: new TextDecoder().decode(
            (await file.arrayBuffer()).slice(4, 8),
          ),
          active,
        });
      },
    });
  });
  await demo(page);
  for (const platform of ["Instagram", "WhatsApp"]) {
    await page.getByRole("button", { name: "Share reel" }).click();
    await expect(
      page.getByRole("button", { name: platform, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: platform, exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
  const shared = await page.evaluate(
    () =>
      (
        window as unknown as {
          sharedVideos: {
            type: string;
            size: number;
            header: string;
            active: boolean;
          }[];
        }
      ).sharedVideos,
  );
  expect(shared).toHaveLength(2);
  for (const file of shared) {
    expect(file.type).toBe("video/mp4");
    expect(file.size).toBeGreaterThan(100000);
    expect(file.header).toBe("ftyp");
    expect(file.active).toBeTruthy();
  }
});

test("unsupported sharing offers an MP4 download and cancellation never claims publication", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "canShare", {
      configurable: true,
      value: () => false,
    });
  });
  await demo(page);
  await page.getByRole("button", { name: "Share reel" }).click();
  await expect(
    page.getByText(/This browser can't share video files directly/),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /Download reel/ })).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.evaluate(() => {
    Object.defineProperty(navigator, "canShare", {
      configurable: true,
      value: () => true,
    });
    Object.defineProperty(navigator, "share", {
      configurable: true,
      value: () => Promise.reject(new DOMException("Canceled", "AbortError")),
    });
  });
  await page.getByRole("button", { name: "Share reel" }).click();
  await page.getByRole("button", { name: "Instagram", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.locator(".toast.error")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "WhatsApp", exact: true }),
  ).toBeEnabled();
});
