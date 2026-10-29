export type Kind = "footstep" | "impact" | "movement" | "ambience";
export type Profile =
  "wood" | "metal" | "stone" | "soft" | "glass" | "paper" | "water" | "synth";

export interface Box {
  time: number;
  x: number;
  y: number;
  width: number;
  height: number;
  visible: boolean;
}

export interface SceneObject {
  id: string;
  name: string;
  color: string;
  profile: Profile;
  sound_overrides: Partial<Record<Kind, string>>;
  gain_db: number;
  muted: boolean;
  keyframes: Box[];
}

export interface Cue {
  id: string;
  object_id: string;
  kind: Kind;
  time: number;
  duration: number;
  asset_id: string;
  gain_db: number;
  pan: number | null;
  playback_rate: number;
  lowpass_hz: number | null;
  fade_in: number;
  fade_out: number;
  muted: boolean;
}

export interface Asset {
  id: string;
  name: string;
  duration: number;
  source: string;
}

export interface Project {
  schema_version: 1;
  id: string;
  name: string;
  brief: string;
  media: {
    duration: number;
    fps: number;
    width: number;
    height: number;
    filename: string;
    has_audio: boolean;
  };
  objects: SceneObject[];
  cues: Cue[];
  assets: Asset[];
  music: { style: "ambient"; gain_db: number } | null;
  caption: { text: string } | null;
  source_audio_muted: boolean;
  source_credit: string;
  visual_edits: {
    id: string;
    target: string;
    color: string;
    source_color: string;
    surface_kind: "fabric" | "object";
    confidence: number;
    keyframes: {
      time: number;
      visible: boolean;
      points: { x: number; y: number }[];
      seeds: { x: number; y: number }[];
      protected: { x: number; y: number }[];
    }[];
  }[];
  preview_id: string | null;
  revision: number;
  undo_revisions: number[];
  created_at: string;
  updated_at: string;
  analysis_note: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  updated_at: string;
  duration: number;
  objects: number;
  cues: number;
}

export interface Sample {
  id: string;
  name: string;
  profile: Profile;
  kind: Kind;
  duration: number;
  source: string;
  license: string;
  url: string;
}

export interface Configuration {
  ai_available: boolean;
  voice_available: boolean;
  storage: string;
  profiles: { id: Profile; name: string }[];
  limits: {
    duration: number;
    upload_mb: number;
    objects: number;
    cues: number;
  };
}

export interface Operation {
  type: "set_sound" | "gain" | "pan" | "shift" | "mute" | "filter";
  kind?: Kind;
  cue_ids?: string[];
  profile?: Profile;
  asset_id?: string;
  value?: number | null;
  frames?: number;
}

export interface ExportResult {
  id: string;
  revision: number;
  video_url: string;
  bundle_url: string;
  project_url: string;
  mix_url: string;
}

export const kindLabels: Record<Kind, string> = {
  footstep: "Footsteps",
  impact: "Impacts",
  movement: "Movement",
  ambience: "Ambience",
};

export function boxAt(object: SceneObject, time: number): Box | null {
  if (!object.keyframes.length) return null;
  let left = object.keyframes[0];
  for (const right of object.keyframes.slice(1)) {
    if (time < right.time) {
      if (!left.visible) return left;
      const factor = Math.max(
        0,
        Math.min(
          1,
          (time - left.time) / Math.max(0.001, right.time - left.time),
        ),
      );
      return {
        time,
        visible: left.visible,
        x: left.x + (right.x - left.x) * factor,
        y: left.y + (right.y - left.y) * factor,
        width: left.width + (right.width - left.width) * factor,
        height: left.height + (right.height - left.height) * factor,
      };
    }
    left = right;
  }
  return left;
}

export function assetUrl(project: Project, id: string): string {
  return project.assets.some((asset) => asset.id === id)
    ? `/api/projects/${project.id}/assets/${id}.wav`
    : `/api/samples/${id}.wav`;
}

export function videoUrl(project: Project): string {
  return project.preview_id
    ? `/api/projects/${project.id}/previews/${project.preview_id}.mp4`
    : `/api/projects/${project.id}/source.mp4`;
}

export function isLegacyDemo(project: Project): boolean {
  return (
    project.media.filename === "the-tiny-crossing.mp4" &&
    project.analysis_note.startsWith("Original illustrated demo")
  );
}

export function timecode(time: number, fps = 24): string {
  const totalFrames = Math.floor(Math.max(0, time) * fps + 0.0001);
  const seconds = Math.floor(totalFrames / fps);
  const frames = Math.floor(totalFrames - seconds * fps);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}:${String(frames).padStart(2, "0")}`;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (typeof init.body === "string")
    headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((entry: { msg: string }) => entry.msg).join("; ")
          : `The request failed (${response.status}). Please retry.`;
    throw new ApiError(message, response.status);
  }
  return data as T;
}
