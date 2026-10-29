import {
  ArrowLeft,
  ArrowRight,
  AudioLines,
  AudioWaveform,
  Box as BoxIcon,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Download,
  Ellipsis,
  Eye,
  EyeOff,
  FileArchive,
  Film,
  FolderOpen,
  Footprints,
  Headphones,
  Instagram,
  Layers3,
  LoaderCircle,
  Maximize,
  Minimize2,
  Mic,
  MessageCircle,
  MousePointer2,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  RotateCcw,
  Scan,
  Search,
  Send,
  ShieldCheck,
  Share2,
  SkipBack,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Upload,
  Volume2,
  VolumeX,
  WandSparkles,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { PreviewEngine } from "./audio";
import {
  api,
  ApiError,
  assetUrl,
  boxAt,
  kindLabels,
  isLegacyDemo,
  timecode,
  videoUrl,
  type Box,
  type Configuration,
  type Cue,
  type ExportResult,
  type Kind,
  type Operation,
  type Profile,
  type Project,
  type ProjectSummary,
  type Sample,
} from "./types";

type ModalName = "options" | "projects" | "sounds" | "help" | "export" | null;
type Toast = { text: string; error: boolean };
type Binding = { objectId: string | null };
type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  scope?: string;
  assetId?: string;
};
const kinds = Object.keys(kindLabels) as Kind[];

function conversationFor(scene: Project): ChatMessage[] {
  try {
    const saved: unknown = JSON.parse(
      localStorage.getItem(`foleygraph-chat:${scene.id}`) ?? "null",
    );
    if (
      Array.isArray(saved) &&
      saved.length &&
      saved.every(
        (message) =>
          message &&
          typeof message.id === "string" &&
          ["user", "assistant"].includes(message.role) &&
          typeof message.text === "string" &&
          message.text.length <= 2000 &&
          (message.scope === undefined || typeof message.scope === "string") &&
          (message.assetId === undefined ||
            typeof message.assetId === "string"),
      )
    )
      return saved.slice(-40) as ChatMessage[];
  } catch {
    // Browser storage is optional; the conversation still works in memory.
  }
  return [
    {
      id: "welcome",
      role: "assistant",
      text:
        scene.source_credit && scene.media.filename === "weekend-style.mp4"
          ? "Real footage, ready for your remix. Change an outfit color, add a title, or set the mood with music. Just tell me."
          : scene.source_credit && scene.media.filename === "morning-ritual.mp4"
            ? "Your morning reel is ready. Want a different look or vibe? Just tell me."
            : scene.objects.length
              ? "What would you like to change?"
              : "Your clip is ready. Tell me the vibe or what you'd like to change. I'll take care of the details.",
    },
  ];
}

function IconButton({
  label,
  children,
  className = "",
  ...props
}: {
  label: string;
  children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`icon-button ${className}`}
      title={label}
      aria-label={label}
      {...props}
    >
      {children}
    </button>
  );
}

