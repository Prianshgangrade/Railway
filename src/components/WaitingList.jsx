export default function WaitingList({ waitingList, onFindPlatform, onRemove }) {
  if (!waitingList || waitingList.length === 0) return null;
  return (
    <div className="w-full max-w-4xl mx-auto p-4 mb-4 bg-red-100 border border-red-300 rounded-xl shadow-lg">
      <h3 className="text-xl font-bold text-red-800 mb-3 text-center">Waiting List</h3>
      <div className="space-y-2">
        {waitingList.map(train => (
          <div key={train.trainNo} className="flex justify-between items-center p-3 bg-white rounded-lg shadow-sm">
            <div>
              <p className="font-bold text-gray-800">{train.trainNo} - {train.name}</p>
              <p className="text-sm text-gray-500">Scheduled: {train.scheduled_arrival ? `${train.scheduled_arrival} (Arr)` : `${train.scheduled_departure} (Dep)`}</p>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => onFindPlatform(train)} className="bg-blue-600 text-white font-semibold px-4 py-2 rounded-md hover:bg-blue-700 transition-colors">Find Platform</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
