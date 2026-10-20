/**
 * <img> for protected backend images: fetched with the login token (an <img>
 * tag cannot send it) and shown from an object URL that is revoked on unmount.
 */

import React, { useEffect, useState } from 'react'
import { fetchProtectedBlobUrl } from '@api/portal'

export interface AuthImageProps extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  /** API URL as returned by the backend, e.g. /api/incidents/{id}/evidence/{eid} */
  src: string | null | undefined
  fallback?: React.ReactNode
}

const UNAVAILABLE = (
  <div className="flex min-h-[4rem] items-center justify-center rounded border border-dashed border-slate-300 bg-slate-50 px-2 text-xs text-slate-500">
    Image unavailable
  </div>
)

export const AuthImage: React.FC<AuthImageProps> = ({ src, fallback = UNAVAILABLE, alt = '', ...props }) => {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let objectUrl: string | null = null
    let cancelled = false
    setUrl(null)
    setFailed(false)
    if (!src) return
    fetchProtectedBlobUrl(src)
      .then((value) => {
        if (cancelled) URL.revokeObjectURL(value)
        else {
          objectUrl = value
          setUrl(value)
        }
      })
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [src])

  if (!src || failed) return <>{fallback}</>
  if (!url) return <div className={`animate-pulse bg-slate-200 ${props.className ?? ''}`} aria-busy="true" />
  return <img src={url} alt={alt} {...props} />
}
