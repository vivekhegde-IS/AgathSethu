import { getToken } from '@api/apiClient'

export type LiveCameraMessage =
  | {
      type: 'camera_frame'
      [key: string]: unknown
    }
  | {
      type: 'crash_alert'
      [key: string]: unknown
    }
  | {
      type?: string
      [key: string]: unknown
    }

const LIVE_CAMERA_WS_URL = import.meta.env.VITE_LIVE_CAMERA_WS_URL || 'ws://127.0.0.1:8001/ws/live-cameras'

let socket: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0
let statusSubscribers = new Set<(connected: boolean) => void>()
let messageSubscribers = new Set<(message: LiveCameraMessage) => void>()

function notifyStatus(connected: boolean) {
  statusSubscribers.forEach((subscriber) => subscriber(connected))
}

function reconnect() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
  }

  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 10000)
  reconnectAttempts += 1

  reconnectTimer = window.setTimeout(() => {
    connectLiveCameraSocket()
  }, delay)
}

export function connectLiveCameraSocket(): WebSocket | null {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return socket
  }

  if (socket && socket.readyState === WebSocket.CLOSING) {
    return socket
  }

  // The backend accepts authority logins only; the token goes in the query
  // string because browsers cannot set headers on a WebSocket.
  const token = getToken()
  if (!token) return null
  socket = new WebSocket(`${LIVE_CAMERA_WS_URL}?token=${encodeURIComponent(token)}`)
  notifyStatus(false)

  socket.onopen = () => {
    reconnectAttempts = 0
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    notifyStatus(true)
  }

  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data) as LiveCameraMessage
      messageSubscribers.forEach((subscriber) => subscriber(message))
    } catch (error) {
      console.error('[LIVE CAMERA WS] Failed to parse websocket message:', error)
    }
  }

  socket.onerror = (error) => {
    console.error('[LIVE CAMERA WS] WebSocket error:', error)
  }

  socket.onclose = () => {
    notifyStatus(false)
    socket = null
    reconnect()
  }

  return socket
}

export function subscribeToLiveCameraStatus(callback: (connected: boolean) => void) {
  statusSubscribers.add(callback)
  callback(socket?.readyState === WebSocket.OPEN)

  return () => {
    statusSubscribers.delete(callback)
  }
}

export function subscribeToLiveCameraMessages(callback: (message: LiveCameraMessage) => void) {
  messageSubscribers.add(callback)

  return () => {
    messageSubscribers.delete(callback)
  }
}

export function disconnectLiveCameraSocket() {
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  if (socket) {
    socket.onclose = null // an intentional close must not schedule a reconnect
    socket.close()
    socket = null
  }
  reconnectAttempts = 0

  notifyStatus(false)
}
