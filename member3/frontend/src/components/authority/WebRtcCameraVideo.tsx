/**
 * One camera tile's video: WebRTC (WHEP, H.264) when available, the existing
 * JPEG frame otherwise. Drop-in for the media area of a Live page tile; the
 * tile's header, badges and crash overlay stay in the parent.
 */

import { ReactNode, useEffect, useRef, useState } from 'react'
import { getApiBaseUrl, getToken } from '@api/apiClient'
import { PlayerStatus, WhepPlayer } from '@services/webrtc/whepPlayer'

export interface WebRtcCameraVideoProps {
  /** WHEP path from GET /api/streams (e.g. "/api/streams/cam1/whep"); null = WebRTC unavailable */
  whepUrl: string | null
  iceServers: RTCIceServer[]
  /** Rendered when WebRTC is not live (the JPEG frame, or the waiting card) */
  fallback: ReactNode
  /** true when `fallback` is a real (JPEG) camera frame, not the waiting card */
  hasFallbackFrame?: boolean
  label: string
  onStatusChange?: (status: PlayerStatus | 'disabled') => void
}

const API_ORIGIN = getApiBaseUrl().replace(/\/api\/?$/, '')

const STATUS_STYLE: Record<PlayerStatus, { text: string; color: string }> = {
  connecting: { text: 'CONNECTING', color: '#fbbf24' },
  live: { text: 'WEBRTC', color: '#22c55e' },
  reconnecting: { text: 'RECONNECTING', color: '#f97316' },
  offline: { text: 'STREAM OFFLINE', color: '#9ca3af' },
}

const buttonStyle = {
  padding: '4px 7px',
  background: 'rgba(0,0,0,0.65)',
  border: '1px solid rgba(255,255,255,0.15)',
  borderRadius: '5px',
  color: '#ffffff',
  fontSize: '11px',
  cursor: 'pointer',
} as const

export function WebRtcCameraVideo({
  whepUrl, iceServers, fallback, hasFallbackFrame = false, label, onStatusChange,
}: WebRtcCameraVideoProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [status, setStatus] = useState<PlayerStatus | null>(null)
  const [detail, setDetail] = useState<string | undefined>()
  const statusCallback = useRef(onStatusChange)
  statusCallback.current = onStatusChange

  useEffect(() => {
    const video = videoRef.current
    if (!whepUrl || !video) {
      setStatus(null)
      statusCallback.current?.('disabled')
      return
    }
    const player = new WhepPlayer({
      url: `${API_ORIGIN}${whepUrl}`,
      video,
      iceServers,
      getToken,
      onStatus: (next, why) => {
        setStatus(next)
        setDetail(why)
        statusCallback.current?.(next)
      },
    })
    player.start()
    return () => player.stop() // unmount: DELETE the WHEP session, close the peer connection
    // iceServers is fetched once; re-creating the player on identity change is not wanted
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [whepUrl])

  const live = status === 'live'
  const style = status ? STATUS_STYLE[status] : null

  const toggleFullscreen = () => {
    const element = containerRef.current
    if (!element) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else void element.requestFullscreen?.()
  }

  return (
    <div ref={containerRef} style={{ position: 'absolute', inset: 0, background: '#030712' }}>
      <video
        ref={videoRef}
        autoPlay
        muted
        playsInline
        disablePictureInPicture
        aria-label={`Live camera feed ${label}`}
        style={{ width: '100%', height: '100%', objectFit: 'contain', display: live ? 'block' : 'none' }}
      />
      {!live && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {fallback}
        </div>
      )}

      {/* stream state, bottom-left (the crash banner, when shown, covers the bottom edge) */}
      {style && (
        <div
          title={detail}
          style={{
            position: 'absolute', left: '10px', bottom: '10px', padding: '3px 7px', borderRadius: '5px',
            background: 'rgba(0,0,0,0.65)', color: style.color, fontSize: '10px', fontWeight: 700,
            letterSpacing: '0.06em', pointerEvents: 'auto',
          }}
        >
          {style.text}
          {!live && hasFallbackFrame ? ' · JPEG' : ''}
        </div>
      )}

      {/* controls, below the PLATE badge */}
      {whepUrl && (
        <div style={{ position: 'absolute', top: '42px', right: '10px', display: 'flex', gap: '6px' }}>
          <button type="button" style={buttonStyle} onClick={toggleFullscreen} title="Fullscreen">
            ⛶
          </button>
        </div>
      )}

    </div>
  )
}
