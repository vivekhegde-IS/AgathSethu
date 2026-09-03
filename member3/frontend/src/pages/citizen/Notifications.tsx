import React from 'react'
import { Card, Badge, Button } from '@components/ui'

export const CitizenNotifications: React.FC = () => {
  const notifications = [
    {
      id: 'NOTIF-01',
      title: 'New Speeding Challan Generated (KA01MJ4582)',
      message:
        'A speed violation of 68.5 km/h was captured at Koramangala 80ft Road North Mast. Please review evidence.',
      time: '2 hours ago',
      type: 'violation',
      unread: true,
    },
    {
      id: 'NOTIF-02',
      title: 'FASTag Transponder Synced (EPC-3416FA)',
      message: 'Your RFID transponder was successfully verified across Koramangala 80ft Gantry 1.',
      time: '1 day ago',
      type: 'rfid',
      unread: false,
    },
    {
      id: 'NOTIF-03',
      title: 'PUC Renewal Reminder',
      message: 'Pollution Under Control certificate for vehicle KA05XY7711 is due in 45 days.',
      time: '3 days ago',
      type: 'reminder',
      unread: false,
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Citizen Alert Center</h2>
          <p className="text-xs text-slate-400 font-mono">
            Direct notifications regarding e-challans, FASTag crossings, and document renewals.
          </p>
        </div>
        <Button variant="secondary" size="sm">
          Mark All Read
        </Button>
      </div>

      <div className="space-y-3">
        {notifications.map((n) => (
          <Card key={n.id} className={n.unread ? 'border-aghat-blue/60 bg-blue-950/10' : ''}>
            <div className="flex items-start justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  {n.unread && (
                    <span className="w-2 h-2 rounded-full bg-aghat-blue animate-pulse" />
                  )}
                  <h4 className="text-sm font-semibold font-mono text-white">{n.title}</h4>
                </div>
                <p className="text-xs text-slate-300">{n.message}</p>
                <span className="text-[10px] font-mono text-slate-500 block pt-1">{n.time}</span>
              </div>
              <Badge variant={n.type === 'violation' ? 'danger' : 'info'} size="sm">
                {n.type.toUpperCase()}
              </Badge>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}
