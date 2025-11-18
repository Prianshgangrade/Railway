export default function Platform({ name, platformData, onUnassignPlatform }) {
  if (!platformData) {
    return (
      <div className="bg-gray-200 px-3 py-2 rounded-lg shadow-sm border-l-4 border-gray-300 animate-pulse">
        <h4 className="font-bold text-md text-gray-500">{name}</h4>
        <p className="text-xs text-gray-400">No data</p>
      </div>
    );
  }

  const { isUnderMaintenance, isOccupied, trainDetails, isTerminating, actualArrival } = platformData;
  const cardStyle = isUnderMaintenance ? 'bg-yellow-100 border-yellow-500' : isOccupied ? 'bg-green-500 text-white shadow-lg' : 'bg-white border-gray-300';
  const statusText = isUnderMaintenance ? 'Maintenance' : isOccupied ? 'Occupied' : 'Available';
  const statusBgColor = isUnderMaintenance ? 'bg-yellow-200 text-yellow-800' : isOccupied ? 'bg-green-200 text-green-800' : 'bg-gray-200 text-gray-800';

  return (
    <div className={`px-3 py-2 rounded-lg shadow-sm border-l-4 ${cardStyle} transition-all`}>
      <div className="flex justify-between items-center mb-0.5">
        <h4 className={`font-bold text-md ${isOccupied ? 'text-white' : 'text-gray-800'}`}>{name}</h4>
        <span className={`text-xs font-semibold px-2 py-1 rounded-full ${statusBgColor}`}>{statusText}</span>
      </div>
      {isOccupied && trainDetails ? (
        <div>
          <div className="flex justify-between items-center mt-0.5">
            <div className={`text-sm ${isOccupied ? 'text-green-100' : 'text-gray-700'} flex-1 min-w-0 mr-2`}>
              <p className="font-medium truncate">{trainDetails.trainNo} - {trainDetails.name}</p>
            </div>
            <button onClick={() => onUnassignPlatform(platformData.id, trainDetails)} className="bg-red-500 text-white text-xs font-bold py-0.5 px-2 rounded-md hover:bg-red-600 transition-all flex-shrink-0">Unassign</button>
          </div>
          {actualArrival && (
            <p className={`text-xs mt-0.5 font-semibold ${isOccupied ? 'text-green-200' : 'text-gray-600'}`}></p>
          )}
        </div>
      ) : <div className="h-6"></div>}
      <div className={`text-xs mt-1 flex justify-end ${isOccupied ? 'text-purple-200' : 'text-purple-700'}`}>
        {isTerminating && <span className="font-semibold">Terminating</span>}
      </div>
    </div>
  );
}
