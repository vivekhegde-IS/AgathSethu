import React, { ReactNode } from 'react'

export interface TabItem {
  id: string
  label: ReactNode
  count?: number
  icon?: ReactNode
}

export interface TabsProps {
  tabs: TabItem[]
  activeTab: string
  onChange: (tabId: string) => void
  className?: string
}

export const Tabs: React.FC<TabsProps> = ({ tabs, activeTab, onChange, className = '' }) => {
  return (
    <div className={`flex border-b border-slate-200 space-x-1 ${className}`}>
      {tabs.map((tab) => {
        const isActive = tab.id === activeTab
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`inline-flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all -mb-px ${
              isActive
                ? 'border-blue-900 text-blue-900 bg-blue-50'
                : 'border-transparent text-slate-600 hover:text-blue-900 hover:border-slate-300'
            }`}
          >
            {tab.icon}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono ${
                  isActive ? 'bg-blue-100 text-blue-800' : 'bg-slate-100 text-slate-600'
                }`}
              >
                {tab.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
