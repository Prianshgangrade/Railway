import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Modal from '../Modal';
import { apiUrl } from '../../utils/api';

const DEFAULT_LINES = [
  'HWH UP', 'HWH MID', 'HWH DN', 'MDN UP', 'MDN MID', 'MDN DN', 'TATA UP', 'TATA DN', 'BHC UP', 'BHC DN'
];

export default function DepartingModal({ isOpen, onClose, platforms, onDepartTrain, onlyPlatformId = null }) {
  // Default: show only primary occupied platforms (where user assigned) or single-platform trains.
  // But if the modal is opened for a specific platform (per-card Depart), show that platform
  // even if it's the secondary linked platform.
  const occupiedPlatforms = platforms
    .filter(p => p && p.isOccupied && !p.isUnderMaintenance)
    .filter(p => {
      if (onlyPlatformId) return p.id === onlyPlatformId;
      const td = p.trainDetails || {};
      if (td.isPrimary) return true;
      if (!td.linkedPlatformId) return true;
      return false;
    });
  const [selectedLineByPlatform, setSelectedLineByPlatform] = useState({});
  const [lineOptions, setLineOptions] = useState(DEFAULT_LINES);

  const loadLines = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/incoming-lines'));
      if (!res.ok) throw new Error('Failed to load lines');
      const data = await res.json();
      if (Array.isArray(data) && data.length) setLineOptions(data);
    } catch (e) {
      // keep defaults on failure
      console.warn('Using default line list; fetch failed.', e);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      // Reset selection each time the modal is opened (and when opened for a different platform)
      setSelectedLineByPlatform({});
      loadLines();
    }
  }, [isOpen, onlyPlatformId, loadLines]);

  const handleLogAndDepart = async (platformId) => {
    const chosen = selectedLineByPlatform[platformId] || '';
    if (!chosen) return; // simple guard; could show a toast if needed
    onDepartTrain(platformId, chosen);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Depart Train from Platform">
      <div className="space-y-3">
        {occupiedPlatforms.length > 0 ? (
          occupiedPlatforms.map(p => (
            <div key={p.id} className="p-3 bg-gray-100 rounded-md">
              <div className="flex justify-between items-center">
                <div>
                  <p className="font-semibold">{p.id}: {p.trainDetails.trainNo}</p>
                  <p className="text-sm text-gray-600">{p.trainDetails.name}</p>
                </div>
              </div>
              <div className="mt-2 flex gap-2 items-center">
                <select
                  value={selectedLineByPlatform[p.id] || ''}
                  onChange={(e) => setSelectedLineByPlatform(prev => ({ ...prev, [p.id]: e.target.value }))}
                  className="flex-1 p-2 border rounded-md"
                >
                  <option value="" disabled>Select departure line...</option>
                  {lineOptions.map(line => (
                    <option key={line} value={line}>{line}</option>
                  ))}
                </select>
                <button
                  onClick={() => handleLogAndDepart(p.id)}
                  disabled={!selectedLineByPlatform[p.id]}
                  className="btn-depart bg-red-500 disabled:bg-gray-400 text-white px-4 py-1 rounded-md hover:bg-red-600 transition text-sm"
                >
                  Depart
                </button>
              </div>
            </div>
          ))
        ) : (
          null
        )}
      </div>
      <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">Close</button>
    </Modal>
  );
}
