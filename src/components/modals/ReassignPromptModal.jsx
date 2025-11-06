import React from 'react';

export default function ReassignPromptModal({ reassignPrompt, onCancel, onConfirmAddToWaitingList, onConfirmReassign }) {
  if (!reassignPrompt.isOpen) return null;
  return (
    <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center p-4 z-50">
      <div className="bg-white p-6 rounded-lg shadow-xl text-center max-w-sm w-full">
        <h4 className="text-lg font-bold mb-2">Remove Train</h4>
        <p className="mb-1">
          You are about to unassign train 
          <span className="font-bold mx-1">{reassignPrompt.trainDetails.trainNo}</span>
          from 
          <span className="font-bold mx-1">{reassignPrompt.platformId}</span>.
        </p>
        <p className="text-gray-600 mb-6">Do you want to find a new platform for this train immediately?</p>
        <div className="flex justify-center gap-4">
          <button onClick={onConfirmAddToWaitingList} className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700">Add to Waiting List</button>
          <button onClick={onConfirmReassign} className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">Yes, Re-assign</button>
        </div>
        <button onClick={onCancel} className="mt-4 text-sm text-gray-500 hover:underline">Cancel</button>
      </div>
    </div>
  );
}
