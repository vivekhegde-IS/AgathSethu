import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useSearchParams } from 'react-router-dom'
import { useIncidentStore } from '@stores/incidentStore'
import { WebRtcCameraVideo } from '@components/authority/WebRtcCameraVideo'
import apiClient from '@api/apiClient'
import { CameraStatus, fetchCameraStatus, formatIst } from '@api/portal'
import type { PlayerStatus } from '@services/webrtc/whepPlayer'
import {
  connectLiveCameraSocket,
  subscribeToLiveCameraMessages,
  subscribeToLiveCameraStatus,
} from '@services/websocket/liveCamerasSocket'

interface CameraFrameMessage {
  type: "camera_frame";
  timestamp_sim: number;
  frame: number;
  camera_id: string;
  junction_id: string;
  encoding: string;
  width: number;
  height: number;
  has_number_plate_overlay: boolean;
  image: string;
}

interface CameraState {
  image: string | null;
  cameraId: string | null;
  frame: number | null;
  timestampSim: number | null;
  width: number | null;
  height: number | null;
  hasNumberPlateOverlay: boolean;
  connected: boolean;
}

const INITIAL_CAMERA_STATE: CameraState = {
  image: null,
  cameraId: null,
  frame: null,
  timestampSim: null,
  width: null,
  height: null,
  hasNumberPlateOverlay: false,
  connected: false,
};

// WebRTC (H.264 over WHEP via MediaMTX) is the video path; the JPEG frames of
// the live-camera socket remain the fallback. VITE_WEBRTC_ENABLED=false turns it off.
const WEBRTC_ENABLED = import.meta.env.VITE_WEBRTC_ENABLED !== 'false'

interface StreamsConfig {
  whepByJunction: Record<string, string>
  iceServers: RTCIceServer[]
}

const INITIAL_CAMERAS: Record<string, CameraState> = {
  J01: { ...INITIAL_CAMERA_STATE },
  J02: { ...INITIAL_CAMERA_STATE },
  J03: { ...INITIAL_CAMERA_STATE },
};

// Camera server health is polled from the backend, which measures whether
// frames are actually arriving from the CARLA camera sender.
const CAMERA_STATUS_POLL_MS = 5000

const junctionName = (junctionId: string) => `Junction ${Number(junctionId.replace(/\D/g, '')) || junctionId}`

