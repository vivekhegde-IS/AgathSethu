import React, { useState } from 'react'
import { useVehicleStore, CitizenVehicle } from '@stores/vehicleStore'
import { Card, Button, Badge, Modal, Input, Select } from '@components/ui'

export const CitizenVehicles: React.FC = () => {
  const { citizenVehicles, addCitizenVehicle } = useVehicleStore()
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [regNo, setRegNo] = useState('')
  const [model, setModel] = useState('')
  const [vType, setVType] = useState<'car' | 'motorcycle' | 'truck' | 'bus'>('car')
  const [chassis, setChassis] = useState('')

  const handleAddVehicle = (e: React.FormEvent) => {
    e.preventDefault()
    if (!regNo) return
    const newVeh: CitizenVehicle = {
      vehicleId: `VEH-${regNo.replace(/\s+/g, '')}`,
      registrationNumber: regNo.toUpperCase(),
      model: model || 'Registered Private Vehicle',
      vehicleType: vType,
      rfidTag: `EPC-${Math.floor(100000 + Math.random() * 900000)}-${regNo.toUpperCase()}`,
      chassisNumber: chassis || 'MALC99812903123',
      pucExpiry: '2027-04-01',
      insuranceExpiry: '2027-04-01',
      activeViolationsCount: 0,
    }
    addCitizenVehicle(newVeh)
    setIsModalOpen(false)
    setRegNo('')
    setModel('')
    setChassis('')
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold font-mono text-white">Registered Vehicles & FASTag</h2>
          <p className="text-xs text-slate-400 font-mono">
            Manage your vehicles, FASTag RFID binding, and view compliance status.
          </p>
        </div>
        <Button variant="primary" size="sm" onClick={() => setIsModalOpen(true)}>
          + Add New Vehicle
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {citizenVehicles.map((veh) => (
          <Card key={veh.vehicleId} glow className="relative">
            <div className="flex items-start justify-between border-b border-slate-800 pb-3 mb-3">
              <div>
                <span className="font-mono text-lg font-bold text-white tracking-wide">{veh.registrationNumber}</span>
                <p className="text-xs text-slate-400 font-medium">{veh.model}</p>
              </div>
              <Badge variant={veh.activeViolationsCount > 0 ? 'warning' : 'success'} size="md">
                {veh.vehicleType.toUpperCase()}
              </Badge>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs font-mono py-2">
              <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">FASTag EPC Code</span>
                <span className="text-cyan-300 font-semibold">{veh.rfidTag}</span>
              </div>
              <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Chassis Number</span>
                <span className="text-slate-300 truncate block">{veh.chassisNumber}</span>
              </div>
              <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">PUC Certificate</span>
                <span className="text-emerald-400">Valid till {veh.pucExpiry}</span>
              </div>
              <div className="p-2.5 bg-[#121820] rounded border border-slate-800">
                <span className="text-[10px] text-slate-500 uppercase block">Motor Insurance</span>
                <span className="text-emerald-400">Valid till {veh.insuranceExpiry}</span>
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-xs font-mono">
              <span className="text-slate-400">
                Challans: <strong className="text-white">{veh.activeViolationsCount} Pending</strong>
              </span>
              <span className="text-emerald-400">✓ RFID Telemetry Synced</span>
            </div>
          </Card>
        ))}
      </div>

      {/* Add Vehicle Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Register Vehicle with FASTag"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setIsModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={handleAddVehicle}>
              Save Vehicle
            </Button>
          </>
        }
      >
        <form onSubmit={handleAddVehicle} className="space-y-4">
          <Input
            label="Registration Number (Plate #)"
            placeholder="e.g. KA01MJ4582"
            value={regNo}
            onChange={(e) => setRegNo(e.target.value.toUpperCase())}
            required
          />
          <Input
            label="Make & Model"
            placeholder="e.g. Hyundai Creta 1.5 Diesel"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            required
          />
          <Select
            label="Vehicle Category"
            value={vType}
            onChange={(e) => setVType(e.target.value as 'car' | 'motorcycle' | 'truck' | 'bus')}
            options={[
              { value: 'car', label: 'Car / LMV / SUV' },
              { value: 'motorcycle', label: 'Motorcycle / Two-Wheeler' },
              { value: 'truck', label: 'Commercial Truck / HGV' },
              { value: 'bus', label: 'Passenger Bus' },
            ]}
          />
          <Input
            label="Chassis Number"
            placeholder="e.g. MALC141EALM829103"
            value={chassis}
            onChange={(e) => setChassis(e.target.value.toUpperCase())}
          />
        </form>
      </Modal>
    </div>
  )
}
