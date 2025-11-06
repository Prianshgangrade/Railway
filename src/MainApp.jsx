import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Header from './components/Header';
import Track from './components/Track';
import Platform from './components/Platform';
import WaitingList from './components/WaitingList';
import Modal from './components/Modal';
import SuggestionModal from './components/modals/SuggestionModal';
import DepartingModal from './components/modals/DepartingModal';
import MaintenanceModal from './components/modals/MaintenanceModal';
import MiscModal from './components/modals/MiscModal';
import LogModal from './components/modals/LogModal';
import ReassignPromptModal from './components/modals/ReassignPromptModal';
import { apiUrl, eventSourceUrl } from './utils/api';
import { toast } from 'react-toastify';

// Modals extracted into separate components to preserve behavior and UI.

export default function MainApp() {
  const [platforms, setPlatforms] = useState([]);
  const [arrivingTrains, setArrivingTrains] = useState([]);
  const [waitingList, setWaitingList] = useState([]);
  const [activeModal, setActiveModal] = useState(null);
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState([]);
  const [reassignPrompt, setReassignPrompt] = useState({ isOpen: false, platformId: null, trainDetails: null });
  const [trainForImmediateSuggestion, setTrainForImmediateSuggestion] = useState(null);

  // Show all available trains for arrival; filtering will be handled by the search bar in SuggestionModal

  const fetchStationData = useCallback(async () => {
    try {
      const response = await fetch(apiUrl('/api/station-data'));
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      setPlatforms(data.platforms || []);
      setArrivingTrains(data.arrivingTrains || []);
      setWaitingList(data.waitingList || []);
    } catch (err) {
      console.error('Error fetching station data:', err);
      setError(err.message);
      toast.error(`Failed to load station data: ${err.message}`);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const response = await fetch(apiUrl('/api/logs'));
      if (!response.ok) throw new Error('Failed to fetch logs');
      const data = await response.json();
      setLogs(data);
    } catch (err) {
      toast.error(err.message);
    }
  }, []);

  useEffect(() => { fetchStationData(); }, [fetchStationData]);
  useEffect(() => { if (activeModal === 'logs') fetchLogs(); }, [activeModal, fetchLogs]);

  useEffect(() => {
    const sseUrl = eventSourceUrl('/api/stream');
    const eventSource = new EventSource(sseUrl);
    console.log('Connecting to SSE stream at:', sseUrl);
    eventSource.addEventListener('departure_alert', (event) => {
      const data = JSON.parse(event.data);
      toast.error(`DEPARTURE ALERT: Train ${data.train_number} (${data.train_name}) should depart from ${data.platform_id}`, { autoClose: false, position: 'top-right', toastId: `dep-${data.train_number}` });
    });
    eventSource.onerror = (err) => console.error('SSE Connection Error:', err);
    return () => eventSource.close();
  }, []);

  const handleApiCall = async (endpoint, body, successMsg) => {
    try {
      const response = await fetch(apiUrl(`/api/${endpoint}`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'An unknown error occurred.');
      toast.success(data.message || successMsg);
      await fetchStationData();
      return true;
    } catch (err) {
      console.error(`Error calling ${endpoint}:`, err);
      toast.error(err.message);
      return false;
    }
  };

  const promptForReassignment = (platformId, trainDetails) => {
    setReassignPrompt({ isOpen: true, platformId, trainDetails });
  };

  const handleUnassignPlatform = useCallback((platformId) => handleApiCall('unassign-platform', { platformId }, `Unassigning train from ${platformId}...`), []);
  const handleAssignPlatform = useCallback((trainNo, platformIds, actualArrival) => handleApiCall('assign-platform', { trainNo, platformIds, actualArrival }, `Assigning train ${trainNo}...`), []);
  const handleAddToWaitingList = useCallback((trainNo) => handleApiCall('add-to-waiting-list', { trainNo }, `Adding ${trainNo} to waiting list...`), []);
  const handleRemoveFromWaitingList = useCallback((trainNo) => handleApiCall('remove-from-waiting-list', { trainNo }, `Removing ${trainNo} from waiting list...`), []);
  const handleDepartTrain = useCallback((platformId) => handleApiCall('depart-train', { platformId }, `Departing train from ${platformId}...`), []);
  const handleToggleMaintenance = useCallback((platformId) => handleApiCall('toggle-maintenance', { platformId }, `Updating maintenance for ${platformId}...`), []);
  const handleAddTrain = useCallback((trainData) => handleApiCall('add-train', trainData, `Adding train ${trainData['TRAIN NO']}...`), []);
  const handleDeleteTrain = useCallback((trainNo) => handleApiCall('delete-train', { trainNo }, `Deleting train ${trainNo}...`), []);

  const platformMap = new Map(platforms.map(p => [p.id, p]));

  return (
    <div className="bg-gray-100 min-h-screen text-gray-800" style={{ fontFamily: "'Inter', sans-serif" }}>
      <div className="container mx-auto p-4 md:p-8">
        <Header />
        <div className="w-full max-w-4xl mx-auto p-6 space-y-3 bg-gray-200 rounded-xl shadow-lg">
          <div className="mb-6">
            <nav className="flex gap-0 justify-center bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
              <button onClick={() => setActiveModal('suggestions')} className="flex-1 px-4 py-3 bg-orange-100 text-orange-800 hover:bg-orange-200 transition-colors border-r border-gray-200 font-semibold">Arriving trains</button>
              <button onClick={() => setActiveModal('departing')} className="flex-1 px-4 py-3 bg-blue-100 text-blue-800 hover:bg-blue-200 transition-colors border-r border-gray-200 font-semibold">Departing trains</button>
              <button onClick={() => setActiveModal('maintenance')} className="flex-1 px-4 py-3 bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors border-r border-gray-200 font-semibold">Maintenance</button>
              <button onClick={() => setActiveModal('misc')} className="flex-1 px-4 py-3 bg-purple-100 text-purple-800 hover:bg-purple-200 transition-colors border-r border-gray-200 font-semibold">Miscellaneous</button>
              <button onClick={() => setActiveModal('logs')} className="flex-1 px-4 py-3 bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors font-semibold">View Logs</button>
            </nav>
          </div>

          <WaitingList waitingList={waitingList} onFindPlatform={(train) => { setTrainForImmediateSuggestion(train); setActiveModal('suggestions'); }} onRemove={handleRemoveFromWaitingList} />

          <Track number="1" trackData={platformMap.get('Track 1')} onUnassignPlatform={promptForReassignment} />
          <Track number="2" trackData={platformMap.get('Track 2')} onUnassignPlatform={promptForReassignment} />
          <Track number="3" trackData={platformMap.get('Track 3')} onUnassignPlatform={promptForReassignment} />
          <Track number="4" trackData={platformMap.get('Track 4')} onUnassignPlatform={promptForReassignment} />

          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 1" platformData={platformMap.get('Platform 1')} onUnassignPlatform={promptForReassignment} />
            <Platform name="Platform 3" platformData={platformMap.get('Platform 3')} onUnassignPlatform={promptForReassignment} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 1A" platformData={platformMap.get('Platform 1A')} onUnassignPlatform={promptForReassignment} />
            <Platform name="Platform 3A" platformData={platformMap.get('Platform 3A')} onUnassignPlatform={promptForReassignment} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 2A" platformData={platformMap.get('Platform 2A')} onUnassignPlatform={promptForReassignment} />
            <Platform name="Platform 4A" platformData={platformMap.get('Platform 4A')} onUnassignPlatform={promptForReassignment} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 2" platformData={platformMap.get('Platform 2')} onUnassignPlatform={promptForReassignment} />
            <Platform name="Platform 4" platformData={platformMap.get('Platform 4')} onUnassignPlatform={promptForReassignment} />
          </div>

          <Platform name="Platform 5" platformData={platformMap.get('Platform 5')} onUnassignPlatform={promptForReassignment} />
          <Platform name="Platform 6" platformData={platformMap.get('Platform 6')} onUnassignPlatform={promptForReassignment} />
          <Platform name="Platform 7" platformData={platformMap.get('Platform 7')} onUnassignPlatform={promptForReassignment} />
          <Platform name="Platform 8" platformData={platformMap.get('Platform 8')} onUnassignPlatform={promptForReassignment} />

          <Track number="5" trackData={platformMap.get('Track 5')} onUnassignPlatform={promptForReassignment} />
          <Track number="6" trackData={platformMap.get('Track 6')} onUnassignPlatform={promptForReassignment} />
          <Track number="7" trackData={platformMap.get('Track 7')} onUnassignPlatform={promptForReassignment} />
          <Track number="8" trackData={platformMap.get('Track 8')} onUnassignPlatform={promptForReassignment} />
          <Track number="9" trackData={platformMap.get('Track 9')} onUnassignPlatform={promptForReassignment} />
          <Track number="10" trackData={platformMap.get('Track 10')} onUnassignPlatform={promptForReassignment} />
          <Track number="11" trackData={platformMap.get('Track 11')} onUnassignPlatform={promptForReassignment} />
          <Track number="12" trackData={platformMap.get('Track 12')} onUnassignPlatform={promptForReassignment} />
        </div>
      </div>
      {/* --- Modals --- */}
      <SuggestionModal
        isOpen={activeModal === 'suggestions'}
        onClose={() => { setActiveModal(null); setTrainForImmediateSuggestion(null); }}
        arrivingTrains={[...arrivingTrains, ...waitingList]}
        platforms={platforms}
        onAssignPlatform={handleAssignPlatform}
        trainToReassign={trainForImmediateSuggestion}
        onAddToWaitingList={handleAddToWaitingList}
      />
      <DepartingModal isOpen={activeModal === 'departing'} onClose={() => setActiveModal(null)} platforms={platforms} onDepartTrain={handleDepartTrain} />
      <MaintenanceModal isOpen={activeModal === 'maintenance'} onClose={() => setActiveModal(null)} platforms={platforms} onToggleMaintenance={handleToggleMaintenance} />
      <MiscModal isOpen={activeModal === 'misc'} onClose={() => setActiveModal(null)} arrivingTrains={arrivingTrains} onAddTrain={handleAddTrain} onDeleteTrain={handleDeleteTrain} />
      <LogModal isOpen={activeModal === 'logs'} onClose={() => setActiveModal(null)} logs={logs} />
      <ReassignPromptModal
        reassignPrompt={reassignPrompt}
        onCancel={() => setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null })}
        onConfirmAddToWaitingList={async () => {
          const { platformId, trainDetails } = reassignPrompt;
          const success = await handleUnassignPlatform(platformId);
          if (success && trainDetails?.trainNo) {
            await handleAddToWaitingList(trainDetails.trainNo);
          }
          setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null });
        }}
        onConfirmReassign={async () => { const { platformId, trainDetails } = reassignPrompt; const success = await handleUnassignPlatform(platformId); if (success) { setTrainForImmediateSuggestion(trainDetails); setActiveModal('suggestions'); } setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null }); }}
      />
    </div>
  );
}
