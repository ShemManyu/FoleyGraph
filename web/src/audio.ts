import { assetUrl, boxAt, type Project } from "./types";

export class PreviewEngine {
  private context: AudioContext | null = null;
  private buffers = new Map<string, Promise<AudioBuffer>>();
  private sources: AudioBufferSourceNode[] = [];
  private nodes: AudioNode[] = [];
  private analysers = new Map<string, AnalyserNode>();
  private master: GainNode | null = null;

  private getContext() {
    if (!this.context) this.context = new AudioContext();
    return this.context;
  }

  async prepare(project: Project) {
    const context = this.getContext();
    await context.resume();
    const urls = [
      ...new Set(project.cues.map((cue) => assetUrl(project, cue.asset_id))),
    ];
    if (project.music) urls.push(`/api/projects/${project.id}/music.wav`);
    if (project.media.has_audio && !project.source_audio_muted)
      urls.push(`/api/projects/${project.id}/original.wav`);
    await Promise.all(
      urls.map((url) => {
        if (!this.buffers.has(url)) {
          const promise = fetch(url, { credentials: "same-origin" })
            .then((response) => {
              if (!response.ok)
                throw new Error("A sound could not be loaded. Please reload.");
              return response.arrayBuffer();
            })
            .then((data) => context.decodeAudioData(data))
            .catch((error: unknown) => {
              this.buffers.delete(url);
              throw error;
            });
          this.buffers.set(url, promise);
        }
        return this.buffers.get(url);
      }),
    );
  }

  async start(
    project: Project,
    offset: number,
    solo: string | null,
    volume: number,
  ) {
    this.stop();
    const context = this.getContext();
    const master = context.createGain();
    master.gain.value = volume;
    this.master = master;
    const compressor = context.createDynamicsCompressor();
    compressor.threshold.value = -3;
    compressor.knee.value = 6;
    compressor.ratio.value = 12;
    compressor.connect(master).connect(context.destination);
    this.nodes.push(master, compressor);
    const outputs = new Map<string, AnalyserNode>();
    for (const object of project.objects) {
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.connect(compressor);
      outputs.set(object.id, analyser);
      this.analysers.set(object.id, analyser);
      this.nodes.push(analyser);
    }
    const loaded = new Map<string, AudioBuffer>();
    for (const id of new Set(project.cues.map((cue) => cue.asset_id))) {
      const buffer = await this.buffers.get(assetUrl(project, id));
      if (buffer) loaded.set(id, buffer);
    }
    const backgrounds: { buffer: AudioBuffer; gain: number }[] = [];
    if (!solo) {
      if (project.music) {
        const buffer = await this.buffers.get(
          `/api/projects/${project.id}/music.wav`,
        );
        if (buffer)
          backgrounds.push({
            buffer,
            gain: 10 ** (project.music.gain_db / 20),
          });
      }
      if (project.media.has_audio && !project.source_audio_muted) {
        const buffer = await this.buffers.get(
          `/api/projects/${project.id}/original.wav`,
        );
        if (buffer) backgrounds.push({ buffer, gain: 1 });
      }
    }
    const clock = context.currentTime + 0.025;
    for (const { buffer, gain: level } of backgrounds) {
      const remaining =
        Math.min(buffer.duration, project.media.duration) - offset;
      if (remaining <= 0) continue;
      const source = context.createBufferSource();
      source.buffer = buffer;
      const gain = context.createGain();
      gain.gain.value = level;
      source.connect(gain).connect(compressor);
      source.start(clock, offset);
      source.stop(clock + remaining);
      this.sources.push(source);
      this.nodes.push(gain);
    }
    for (const cue of project.cues) {
      const object = project.objects.find((item) => item.id === cue.object_id);
      const buffer = loaded.get(cue.asset_id);
      if (
        !object ||
        !buffer ||
        object.muted ||
        cue.muted ||
        (solo && object.id !== solo) ||
        cue.time + cue.duration <= offset
      )
        continue;
      const elapsed = Math.max(0, offset - cue.time);
      const audible =
        cue.kind === "ambience"
          ? cue.duration
          : Math.min(cue.duration, buffer.duration / cue.playback_rate);
      if (elapsed >= audible) continue;
      const when = clock + Math.max(0, cue.time - offset);
      const remaining = audible - elapsed;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = cue.playback_rate;
      source.loop = cue.kind === "ambience";
      const gain = context.createGain();
      const level = 10 ** ((cue.gain_db + object.gain_db) / 20);
      const envelope = (position: number) =>
        Math.max(
          0,
          Math.min(
            1,
            cue.fade_in ? position / cue.fade_in : 1,
            cue.fade_out ? (audible - position) / cue.fade_out : 1,
          ),
        ) * level;
      gain.gain.setValueAtTime(envelope(elapsed), when);
      if (elapsed < cue.fade_in)
        gain.gain.linearRampToValueAtTime(
          envelope(cue.fade_in),
          when + cue.fade_in - elapsed,
        );
      const fadeStart = Math.max(elapsed, audible - cue.fade_out);
      gain.gain.setValueAtTime(envelope(fadeStart), when + fadeStart - elapsed);
      gain.gain.linearRampToValueAtTime(0, when + remaining);
      const filter = context.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = cue.lowpass_hz ?? 22000;
      const panner = context.createStereoPanner();
      const box = boxAt(object, Math.max(offset, cue.time));
      panner.pan.setValueAtTime(
        cue.pan ?? (box ? (box.x + box.width / 2) * 2 - 1 : 0),
        when,
      );
      if (cue.pan === null) {
        for (const frame of object.keyframes) {
          if (
            frame.time > Math.max(offset, cue.time) &&
            frame.time < cue.time + audible
          )
            panner.pan.linearRampToValueAtTime(
              Math.max(-1, Math.min(1, (frame.x + frame.width / 2) * 2 - 1)),
              clock + frame.time - offset,
            );
        }
      }
      source
        .connect(gain)
        .connect(filter)
        .connect(panner)
        .connect(outputs.get(object.id)!);
      source.start(
        when,
        (elapsed * cue.playback_rate) %
          (cue.kind === "ambience" ? buffer.duration : Infinity),
      );
      source.stop(when + remaining);
      this.sources.push(source);
      this.nodes.push(gain, filter, panner);
    }
  }

  setVolume(value: number) {
    if (this.master && this.context)
      this.master.gain.setTargetAtTime(value, this.context.currentTime, 0.015);
  }

  levels(): Record<string, number> {
    const result: Record<string, number> = {};
    for (const [id, analyser] of this.analysers) {
      const buffer = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(buffer);
      const rms = Math.sqrt(
        buffer.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) /
          buffer.length,
      );
      result[id] = Math.min(1, rms * 5);
    }
    return result;
  }

  stop() {
    for (const source of this.sources) {
      try {
        source.stop();
        source.disconnect();
      } catch {
        // A scheduled one-shot may already have ended.
      }
    }
    for (const node of this.nodes) node.disconnect();
    this.sources = [];
    this.nodes = [];
    this.analysers.clear();
    this.master = null;
  }

  close() {
    this.stop();
    void this.context?.close();
    this.context = null;
  }
}
