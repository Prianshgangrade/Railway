import React from 'react';
import Modal from '../Modal';

export default function LogModal({ isOpen, onClose, logs }) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Operational Logs">
      <div className="space-y-2 max-h-[60vh] overflow-y-auto">
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
    </Modal>
  );
}