export function Live() {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const activeIncident = useIncidentStore((state) => state.activeIncident)
  const registerLiveIncidentMessage = useIncidentStore((state) => state.registerLiveIncidentMessage)

  const crashContext = useMemo(() => {
    const state = (location.state ?? {}) as Record<string, unknown>
    const alert = activeIncident?.alert

    return {
      focusJunction:
        (typeof state.focusJunction === 'string' && state.focusJunction) ||
        // "View Live Feed" on an incident opens /authority/live?junction=J02
        searchParams.get('junction') ||
        // Live crash alerts carry the junction directly — no navigation needed.
        (typeof alert?.junction_id === 'string' && alert.junction_id) ||
        (typeof alert?.junction === 'string' && alert.junction) ||
        null,
      alertId:
        (typeof state.alertId === 'string' && state.alertId) ||
        (alert?.alert_id && alert.alert_id !== 'unknown' ? alert.alert_id : null) ||
        null,
      vehicle:
        (typeof state.vehicle === 'string' && state.vehicle) ||
        (typeof alert?.vehicle === 'string' ? alert.vehicle : null),
      collisionPartner:
        (typeof state.collisionPartner === 'string' && state.collisionPartner) ||
        (typeof alert?.collision_partner === 'string' ? alert.collision_partner : null),
      alert,
    }
  }, [activeIncident?.alert, location.state, searchParams])

  // Snap the crash's real date and time the moment the alert goes active: the
  // backend's receive time (received_at), else the moment this page saw it.
  // Simulator seconds are never shown to the operator.
  const [crashWallTime, setCrashWallTime] = useState<string | null>(null)
  const crashAlertId = crashContext.alertId
  useEffect(() => {
    if (crashAlertId) {
      setCrashWallTime(activeIncident?.alert?.received_at ?? new Date().toISOString())
    } else {
      setCrashWallTime(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [crashAlertId])

  const [cameras, setCameras] =
    useState<Record<string, CameraState>>(INITIAL_CAMERAS);

  // null = first check still pending; undefined = the backend did not answer
  const [cameraStatus, setCameraStatus] = useState<CameraStatus | null | undefined>(null)
  useEffect(() => {
    let cancelled = false
    const check = () =>
      fetchCameraStatus()
        .then((status) => !cancelled && setCameraStatus(status))
        .catch(() => !cancelled && setCameraStatus(undefined))
    check()
    const timer = window.setInterval(check, CAMERA_STATUS_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])
  const cameraServerConnected = Boolean(cameraStatus?.connected)

  // WebRTC stream list (GET /api/streams) and per-junction player status
  const [streamsConfig, setStreamsConfig] = useState<StreamsConfig | null>(null)
  const [webrtcStatus, setWebrtcStatus] = useState<Record<string, PlayerStatus | 'disabled'>>({})
  useEffect(() => {
    if (!WEBRTC_ENABLED) return
    let cancelled = false
    apiClient
      .get<{ enabled: boolean; streams: { junction_id: string; whep_url: string }[]; ice_servers: RTCIceServer[] }>(
        '/streams',
      )
      .then(({ data }) => {
        if (cancelled || !data.enabled) return
        setStreamsConfig({
          whepByJunction: Object.fromEntries(data.streams.map((s) => [s.junction_id, s.whep_url])),
          iceServers: data.ice_servers,
        })
      })
      .catch(() => undefined) // no WebRTC: tiles keep using the JPEG frames
    return () => {
      cancelled = true
    }
  }, [])

  // Per-junction last-rendered timestamps for frame throttling (no re-render).
  const lastFrameRenderRef = useRef<Record<string, number>>({
    J01: 0,
    J02: 0,
    J03: 0,
  });

  useEffect(() => {
    const socket = connectLiveCameraSocket();
    if (!socket) return

    const unsubscribeStatus = subscribeToLiveCameraStatus((connected) => {
      setCameras((previous) => {
        const updated = { ...previous }
        Object.keys(updated).forEach((junctionId) => {
          updated[junctionId] = {
            ...updated[junctionId],
            connected,
          }
        })
        return updated
      })
    })

    const unsubscribeMessages = subscribeToLiveCameraMessages((message) => {
      if (message.type === "camera_frame") {
        const cameraMessage = message as unknown as CameraFrameMessage
        const {
          junction_id,
          camera_id,
          frame,
          timestamp_sim,
          encoding,
          width,
          height,
          has_number_plate_overlay,
          image,
        } = cameraMessage

        if (!["J01", "J02", "J03"].includes(junction_id)) {
          console.warn(
            `[LIVE CAMERA WS] Unknown junction received: ${junction_id}`
          );
          return;
        }

        if (!image) {
          console.warn(
            `[LIVE CAMERA WS] Empty image received for ${junction_id}`
          );
          return;
        }

        if (encoding !== "jpeg_base64") {
          console.warn(
            `[LIVE CAMERA WS] Unsupported encoding for ${junction_id}: ${encoding}`
          );
          return;
        }

        // Drop frames arriving faster than the UI can meaningfully render.
        // The stream is already throttled upstream; this guards against
        // bursts after reconnects so React never re-renders per message.
        const now = Date.now()
        if (now - lastFrameRenderRef.current[junction_id] < 70) {
          return
        }
        lastFrameRenderRef.current[junction_id] = now

        const imageSource = `data:image/jpeg;base64,${image}`;

        setCameras((previous) => ({
          ...previous,
          [junction_id]: {
            image: imageSource,
            cameraId: camera_id,
            frame,
            timestampSim: timestamp_sim,
            width,
            height,
            hasNumberPlateOverlay: has_number_plate_overlay,
            connected: true,
          },
        }));
        registerLiveIncidentMessage(message as Record<string, unknown>)
        return
      }

      registerLiveIncidentMessage(message as Record<string, unknown>)
    })

    return () => {
      unsubscribeStatus()
      unsubscribeMessages()
    }
  }, [registerLiveIncidentMessage])

  const alert = activeIncident?.alert

  const renderCamera = (
    junctionId: string,
    cameraTitle: string
  ) => {
    const camera = cameras[junctionId];
    const isLive = webrtcStatus[junctionId] === 'live' || Boolean(camera.image)
    const isCrashJunction = crashContext.focusJunction === junctionId || crashContext.focusJunction === `J${junctionId.replace('J', '')}`

    return (
      <div
        key={junctionId}
        style={{
          background: "#ffffff",
          borderRadius: "12px",
          overflow: "hidden",
          border: isCrashJunction ? "2px solid #ef4444" : "1px solid #e2e8f0",
          boxShadow: isCrashJunction ? "0 0 0 2px rgba(239,68,68,0.35)" : "0 4px 12px rgba(0,0,0,0.15)",
          position: "relative",
        }}
      >
        {/* Camera Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            background: "#ffffff",
            borderBottom: "1px solid #e2e8f0",
          }}
        >
          <div>
            <div
              style={{
                color: "#172554",
                fontSize: "16px",
                fontWeight: 600,
              }}
            >
              {cameraTitle}
            </div>

            <div
              style={{
                color: "#475569",
                fontSize: "12px",
                marginTop: "3px",
              }}
            >
              {junctionName(junctionId)}
              {camera.cameraId
                ? ` • ${camera.cameraId}`
                : ""}
            </div>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "7px",
              fontSize: "12px",
              fontWeight: 600,
            }}
          >
            <span
              style={{
                width: "8px",
                height: "8px",
                borderRadius: "50%",
                background: isLive
                  ? "#22c55e"
                  : "#6b7280",
                display: "inline-block",
              }}
            />

            <span
              style={{
                color: isLive
                  ? "#22c55e"
                  : "#64748b",
              }}
            >
              {isLive ? "LIVE" : "WAITING"}
            </span>
          </div>
        </div>

        {/* Camera Image */}
        <div
          style={{
            position: "relative",
            width: "100%",
            aspectRatio: "16 / 9",
            background: "#030712",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          <WebRtcCameraVideo
            whepUrl={streamsConfig?.whepByJunction[junctionId] ?? null}
            iceServers={streamsConfig?.iceServers ?? []}
            label={junctionId}
            hasFallbackFrame={Boolean(camera.image)}
            onStatusChange={(status) =>
              setWebrtcStatus((previous) => (previous[junctionId] === status ? previous : { ...previous, [junctionId]: status }))
            }
            fallback={camera.image ? (
            <img
              src={camera.image}
              alt={`Live camera feed ${junctionId}`}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                display: "block",
              }}
            />
          ) : (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                color: "#9ca3af",
                textAlign: "center",
                padding: "20px",
              }}
            >
              <div
                style={{
                  fontSize: "15px",
                  fontWeight: 500,
                  marginBottom: "6px",
                }}
              >
                Waiting for camera...
              </div>

              <div
                style={{
                  fontSize: "12px",
                  color: "#6b7280",
                }}
              >
                No frames from {junctionName(junctionId)} yet
              </div>
            </div>
          )}
          />

          {/* Live indicator */}
          {isLive && (
            <div
              style={{
                position: "absolute",
                top: "10px",
                left: "10px",
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "5px 8px",
                background: "rgba(0,0,0,0.65)",
                borderRadius: "5px",
                color: "#ffffff",
                fontSize: "11px",
                fontWeight: 600,
              }}
            >
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  borderRadius: "50%",
                  background: "#ef4444",
                  display: "inline-block",
                }}
              />
              LIVE
            </div>
          )}

          {/* Plate overlay indicator */}
          {isLive &&
            camera.hasNumberPlateOverlay && (
              <div
                style={{
                  position: "absolute",
                  top: "10px",
                  right: "10px",
                  padding: "5px 8px",
                  background: "rgba(0,0,0,0.65)",
                  borderRadius: "5px",
                  color: "#ffffff",
                  fontSize: "11px",
                  fontWeight: 500,
                }}
              >
                PLATE
              </div>
            )}

          {/* Crash moment overlay — pinned to the exact crash junction */}
          {isCrashJunction && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                pointerEvents: "none",
                boxShadow: "inset 0 0 0 3px rgba(239,68,68,0.85)",
              }}
            >
              <div
                style={{
                  position: "absolute",
                  bottom: "12px",
                  left: "12px",
                  right: "12px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "10px",
                  padding: "8px 12px",
                  background: "rgba(153, 27, 27, 0.92)",
                  borderRadius: "8px",
                  color: "#fee2e2",
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", fontWeight: 700 }}>
                  <span style={{ width: "9px", height: "9px", borderRadius: "50%", background: "#ef4444", display: "inline-block" }} />
                  CRASH DETECTED {crashWallTime ? `• ${formatIst(crashWallTime)}` : ''}
                </span>
                <span style={{ fontSize: "11px", fontWeight: 500 }}>
                  {crashContext.vehicle ? `${crashContext.vehicle}${crashContext.collisionPartner ? ` ↔ ${crashContext.collisionPartner}` : ''}` : ''}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Camera Information */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "9px 14px",
            background: "#ffffff",
            color: "#475569",
            fontSize: "11px",
          }}
        >
          <span>
            {camera.frame !== null
              ? `Frame ${camera.frame}`
              : "No frame"}
          </span>

          <span>
            {camera.width && camera.height
              ? `${camera.width} × ${camera.height}`
              : "—"}
          </span>

          <span>
            {camera.timestampSim !== null
              ? `t=${camera.timestampSim.toFixed(2)}s`
              : "—"}
          </span>
        </div>
      </div>
    );
  };

  return (
    <div
      style={{
        width: "100%",
        minHeight: "100%",
        padding: "24px",
        boxSizing: "border-box",
        background: "transparent",
      }}
    >
      {/* Page Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "24px",
        }}
      >
        <div>
          <h1
            style={{
              margin: 0,
              fontSize: "28px",
              fontWeight: 700,
              color: "#172554",
            }}
          >
            Live Camera Monitoring
          </h1>

          <p
            style={{
              margin: "6px 0 0 0",
              color: "#6b7280",
              fontSize: "14px",
            }}
          >
            Live feeds from the junction cameras
          </p>
        </div>

        {/* Camera server state: polled health check, not the browser socket */}
        <div
          role="status"
          aria-live="polite"
          title={
            cameraStatus === undefined
              ? 'The backend did not answer the camera health check'
              : cameraStatus && !cameraStatus.connected
                ? cameraStatus.sender_attached
                  ? `No camera frames in the last ${cameraStatus.stale_after_s} s`
                  : 'No camera sender is connected'
                : undefined
          }
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            padding: "8px 12px",
            borderRadius: "8px",
            background: cameraStatus === null ? "#f3f4f6" : cameraServerConnected ? "#ecfdf5" : "#fef2f2",
            border: `1px solid ${cameraStatus === null ? "#d1d5db" : cameraServerConnected ? "#a7f3d0" : "#fecaca"}`,
          }}
        >
          <span
            style={{
              width: "9px",
              height: "9px",
              borderRadius: "50%",
              background: cameraStatus === null ? "#9ca3af" : cameraServerConnected ? "#10b981" : "#dc2626",
            }}
          />
          <span
            style={{
              fontSize: "12px",
              fontWeight: 600,
              color: cameraStatus === null ? "#6b7280" : cameraServerConnected ? "#047857" : "#b91c1c",
            }}
          >
            {cameraStatus === null
              ? "Checking camera server…"
              : cameraServerConnected
                ? "Camera server: Connected"
                : "Camera server: Disconnected"}
          </span>
        </div>
      </div>

      {alert && (
        <div
          style={{
            marginBottom: "16px",
            padding: "16px",
            borderRadius: "12px",
            background: "#fef2f2",
            border: "1px solid rgba(248, 113, 113, 0.45)",
            color: "#7f1d1d",
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <div>
              <div style={{ fontSize: '11px', letterSpacing: '0.18em', textTransform: 'uppercase', color: '#b91c1c', fontWeight: 700 }}>Crash detected</div>
              <div style={{ fontSize: '21px', fontWeight: 700, marginTop: '4px' }}>
                {crashContext.focusJunction ? junctionName(crashContext.focusJunction) : 'Location being determined'}
              </div>
            </div>
            <div style={{ fontSize: '12px', color: '#991b1b', textAlign: 'right' }}>
              {alert.alert_id}
              <div style={{ marginTop: '4px' }}>{formatIst(crashWallTime ?? alert.received_at)}</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
            <div style={{ background: '#ffffff', borderRadius: '8px', padding: '10px 12px', border: '1px solid #fecaca' }}>
              <div style={{ fontSize: '10px', color: '#64748b', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Vehicle</div>
              <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '6px' }}>{alert.vehicle}</div>
            </div>
            <div style={{ background: '#ffffff', borderRadius: '8px', padding: '10px 12px', border: '1px solid #fecaca' }}>
              <div style={{ fontSize: '10px', color: '#64748b', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Other vehicle</div>
              <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '6px' }}>{alert.collision_partner ?? '—'}</div>
            </div>
            <div style={{ background: '#ffffff', borderRadius: '8px', padding: '10px 12px', border: '1px solid #fecaca' }}>
              <div style={{ fontSize: '10px', color: '#64748b', letterSpacing: '0.1em', textTransform: 'uppercase' }}>Plate</div>
              <div style={{ fontSize: '15px', fontWeight: 700, marginTop: '6px' }}>{alert.plate || '—'}</div>
            </div>
          </div>
        </div>
      )}

      {crashContext.focusJunction && (
        <div
          style={{
            marginBottom: "16px",
            padding: "10px 14px",
            borderRadius: "10px",
            background: "#fef2f2",
            border: "1px solid rgba(239,68,68,0.4)",
            color: "#991b1b",
            fontSize: "12px",
            fontWeight: 600,
          }}
        >
          Showing crash location: {junctionName(crashContext.focusJunction)} {crashContext.vehicle ? `• vehicle ${crashContext.vehicle}` : ''}
          {crashContext.collisionPartner ? ` • partner ${crashContext.collisionPartner}` : ''}
        </div>
      )}

      {/* Three Live Camera Feeds */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(360px, 1fr))",
          gap: "20px",
          width: "100%",
        }}
      >
        {renderCamera("J01", "Junction 1 camera")}
        {renderCamera("J02", "Junction 2 camera")}
        {renderCamera("J03", "Junction 3 camera")}
      </div>
    </div>
  );
}

export const LiveMonitoring = Live;
export default Live;