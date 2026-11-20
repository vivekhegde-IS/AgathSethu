/**
 * useLiveEvents — the /ws/events socket for the live dashboards.
 *
 * - ONE socket per tab, shared by every component that calls the hook (the
 *   crash pop-up in the layout, the page, the notification bell...). It opens
 *   with the first subscriber and closes shortly after the last one leaves.
 * - Authenticates with this tab's token as the FIRST message (never in the URL).
 * - The server decides the room (authority or this owner), not the client.
 * - On every (re)connect, each subscriber's `onSync` runs so the page reloads
 *   its state over REST: nothing is lost while a tab was closed or the socket
 *   was down. A subscriber that joins an already-open socket syncs at once.
 * - Reconnects with exponential backoff (1 s .. 30 s, with jitter).
 */

import { useEffect, useRef, useState } from 'react'
import { getEventsSocketUrl, getToken } from '@api/apiClient'
import type { LiveEvent } from '@api/live'

export type LiveStatus = 'connecting' | 'live' | 'offline'

interface Subscriber {
  onEvent: (event: LiveEvent) => void
  onSync: () => void
  onStatus: (status: LiveStatus) => void
}

const CLOSE_GRACE_MS = 3000      // page changes inside a portal keep the same socket

const subscribers = new Set<Subscriber>()
let socket: WebSocket | null = null
let socketToken: string | null = null    // a different login in this tab gets a new socket
let status: LiveStatus = 'offline'
let attempt = 0
let retryTimer: ReturnType<typeof setTimeout> | undefined
let closeTimer: ReturnType<typeof setTimeout> | undefined

function setStatus(next: LiveStatus) {
  status = next
  subscribers.forEach((s) => s.onStatus(next))
}

function schedule() {
  if (subscribers.size === 0) return
  const delay = Math.min(30_000, 1000 * 2 ** attempt) * (0.75 + Math.random() * 0.5)
  attempt += 1
  retryTimer = setTimeout(connect, delay)
}

function connect() {
  clearTimeout(retryTimer)
  const token = getToken()
  if (!token) {
    setStatus('offline')
    return
  }
  setStatus('connecting')
  const ws = new WebSocket(getEventsSocketUrl())
  socket = ws
  socketToken = token
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }))
  ws.onmessage = (message) => {
    let event: { type: string }
    try {
      event = JSON.parse(message.data) as { type: string }
    } catch {
      return
    }
    if (event.type === 'ready') {
      attempt = 0
      setStatus('live')
      subscribers.forEach((s) => s.onSync())
    } else if (event.type !== 'ping' && event.type !== 'error') {
      subscribers.forEach((s) => s.onEvent(event as LiveEvent))
    }
  }
  ws.onclose = () => {
    if (socket !== ws) return          // an old socket closing after a reconnect
    socket = null
    setStatus('offline')
    schedule()
  }
  ws.onerror = () => ws.close()
}

function subscribe(sub: Subscriber) {
  clearTimeout(closeTimer)
  subscribers.add(sub)
  sub.onStatus(status)
  if (socket && socketToken !== getToken()) {
    const old = socket
    socket = null
    old.close()
  }
  if (!socket) connect()
  else if (status === 'live') sub.onSync()
}

function unsubscribe(sub: Subscriber) {
  subscribers.delete(sub)
  if (subscribers.size > 0) return
  closeTimer = setTimeout(() => {
    if (subscribers.size > 0) return
    clearTimeout(retryTimer)
    const ws = socket
    socket = null
    ws?.close()
    status = 'offline'
  }, CLOSE_GRACE_MS)
}

export function useLiveEvents(onEvent: (event: LiveEvent) => void, onSync: () => void): LiveStatus {
  const [state, setState] = useState<LiveStatus>(status)
  const handlers = useRef({ onEvent, onSync })
  handlers.current = { onEvent, onSync }

  useEffect(() => {
    const sub: Subscriber = {
      onEvent: (event) => handlers.current.onEvent(event),
      onSync: () => handlers.current.onSync(),
      onStatus: setState,
    }
    subscribe(sub)
    return () => unsubscribe(sub)
  }, [])

  return state
}
