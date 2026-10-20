/**
 * Footer information pages: Privacy Policy, Terms of Use, Accessibility
 * Statement, Help & Contact. Plain placeholders describing what the portal
 * actually does; no invented contact numbers or addresses.
 */

import React from 'react'
import { Link } from 'react-router-dom'

type Section = { heading: string; body: React.ReactNode }

const PAGES: Record<string, { title: string; sections: Section[] }> = {
  privacy: {
    title: 'Privacy Policy',
    sections: [
      {
        heading: 'What this portal stores',
        body: (
          <ul className="list-disc pl-5 space-y-1">
            <li>Account details you provide: name, email address and mobile number.</li>
            <li>Vehicle registration numbers linked to your account.</li>
            <li>E-challans issued to those vehicles, with the evidence image recorded for each violation.</li>
            <li>Records of fine payments made through the portal, with their receipt numbers.</li>
            <li>Crash incident records in which a registered vehicle was involved, and the notifications sent about them.</li>
          </ul>
        ),
      },
      {
        heading: 'Who can see it',
        body: 'A citizen sees only their own account, vehicles, challans, payments and notifications. Camera evidence and incident records are visible only to signed-in authority officers.',
      },
      {
        heading: 'Status of this policy',
        body: 'This is a placeholder policy for the current version of the portal. The final policy will be published here by the operating authority.',
      },
    ],
  },
  terms: {
    title: 'Terms of Use',
    sections: [
      {
        heading: 'Use of the portal',
        body: 'Use your own account only and keep your password private. Authority accounts are for authorised officers and are activated only after administrator approval.',
      },
      {
        heading: 'Payments',
        body: 'Payment of a fine is recorded against the challan and a receipt number is issued. Keep the receipt number for any query about the payment.',
      },
      {
        heading: 'Status of these terms',
        body: 'These are placeholder terms for the current version of the portal. The final terms will be published here by the operating authority.',
      },
    ],
  },
  accessibility: {
    title: 'Accessibility Statement',
    sections: [
      {
        heading: 'Our aim',
        body: 'The portal aims to meet WCAG 2.1 Level AA. Pages use plain language, keyboard-reachable controls, visible focus outlines and a "Skip to main content" link.',
      },
      {
        heading: 'Known limitations',
        body: 'Live camera video and evidence images cannot be fully described for screen-reader users. Text summaries (plates, time, location, status) are provided next to them.',
      },
      {
        heading: 'Feedback',
        body: (
          <>
            If you face a barrier on this portal, report it through the <Link to="/help" className="text-blue-900 underline">Help &amp; Contact</Link> page.
          </>
        ),
      },
    ],
  },
  help: {
    title: 'Help & Contact',
    sections: [
      {
        heading: 'Citizens',
        body: 'Sign in with Citizen Login to see challans for your vehicles, pay them, and view receipts and notifications. If a challan or a crash notification looks wrong, quote its challan number or incident reference when contacting the traffic authority.',
      },
      {
        heading: 'Officers',
        body: 'Sign in with Authority Login. If you cannot sign in, ask your administrator to check that your account is approved and active.',
      },
      {
        heading: 'Contact details',
        body: 'Helpline and office contact details will be published here by the operating authority.',
      },
    ],
  },
}

export const InfoPage: React.FC<{ page: keyof typeof PAGES }> = ({ page }) => {
  const content = PAGES[page]
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10">
      <Link to="/" className="text-sm text-blue-900 hover:underline">
        ← Back to portal home
      </Link>
      <article className="mt-3 bg-white border border-slate-200 rounded-lg shadow-sm px-6 py-6">
        <h1 className="text-2xl font-semibold text-blue-950">{content.title}</h1>
        <div className="mt-4 space-y-5 text-sm text-slate-700 leading-relaxed">
          {content.sections.map((section) => (
            <section key={section.heading}>
              <h2 className="text-base font-semibold text-slate-900">{section.heading}</h2>
              <div className="mt-1">{section.body}</div>
            </section>
          ))}
        </div>
      </article>
    </div>
  )
}
