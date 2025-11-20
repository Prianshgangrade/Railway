import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

const TRACK_LABELS = {
  'Track 1': 'Cuttuck 1',
  'Track 2': 'Cuttuck 2',
  'Track 3': 'Cuttuck 3',
  'Track 4': 'Midnapore 1',
  'Track 5': 'Midnapore 2',
  'Track 6': 'Midnapore 3',
};
const TRACK_GROUPS = [
  ['Track 1', 'Track 4'],
  ['Track 2', 'Track 5'],
  ['Track 3', 'Track 6'],
];

const normalizeTrainNo = (value) => (value === undefined || value === null ? '' : String(value));
const extractTrainNo = (entity) => normalizeTrainNo(entity?.trainNo ?? entity?.train_no ?? entity?.['TRAIN NO']);
const matchTrainNumber = (entity, target) => extractTrainNo(entity) === normalizeTrainNo(target);
const toIdArray = (value) => (Array.isArray(value) ? value : [value]).filter(Boolean);

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
  const [autoSuggestion, setAutoSuggestion] = useState(null); // automated suggestion from backend
  const latestFetchIdRef = useRef(0);
  const platformsRef = useRef(platforms);
  const arrivingTrainsRef = useRef(arrivingTrains);
  const waitingListRef = useRef(waitingList);

  // Show all available trains for arrival; filtering will be handled by the search bar in SuggestionModal

  const fetchStationData = useCallback(async () => {
    const fetchId = latestFetchIdRef.current + 1;
    latestFetchIdRef.current = fetchId;
    try {
      const response = await fetch(apiUrl('/api/station-data'));
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      if (fetchId !== latestFetchIdRef.current) return;
      setPlatforms(data.platforms || []);
      setArrivingTrains(data.arrivingTrains || []);
      setWaitingList(data.waitingList || []);
    } catch (err) {
      console.error('Error fetching station data:', err);
      if (fetchId === latestFetchIdRef.current) {
        setError(err.message);
        toast.error(`Failed to load station data: ${err.message}`);
      }
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

  useEffect(() => { platformsRef.current = platforms; }, [platforms]);
  useEffect(() => { arrivingTrainsRef.current = arrivingTrains; }, [arrivingTrains]);
  useEffect(() => { waitingListRef.current = waitingList; }, [waitingList]);

  useEffect(() => { fetchStationData(); }, [fetchStationData]);
  useEffect(() => { if (activeModal === 'logs') fetchLogs(); }, [activeModal, fetchLogs]);

  useEffect(() => {
    const sseUrl = eventSourceUrl('/api/stream');
    const es = new EventSource(sseUrl);
    console.log('Connecting to SSE stream at:', sseUrl);

    es.addEventListener('departure_alert', (event) => {
      try {
        const data = JSON.parse(event.data);
        toast.error(`DEPARTURE ALERT: Train ${data.train_number} (${data.train_name}) should depart from ${data.platform_id}`, { autoClose: false, position: 'top-right', toastId: `dep-${data.train_number}` });
      } catch (e) { console.warn('Bad departure_alert payload', e); }
    });

    es.addEventListener('waiting_suggestion', (event) => {
      try {
        const data = JSON.parse(event.data);
        setAutoSuggestion(data);
        toast.info(`Suggestion: Train ${data.trainNo} → ${data.suggestedPlatformIds.join(', ')}`);
      } catch (e) { console.warn('Bad waiting_suggestion payload', e); }
    });

    es.addEventListener('waiting_suggestion_expired', (event) => {
      try {
        const data = JSON.parse(event.data);
        if (autoSuggestion && data.suggestion_id === autoSuggestion.suggestion_id) {
          setAutoSuggestion(null);
          toast.warning('Suggestion expired');
        }
      } catch (e) { console.warn('Bad waiting_suggestion_expired payload', e); }
    });

    es.addEventListener('waiting_suggestion_accepted', async (event) => {
      try {
        const data = JSON.parse(event.data);
        toast.success(`Suggestion accepted: Train ${data.trainNo} assigned to ${data.platforms.join(', ')}`);
        setAutoSuggestion(null);
        await fetchStationData();
      } catch (e) { console.warn('Bad waiting_suggestion_accepted payload', e); }
    });

    es.onerror = (err) => console.error('SSE Connection Error:', err);
    return () => es.close();
  }, [fetchStationData, autoSuggestion]);

  const handleAcceptAutoSuggestion = async () => {
    if (!autoSuggestion) return;
    try {
      const response = await fetch(apiUrl('/api/accept-waiting-suggestion'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ suggestion_id: autoSuggestion.suggestion_id })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.error || 'Failed to accept suggestion');
      toast.success(data.message || 'Suggestion accepted');
      setAutoSuggestion(null);
      await fetchStationData();
    } catch (e) {
      toast.error(e.message);
    }
  };

  const lookupTrainByNumber = useCallback((trainNo) => {
    const target = normalizeTrainNo(trainNo);
    if (!target) return null;
    const fromArrivals = arrivingTrainsRef.current.find(train => extractTrainNo(train) === target);
    if (fromArrivals) return fromArrivals;
    return waitingListRef.current.find(train => extractTrainNo(train) === target) || null;
  }, []);

  const buildTrainDetails = useCallback((trainNo, overrides = {}, extras = {}) => {
    const fallback = lookupTrainByNumber(trainNo) || {};
    const resolvedIncoming = overrides.incomingLine || overrides.incoming_line || fallback.incoming_line || fallback.incomingLine || null;
    const resolvedArrival = overrides.actualArrival || overrides.actual_arrival || fallback.actualArrival || fallback.actual_arrival || null;
    const resolvedName = overrides.trainName || fallback.name || (trainNo ? `Train ${trainNo}` : 'Train');
    const terminating = overrides.isTerminating ?? fallback.isTerminating ?? fallback.ISTERMINATING ?? false;
    return {
      trainNo: trainNo || overrides.trainNo || fallback.trainNo || fallback.train_no || resolvedName,
      name: resolvedName,
      incomingLine: resolvedIncoming,
      incoming_line: resolvedIncoming,
      actualArrival: resolvedArrival,
      isTerminating: terminating,
        ...extras,
    };
  }, [lookupTrainByNumber]);

  const applyPlatformChanges = useCallback((targetIds, updater) => {
    const ids = toIdArray(targetIds);
    if (ids.length === 0) return;
    const idSet = new Set(ids);
    setPlatforms(prev => prev.map(platform => (idSet.has(platform.id) ? updater(platform) : platform)));
  }, []);

  const handleApiCall = useCallback(async (endpoint, body, successMsg, optimisticUpdate) => {
    const snapshot = optimisticUpdate ? {
      platforms: platformsRef.current,
      arrivingTrains: arrivingTrainsRef.current,
      waitingList: waitingListRef.current,
    } : null;
    if (optimisticUpdate) {
      try {
        optimisticUpdate();
      } catch (optimisticErr) {
        console.warn('Optimistic update failed:', optimisticErr);
      }
    }
    try {
      const response = await fetch(apiUrl(`/api/${endpoint}`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'An unknown error occurred.');
      toast.success(data.message || successMsg);
      fetchStationData();
      return true;
    } catch (err) {
      console.error(`Error calling ${endpoint}:`, err);
      if (snapshot) {
        setPlatforms(snapshot.platforms || []);
        setArrivingTrains(snapshot.arrivingTrains || []);
        setWaitingList(snapshot.waitingList || []);
      }
      toast.error(err.message);
      return false;
    }
  }, [fetchStationData]);

  const promptForReassignment = (platformId, trainDetails) => {
    setReassignPrompt({ isOpen: true, platformId, trainDetails });
  };

  const handleUnassignPlatform = useCallback((platformId) => handleApiCall(
    'unassign-platform',
    { platformId },
    `Unassigning train from ${platformId}...`,
    () => applyPlatformChanges(platformId, (platform) => ({ ...platform, isOccupied: false, trainDetails: null, actualArrival: null }))
  ), [handleApiCall, applyPlatformChanges]);

  const handleAssignPlatform = useCallback((trainNo, platformIds, actualArrival, incomingLine) => {
    const body = { trainNo, platformIds, actualArrival };
    if (incomingLine) body.incomingLine = incomingLine;
    const ids = toIdArray(platformIds);
    const arrivalTime = actualArrival || new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const linkedMeta = new Map();
    if (ids.length > 1) {
      ids.forEach((id, index) => {
        const partner = ids.find(otherId => otherId !== id);
        linkedMeta.set(id, { linkedPlatformId: partner || null, isPrimary: index === 0 });
      });
    } else if (ids.length === 1) {
      linkedMeta.set(ids[0], { linkedPlatformId: null, isPrimary: true });
    }
    return handleApiCall('assign-platform', body, `Assigning train ${trainNo}...`, () => {
      applyPlatformChanges(ids, (platform) => {
        const meta = linkedMeta.get(platform.id) || { linkedPlatformId: null, isPrimary: true };
        const trainDetails = buildTrainDetails(trainNo, { actualArrival: arrivalTime, incomingLine }, {
          linkedPlatformId: meta.linkedPlatformId,
          isPrimary: meta.isPrimary,
        });
        return {
          ...platform,
          isOccupied: true,
          isUnderMaintenance: false,
          trainDetails,
          actualArrival: arrivalTime,
        };
      });
      setWaitingList(prev => prev.filter(train => !matchTrainNumber(train, trainNo)));
      setArrivingTrains(prev => prev.filter(train => !matchTrainNumber(train, trainNo)));
    });
  }, [handleApiCall, applyPlatformChanges, buildTrainDetails]);

  const handleAssignFreightToPlatform = useCallback(({ platformId, incomingLine, trainName }) => {
    const body = {
      platformIds: [platformId],
      forceCreateFreight: true,
    };
    if (incomingLine) body.incomingLine = incomingLine;
    if (trainName) body.trainName = trainName;
    const placeholderTrainNo = trainName || `Freight-${platformId}`;
    return handleApiCall('assign-platform', body, `Assigning freight to ${platformId}...`, () => {
      const trainDetails = buildTrainDetails(placeholderTrainNo, { trainName: trainName || 'Freight Consist', incomingLine });
      applyPlatformChanges(platformId, (platform) => ({
        ...platform,
        isOccupied: true,
        isUnderMaintenance: false,
        trainDetails,
        actualArrival: null,
      }));
    });
  }, [handleApiCall, applyPlatformChanges, buildTrainDetails]);

  const handleAssignFreightToTrack = useCallback(({ trackId, incomingLine, trainName }) => {
    const body = { trackId };
    if (incomingLine) body.incomingLine = incomingLine;
    if (trainName) body.trainName = trainName;
    const placeholderTrainNo = trainName || `Freight-${trackId}`;
    return handleApiCall('assign-track', body, `Assigning freight to ${trackId}...`, () => {
      const trainDetails = buildTrainDetails(placeholderTrainNo, { trainName: trainName || `Freight @ ${trackId}`, incomingLine });
      applyPlatformChanges(trackId, (platform) => ({
        ...platform,
        isOccupied: true,
        isUnderMaintenance: false,
        trainDetails,
        actualArrival: null,
      }));
    });
  }, [handleApiCall, applyPlatformChanges, buildTrainDetails]);

  const handleAddToWaitingList = useCallback((trainNo, incomingLine, actualArrival, metadata = null) => {
    const body = { trainNo };
    if (incomingLine) body.incomingLine = incomingLine;
    if (actualArrival) body.actualArrival = actualArrival;
    // Debug: log the body so we can confirm frontend is sending incomingLine
    try { console.debug('AddToWaitingList body ->', body); } catch (e) {}
    return handleApiCall('add-to-waiting-list', body, `Adding ${trainNo} to waiting list...`, () => {
      const cachedTrain = metadata || lookupTrainByNumber(trainNo) || {};
      const enqueuedAt = new Date().toISOString();
      const arrivalDisplay = actualArrival || cachedTrain.actualArrival || cachedTrain.actual_arrival || new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
      const waitingEntry = {
        ...cachedTrain,
        trainNo,
        name: cachedTrain.name || `Train ${trainNo}`,
        incomingLine: incomingLine || cachedTrain.incomingLine || cachedTrain.incoming_line,
        incoming_line: incomingLine || cachedTrain.incoming_line,
        actualArrival: arrivalDisplay,
        enqueued_at: enqueuedAt,
      };
      setWaitingList(prev => {
        const hasTrain = prev.some(train => matchTrainNumber(train, trainNo));
        if (hasTrain) {
          return prev.map(train => (matchTrainNumber(train, trainNo) ? waitingEntry : train));
        }
        return [...prev, waitingEntry];
      });
      setArrivingTrains(prev => prev.filter(train => !matchTrainNumber(train, trainNo)));
    });
  }, [handleApiCall, lookupTrainByNumber]);

  const handleRemoveFromWaitingList = useCallback((trainNo) => handleApiCall(
    'remove-from-waiting-list',
    { trainNo },
    `Removing ${trainNo} from waiting list...`,
    () => setWaitingList(prev => prev.filter(train => !matchTrainNumber(train, trainNo)))
  ), [handleApiCall]);

  const resolveLinkedDepartureIds = useCallback((platformId) => {
    const primary = platformsRef.current.find(p => p?.id === platformId);
    if (!primary || !primary.isOccupied || !primary.trainDetails) {
      return [platformId];
    }
    const linkedId = primary.trainDetails.linkedPlatformId;
    if (linkedId) {
      return [platformId, linkedId];
    }
    const trainNo = primary.trainDetails.trainNo;
    if (!trainNo) {
      return [platformId];
    }
    const partner = platformsRef.current.find(p => p?.id !== platformId && p?.isOccupied && p?.trainDetails?.trainNo === trainNo);
    if (partner) {
      return [platformId, partner.id];
    }
    return [platformId];
  }, []);

  const handleDepartTrain = useCallback((platformId) => {
    const idsToClear = resolveLinkedDepartureIds(platformId);
    return handleApiCall(
      'depart-train',
      { platformId },
      `Departing train from ${platformId}...`,
      () => applyPlatformChanges(idsToClear, (platform) => ({ ...platform, isOccupied: false, trainDetails: null, actualArrival: null }))
    );
  }, [handleApiCall, applyPlatformChanges, resolveLinkedDepartureIds]);

  const handleToggleMaintenance = useCallback((platformId) => handleApiCall(
    'toggle-maintenance',
    { platformId },
    `Updating maintenance for ${platformId}...`,
    () => applyPlatformChanges(platformId, (platform) => {
      const nextMaintenance = !platform.isUnderMaintenance;
      return {
        ...platform,
        isUnderMaintenance: nextMaintenance,
        isOccupied: nextMaintenance ? false : platform.isOccupied,
        trainDetails: nextMaintenance ? null : platform.trainDetails,
      };
    })
  ), [handleApiCall, applyPlatformChanges]);

  const handleAddTrain = useCallback((trainData) => handleApiCall(
    'add-train',
    trainData,
    `Adding train ${trainData['TRAIN NO']}...`,
    () => {
      const normalized = {
        trainNo: trainData['TRAIN NO'],
        name: trainData['TRAIN NAME'],
        scheduled_arrival: trainData['ARRIVAL AT KGP'] || trainData['ARRIVAL'] || '',
        scheduled_departure: trainData['DEPARTURE FROM KGP'] || trainData['DEPARTURE'] || '',
        ISTERMINATING: trainData['ISTERMINATING'],
      };
      setArrivingTrains(prev => {
        const filtered = normalized.trainNo ? prev.filter(train => !matchTrainNumber(train, normalized.trainNo)) : prev;
        return [normalized, ...filtered];
      });
    }
  ), [handleApiCall]);

  const handleDeleteTrain = useCallback((trainNo) => handleApiCall(
    'delete-train',
    { trainNo },
    `Deleting train ${trainNo}...`,
    () => setArrivingTrains(prev => prev.filter(train => !matchTrainNumber(train, trainNo)))
  ), [handleApiCall]);

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

          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 1" platformData={platformMap.get('Platform 1')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
            <Platform name="Platform 3" platformData={platformMap.get('Platform 3')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 1A" platformData={platformMap.get('Platform 1A')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
            <Platform name="Platform 3A" platformData={platformMap.get('Platform 3A')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 2A" platformData={platformMap.get('Platform 2A')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
            <Platform name="Platform 4A" platformData={platformMap.get('Platform 4A')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Platform name="Platform 2" platformData={platformMap.get('Platform 2')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
            <Platform name="Platform 4" platformData={platformMap.get('Platform 4')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          </div>

          <Platform name="Platform 5" platformData={platformMap.get('Platform 5')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          <Platform name="Platform 6" platformData={platformMap.get('Platform 6')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          <Platform name="Platform 7" platformData={platformMap.get('Platform 7')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          <Platform name="Platform 8" platformData={platformMap.get('Platform 8')} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
          {TRACK_GROUPS.map(([leftId, rightId]) => (
            <div className="grid grid-cols-2 gap-3" key={`${leftId}-${rightId}`}>
              <Track label={TRACK_LABELS[leftId] || leftId} trackData={platformMap.get(leftId)} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
              <Track label={TRACK_LABELS[rightId] || rightId} trackData={platformMap.get(rightId)} onUnassignPlatform={promptForReassignment} onDepartTrain={handleDepartTrain} />
            </div>
          ))}
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
        onAssignFreightToPlatform={handleAssignFreightToPlatform}
        onAssignFreightToTrack={handleAssignFreightToTrack}
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
            const incomingLine = trainDetails?.incomingLine; // captured in Platform trainDetails if present
            await handleAddToWaitingList(trainDetails.trainNo, incomingLine, undefined, trainDetails);
          }
          setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null });
        }}
        onConfirmReassign={async () => { const { platformId, trainDetails } = reassignPrompt; const success = await handleUnassignPlatform(platformId); if (success) { setTrainForImmediateSuggestion(trainDetails); setActiveModal('suggestions'); } setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null }); }}
      />
      {/* Automated suggestion lightweight modal */}
      {autoSuggestion && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/40 z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md space-y-4">
            <h2 className="text-lg font-semibold text-gray-800">Platform Suggestion</h2>
            <p className="text-sm text-gray-700">
              Train <span className="font-semibold">{autoSuggestion.trainNo}</span> – {autoSuggestion.trainName}<br />
              Suggested Platform: <span className="font-semibold">{autoSuggestion.suggestedPlatformIds.join(', ')}</span>
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button onClick={() => setAutoSuggestion(null)} className="px-4 py-2 rounded-md border border-gray-300 text-gray-700 hover:bg-gray-100">Ignore</button>
              <button onClick={handleAcceptAutoSuggestion} className="px-4 py-2 rounded-md bg-green-600 text-white font-semibold hover:bg-green-700">Assign</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