function Modal({
  title,
  subtitle,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${wide ? "modal-wide" : ""}`}
      onCancel={onClose}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      aria-label={title}
    >
      <div className="modal-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <IconButton label="Close dialog" onClick={onClose}>
          <X size={19} />
        </IconButton>
      </div>
      {children}
    </dialog>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onCommit,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onCommit: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  function commit() {
    if (draft !== value) onCommit(draft);
  }
  return (
    <label className="slider-field">
      <span>
        {label}
        <output>
          {draft.toFixed(step < 1 ? 2 : 0)}
          {unit}
        </output>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(Number(event.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        aria-label={label}
      />
    </label>
  );
}

function Waveform({
  seed,
  compact = false,
}: {
  seed: string;
  compact?: boolean;
}) {
  const offset = [...seed].reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return (
    <svg
      viewBox="0 0 100 24"
      preserveAspectRatio="none"
      aria-hidden="true"
      className={`waveform ${compact ? "compact" : ""}`}
    >
      {Array.from({ length: 32 }, (_, index) => {
        const height =
          3 +
          Math.abs(Math.sin(index * 2.71 + offset)) *
            (18 - Math.abs(index - 12) * 0.42);
        return (
          <rect
            key={index}
            x={index * 3.125}
            y={(24 - height) / 2}
            width={1.7}
            height={height}
            rx={0.7}
          />
        );
      })}
    </svg>
  );
}

export default function App() {
  const [config, setConfig] = useState<Configuration | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const projectRef = useRef<Project | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cueId, setCueId] = useState<string | null>(null);
  const [actionKind, setActionKind] = useState<Kind>("footstep");
  const [modal, setModal] = useState<ModalName>(null);
  const [busy, setBusy] = useState("Opening the studio");
  const busyRef = useRef(true);
  const [toast, setToast] = useState<Toast | null>(null);
  const [brief, setBrief] = useState("");
  const [name, setName] = useState("");
  const [instruction, setInstruction] = useState("");
  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  const [advanced, setAdvanced] = useState(false);
  const [previewExpanded, setPreviewExpanded] = useState(false);
  const [demoScene, setDemoScene] = useState<"coffee" | "style">("style");
  const [shareFile, setShareFile] = useState<File | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [solo, setSolo] = useState<string | null>(null);
  const [volume, setVolume] = useState(0.8);
  const [previewMuted, setPreviewMuted] = useState(false);
  const [overlays, setOverlays] = useState(false);
  const [binding, setBinding] = useState<Binding | null>(null);
  const [drawStart, setDrawStart] = useState<{ x: number; y: number } | null>(
    null,
  );
  const [drawBox, setDrawBox] = useState<Box | null>(null);
  const [levels, setLevels] = useState<Record<string, number>>({});
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [sampleFilter, setSampleFilter] = useState("");
  const [sampleKind, setSampleKind] = useState<Kind>("footstep");
  const [auditionId, setAuditionId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [recordMode, setRecordMode] = useState<"sound" | "voice" | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [recordName, setRecordName] = useState("Desk tap");
  const [permissionPending, setPermissionPending] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const surroundRef = useRef<HTMLDivElement>(null);
  const [previewWidth, setPreviewWidth] = useState(640);
  const uploadRef = useRef<HTMLInputElement>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const soundRef = useRef<HTMLInputElement>(null);
  const auditionRef = useRef<HTMLAudioElement | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const discardRecording = useRef(false);
  const chatLogRef = useRef<HTMLDivElement>(null);
  const attachmentRef = useRef<HTMLDetailsElement>(null);
  const pendingSeekRef = useRef<number | null>(null);
  const engine = useMemo(() => new PreviewEngine(), []);

  const selected = project?.objects.find((item) => item.id === selectedId);
  const cue = project?.cues.find((item) => item.id === cueId);
  const scopeKind = cue?.kind ?? actionKind;
  const aspectRatio = project
    ? project.media.width / project.media.height
    : null;
  const disabled = Boolean(busy) || recording || permissionPending;

  const notify = useCallback((text: string, error = false) => {
    setToast({ text, error });
  }, []);

  const say = useCallback(
    (
      role: ChatMessage["role"],
      text: string,
      scope?: string,
      assetId?: string,
    ) => {
      setConversation((current) => [
        ...current.slice(-39),
        {
          id: crypto.randomUUID(),
          role,
          text: text.slice(0, 2000),
          scope,
          assetId,
        },
      ]);
    },
    [],
  );

  const pause = useCallback(() => {
    videoRef.current?.pause();
    engine.stop();
    setPlaying(false);
  }, [engine]);

  const accept = useCallback(
    (scene: Project) => {
      const changed = projectRef.current?.id !== scene.id;
      if (changed) pendingSeekRef.current = 0;
      else if (projectRef.current?.preview_id !== scene.preview_id)
        pendingSeekRef.current = videoRef.current?.currentTime ?? 0;
      if (changed || projectRef.current?.revision !== scene.revision)
        setShareFile(null);
      projectRef.current = scene;
      setProject(scene);
      setSelectedId((id) =>
        scene.objects.some((item) => item.id === id)
          ? id
          : (scene.objects[0]?.id ?? null),
      );
      setCueId((id) => (scene.cues.some((item) => item.id === id) ? id : null));
      setBinding(null);
      setDrawBox(null);
      if (changed) {
        pause();
        setConversation(conversationFor(scene));
        setInstruction("");
        setAdvanced(false);
        setPreviewExpanded(false);
        setOverlays(false);
        setTime(0);
        setSolo(null);
        setCueId(null);
        setSelectedId(scene.objects[0]?.id ?? null);
        setActionKind(
          scene.cues.find((item) => item.object_id === scene.objects[0]?.id)
            ?.kind ?? "movement",
        );
        setExportResult(null);
      }
      setProjects((current) => [
        {
          id: scene.id,
          name: scene.name,
          updated_at: scene.updated_at,
          duration: scene.media.duration,
          objects: scene.objects.length,
          cues: scene.cues.length,
        },
        ...current.filter((item) => item.id !== scene.id),
      ]);
    },
    [pause],
  );

  const run = useCallback(
    async <T,>(
      label: string,
      work: () => Promise<T>,
      done: (result: T) => void,
      failed?: (message: string) => void,
    ) => {
      if (busyRef.current) return;
      busyRef.current = true;
      pause();
      setBusy(label);
      try {
        done(await work());
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Something went wrong.";
        notify(message, true);
        failed?.(message);
        if (error instanceof ApiError && error.status === 409) {
          const current = projectRef.current;
          if (current) {
            try {
              accept(await api<Project>(`/api/projects/${current.id}`));
            } catch {
              // Keep the last visible scene if storage is temporarily unavailable.
            }
          }
        }
      } finally {
        busyRef.current = false;
        setBusy("");
      }
    },
    [accept, notify, pause],
  );

  const mutate = useCallback(
    (suffix: string, body: object, method = "POST", message?: string) => {
      const current = projectRef.current;
      if (!current) return;
      return run(
        "Saving your direction",
        () =>
          api<Project>(`/api/projects/${current.id}${suffix}`, {
            method,
            body: JSON.stringify({ revision: current.revision, ...body }),
          }),
        (scene) => {
          accept(scene);
          if (message) {
            notify(message);
            say("assistant", message);
          }
        },
      );
    },
    [accept, notify, run, say],
  );

  const edit = useCallback(
    (operations: Operation[], message?: string) => {
      if (!selectedId) return;
      return mutate(
        "/edit",
        { object_id: selectedId, cue_id: cueId, operations },
        "POST",
        message,
      );
    },
    [cueId, mutate, selectedId],
  );

  useEffect(() => {
    let active = true;
    async function open() {
      try {
        const configuration = await api<Configuration>("/api/config");
        const [library, scenes] = await Promise.all([
          api<Sample[]>("/api/samples"),
          api<ProjectSummary[]>("/api/projects"),
        ]);
        if (!active) return;
        setConfig(configuration);
        setSamples(library);
        setProjects(scenes);
        if (scenes.length) {
          const scene = await api<Project>(`/api/projects/${scenes[0].id}`);
          if (active && !isLegacyDemo(scene)) accept(scene);
          else if (active)
            notify(
              "Your earlier demo is still in Your reels. Try the new real-footage scenes below.",
            );
        }
      } catch (error) {
        if (active)
          notify(
            error instanceof Error
              ? error.message
              : "The studio is unavailable.",
            true,
          );
      } finally {
        if (active) {
          busyRef.current = false;
          setBusy("");
        }
      }
    }
    void open();
    return () => {
      active = false;
    };
  }, [accept, notify]);

  useEffect(() => {
    setBrief(project?.brief ?? "");
    setName(project?.name ?? "");
  }, [project?.brief, project?.name, project?.id]);

  useEffect(() => {
    if (!project?.id || !conversation.length) return;
    try {
      localStorage.setItem(
        `foleygraph-chat:${project.id}`,
        JSON.stringify(conversation),
      );
    } catch {
      // Saving the scene does not depend on browser conversation storage.
    }
  }, [conversation, project?.id]);

  useEffect(() => {
    const log = chatLogRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [conversation, busy]);

  useEffect(() => {
    const update = () => {
      document.documentElement.style.setProperty(
        "--app-height",
        `${window.visualViewport?.height ?? window.innerHeight}px`,
      );
      if (document.activeElement?.id === "direction-text")
        requestAnimationFrame(() => {
          const log = chatLogRef.current;
          if (log) log.scrollTop = log.scrollHeight;
        });
    };
    update();
    window.addEventListener("resize", update);
    window.visualViewport?.addEventListener("resize", update);
    return () => {
      window.removeEventListener("resize", update);
      window.visualViewport?.removeEventListener("resize", update);
    };
  }, []);

  useEffect(() => {
    if (!toast || toast.error) return;
    const timeout = window.setTimeout(() => setToast(null), 6500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  useEffect(() => {
    engine.setVolume(previewMuted ? 0 : volume);
  }, [engine, previewMuted, volume]);

  useEffect(() => {
    const element = surroundRef.current;
    if (!element || !aspectRatio) return;
    const observer = new ResizeObserver(([entry]) => {
      setPreviewWidth(
        Math.min(
          entry.contentRect.width,
          entry.contentRect.height * aspectRatio,
        ),
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [project?.id, aspectRatio]);

  useEffect(() => {
    if (!playing) {
      setLevels({});
      return;
    }
    let frame = 0;
    let last = 0;
    function tick(timestamp: number) {
      if (videoRef.current) setTime(videoRef.current.currentTime);
      if (timestamp - last > 80) {
        setLevels(engine.levels());
        last = timestamp;
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [engine, playing]);

  useEffect(
    () => () => {
      engine.close();
      auditionRef.current?.pause();
      discardRecording.current = true;
      if (recorderRef.current?.state === "recording")
        recorderRef.current.stop();
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    },
    [engine],
  );

  const seek = useCallback(
    (position: number) => {
      pause();
      const end = projectRef.current?.media.duration ?? 0;
      const next = Math.max(0, Math.min(end, position));
      if (videoRef.current) videoRef.current.currentTime = next;
      setTime(next);
    },
    [pause],
  );

  const togglePlay = useCallback(async () => {
    if (busyRef.current) return;
    const video = videoRef.current;
    const scene = projectRef.current;
    if (!video || !scene) return;
    if (!video.paused) {
      pause();
      return;
    }
    try {
      if (video.currentTime >= scene.media.duration - 0.02)
        video.currentTime = 0;
      await engine.prepare(scene);
      await engine.start(
        scene,
        video.currentTime,
        solo,
        previewMuted ? 0 : volume,
      );
      await video.play();
      setPlaying(true);
    } catch (error) {
      pause();
      notify(
        error instanceof Error
          ? error.message
          : "Playback is unavailable in this browser.",
        true,
      );
    }
  }, [engine, notify, pause, previewMuted, solo, volume]);

  const undo = useCallback(() => {
    if (projectRef.current?.undo_revisions.length)
      void mutate("/undo", {}, "POST", "Last edit undone.");
  }, [mutate]);

  const deleteCue = useCallback(() => {
    if (cueId)
      void mutate(
        `/cues/${cueId}`,
        {},
        "DELETE",
        "Cue removed. Undo brings it back.",
      );
  }, [cueId, mutate]);

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      const target = event.target as HTMLElement;
      if (
        target.closest("input,textarea,select") ||
        modal ||
        recordMode ||
        busyRef.current
      )
        return;
      if (event.code === "Space" && !target.closest("button")) {
        event.preventDefault();
        void togglePlay();
      } else if ((event.metaKey || event.ctrlKey) && event.key === "z") {
        event.preventDefault();
        undo();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        seek(
          (videoRef.current?.currentTime ?? 0) +
            (event.key === "ArrowLeft" ? -1 : 1) /
              (projectRef.current?.media.fps ?? 24),
        );
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteCue();
      } else if (event.key === "Escape") {
        setBinding(null);
        setDrawBox(null);
      }
    }
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [deleteCue, modal, recordMode, seek, togglePlay, undo]);

  function uploadVideo(file: File) {
    const form = new FormData();
    form.append("file", file);
    void run(
      "Preparing your silent scene",
      () => api<Project>("/api/projects", { method: "POST", body: form }),
      (scene) => {
        accept(scene);
        setModal(null);
        notify("Clip ready. Tell me the feeling you're going for.");
      },
    );
  }

  function importProject(file: File) {
    const form = new FormData();
    form.append("file", file);
    void run(
      "Restoring your editable scene",
      () =>
        api<Project>("/api/projects/import", { method: "POST", body: form }),
      (scene) => {
        accept(scene);
        setModal(null);
        notify("Scene restored with its tracks, cues, and recordings.");
      },
    );
  }

  function uploadSound(file: File) {
    const current = projectRef.current;
    if (!current) return;
    const form = new FormData();
    form.append("file", file);
    form.append("revision", String(current.revision));
    void run(
      "Preparing your sound",
      () =>
        api<Project>(`/api/projects/${current.id}/assets`, {
          method: "POST",
          body: form,
        }),
      (scene) => {
        accept(scene);
        setRecordMode(null);
        const asset = scene.assets.at(-1);
        say(
          "assistant",
          "Your sound is ready. Use it as a replacement, or tell me how you'd like it used.",
          "Your recording",
          asset?.id,
        );
      },
    );
  }

  function createDemo(scene: "coffee" | "style" = "coffee") {
    void run(
      scene === "style"
        ? "Opening your street-style reel"
        : "Opening your coffee reel",
      () =>
        api<Project>(
          scene === "style" ? "/api/demo?scene=style" : "/api/demo",
          {
            method: "POST",
          },
        ),
      (scene) => {
        accept(scene);
        setModal(null);
      },
    );
  }

  function analyze(direction = brief, fromChat = false) {
    if (!project || !direction.trim() || busyRef.current) return;
    if (
      project.cues.length &&
      !window.confirm(
        "Generate a new proposal? This replaces the current objects and cues. You can undo it.",
      )
    )
      return;
    const current = project;
    if (fromChat) say("user", direction, "First sound pass");
    void run(
      "Finding the sounds in your scene",
      () =>
        api<Project>(`/api/projects/${current.id}/analyze`, {
          method: "POST",
          body: JSON.stringify({
            revision: current.revision,
            brief: direction,
          }),
        }),
      (scene) => {
        accept(scene);
        setCueId(null);
        setInstruction("");
        setSelectedId(scene.objects[0]?.id ?? null);
        setActionKind(
          scene.cues.find((item) => item.object_id === scene.objects[0]?.id)
            ?.kind ?? "movement",
        );
        say(
          "assistant",
          scene.objects.length
            ? `I've suggested ${scene.objects.length} sound layer${scene.objects.length === 1 ? "" : "s"}. Press play, then pick a sound and tell me what to change. Timing is a first pass; you can always fine-tune it.`
            : "I couldn't confidently identify actions in this shot. Try telling me which moment to focus on.",
        );
      },
      (message) =>
        say("assistant", `I couldn't prepare that sound pass. ${message}`),
    );
  }

  function sendDirection(suggestion?: string) {
    const direction = (suggestion ?? instruction).trim();
    if (!project || !direction || busyRef.current || !config?.ai_available)
      return;
    if (
      /^undo(?: (?:that|(?:the )?last (?:edit|change)))?[.!]?$/i.test(direction)
    ) {
      say("user", direction);
      setInstruction("");
      if (!project.undo_revisions.length) {
        say(
          "assistant",
          "Nothing to undo yet. Your reel is still as you found it.",
        );
        return;
      }
      const current = project;
      void run(
        "Bringing back your previous edit",
        () =>
          api<Project>(`/api/projects/${current.id}/undo`, {
            method: "POST",
            body: JSON.stringify({ revision: current.revision }),
          }),
        (scene) => {
          accept(scene);
          say("assistant", "Done. Your last change is undone.");
        },
        (message) =>
          say("assistant", `I couldn't undo that change. ${message}`),
      );
      return;
    }
    const current = project;
    const scope =
      advanced && selected
        ? cue
          ? `${selected.name} / one action`
          : selected.name
        : undefined;
    say("user", direction, scope);
    void run(
      "Making your edit. This can take a few minutes.",
      () =>
        api<{ project: Project; message: string }>(
          `/api/projects/${current.id}/direct`,
          {
            method: "POST",
            headers: { Prefer: "respond-async" },
            body: JSON.stringify({
              revision: current.revision,
              object_id: advanced ? selected?.id : null,
              cue_id: advanced ? cueId : null,
              instruction: direction,
              history: conversation
                .slice(-12)
                .map(({ role, text }) => ({ role, text })),
            }),
          },
        ),
      (result) => {
        accept(result.project);
        setInstruction("");
        say("assistant", result.message, scope);
      },
      (message) =>
        say("assistant", `I couldn't make that change. ${message}`, scope),
    );
  }

  function renderExport() {
    if (!project) return;
    const current = project;
    setModal("export");
    void run(
      "Getting your reel ready to share",
      async () => {
        const result = await api<ExportResult>(
          `/api/projects/${current.id}/exports`,
          {
            method: "POST",
            body: JSON.stringify({ revision: current.revision }),
          },
        );
        const response = await fetch(result.video_url, {
          credentials: "same-origin",
        });
        if (!response.ok)
          throw new Error("Your video could not be loaded. Please try again.");
        const slug = current.name.replace(/[^a-zA-Z0-9_-]+/g, "-") || "my-reel";
        const file = new File([await response.blob()], `${slug}.mp4`, {
          type: "video/mp4",
        });
        return { result, file };
      },
      ({ result, file }) => {
        setExportResult(result);
        setShareFile(file);
      },
    );
  }

  function canShareVideo() {
    if (!shareFile || !navigator.share || !navigator.canShare) return false;
    try {
      return navigator.canShare({ files: [shareFile] });
    } catch {
      return false;
    }
  }

  function shareVideo(platform: "Instagram" | "WhatsApp") {
    if (
      !shareFile ||
      !canShareVideo() ||
      exportResult?.revision !== project?.revision
    )
      return;
    void run(
      `Choose ${platform} in your phone's share menu`,
      async () => {
        try {
          await navigator.share({ files: [shareFile], title: project?.name });
          return true;
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError")
            return false;
          throw new Error(
            "Your phone couldn't share this video. Save the MP4 and attach it in the app instead.",
          );
        }
      },
      (shared) => {
        if (shared) setModal(null);
      },
    );
  }

  function audition(url: string, id: string) {
    auditionRef.current?.pause();
    if (auditionId === id) {
      setAuditionId(null);
      return;
    }
    const audio = new Audio(url);
    auditionRef.current = audio;
    audio.volume = 0.7;
    audio.onended = () => setAuditionId(null);
    setAuditionId(id);
    void audio.play().catch(() => {
      setAuditionId(null);
      notify("This sound could not be played.", true);
    });
  }

  function selectObject(id: string) {
    setSelectedId(id);
    setCueId(null);
    setActionKind(
      project?.cues.find((item) => item.object_id === id)?.kind ?? "movement",
    );
  }

  function selectCue(item: Cue) {
    setSelectedId(item.object_id);
    setCueId(item.id);
    setActionKind(item.kind);
    seek(item.time);
  }

  function position(event: ReactPointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    };
  }

  function drawPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (!binding || disabled || !project) return;
    event.preventDefault();
    pause();
    const start = position(event);
    setDrawStart(start);
    setDrawBox(null);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function drawPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!drawStart || !project || !binding) return;
    const end = position(event);
    setDrawBox({
      time: Math.min(project.media.duration, time),
      x: Math.min(drawStart.x, end.x),
      y: Math.min(drawStart.y, end.y),
      width: Math.abs(end.x - drawStart.x),
      height: Math.abs(end.y - drawStart.y),
      visible: true,
    });
  }

  function drawPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (!binding || !drawStart || !project) return;
    const end = position(event);
    const x = Math.min(drawStart.x, end.x);
    const y = Math.min(drawStart.y, end.y);
    const box: Box = {
      time: Math.min(
        project.media.duration,
        Math.round(time * project.media.fps) / project.media.fps,
      ),
      x: Math.min(x, 0.98),
      y: Math.min(y, 0.98),
      width: Math.min(
        1 - Math.min(x, 0.98),
        Math.max(0.02, Math.abs(end.x - drawStart.x)),
      ),
      height: Math.min(
        1 - Math.min(y, 0.98),
        Math.max(0.02, Math.abs(end.y - drawStart.y)),
      ),
      visible: true,
    };
    const target = binding.objectId;
    setDrawStart(null);
    setDrawBox(null);
    setBinding(null);
    if (target) {
      void mutate(
        `/objects/${target}`,
        { keyframe: box },
        "PATCH",
        "Tracking corrected at this frame.",
      );
    } else {
      void mutate(
        "/objects",
        { name: `Object ${project.objects.length + 1}`, box, profile: "wood" },
        "POST",
        "Object bound. Add a cue at a visible action, not for its presence alone.",
      );
    }
  }

  async function startRecording() {
    if (!recordMode || permissionPending) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      notify(
        "Microphone recording needs HTTPS and a supported browser. You can import an audio file instead.",
        true,
      );
      return;
    }
    setPermissionPending(true);
    discardRecording.current = false;
    const mode = recordMode;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: mode === "voice",
          noiseSuppression: mode === "voice",
          autoGainControl: mode === "voice",
        },
      });
      if (discardRecording.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      const mimeType = ["audio/webm;codecs=opus", "audio/mp4"].find((type) =>
        MediaRecorder.isTypeSupported(type),
      );
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      const chunks: Blob[] = [];
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        if (discardRecording.current) return;
        const blob = new Blob(chunks, { type: recorder.mimeType });
        const file = new File(
          [blob],
          `${mode === "sound" ? recordName || "My sound" : "direction"}.${recorder.mimeType.includes("mp4") ? "m4a" : "webm"}`,
          { type: recorder.mimeType },
        );
        if (mode === "sound") {
          uploadSound(file);
        } else {
          const form = new FormData();
          form.append("file", file);
          void run(
            "Listening to your direction",
            () =>
              api<{ text: string }>("/api/transcribe", {
                method: "POST",
                body: form,
              }),
            (result) => {
              setInstruction(result.text);
              setRecordMode(null);
              notify("Direction transcribed. Review it, then send.");
            },
          );
        }
      };
      recorder.start();
      setRecordSeconds(0);
      setRecording(true);
      const started = Date.now();
      const timer = window.setInterval(() => {
        const elapsed = (Date.now() - started) / 1000;
        setRecordSeconds(elapsed);
        if (elapsed >= (mode === "sound" ? 4.8 : 29)) {
          window.clearInterval(timer);
          if (recorder.state === "recording") recorder.stop();
        } else if (recorder.state !== "recording") {
          window.clearInterval(timer);
        }
      }, 100);
    } catch {
      notify(
        "Microphone access was not available. Allow access in your browser, or import a sound file.",
        true,
      );
    } finally {
      setPermissionPending(false);
    }
  }

  function closeRecorder() {
    discardRecording.current = true;
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    setRecording(false);
    setRecordMode(null);
  }

  function toggleAdvanced() {
    setAdvanced(!advanced);
    setPreviewExpanded(false);
    setOverlays(false);
    setBinding(null);
    setDrawBox(null);
    setSolo(null);
    setPreviewMuted(false);
    setVolume(0.8);
    setModal(null);
  }

  function addCue() {
    if (!selected) return;
    void mutate("/cues", {
      object_id: selected.id,
      kind: actionKind,
      time: videoRef.current?.currentTime ?? time,
    });
  }

  function shift(frames: number) {
    void edit(
      [{ type: "shift", frames }],
      `${Math.abs(frames)} frame ${frames < 0 ? "earlier" : "later"}.`,
    );
  }

  const representative =
    cue ??
    project?.cues.find(
      (item) => item.object_id === selectedId && item.kind === scopeKind,
    );
  const selectedAssetId =
    representative?.asset_id ??
    selected?.sound_overrides[scopeKind] ??
    `${selected?.profile ?? "wood"}-${scopeKind}`;
  const selectedRecording = project?.assets.find(
    (asset) => asset.id === selectedAssetId,
  );
  const selectedMaterial = selectedRecording
    ? "custom"
    : selectedAssetId.split("-")[0];
  const filteredSamples = samples.filter(
    (sample) =>
      sample.kind === sampleKind &&
      sample.name.toLowerCase().includes(sampleFilter.toLowerCase()),
  );

  return (
    <div className="app-shell">
      <input
        ref={uploadRef}
        type="file"
        accept="video/*"
        hidden
        aria-label="Upload video file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) uploadVideo(file);
          event.target.value = "";
        }}
      />
      <input
        ref={importRef}
        type="file"
        accept=".zip,application/zip"
        hidden
        aria-label="Import project bundle"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) importProject(file);
          event.target.value = "";
        }}
      />
      <input
        ref={soundRef}
        type="file"
        accept="audio/*"
        hidden
        aria-label="Import audio file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) uploadSound(file);
          event.target.value = "";
        }}
      />

      <header className={`topbar ${project ? "editing-reel" : ""}`}>
        <a
          href="/"
          className="brand"
          aria-label={project ? "Your reels" : "FoleyGraph home"}
          onClick={(event) => {
            if (project) {
              event.preventDefault();
              setModal("projects");
            }
          }}
        >
          <span className="brand-icon">
            <AudioLines size={23} strokeWidth={2.2} />
          </span>
          <span>
            foley<span className="brand-light">graph</span>
            <sup>STUDIO</sup>
          </span>
        </a>
        {project && (
          <span className="mobile-reel-title" aria-label="Current reel">
            {project.name}
          </span>
        )}
        <div className="topbar-middle">Your idea. A reel worth replaying.</div>
        <nav className="topbar-actions">
          {!project && (
            <button
              className="button ghost"
              aria-label="Your reels"
              onClick={() => setModal("projects")}
              disabled={disabled}
            >
              <FolderOpen size={16} />
              <span>Your reels</span>
              <span className="count">{projects.length}</span>
            </button>
          )}
          {project && (
            <>
              <button
                className="button primary"
                disabled={disabled}
                onClick={() => {
                  setModal("export");
                  if (exportResult?.revision !== project.revision || !shareFile)
                    renderExport();
                }}
              >
                <Share2 size={16} />
                Share reel
              </button>
              <IconButton
                label="More reel options"
                disabled={disabled}
                onClick={() => setModal("options")}
              >
                <Ellipsis size={21} />
              </IconButton>
            </>
          )}
        </nav>
      </header>

      {!project ? (
        <main className="welcome">
          <div className="welcome-copy">
            <span className="eyebrow">
              <span className="live-dot" /> YOUR VIDEO. A WHOLE NEW FEELING.
            </span>
            <h1>
              A little direction.
              <br />
              <span>A reel worth replaying.</span>
            </h1>
            <p className="welcome-description">
              Bring a clip. Tell us how it should feel.
              <br />
              Change its look and sound, without the maze of controls.
            </p>
            <div
              className="demo-scene-tabs"
              role="group"
              aria-label="Choose real stock footage"
            >
              <button
                type="button"
                aria-pressed={demoScene === "style"}
                disabled={disabled}
                onClick={() => setDemoScene("style")}
              >
                People &amp; style
              </button>
              <button
                type="button"
                aria-pressed={demoScene === "coffee"}
                disabled={disabled}
                onClick={() => setDemoScene("coffee")}
              >
                Coffee ritual
              </button>
            </div>
            <div className="welcome-buttons">
              <button
                className="button outline large"
                disabled={disabled}
                onClick={() => uploadRef.current?.click()}
              >
                <Upload size={19} />
                Upload your clip
              </button>
              <button
                className="button primary large"
                disabled={disabled}
                onClick={() => createDemo(demoScene)}
              >
                <Play size={17} />
                Try the demo
              </button>
            </div>
            <p className="muted small">
              Remix real stock footage. Or bring your own clip, up to 20
              seconds.
            </p>
            <button
              className="text-button import-link"
              disabled={disabled}
              onClick={() => importRef.current?.click()}
            >
              <FileArchive size={15} />
              Or reopen an editable scene bundle
              <ArrowRight size={14} />
            </button>
            <p className="welcome-promise">
              Made for Instagram reels and WhatsApp status. No editing
              experience needed.
            </p>
          </div>
          <div
            className={`welcome-art ${dragging ? "dragging" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              const file = event.dataTransfer.files[0];
              if (!file || disabled) return;
              if (file.name.toLowerCase().endsWith(".zip")) importProject(file);
              else uploadVideo(file);
            }}
          >
            <img
              className="reel-cover"
              src={
                demoScene === "style" ? "/style-poster.jpg" : "/demo-poster.jpg"
              }
              alt={
                demoScene === "style"
                  ? "Two real people outdoors in a licensed street-style stock video."
                  : "A real cafe pour, framed as a portrait reel."
              }
            />
            <span className="reel-badge">
              {demoScene === "style"
                ? "THE STYLE REMIX / 6 SECONDS"
                : "THE COFFEE REEL / 8 SECONDS"}
            </span>
            <div className="floating-cue">
              <MessageCircle size={23} />
              <div>
                <strong>
                  {demoScene === "style"
                    ? "A new outfit. A new mood."
                    : "A softer pour. Ambient music."}
                </strong>
                <span>A few words. A whole different feeling.</span>
              </div>
              <Check size={16} />
            </div>
            <span className="art-caption">
              {dragging
                ? "Drop your clip here"
                : "REAL FOOTAGE. YOUR CREATIVE DIRECTION."}
            </span>
          </div>
          <div className="welcome-bottom">
            <span>
              <ShieldCheck size={14} /> Licensed footage. Original sound design.
            </span>
            <span>
              <Sparkles size={14} /> Directed with Azure OpenAI
            </span>
          </div>
        </main>
      ) : (
        <main
          className={`workspace ${advanced ? "advanced-open" : ""} ${previewExpanded ? "preview-expanded" : ""}`}
          style={
            {
              "--reel-aspect-inverse":
                project.media.height / project.media.width,
            } as CSSProperties
          }
        >
          <section className="workspace-heading">
            <div>
              <div className="breadcrumb">YOUR REEL</div>
              <div className="scene-title-row">
                <input
                  className="scene-title"
                  aria-label="Scene name"
                  value={name}
                  maxLength={100}
                  onChange={(event) => setName(event.target.value)}
                  disabled={disabled}
                  onBlur={() => {
                    if (name.trim() && name.trim() !== project.name)
                      void mutate("", { name: name.trim() }, "PATCH");
                    else setName(project.name);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                  }}
                />
                <span className="saved-status">
                  <span className="live-dot" />
                  {busy ? "Working" : "All changes saved"}
                </span>
              </div>
            </div>
            {advanced && (
              <div className="workspace-tools">
                {project.undo_revisions.length > 0 && (
                  <IconButton
                    label="Undo last edit"
                    disabled={disabled}
                    onClick={undo}
                  >
                    <RotateCcw size={17} />
                  </IconButton>
                )}
                <button
                  className="button ghost fine-tune-toggle"
                  aria-expanded={advanced}
                  aria-controls="fine-tune-tools"
                  onClick={toggleAdvanced}
                >
                  <SlidersHorizontal size={15} />
                  Back to chat
                </button>
              </div>
            )}
          </section>

          <div className="studio-grid">
            <aside
              id="fine-tune-tools"
              className="objects-panel panel"
              hidden={!advanced}
            >
              <div className="panel-heading">
                <span>SCENE OBJECTS</span>
                <span className="count">{project.objects.length} / 3</span>
              </div>
              <p className="panel-intro">Real moments. Their own sound.</p>
              <div className="object-list">
                {project.objects.map((object, index) => {
                  const objectCues = project.cues.filter(
                    (item) => item.object_id === object.id,
                  );
                  return (
                    <div
                      className={`object-card ${selectedId === object.id ? "selected" : ""}`}
                      key={object.id}
                      style={{ "--track-color": object.color } as CSSProperties}
                    >
                      <button
                        className="object-select"
                        onClick={() => selectObject(object.id)}
                        aria-pressed={selectedId === object.id}
                      >
                        <span className="object-avatar">
                          {index < 2 ? (
                            <BoxIcon size={20} />
                          ) : (
                            <Radio size={20} />
                          )}
                        </span>
                        <span className="object-info">
                          <strong>{object.name}</strong>
                          <span>
                            {objectCues.length} cues
                            <span className="mid-dot">/</span>
                            {
                              config?.profiles.find(
                                (item) => item.id === object.profile,
                              )?.name
                            }
                          </span>
                        </span>
                        {selectedId === object.id && (
                          <span className="selected-dot" />
                        )}
                      </button>
                      <div className="object-card-footer">
                        <span className="mini-meter">
                          <span
                            style={{
                              width: `${(levels[object.id] ?? 0) * 100}%`,
                            }}
                          />
                        </span>
                        <button
                          className={`track-toggle ${object.muted ? "active" : ""}`}
                          aria-label={`Mute ${object.name}`}
                          aria-pressed={object.muted}
                          disabled={disabled}
                          onClick={() =>
                            void mutate(
                              `/objects/${object.id}`,
                              { muted: !object.muted },
                              "PATCH",
                            )
                          }
                        >
                          M
                        </button>
                        <button
                          className={`track-toggle ${solo === object.id ? "solo" : ""}`}
                          aria-label={`Solo ${object.name}`}
                          aria-pressed={solo === object.id}
                          disabled={disabled}
                          onClick={() => {
                            pause();
                            setSolo(solo === object.id ? null : object.id);
                          }}
                        >
                          S
                        </button>
                        <span className="object-track-label">
                          {solo === object.id
                            ? "PREVIEW SOLO"
                            : `LAYER ${String(index + 1).padStart(2, "0")}`}
                        </span>
                      </div>
                    </div>
                  );
                })}
                {!project.objects.length && (
                  <div className="objects-empty">
                    <Scan size={25} />
                    <p>A cast of zero, for now.</p>
                    <span>
                      Analyze the clip or draw a box around your first
                      character.
                    </span>
                  </div>
                )}
              </div>
              <button
                className={`button bind-button ${binding && !binding.objectId ? "binding-active" : ""}`}
                disabled={disabled || project.objects.length >= 3}
                onClick={() => {
                  pause();
                  setBinding(binding ? null : { objectId: null });
                  setOverlays(true);
                  surroundRef.current?.scrollIntoView({ block: "center" });
                }}
              >
                <Plus size={15} />
                Bind an object
              </button>
              <p className="tiny muted object-tip">
                <MousePointer2 size={13} />
                Click a box in the scene to select its sounds.
              </p>

              <div className="creative-brief">
                <div className="panel-heading">
                  <span>THE CREATIVE DIRECTION</span>
                  <Sparkles size={14} />
                </div>
                <textarea
                  aria-label="Creative brief"
                  value={brief}
                  onChange={(event) => setBrief(event.target.value)}
                  maxLength={1200}
                  disabled={disabled}
                  rows={3}
                />
                <button
                  className="button analyze-button"
                  disabled={disabled || !brief.trim() || !config?.ai_available}
                  onClick={() => analyze()}
                >
                  <WandSparkles size={15} />
                  Analyze scene
                  <ArrowRight size={14} />
                </button>
                <p className="tiny muted">
                  {config?.ai_available
                    ? "Foundry proposes. You have the final say."
                    : "Manual mode. Foundry is not configured."}
                </p>
              </div>
            </aside>

            <section className="preview-panel panel">
              <div className="panel-heading preview-heading">
                <span>YOUR REEL</span>
                <div className="preview-heading-actions">
                  <span className="reel-format">
                    {project.media.width < project.media.height
                      ? "PORTRAIT"
                      : "ORIGINAL FORMAT"}
                    {" / "}
                    {project.media.duration.toFixed(0)}s
                  </span>
                  {advanced && (
                    <>
                      <IconButton
                        label={
                          overlays
                            ? "Hide tracking boxes"
                            : "Show tracking boxes"
                        }
                        onClick={() => setOverlays(!overlays)}
                      >
                        {overlays ? <Eye size={15} /> : <EyeOff size={15} />}
                      </IconButton>
                      <IconButton
                        label="Fullscreen preview"
                        onClick={() =>
                          void videoRef.current?.requestFullscreen()
                        }
                      >
                        <Maximize size={14} />
                      </IconButton>
                    </>
                  )}
                </div>
              </div>
              <div
                className="video-surround"
                id="reel-preview"
                ref={surroundRef}
              >
                <div
                  className={`video-stage ${binding ? "is-binding" : ""}`}
                  style={{
                    aspectRatio: project.media.width / project.media.height,
                    width: previewWidth,
                    maxWidth: "100%",
                  }}
                  onPointerDown={drawPointerDown}
                  onPointerMove={drawPointerMove}
                  onPointerUp={drawPointerUp}
                >
                  <video
                    ref={videoRef}
                    key={project.id}
                    src={videoUrl(project)}
                    poster={`/api/projects/${project.id}/poster.jpg?v=${project.preview_id ?? "source"}`}
                    preload="auto"
                    muted
                    playsInline
                    onLoadedMetadata={() => {
                      const video = videoRef.current;
                      if (video && pendingSeekRef.current !== null) {
                        video.currentTime = Math.min(
                          pendingSeekRef.current,
                          Math.max(0, video.duration - 0.01),
                        );
                        setTime(video.currentTime);
                        pendingSeekRef.current = null;
                      }
                    }}
                    onEnded={() => {
                      pause();
                      setTime(project.media.duration);
                    }}
                    onTimeUpdate={() => {
                      if (!playing && pendingSeekRef.current === null)
                        setTime(videoRef.current?.currentTime ?? 0);
                    }}
                    aria-label="Scene video"
                  />
                  {overlays &&
                    project.objects.map((object) => {
                      const box = boxAt(object, time);
                      if (!box?.visible) return null;
                      return (
                        <button
                          key={object.id}
                          className={`tracking-box ${selectedId === object.id ? "is-selected" : ""}`}
                          style={
                            {
                              left: `${box.x * 100}%`,
                              top: `${box.y * 100}%`,
                              width: `${box.width * 100}%`,
                              height: `${box.height * 100}%`,
                              "--track-color": object.color,
                            } as CSSProperties
                          }
                          onClick={() => selectObject(object.id)}
                          aria-label={`Select ${object.name} in video`}
                        >
                          <span>
                            <span className="object-dot" />
                            {object.name}
                          </span>
                          <i />
                          <i />
                          <i />
                          <i />
                        </button>
                      );
                    })}
                  {binding && <div className="drawing-layer" />}
                  {drawBox && (
                    <div
                      className="draw-box"
                      style={{
                        left: `${drawBox.x * 100}%`,
                        top: `${drawBox.y * 100}%`,
                        width: `${drawBox.width * 100}%`,
                        height: `${drawBox.height * 100}%`,
                      }}
                    />
                  )}
                  {advanced && (
                    <span className="video-frame-label">
                      F{" "}
                      {String(Math.floor(time * project.media.fps)).padStart(
                        4,
                        "0",
                      )}
                    </span>
                  )}
                </div>
              </div>
              {binding ? (
                <div className="binding-hint">
                  <Scan size={15} />
                  <span>
                    Draw a box around{" "}
                    {binding.objectId
                      ? (selected?.name ?? "the object")
                      : "a character or prop"}{" "}
                    at this frame.
                  </span>
                  <button
                    className="text-button"
                    onClick={() => {
                      setBinding(null);
                      setDrawBox(null);
                    }}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="preview-caption">
                  <span>
                    <span className="live-dot" />
                    {solo
                      ? `${project.objects.find((item) => item.id === solo)?.name ?? "One layer"} solo, preview only`
                      : "Press play. Feel the difference."}
                  </span>
                </div>
              )}
              <div className="transport">
                {advanced && (
                  <IconButton
                    label="Back to beginning"
                    disabled={disabled}
                    onClick={() => seek(0)}
                  >
                    <SkipBack size={16} />
                  </IconButton>
                )}
                <button
                  className="play-button"
                  aria-label={playing ? "Pause scene" : "Play scene"}
                  disabled={disabled}
                  onClick={() => void togglePlay()}
                >
                  {playing ? (
                    <Pause size={18} fill="currentColor" />
                  ) : (
                    <Play size={18} fill="currentColor" />
                  )}
                </button>
                {advanced && (
                  <>
                    <IconButton
                      label="Previous frame"
                      disabled={disabled}
                      onClick={() => seek(time - 1 / project.media.fps)}
                    >
                      <ChevronLeft size={17} />
                    </IconButton>
                    <IconButton
                      label="Next frame"
                      disabled={disabled}
                      onClick={() => seek(time + 1 / project.media.fps)}
                    >
                      <ChevronRight size={17} />
                    </IconButton>
                  </>
                )}
                <span className="timecode">
                  {time.toFixed(1)}
                  <span> / {project.media.duration.toFixed(1)}s</span>
                </span>
                <input
                  className="transport-scrub"
                  type="range"
                  min={0}
                  max={project.media.duration}
                  step={1 / project.media.fps}
                  value={time}
                  onChange={(event) => seek(Number(event.target.value))}
                  aria-label="Playhead"
                  disabled={disabled}
                />
                {!advanced && project.media.height >= project.media.width && (
                  <IconButton
                    className="mobile-preview-toggle"
                    label={
                      previewExpanded ? "Make room for chat" : "Enlarge preview"
                    }
                    aria-expanded={previewExpanded}
                    aria-controls="reel-preview"
                    onClick={() => setPreviewExpanded(!previewExpanded)}
                  >
                    {previewExpanded ? (
                      <Minimize2 size={17} />
                    ) : (
                      <Maximize size={17} />
                    )}
                  </IconButton>
                )}
                {advanced && (
                  <IconButton
                    label={previewMuted ? "Unmute preview" : "Mute preview"}
                    onClick={() => setPreviewMuted(!previewMuted)}
                  >
                    {previewMuted ? (
                      <VolumeX size={17} />
                    ) : (
                      <Volume2 size={17} />
                    )}
                  </IconButton>
                )}
                {advanced && (
                  <input
                    className="preview-volume"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={volume}
                    aria-label="Preview volume"
                    onChange={(event) => setVolume(Number(event.target.value))}
                  />
                )}
              </div>
              {advanced && project.source_credit && (
                <p className="stock-credit">{project.source_credit}</p>
              )}
            </section>

            <section className="chat-panel" aria-label="Reel conversation">
              <div className="chat-heading">
                <span className="director-avatar">
                  <Sparkles size={20} />
                </span>
                <div>
                  <h2>Make it yours.</h2>
                  <p>You direct. The details take care of themselves.</p>
                </div>
              </div>
              <div
                className="chat-log"
                ref={chatLogRef}
                role="log"
                aria-label="Conversation"
                aria-live="polite"
              >
                {conversation.map((message) => {
                  const attached = project.assets.find(
                    (asset) => asset.id === message.assetId,
                  );
                  return (
                    <article
                      key={message.id}
                      className={`chat-message ${message.role}`}
                    >
                      <span className="message-author">
                        {message.role === "user" ? "You" : "FoleyGraph"}
                        {message.scope && <span> / {message.scope}</span>}
                      </span>
                      <p>{message.text}</p>
                      {attached && (
                        <div className="chat-attachment">
                          <IconButton
                            label={`Preview ${attached.name}`}
                            onClick={() =>
                              audition(
                                assetUrl(project, attached.id),
                                attached.id,
                              )
                            }
                          >
                            {auditionId === attached.id ? (
                              <Square size={14} />
                            ) : (
                              <Play size={14} />
                            )}
                          </IconButton>
                          <span>{attached.name}</span>
                          <button
                            className="text-button"
                            disabled={disabled || !selected}
                            onClick={() =>
                              void edit(
                                [
                                  {
                                    type: "set_sound",
                                    asset_id: attached.id,
                                    kind: scopeKind,
                                  },
                                ],
                                `${attached.name} is now ${selected?.name}'s sound. Other layers are unchanged.`,
                              )
                            }
                          >
                            Use on {selected?.name ?? "a sound"}
                          </button>
                        </div>
                      )}
                    </article>
                  );
                })}
                {busy && (
                  <div className="chat-working" role="status">
                    <LoaderCircle size={15} className="spin" />
                    {busy}
                  </div>
                )}
              </div>
              <div className="chat-composer-area">
                {advanced && project.objects.length > 0 && (
                  <div className="chat-scope">
                    <span>Editing</span>
                    <div
                      className="sound-pills"
                      role="group"
                      aria-label="Choose a sound to edit"
                    >
                      {project.objects.map((object) => (
                        <button
                          key={object.id}
                          className={selectedId === object.id ? "active" : ""}
                          aria-label={`Edit ${object.name}`}
                          aria-pressed={selectedId === object.id}
                          disabled={disabled}
                          onClick={() => selectObject(object.id)}
                          style={
                            { "--track-color": object.color } as CSSProperties
                          }
                        >
                          <span className="object-dot" />
                          {object.name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {advanced && cue && (
                  <button
                    className="selected-cue-note"
                    onClick={() => setCueId(null)}
                  >
                    One {cue.kind} at {cue.time.toFixed(2)}s <X size={12} />
                  </button>
                )}
                {config?.ai_available &&
                  !conversation.some((message) => message.role === "user") && (
                    <div
                      className="chat-suggestions"
                      aria-label="Try a direction"
                    >
                      {(project.source_credit &&
                      project.media.filename === "weekend-style.mp4" &&
                      !advanced
                        ? [
                            "Make the left outfit terracotta",
                            "Write a title and add ambient music",
                          ]
                        : project.source_credit &&
                            project.media.filename === "morning-ritual.mp4" &&
                            !advanced
                          ? [
                              "Make the coffee pour quieter",
                              "Add ambient music",
                            ]
                          : project.objects.length
                            ? ["Make it warmer", "Add ambient music"]
                            : [
                                "A warm, cinematic sound pass",
                                "Add ambient music",
                              ]
                      ).map((suggestion) => (
                        <button
                          key={suggestion}
                          disabled={disabled}
                          onClick={() => sendDirection(suggestion)}
                        >
                          {suggestion}
                          <ArrowRight size={12} />
                        </button>
                      ))}
                    </div>
                  )}
                <form
                  className="chat-composer"
                  onSubmit={(event) => {
                    event.preventDefault();
                    sendDirection();
                  }}
                >
                  <label className="sr-only" htmlFor="direction-text">
                    Edit direction
                  </label>
                  <details className="composer-attachments" ref={attachmentRef}>
                    <summary
                      aria-label="Add your own sound"
                      title="Add your own sound"
                    >
                      <Plus size={19} />
                    </summary>
                    <div className="attachment-menu">
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          attachmentRef.current?.removeAttribute("open");
                          setRecordMode("sound");
                        }}
                      >
                        <Mic size={16} />
                        Record a sound
                      </button>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          attachmentRef.current?.removeAttribute("open");
                          soundRef.current?.click();
                        }}
                      >
                        <Upload size={16} />
                        Upload a sound
                      </button>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => {
                          attachmentRef.current?.removeAttribute("open");
                          setModal("sounds");
                        }}
                      >
                        <Headphones size={16} />
                        Sound library
                      </button>
                    </div>
                  </details>
                  <textarea
                    id="direction-text"
                    aria-label="Edit direction"
                    value={instruction}
                    disabled={disabled}
                    maxLength={1200}
                    rows={1}
                    enterKeyHint="send"
                    placeholder="Tell me the vibe, or what to change..."
                    onFocus={() => setPreviewExpanded(false)}
                    onChange={(event) => setInstruction(event.target.value)}
                    onKeyDown={(event) => {
                      if (
                        event.key === "Enter" &&
                        !event.shiftKey &&
                        !event.nativeEvent.isComposing
                      ) {
                        event.preventDefault();
                        sendDirection();
                      }
                    }}
                  />
                  {config?.voice_available && !instruction.trim() ? (
                    <IconButton
                      label="Speak a direction"
                      disabled={disabled}
                      onClick={() => setRecordMode("voice")}
                    >
                      <Mic size={18} />
                    </IconButton>
                  ) : (
                    <button
                      className="send-direction"
                      type="submit"
                      aria-label="Send direction"
                      title="Send direction"
                      disabled={
                        disabled ||
                        !instruction.trim() ||
                        !config?.ai_available ||
                        (advanced && project.objects.length > 0 && !selected)
                      }
                    >
                      <Send size={17} />
                    </button>
                  )}
                </form>
                <p className="composer-note">
                  {!config?.ai_available
                    ? "AI isn't connected. Advanced tools are available in More."
                    : advanced && selected
                      ? `Only ${selected.name} changes. Everything else stays.`
                      : "Just describe it."}
                </p>
              </div>
            </section>

            <aside className="inspector-panel panel" hidden={!advanced}>
              <div className="panel-heading">
                <span>SOUND IDENTITY</span>
                <SlidersHorizontal size={14} />
              </div>
              {selected ? (
                <>
                  <div className="inspector-object">
                    <span
                      className="object-avatar"
                      style={
                        { "--track-color": selected.color } as CSSProperties
                      }
                    >
                      <BoxIcon size={22} />
                    </span>
                    <div>
                      <input
                        aria-label="Object name"
                        key={`${selected.id}-${selected.name}`}
                        defaultValue={selected.name}
                        maxLength={60}
                        disabled={disabled}
                        onBlur={(event) => {
                          const next = event.target.value.trim();
                          if (next && next !== selected.name)
                            void mutate(
                              `/objects/${selected.id}`,
                              { name: next },
                              "PATCH",
                            );
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") event.currentTarget.blur();
                        }}
                      />
                      <span>
                        {cue ? "ONE ACTION SELECTED" : "OBJECT LAYER SELECTED"}
                      </span>
                    </div>
                  </div>
                  <div className="scope-row">
                    <label htmlFor="action-scope">Apply sound to</label>
                    {cue ? (
                      <button
                        className="scope-pill"
                        onClick={() => setCueId(null)}
                        title="Click to select all actions on this object"
                      >
                        {cue.kind}
                        <X size={11} />
                      </button>
                    ) : (
                      <select
                        id="action-scope"
                        value={actionKind}
                        disabled={disabled}
                        onChange={(event) =>
                          setActionKind(event.target.value as Kind)
                        }
                      >
                        {kinds.map((kind) => (
                          <option value={kind} key={kind}>
                            {kindLabels[kind]}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  <label className="field-label" htmlFor="material">
                    THE MATERIAL
                  </label>
                  <div className="material-select">
                    <span className="material-icon">
                      <Footprints size={19} />
                    </span>
                    <select
                      id="material"
                      aria-label="Sound material"
                      value={selectedMaterial}
                      disabled={disabled}
                      onChange={(event) =>
                        void edit(
                          [
                            {
                              type: "set_sound",
                              profile: event.target.value as Profile,
                              kind: scopeKind,
                            },
                          ],
                          `${selected.name}'s ${kindLabels[scopeKind].toLowerCase()} have a new sound. Other layers are unchanged.`,
                        )
                      }
                    >
                      {selectedRecording && (
                        <option value="custom" disabled>
                          {selectedRecording.name}
                        </option>
                      )}
                      {config?.profiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.name}
                        </option>
                      ))}
                    </select>
                    <ChevronDown size={14} />
                    <IconButton
                      label="Audition current material"
                      onClick={() =>
                        audition(
                          assetUrl(project, selectedAssetId),
                          selectedAssetId,
                        )
                      }
                    >
                      {auditionId === selectedAssetId ? (
                        <Square size={13} />
                      ) : (
                        <Play size={13} />
                      )}
                    </IconButton>
                  </div>
                  <p className="isolation-note">
                    <ShieldCheck size={12} />
                    {cue
                      ? "Only this cue changes."
                      : `Only ${selected.name}'s ${kindLabels[scopeKind].toLowerCase()} change.`}
                  </p>
                  <div className="inspector-controls">
                    <Slider
                      label={cue ? "Cue gain" : "Layer gain"}
                      min={-36}
                      max={12}
                      value={cue?.gain_db ?? selected.gain_db}
                      unit=" dB"
                      disabled={disabled}
                      onCommit={(value) =>
                        cue
                          ? void mutate(
                              `/cues/${cue.id}`,
                              { gain_db: value },
                              "PATCH",
                            )
                          : void mutate(
                              `/objects/${selected.id}`,
                              { gain_db: value },
                              "PATCH",
                            )
                      }
                    />
                    {cue ? (
                      <>
                        <div className="timing-fields">
                          <label>
                            <span>Start (s)</span>
                            <input
                              aria-label="Cue start seconds"
                              key={`${cue.id}-${project.revision}-time`}
                              type="number"
                              step={1 / project.media.fps}
                              min={0}
                              max={project.media.duration - cue.duration}
                              defaultValue={cue.time.toFixed(3)}
                              disabled={disabled}
                              onBlur={(event) => {
                                const value = Number(event.target.value);
                                if (
                                  Number.isFinite(value) &&
                                  Math.abs(value - cue.time) > 0.0005
                                )
                                  void mutate(
                                    `/cues/${cue.id}`,
                                    { time: value },
                                    "PATCH",
                                  );
                              }}
                              onKeyDown={(event) => {
                                if (event.key === "Enter")
                                  event.currentTarget.blur();
                              }}
                            />
                          </label>
                          <label>
                            <span>Length (s)</span>
                            <input
                              aria-label="Cue duration seconds"
                              key={`${cue.id}-${project.revision}-duration`}
                              type="number"
                              step={0.01}
                              min={0.04}
                              max={project.media.duration - cue.time}
                              defaultValue={cue.duration.toFixed(3)}
                              disabled={disabled}
                              onBlur={(event) => {
                                const value = Number(event.target.value);
                                if (
                                  Number.isFinite(value) &&
                                  Math.abs(value - cue.duration) > 0.0005
                                )
                                  void mutate(
                                    `/cues/${cue.id}`,
                                    { duration: value },
                                    "PATCH",
                                  );
                              }}
                              onKeyDown={(event) => {
                                if (event.key === "Enter")
                                  event.currentTarget.blur();
                              }}
                            />
                          </label>
                        </div>
                        <div className="frame-buttons">
                          <button
                            className="button subtle"
                            disabled={disabled}
                            onClick={() => shift(-1)}
                          >
                            <ArrowLeft size={13} />1 frame
                          </button>
                          <button
                            className="button subtle"
                            disabled={disabled}
                            onClick={() => shift(1)}
                          >
                            1 frame
                            <ArrowRight size={13} />
                          </button>
                        </div>
                        <Slider
                          label="Playback speed"
                          value={cue.playback_rate}
                          min={0.25}
                          max={3}
                          step={0.05}
                          unit="x"
                          disabled={disabled}
                          onCommit={(value) =>
                            void mutate(
                              `/cues/${cue.id}`,
                              { playback_rate: value },
                              "PATCH",
                            )
                          }
                        />
                        <div className="scope-row pan-mode">
                          <label htmlFor="pan-mode">Stereo position</label>
                          <select
                            id="pan-mode"
                            aria-label="Stereo position"
                            disabled={disabled}
                            value={cue.pan === null ? "auto" : cue.pan}
                            onChange={(event) =>
                              void mutate(
                                `/cues/${cue.id}`,
                                {
                                  pan:
                                    event.target.value === "auto"
                                      ? null
                                      : Number(event.target.value),
                                },
                                "PATCH",
                              )
                            }
                          >
                            <option value="auto">Follow object</option>
                            <option value="-1">Left</option>
                            <option value="-0.5">Slightly left</option>
                            <option value="0">Center</option>
                            <option value="0.5">Slightly right</option>
                            <option value="1">Right</option>
                            {cue.pan !== null &&
                              ![-1, -0.5, 0, 0.5, 1].includes(cue.pan) && (
                                <option value={cue.pan}>
                                  Custom {cue.pan.toFixed(2)}
                                </option>
                              )}
                          </select>
                        </div>
                        <div className="scope-row">
                          <label htmlFor="tone">Tone</label>
                          <select
                            id="tone"
                            disabled={disabled}
                            value={cue.lowpass_hz ?? 0}
                            onChange={(event) =>
                              void mutate(
                                `/cues/${cue.id}`,
                                {
                                  lowpass_hz:
                                    Number(event.target.value) || null,
                                },
                                "PATCH",
                              )
                            }
                          >
                            <option value="0">Natural</option>
                            <option value="800">Muffled</option>
                            <option value="3000">Softened</option>
                            <option value="12000">Bright</option>
                            {cue.lowpass_hz !== null &&
                              ![800, 3000, 12000].includes(cue.lowpass_hz) && (
                                <option value={cue.lowpass_hz}>
                                  {cue.lowpass_hz} Hz
                                </option>
                              )}
                          </select>
                        </div>
                      </>
                    ) : (
                      <button
                        className="button tracking-button"
                        disabled={disabled}
                        onClick={() => {
                          pause();
                          setOverlays(true);
                          setBinding({ objectId: selected.id });
                          surroundRef.current?.scrollIntoView({
                            block: "center",
                          });
                        }}
                      >
                        <Scan size={14} />
                        Correct box at this frame
                      </button>
                    )}
                  </div>
                  <div className="your-sounds">
                    <div className="field-label">
                      SOMETHING ONLY YOU CAN MAKE
                    </div>
                    <div className="record-buttons">
                      <button
                        className="button subtle"
                        disabled={disabled}
                        onClick={() => setRecordMode("sound")}
                      >
                        <Mic size={14} />
                        Record a sound
                      </button>
                      <IconButton
                        label="Import a sound"
                        disabled={disabled}
                        onClick={() => soundRef.current?.click()}
                      >
                        <Upload size={15} />
                      </IconButton>
                    </div>
                    <p className="tiny muted">
                      Tap a mug. Crinkle paper. Give it character.
                      <br />
                      One short sound, up to 5 seconds.
                    </p>
                    {project.assets
                      .filter((asset) => asset.source === "Creator recording")
                      .map((asset) => (
                        <div className="custom-sound" key={asset.id}>
                          <IconButton
                            label={`Preview ${asset.name}`}
                            onClick={() =>
                              audition(assetUrl(project, asset.id), asset.id)
                            }
                          >
                            {auditionId === asset.id ? (
                              <Square size={12} />
                            ) : (
                              <Play size={12} />
                            )}
                          </IconButton>
                          <span title={asset.name}>{asset.name}</span>
                          <button
                            className="text-button"
                            disabled={disabled}
                            onClick={() =>
                              void edit(
                                [
                                  {
                                    type: "set_sound",
                                    asset_id: asset.id,
                                    kind: scopeKind,
                                  },
                                ],
                                `Your recording is assigned to ${selected.name}'s ${kindLabels[scopeKind].toLowerCase()}.`,
                              )
                            }
                          >
                            Use
                          </button>
                        </div>
                      ))}
                  </div>
                  <div className="inspector-bottom">
                    {cue ? (
                      <button
                        className="text-button danger"
                        disabled={disabled}
                        onClick={deleteCue}
                      >
                        <Trash2 size={12} />
                        Remove this cue
                      </button>
                    ) : (
                      <button
                        className="text-button danger"
                        disabled={disabled}
                        onClick={() => {
                          if (
                            window.confirm(
                              `Remove ${selected.name} and its cues? You can undo this.`,
                            )
                          )
                            void mutate(
                              `/objects/${selected.id}`,
                              {},
                              "DELETE",
                            );
                        }}
                      >
                        <Trash2 size={12} />
                        Remove object
                      </button>
                    )}
                    <span className="tiny muted">
                      {cue
                        ? `${cue.kind.toUpperCase()} / ${cue.asset_id.startsWith("user_") ? "YOUR RECORDING" : "LIBRARY SOUND"}`
                        : "EVERY ACTION STAYS EDITABLE"}
                    </span>
                  </div>
                </>
              ) : (
                <div className="inspector-empty">
                  <MousePointer2 size={28} />
                  <h3>One character at a time.</h3>
                  <p>
                    Select an object in your scene to direct its sounds, without
                    touching the rest.
                  </p>
                </div>
              )}
            </aside>
          </div>

          <section className="timeline panel" hidden={!advanced}>
            <div className="timeline-header">
              <div>
                <span className="panel-heading">SOUND TIMELINE</span>
                <span className="timeline-description">
                  {project.cues.length} cues<span className="mid-dot">/</span>
                  {project.objects.length} independent layers
                </span>
              </div>
              <div className="timeline-tools">
                <button
                  className="text-button"
                  onClick={() => setModal("sounds")}
                >
                  <Headphones size={14} />
                  Sound library
                </button>
                <span className="separator" />
                <select
                  aria-label="New cue action"
                  value={actionKind}
                  disabled={disabled}
                  onChange={(event) =>
                    setActionKind(event.target.value as Kind)
                  }
                >
                  {kinds.map((kind) => (
                    <option value={kind} key={kind}>
                      {kindLabels[kind]}
                    </option>
                  ))}
                </select>
                <button
                  className="button subtle small-button"
                  disabled={disabled || !selected}
                  onClick={addCue}
                >
                  <Plus size={13} />
                  Add cue
                </button>
              </div>
            </div>
            <div className="timeline-scroll">
              <div className="timeline-inner">
                <div className="ruler-row">
                  <span className="ruler-label">
                    <AudioWaveform size={13} />
                    OBJECT / LAYER
                  </span>
                  <div
                    className="ruler"
                    onClick={(event) => {
                      const rect = event.currentTarget.getBoundingClientRect();
                      seek(
                        ((event.clientX - rect.left) / rect.width) *
                          project.media.duration,
                      );
                    }}
                  >
                    {Array.from(
                      { length: Math.ceil(project.media.duration) + 1 },
                      (_, index) => (
                        <span
                          key={index}
                          style={{
                            left: `${(index / project.media.duration) * 100}%`,
                          }}
                        >
                          {index < project.media.duration
                            ? `${String(index).padStart(2, "0")}s`
                            : ""}
                        </span>
                      ),
                    )}
                    <i
                      className="playhead-cap"
                      style={{
                        left: `${(time / project.media.duration) * 100}%`,
                      }}
                    />
                  </div>
                </div>
                {project.objects.map((object, index) => (
                  <div
                    key={object.id}
                    className={`track-row ${selectedId === object.id ? "selected" : ""} ${object.muted ? "is-muted" : ""}`}
                    style={{ "--track-color": object.color } as CSSProperties}
                  >
                    <button
                      className="track-label"
                      onClick={() => selectObject(object.id)}
                    >
                      <span className="track-number">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="object-dot" />
                      <span>
                        <strong>{object.name}</strong>
                        <small>
                          {object.muted
                            ? "MUTED"
                            : solo === object.id
                              ? "PREVIEW SOLO"
                              : "FOLEY LAYER"}
                        </small>
                      </span>
                      <AudioLines size={15} />
                    </button>
                    <div
                      className="track-area"
                      onClick={(event) => {
                        if (event.target !== event.currentTarget) return;
                        const rect =
                          event.currentTarget.getBoundingClientRect();
                        seek(
                          ((event.clientX - rect.left) / rect.width) *
                            project.media.duration,
                        );
                      }}
                      style={{
                        backgroundSize: `${100 / project.media.duration}% 100%`,
                      }}
                    >
                      {project.cues
                        .filter((item) => item.object_id === object.id)
                        .map((item) => (
                          <button
                            key={item.id}
                            className={`cue ${item.id === cueId ? "selected" : ""} ${item.muted ? "muted-cue" : ""}`}
                            style={{
                              left: `${(item.time / project.media.duration) * 100}%`,
                              width: `${(item.duration / project.media.duration) * 100}%`,
                            }}
                            aria-label={`${object.name} ${item.kind} at ${item.time.toFixed(2)} seconds`}
                            aria-pressed={item.id === cueId}
                            title={`${object.name} / ${item.kind} / ${timecode(item.time, project.media.fps)}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              selectCue(item);
                            }}
                          >
                            <Waveform seed={item.id} />
                            {item.duration > 0.7 && <span>{item.kind}</span>}
                          </button>
                        ))}
                      <div
                        className="playhead-line"
                        style={{
                          left: `${(time / project.media.duration) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
                {!project.objects.length && (
                  <div className="timeline-empty">
                    <AudioWaveform size={24} />
                    <span>Your first little sound starts with an object.</span>
                  </div>
                )}
              </div>
            </div>
            <div className="timeline-footer">
              <span>
                <span className="live-dot" />
                48 kHz<span className="mid-dot">/</span>Stereo
                <span className="mid-dot">/</span>Frame-accurate edits
              </span>
              <span>
                <kbd>Space</kbd> play / pause<span className="mid-dot">/</span>
                <kbd>Left</kbd>
                <kbd>Right</kbd> step a frame<span className="mid-dot">/</span>
                <kbd>Ctrl / Cmd Z</kbd> undo
              </span>
            </div>
          </section>
          {advanced && project.analysis_note && (
            <p className="analysis-note">
              <CircleHelp size={13} />
              {project.analysis_note}
            </p>
          )}
        </main>
      )}

      <footer className="app-footer">
        <span>
          <span className="live-dot" />
          {config?.ai_available ? "AZURE OPENAI CONNECTED" : "MANUAL STUDIO"}
        </span>
        <span>
          Less editing. More creating.
          <button className="text-button" onClick={() => setModal("help")}>
            Studio guide
            <ArrowRight size={12} />
          </button>
        </span>
      </footer>

      {busy && !project && (
        <div className="busy-indicator" role="status">
          <LoaderCircle size={17} className="spin" />
          <div>
            <strong>{busy}</strong>
            <span>Keep this tab open. Your scene is in good hands.</span>
          </div>
        </div>
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "error-toast" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <CircleHelp size={18} /> : <Check size={18} />}
          <span>{toast.text}</span>
          <IconButton label="Dismiss message" onClick={() => setToast(null)}>
            <X size={15} />
          </IconButton>
        </div>
      )}

      {modal === "options" && project && (
        <Modal
          title="Your reel"
          subtitle="Saved automatically. The extra tools are here if you need them."
          onClose={() => setModal(null)}
        >
          <div className="reel-options">
            <button
              className="button ghost"
              onClick={() => {
                setModal(null);
                uploadRef.current?.click();
              }}
            >
              <Plus size={18} />
              Start a new reel
            </button>
            <button
              className="button ghost"
              onClick={() => setModal("projects")}
            >
              <FolderOpen size={18} />
              Your reels
            </button>
            {project.undo_revisions.length > 0 && (
              <button
                className="button ghost"
                onClick={() => {
                  setModal(null);
                  undo();
                }}
              >
                <RotateCcw size={18} />
                Undo last edit
              </button>
            )}
            <button className="button ghost" onClick={toggleAdvanced}>
              <SlidersHorizontal size={18} />
              {advanced ? "Back to chat" : "Advanced tools"}
            </button>
            <button className="button ghost" onClick={() => setModal("help")}>
              <CircleHelp size={18} />
              Quick guide
            </button>
          </div>
        </Modal>
      )}

      {modal === "projects" && (
        <Modal
          title="Your reels"
          subtitle="Scenes live in this browser's private workspace. A bundle is your portable backup."
          onClose={() => setModal(null)}
          wide
        >
          <div className="project-modal-actions">
            <button
              className="button primary"
              disabled={disabled}
              onClick={() => uploadRef.current?.click()}
            >
              <Plus size={15} />
              New clip
            </button>
            <button
              className="button subtle"
              disabled={disabled}
              onClick={() => importRef.current?.click()}
            >
              <FileArchive size={15} />
              Import bundle
            </button>
            <button
              className="text-button"
              disabled={disabled}
              onClick={() => createDemo()}
            >
              <Play size={14} />
              Try the demo
            </button>
          </div>
          <div className="project-list">
            {projects.length ? (
              projects.map((item) => (
                <div className="project-list-item" key={item.id}>
                  <button
                    className="project-open"
                    disabled={disabled}
                    onClick={() =>
                      void run(
                        "Opening your scene",
                        () => api<Project>(`/api/projects/${item.id}`),
                        (scene) => {
                          accept(scene);
                          setModal(null);
                        },
                      )
                    }
                  >
                    <img
                      src={`/api/projects/${item.id}/poster.jpg`}
                      alt=""
                      loading="lazy"
                    />
                    <span>
                      <strong>{item.name}</strong>
                      <small>
                        {item.duration.toFixed(1)}s / {item.objects} objects /{" "}
                        {item.cues} cues
                      </small>
                    </span>
                    {project?.id === item.id && (
                      <span className="scope-pill">OPEN</span>
                    )}
                  </button>
                  <IconButton
                    label={`Delete scene ${item.name}`}
                    disabled={disabled}
                    onClick={() => {
                      if (
                        !window.confirm(
                          `Delete "${item.name}" and all its media? Download a bundle first. This cannot be undone.`,
                        )
                      )
                        return;
                      void run(
                        "Removing this scene",
                        async () => {
                          const current = await api<Project>(
                            `/api/projects/${item.id}`,
                          );
                          return api(`/api/projects/${item.id}`, {
                            method: "DELETE",
                            body: JSON.stringify({
                              revision: current.revision,
                            }),
                          });
                        },
                        () => {
                          setProjects((current) =>
                            current.filter((entry) => entry.id !== item.id),
                          );
                          if (projectRef.current?.id === item.id) {
                            projectRef.current = null;
                            setProject(null);
                            setConversation([]);
                            pause();
                          }
                          try {
                            localStorage.removeItem(
                              `foleygraph-chat:${item.id}`,
                            );
                          } catch {
                            // Scene deletion also works without browser conversation storage.
                          }
                          notify("Scene deleted.");
                        },
                      );
                    }}
                  >
                    <Trash2 size={15} />
                  </IconButton>
                </div>
              ))
            ) : (
              <div className="modal-empty">
                <Film size={30} />
                <p>
                  No reels yet. Bring your own clip, or try a slow morning at
                  the cafe.
                </p>
              </div>
            )}
          </div>
          <p className="tiny muted modal-footnote">
            No account required. Clearing this browser's cookies loses workspace
            access. Keep an exported bundle of anything important.
          </p>
        </Modal>
      )}

      {modal === "sounds" && (
        <Modal
          title="A small palette of sounds"
          subtitle="32 original procedural samples, dedicated to CC0. No external sound catalog or generation service."
          onClose={() => {
            setModal(null);
            auditionRef.current?.pause();
            setAuditionId(null);
          }}
          wide
        >
          <div className="sound-filters">
            <label className="search-field">
              <Search size={16} />
              <input
                placeholder="Find a material..."
                aria-label="Search sounds"
                value={sampleFilter}
                onChange={(event) => setSampleFilter(event.target.value)}
              />
            </label>
            <select
              aria-label="Library action"
              value={sampleKind}
              onChange={(event) => setSampleKind(event.target.value as Kind)}
            >
              {kinds.map((kind) => (
                <option value={kind} key={kind}>
                  {kindLabels[kind]}
                </option>
              ))}
            </select>
          </div>
          <div className="sound-list">
            {filteredSamples.map((sample) => (
              <div className="sound-list-item" key={sample.id}>
                <button
                  className="sound-play"
                  aria-label={`Preview ${sample.name}`}
                  onClick={() => audition(sample.url, sample.id)}
                >
                  {auditionId === sample.id ? (
                    <Square size={15} />
                  ) : (
                    <Play size={15} />
                  )}
                </button>
                <div>
                  <strong>{sample.name}</strong>
                  <small>
                    {sample.duration.toFixed(2)}s / CC0 / original sample
                  </small>
                </div>
                <Waveform seed={sample.id} compact />
                <button
                  className="button subtle small-button"
                  disabled={
                    disabled ||
                    !selected ||
                    (cue && cue.kind !== sample.kind) ||
                    false
                  }
                  title={
                    cue && cue.kind !== sample.kind
                      ? "Choose a sound matching the selected cue's action"
                      : "Use on the selected object's actions"
                  }
                  onClick={() => {
                    void edit(
                      [
                        {
                          type: "set_sound",
                          profile: sample.profile,
                          kind: sample.kind,
                        },
                      ],
                      `Assigned to ${selected?.name} only.`,
                    );
                  }}
                >
                  Use
                </button>
              </div>
            ))}
          </div>
          {!filteredSamples.length && (
            <p className="muted modal-footnote">
              No sounds match that material.
            </p>
          )}
          <p className="tiny muted modal-footnote">
            These are intentionally simple, synthesized building blocks. Record
            or import a real-world sound for a more personal result. No AI
            audio-generation claim.
          </p>
        </Modal>
      )}

      {modal === "help" && (
        <Modal
          title="Your next reel starts with a message."
          subtitle="Describe it. Preview it. Share it."
          onClose={() => setModal(null)}
        >
          <div className="guide-steps">
            <div>
              <span>01</span>
              <section>
                <h3>Start with a clip</h3>
                <p>
                  Try the coffee reel, or upload a permitted clip up to 20
                  seconds. Tell the chat what feeling you're after for a first
                  edit.
                </p>
              </section>
            </div>
            <div>
              <span>02</span>
              <section>
                <h3>Tell us what to change</h3>
                <p>
                  Ask for a blue shirt, a quieter cup, or ambient music. The
                  chat finds the right item without a tool or layer selection.
                  Use + to add a recording of your own.
                </p>
              </section>
            </div>
            <div>
              <span>03</span>
              <section>
                <h3>Go deeper only when you want to</h3>
                <p>
                  Say "Undo that" to go back. If you want hands-on control, open
                  More, then Advanced tools. The timeline, sound layers, and
                  frame controls are there, never required.
                </p>
              </section>
            </div>
            <div>
              <span>04</span>
              <section>
                <h3>Take your reel with you</h3>
                <p>
                  Tap Share reel for Instagram or WhatsApp, or save the finished
                  video. Choose the app in your phone's share menu. No extra
                  export settings needed.
                </p>
              </section>
            </div>
          </div>
          <div className="honest-note">
            <ShieldCheck size={18} />
            <p>
              Color targeting and motion tracking are approximate. Your original
              audio stays unless you ask to replace it; music and dialogue in
              that track cannot be separated. Sharing opens your phone's menu,
              not automatic publication.
            </p>
          </div>
          <p className="tiny muted modal-footnote">
            Only upload footage and recordings you own or have permission to
            use. Foundry analysis sends sampled visual frames and your brief to
            Azure OpenAI; voice direction sends your recorded speech for
            transcription.
          </p>
        </Modal>
      )}

      {modal === "export" && project && (
        <Modal
          title="Your reel, ready to share."
          subtitle={`"${project.name}" / ${project.media.duration.toFixed(1)} seconds`}
          onClose={() => setModal(null)}
        >
          {exportResult ? (
            <>
              <div className="export-success">
                <span>
                  <Check size={24} />
                </span>
                <div>
                  <h3>Your reel is ready.</h3>
                  <p>
                    {exportResult.revision === project.revision
                      ? "Made yours. Take it with you."
                      : "Your scene has changed. Render again to include the latest edits."}
                  </p>
                </div>
              </div>
              <div className="export-options">
                {exportResult.revision === project.revision && shareFile && (
                  <div className="reel-sharing">
                    {canShareVideo() ? (
                      <>
                        <div className="share-platforms">
                          <button
                            className="button share-instagram"
                            disabled={disabled}
                            onClick={() => shareVideo("Instagram")}
                          >
                            <Instagram size={22} /> Instagram
                          </button>
                          <button
                            className="button share-whatsapp"
                            disabled={disabled}
                            onClick={() => shareVideo("WhatsApp")}
                          >
                            <MessageCircle size={22} /> WhatsApp
                          </button>
                        </div>
                        <p>Choose the app in your phone's share menu.</p>
                      </>
                    ) : (
                      <p className="share-fallback">
                        Save the MP4, then attach it in Instagram or WhatsApp.
                        This browser can't share video files directly.
                      </p>
                    )}
                  </div>
                )}
                <a
                  className="export-option recommended"
                  href={exportResult.video_url}
                  download
                >
                  <span className="export-icon">
                    <Film size={24} />
                  </span>
                  <div>
                    <strong>
                      Download reel<span>MP4</span>
                    </strong>
                    <p>Save the MP4 to your phone or computer.</p>
                  </div>
                  <Download size={18} />
                </a>
                <details className="project-files">
                  <summary>Keep the project files and sound layers</summary>
                  <a
                    className="export-option"
                    href={exportResult.bundle_url}
                    download
                  >
                    <span className="export-icon">
                      <FileArchive size={24} />
                    </span>
                    <div>
                      <strong>Complete scene bundle</strong>
                      <p>
                        Video, editable project, isolated WAV layers, and
                        recordings.
                      </p>
                    </div>
                    <Download size={18} />
                  </a>
                  <a
                    className="export-option"
                    href={exportResult.mix_url}
                    download
                  >
                    <span className="export-icon">
                      <Music2 size={24} />
                    </span>
                    <div>
                      <strong>Just the soundscape</strong>
                      <p>Stereo WAV, 48 kHz, 16-bit PCM.</p>
                    </div>
                    <Download size={18} />
                  </a>
                </details>
              </div>
              {exportResult.revision !== project.revision && (
                <button
                  className="button primary"
                  disabled={disabled}
                  onClick={renderExport}
                >
                  Render latest revision
                  <RotateCcw size={15} />
                </button>
              )}
            </>
          ) : (
            <div className="export-wait">
              {busy ? (
                <>
                  <LoaderCircle size={34} className="spin" />
                  <h3>Getting your reel ready.</h3>
                  <p>
                    Your film and independent WAV layers are being rendered.
                  </p>
                </>
              ) : (
                <>
                  <Layers3 size={34} />
                  <h3>Let's get your reel ready.</h3>
                  <button className="button primary" onClick={renderExport}>
                    Prepare reel
                    <ArrowRight size={15} />
                  </button>
                </>
              )}
            </div>
          )}
          <p className="tiny muted modal-footnote">
            Share a finished video file, not a private project link. Your
            project stays here.
          </p>
        </Modal>
      )}

      {recordMode && (
        <Modal
          title={
            recordMode === "sound"
              ? "Something only you can make."
              : "Tell me your edit."
          }
          subtitle={
            recordMode === "sound"
              ? "One short sound. A tap, a crinkle, a tiny collision. Up to 5 seconds."
              : "A short spoken instruction, up to 30 seconds. Review the transcription before applying."
          }
          onClose={closeRecorder}
        >
          {recordMode === "sound" && (
            <label className="record-name">
              NAME YOUR SOUND
              <input
                aria-label="Recording name"
                value={recordName}
                maxLength={80}
                onChange={(event) => setRecordName(event.target.value)}
                disabled={recording || disabled}
              />
            </label>
          )}
          <div className={`record-center ${recording ? "is-recording" : ""}`}>
            <div className="record-orb">
              <Mic size={34} />
            </div>
            <span className="record-time">
              {recordSeconds.toFixed(1)}
              <small> / {recordMode === "sound" ? "5" : "30"}s</small>
            </span>
            <p>
              {recording
                ? "Listening. Make a little magic."
                : "Your microphone only turns on when you start."}
            </p>
          </div>
          <div className="record-modal-buttons">
            {recording ? (
              <button
                className="button primary large"
                onClick={() => recorderRef.current?.stop()}
              >
                <Square size={16} fill="currentColor" />
                {recordMode === "sound" ? "Save take" : "Transcribe direction"}
              </button>
            ) : (
              <button
                className="button primary large"
                disabled={Boolean(busy) || permissionPending}
                onClick={() => void startRecording()}
              >
                {permissionPending ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <Mic size={17} />
                )}
                Start recording
              </button>
            )}
            <button className="button ghost" onClick={closeRecorder}>
              Cancel
            </button>
          </div>
          {recordMode === "sound" && (
            <p className="tiny muted modal-footnote">
              Use the saved sound on the selected object's actions. For best
              results, make a single clear sound near the start of the take.
            </p>
          )}
        </Modal>
      )}
    </div>
  );
}
