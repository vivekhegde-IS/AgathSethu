/**
 * AGHAT SETHU — WHEP WebRTC player (one instance per camera)
 *
 *   POST {api}/streams/{path}/whep   SDP offer (+ website JWT)  ->  201 SDP answer
 *   media (H.264 over SRTP/UDP) then flows directly from MediaMTX
 *   DELETE {Location}                on stop / before a reconnect
 *
 * - receive-only, H.264 preferred via setCodecPreferences
 * - non-trickle: the offer is sent once ICE gathering is complete, so a WHEP
 *   exchange is exactly one POST
 * - status: connecting -> live -> reconnecting -> offline (no publisher)
 * - automatic reconnect with exponential backoff (1 s .. 10 s, jittered),
 *   also when the picture freezes (no frame decoded for FREEZE_MS)
 * - getStats() every second: fps, bitrate, jitter buffer, RTT, codec, size
 */

export type PlayerStatus = 'connecting' | 'live' | 'reconnecting' | 'offline'

export interface PlayerStats {
  fps: number
  bitrateKbps: number
  jitterBufferMs: number | null
  rttMs: number | null
  codec: string | null
  width: number | null
  height: number | null
  packetsLost: number
  framesDropped: number
}

export interface WhepPlayerOptions {
  /** Absolute WHEP endpoint, e.g. http://host:8001/api/streams/cam1/whep */
  url: string
  video: HTMLVideoElement
  iceServers: RTCIceServer[]
  getToken: () => string | null
  onStatus: (status: PlayerStatus, detail?: string) => void
  onStats?: (stats: PlayerStats) => void
}

const ICE_GATHER_TIMEOUT_MS = 2000
const DISCONNECTED_GRACE_MS = 3000
const FREEZE_MS = 6000
const BACKOFF_MIN_MS = 1000
const BACKOFF_MAX_MS = 10000

class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export class WhepPlayer {
  private pc: RTCPeerConnection | null = null
  private sessionUrl: string | null = null
  private stopped = true
  private attempt = 0
  private generation = 0
  private retryTimer: number | null = null
  private graceTimer: number | null = null
  private statsTimer: number | null = null
  private lastStats: { at: number; bytes: number; frames: number } | null = null
  private lastFrameChange = 0
  private everLive = false
  private status: PlayerStatus | null = null

  constructor(private readonly opts: WhepPlayerOptions) {}

  start(): void {
    if (!this.stopped) return
    this.stopped = false
    this.attempt = 0
    void this.connect()
  }

  stop(): void {
    this.stopped = true
    this.generation += 1
    this.clearTimers()
    this.teardown(true)
    this.opts.video.srcObject = null
  }

  // ---------------------------------------------------------------------------

  private async connect(): Promise<void> {
    const generation = ++this.generation
    this.teardown(true)
    // an offline camera stays "offline" while it is retried
    if (this.status !== 'offline') this.setStatus(this.everLive ? 'reconnecting' : 'connecting')

    const pc = new RTCPeerConnection({ iceServers: this.opts.iceServers, bundlePolicy: 'max-bundle' })
    this.pc = pc
    const transceiver = pc.addTransceiver('video', { direction: 'recvonly' })
    preferH264(transceiver)

    pc.ontrack = (event) => {
      const stream = event.streams[0] ?? new MediaStream([event.track])
      this.opts.video.srcObject = stream
      this.opts.video.play().catch(() => undefined) // muted autoplay is allowed
    }
    pc.onconnectionstatechange = () => this.onConnectionState(pc, generation)

    try {
      await pc.setLocalDescription(await pc.createOffer())
      await waitForIceGathering(pc, ICE_GATHER_TIMEOUT_MS)
      const answer = await this.postOffer(pc.localDescription?.sdp ?? '')
      if (generation !== this.generation) return
      await pc.setRemoteDescription({ type: 'answer', sdp: answer })
    } catch (error) {
      if (generation !== this.generation) return
      const status = error instanceof HttpError ? error.status : 0
      if (status === 401) window.dispatchEvent(new CustomEvent('aghat:unauthorized'))
      this.setStatus(status === 404 ? 'offline' : this.everLive ? 'reconnecting' : 'connecting',
        error instanceof Error ? error.message : String(error))
      this.scheduleReconnect()
    }
  }

