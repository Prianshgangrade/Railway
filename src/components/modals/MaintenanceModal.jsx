import React from 'react';
import Modal from '../Modal';

export default function MaintenanceModal({ isOpen, onClose, platforms, onToggleMaintenance }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Manage Track Maintenance">
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {platforms.map(p => (
          <div key={p.id} className="flex justify-between items-center p-3 bg-gray-50 rounded-md border">
            <span className="font-medium">{p.id}</span>
            <label className="inline-flex items-center cursor-pointer">
              <input type="checkbox" checked={p.isUnderMaintenance} onChange={() => onToggleMaintenance(p.id)} disabled={p.isOccupied} className="sr-only peer" />
              <div className="relative w-11 h-6 bg-gray-200 rounded-full peer peer-focus:ring-4 peer-focus:ring-yellow-300 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-yellow-400"></div>
              <span className="ms-3 text-sm font-medium text-gray-900">{p.isOccupied ? '(Occupied)' : ''}</span>
            </label>
          </div>
        ))}
      </div>
      <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">Done</button>
    </Modal>
  );
}
