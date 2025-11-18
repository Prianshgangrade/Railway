import React, { useState } from 'react';
import Modal from '../Modal';
import { reportDownloadUrl } from '../../utils/api';

export default function LogModal({ isOpen, onClose, logs }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0,10));
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Operational Logs">
      <div className="space-y-2">
        <div className="flex items-center gap-3 mb-3">
          <label className="text-sm font-medium">Select date:</label>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="p-2 border rounded-md" />
          <button onClick={() => window.open(reportDownloadUrl(date), '_blank')} className="ml-2 bg-blue-600 text-white px-3 py-2 rounded-md">Download CSV</button>
        </div>
        <div className="space-y-2 max-h-[54vh] overflow-y-auto">
        {logs.length > 0 ? (
          logs.map((log, index) => (
            <div key={index} className="p-3 bg-gray-50 rounded-md border-l-4 border-gray-300">
              <p className="text-sm text-gray-800">{log.action}</p>
              <p className="text-xs text-gray-500 mt-1">{log.timestamp}</p>
            </div>
          ))
        ) : (
          <p className="text-center text-gray-500 p-4">No log entries found.</p>
        )}
        </div>
      </div>
    </Modal>
  );
}
