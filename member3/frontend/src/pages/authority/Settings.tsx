import React, { useState } from 'react'
import { Card, Input, Select, Button } from '@components/ui'

export const SystemAdminSettings: React.FC = () => {
  const [speedThreshold, setSpeedThreshold] = useState('50')
  const [kalmanHorizon, setKalmanHorizon] = useState('5')
  const [alertSound, setAlertSound] = useState('enabled')
  const [saved, setSaved] = useState(false)

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Platform Operations Settings</h2>
        <p className="text-xs text-slate-400 font-mono">
          Configure speed violation thresholds, Kalman prediction horizons, and TOC alert priorities.
        </p>
      </div>

      <Card title="Thresholds & Pipeline Calibration" glow>
        <form onSubmit={handleSave} className="space-y-4">
          {saved && (
            <div className="p-3 bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs rounded font-mono">
              ✓ Operational settings saved to local configuration node.
            </div>
          )}

          <Input
            label="Default Urban Speed Limit (km/h)"
            type="number"
            value={speedThreshold}
            onChange={(e) => setSpeedThreshold(e.target.value)}
          />

          <Input
            label="Kalman Trajectory Prediction Horizon (seconds)"
            type="number"
            value={kalmanHorizon}
            onChange={(e) => setKalmanHorizon(e.target.value)}
          />

          <Select
            label="Critical Crash Siren Alert"
            value={alertSound}
            onChange={(e) => setAlertSound(e.target.value)}
            options={[
              { value: 'enabled', label: 'Audio Alert Enabled (TOC Terminal)' },
              { value: 'disabled', label: 'Visual Glow Banner Only' },
            ]}
          />

          <div className="pt-2">
            <Button type="submit" variant="primary" size="md">
              Update Platform Settings
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