  private async postOffer(sdp: string): Promise<string> {
    const token = this.opts.getToken()
    const response = await fetch(this.opts.url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: sdp,
    })
    if (response.status !== 201) {
      let detail = `HTTP ${response.status}`
      try {
        detail = (await response.json()).detail ?? detail
      } catch {
        /* non-JSON error body */
      }
      throw new HttpError(response.status, detail)
    }
    const location = response.headers.get('Location')
    this.sessionUrl = location ? new URL(location, this.opts.url).toString() : null
    return response.text()
  }

  private onConnectionState(pc: RTCPeerConnection, generation: number): void {
    if (generation !== this.generation) return
    switch (pc.connectionState) {
      case 'connected':
        this.clearGrace()
        this.attempt = 0
        this.everLive = true
        this.lastFrameChange = performance.now()
        this.setStatus('live')
        this.startStats(pc, generation)
        break
      case 'disconnected':
        // often recovers on its own (Wi-Fi blip); reconnect only if it does not
        this.clearGrace()
        this.graceTimer = window.setTimeout(() => {
          if (generation === this.generation && pc.connectionState !== 'connected') this.scheduleReconnect()
        }, DISCONNECTED_GRACE_MS)
        break
      case 'failed':
      case 'closed':
        this.scheduleReconnect()
        break
      default:
        break
    }
  }

  private scheduleReconnect(): void {
    if (this.stopped) return
    this.generation += 1 // invalidate callbacks of the current connection
    if (this.status === 'live') this.setStatus('reconnecting')
    this.clearTimers()
    this.teardown(true)
    const base = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** this.attempt)
    const delay = base / 2 + Math.random() * (base / 2)
    this.attempt += 1
    this.retryTimer = window.setTimeout(() => void this.connect(), delay)
  }

  private startStats(pc: RTCPeerConnection, generation: number): void {
    if (this.statsTimer !== null) window.clearInterval(this.statsTimer)
    this.lastStats = null
    this.statsTimer = window.setInterval(async () => {
      if (generation !== this.generation) return
      try {
        const report = await pc.getStats()
        const stats = summarize(report, this.lastStats)
        if (stats.sample) {
          if (!this.lastStats || stats.sample.frames !== this.lastStats.frames) {
            this.lastFrameChange = performance.now()
          }
          this.lastStats = stats.sample
        }
        this.opts.onStats?.(stats.stats)
        // connected but frozen (publisher restarted, media path broken): reconnect
        if (performance.now() - this.lastFrameChange > FREEZE_MS) this.scheduleReconnect()
      } catch {
        /* getStats can fail while closing */
      }
    }, 1000)
  }

  private teardown(sendDelete: boolean): void {
    if (this.statsTimer !== null) {
      window.clearInterval(this.statsTimer)
      this.statsTimer = null
    }
    const pc = this.pc
    this.pc = null
    if (pc) {
      pc.ontrack = null
      pc.onconnectionstatechange = null
      pc.close()
    }
    const session = this.sessionUrl
    this.sessionUrl = null
    if (sendDelete && session) {
      const token = this.opts.getToken()
      // keepalive lets the DELETE finish even while the page unloads
      fetch(session, {
        method: 'DELETE',
        keepalive: true,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).catch(() => undefined)
    }
  }

  private setStatus(status: PlayerStatus, detail?: string): void {
    this.status = status
    this.opts.onStatus(status, detail)
  }

  private clearGrace(): void {
    if (this.graceTimer !== null) {
      window.clearTimeout(this.graceTimer)
      this.graceTimer = null
    }
  }

  private clearTimers(): void {
    this.clearGrace()
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
  }
}

