/**
 * Shown for any URL that does not match a route, instead of silently
 * redirecting to the home page (e.g. a mistyped or outdated link).
 */

import { Link, useLocation } from 'react-router-dom'

export function NotFound() {
  const { pathname } = useLocation()

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-16 text-center">
      <p className="text-sm font-semibold text-blue-900">Error 404</p>
      <h1 className="mt-2 text-2xl sm:text-3xl font-bold text-slate-900">Page not found</h1>
      <p className="mt-4 text-slate-600">
        The page <span className="font-mono break-all text-slate-800">{pathname}</span> does not exist
        or may have been moved.
      </p>
      <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
        <Link
          to="/"
          className="px-5 py-2.5 rounded bg-blue-900 text-white font-medium hover:bg-blue-800"
        >
          Go to home page
        </Link>
        <Link
          to="/help"
          className="px-5 py-2.5 rounded border border-slate-300 bg-white text-slate-800 font-medium hover:bg-slate-50"
        >
          Help &amp; Contact
        </Link>
      </div>
    </div>
  )
}
