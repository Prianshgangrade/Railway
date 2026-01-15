export default function WaitingList({ waitingList, onFindPlatform, onRemove }) {
  if (!waitingList || waitingList.length === 0) return null;
  return (
    <div className="w-full max-w-4xl mx-auto p-4 mb-4 bg-red-100 border border-red-300 rounded-xl shadow-lg">
      <h3 className="text-xl font-bold text-red-800 mb-3 text-center">Waiting List</h3>
      <div className="space-y-2">
        {waitingList.map(train => {
          const arrival = train.actualArrival || '—';
          const enqueued = train.enqueued_at ? new Date(train.enqueued_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
          const incomingLine = train.incoming_line || train.incomingLine || 'N/A';
          return (
            <div key={`${train.trainNo}-${train.enqueued_at || ''}`} className="p-3 bg-white rounded-lg shadow-sm">
              <div className="mb-3">
                <p className="font-bold text-gray-800">{train.trainNo} - {train.name}</p>
                <p className="text-sm text-gray-500">Actual Arrival: {arrival}{enqueued && ` • Queued: ${enqueued}`}</p>
                <p className="text-xs text-gray-600">Incoming Line: <span className="font-semibold">{incomingLine}</span></p>
              </div>
              <button
                onClick={() => onFindPlatform(train)}
                className="w-full bg-blue-600 text-white font-semibold px-4 py-2 rounded-md hover:bg-blue-700 transition-colors"
              >
                Find Platform
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