// -----------------------------------------------------------------------------

/** Put H.264 (constrained baseline, packetization-mode=1 first) ahead of VP8/VP9/AV1. */
function preferH264(transceiver: RTCRtpTransceiver): void {
  const capabilities = typeof RTCRtpReceiver !== 'undefined' ? RTCRtpReceiver.getCapabilities?.('video') : null
  if (!capabilities || typeof transceiver.setCodecPreferences !== 'function') return
  const rank = (codec: RTCRtpCodec) => {
    if (codec.mimeType.toLowerCase() !== 'video/h264') return 2
    const fmtp = codec.sdpFmtpLine ?? ''
    return fmtp.includes('packetization-mode=1') && fmtp.includes('42e01f') ? 0 : 1
  }
  const codecs = [...capabilities.codecs].sort((a, b) => rank(a) - rank(b))
  try {
    transceiver.setCodecPreferences(codecs)
  } catch {
    /* browser without H.264: negotiation falls back to the default order */
  }
}

function waitForIceGathering(pc: RTCPeerConnection, timeoutMs: number): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', check)
      window.clearTimeout(timer)
      resolve()
    }
    const check = () => {
      if (pc.iceGatheringState === 'complete') done()
    }
    // host candidates arrive within ms; STUN may be slow or offline: send what we have
    const timer = window.setTimeout(done, timeoutMs)
    pc.addEventListener('icegatheringstatechange', check)
  })
}

function summarize(
  report: RTCStatsReport,
  previous: { at: number; bytes: number; frames: number } | null,
): { stats: PlayerStats; sample: { at: number; bytes: number; frames: number } | null } {
  let inbound: Record<string, unknown> | null = null
  let rttMs: number | null = null
  const byId = new Map<string, Record<string, unknown>>()
  report.forEach((entry: Record<string, unknown>) => {
    byId.set(entry.id as string, entry)
    if (entry.type === 'inbound-rtp' && entry.kind === 'video') inbound = entry
    if (entry.type === 'candidate-pair' && entry.nominated && typeof entry.currentRoundTripTime === 'number') {
      rttMs = Math.round((entry.currentRoundTripTime as number) * 1000)
    }
  })
  const stats: PlayerStats = {
    fps: 0, bitrateKbps: 0, jitterBufferMs: null, rttMs, codec: null,
    width: null, height: null, packetsLost: 0, framesDropped: 0,
  }
  if (!inbound) return { stats, sample: null }
  const rtp = inbound as Record<string, number | string | undefined>
  const now = performance.now()
  const bytes = Number(rtp.bytesReceived ?? 0)
  const frames = Number(rtp.framesDecoded ?? 0)
  if (previous) {
    const seconds = (now - previous.at) / 1000
    if (seconds > 0) {
      stats.fps = Math.round(((frames - previous.frames) / seconds) * 10) / 10
      stats.bitrateKbps = Math.round(((bytes - previous.bytes) * 8) / 1000 / seconds)
    }
  }
  const emitted = Number(rtp.jitterBufferEmittedCount ?? 0)
  if (emitted > 0) stats.jitterBufferMs = Math.round((Number(rtp.jitterBufferDelay ?? 0) / emitted) * 1000)
  const codec = rtp.codecId ? byId.get(String(rtp.codecId)) : undefined
  if (codec) {
    stats.codec = `${String(codec.mimeType ?? '').replace('video/', '')}${codec.sdpFmtpLine ? ` (${
      /profile-level-id=([0-9a-f]+)/i.exec(String(codec.sdpFmtpLine))?.[1] ?? ''})` : ''}`
  }
  stats.width = rtp.frameWidth !== undefined ? Number(rtp.frameWidth) : null
  stats.height = rtp.frameHeight !== undefined ? Number(rtp.frameHeight) : null
  stats.packetsLost = Number(rtp.packetsLost ?? 0)
  stats.framesDropped = Number(rtp.framesDropped ?? 0)
  return { stats, sample: { at: now, bytes, frames } }
}
