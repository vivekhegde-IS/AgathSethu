import React, { useEffect } from 'react'
import { useCameraStore } from '@stores/cameraStore'
import { Card, Table, Badge, Button, Column } from '@components/ui'

export const CameraManagement: React.FC = () => {
  const { cameras, fetchCameras, toggleCameraStatus } = useCameraStore()

  useEffect(() => {
    fetchCameras()
  }, [fetchCameras])

  const columns: Column<(typeof cameras)[0]>[] = [
    {
      header: 'CAMERA ID',
      cell: (row) => <span className="font-mono font-semibold text-cyan-400">{row.camera_id}</span>,
    },
    {
      header: 'PLACEMENT / LOCATION',
      cell: (row) => (
        <div>
          <p className="text-white text-xs">{row.location.description}</p>
          <p className="text-[10px] text-slate-400 font-mono">
            X:{row.location.x} Y:{row.location.y} Z:{row.location.z}m
          </p>
        </div>
      ),
    },
    {
      header: 'RESOLUTION / FPS',
      cell: (row) => (
        <span className="font-mono text-slate-300">
          {row.specifications.resolution} @ {row.specifications.frame_rate}Hz (FOV {row.specifications.fov}°)
        </span>
      ),
    },
    {
      header: 'STATUS',
      cell: (row) => (
        <Badge variant={row.status === 'active' ? 'success' : 'danger'} size="sm">
          {row.status}
        </Badge>
      ),
    },
    {
      header: 'ACTION',
      className: 'text-right',
      cell: (row) => (
        <Button
          variant={row.status === 'active' ? 'secondary' : 'primary'}
          size="sm"
          onClick={() => toggleCameraStatus(row.camera_id)}
        >
          {row.status === 'active' ? 'Disable' : 'Enable'}
        </Button>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold font-mono text-white">Camera Sensor Network</h2>
        <p className="text-xs text-slate-400 font-mono">
          Hardware status, frame rate specifications, and live health of high-speed ANPR optical sensors.
        </p>
      </div>

      <Card title="Camera Registry">
        <Table
          columns={columns}
          data={cameras}
          keyExtractor={(row) => row.camera_id}
        />
      </Card>
    </div>
  )
}
