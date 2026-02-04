import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Modal from '../Modal';
import { apiUrl } from '../../utils/api';

export default function SuggestionModal({
  isOpen,
  onClose,
  arrivingTrains,
  platforms,
  onAssignPlatform,
  trainToReassign,
  onAddToWaitingList,
  onAssignFreightToPlatform,
  onAssignFreightToTrack,
}) {
  const [selectedTrain, setSelectedTrain] = useState(null);
  const [incomingLines, setIncomingLines] = useState([]);
  const [selectedIncomingLine, setSelectedIncomingLine] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [hasFetchedSuggestions, setHasFetchedSuggestions] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState('selection');
  const [mode, setMode] = useState('scheduled');
  const [freightNeedsPlatform, setFreightNeedsPlatform] = useState(null);
  const [loggedArrivalTime, setLoggedArrivalTime] = useState('');
  const [searchTerm, setSearchTerm] = useState('');
  const [freightIncomingLine, setFreightIncomingLine] = useState('');
  const [freightTarget, setFreightTarget] = useState('');
  const [freightPlatformId, setFreightPlatformId] = useState('');
  const [freightTrackId, setFreightTrackId] = useState('');
  const [freightSubmitting, setFreightSubmitting] = useState(false);
  const lastAutoFetchKeyRef = useRef(null);

  const resetState = useCallback(() => {
    setSelectedTrain(null);
    setSelectedIncomingLine('');
    setSuggestions([]);
    setError('');
    setIsLoading(false);
    setHasFetchedSuggestions(false);
    setView('selection');
    setMode('scheduled');
    setFreightNeedsPlatform(null);
    setLoggedArrivalTime('');
    setSearchTerm('');
    setFreightIncomingLine('');
    setFreightTarget('');
    setFreightPlatformId('');
    setFreightTrackId('');
    setFreightSubmitting(false);
    lastAutoFetchKeyRef.current = null;
  }, []);

  const fetchIncomingLines = useCallback(async () => {
    try {
      const res = await fetch(apiUrl('/api/incoming-lines'));
      if (!res.ok) throw new Error('Failed to load incoming lines');
      const data = await res.json();
      setIncomingLines(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  const fetchSuggestionsForTrain = useCallback(async (train, needsPlatform, incomingLine) => {
    setIsLoading(true);
    setHasFetchedSuggestions(false);
    setError('');
    const arrivalTimeToLog = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    setLoggedArrivalTime(arrivalTimeToLog);
    try {
      const response = await fetch(apiUrl('/api/platform-suggestions'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trainNo: train.trainNo, platforms, freightNeedsPlatform: needsPlatform, incomingLine }),
      });
      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.error || 'Failed to fetch suggestions.');
      }
      const data = await response.json();
      setSuggestions(data.suggestions || []);
      setView('suggestion');
    } catch (err) {
      setError(err.message);
      setSuggestions([]);
    } finally {
      setIsLoading(false);
      setHasFetchedSuggestions(true);
    }
  }, [platforms]);

  const resolveIncomingLineForTrain = useCallback((train, masterTrain) => {
    return (
      train?.incoming_line ||
      train?.incomingLine ||
      masterTrain?.incoming_line ||
      masterTrain?.incomingLine ||
      ''
    );
  }, []);

  const resolveAutoFetchKey = useCallback((trainNo, incomingLine, needsPlatform) => {
    return `${String(trainNo ?? '')}|${String(incomingLine ?? '')}|${String(needsPlatform ?? '')}`;
  }, []);

  useEffect(() => {
    if (isOpen) {
      if (incomingLines.length === 0) fetchIncomingLines();
      if (trainToReassign) {
        // When opening from waiting-list/reassign, prefer the waiting-list object itself
        // so we retain backend fields like `incoming_line`. Fall back to master arriving
        // train only for other metadata.
        setSelectedTrain(trainToReassign);
        const masterTrain = arrivingTrains.find(t => String(t.trainNo) === String(trainToReassign.trainNo));
        const presetLine = resolveIncomingLineForTrain(trainToReassign, masterTrain);
        if (presetLine) setSelectedIncomingLine(presetLine);
      }
    } else {
      resetState();
    }
  }, [isOpen, trainToReassign, arrivingTrains, fetchIncomingLines, incomingLines.length, resetState, resolveIncomingLineForTrain]);

  const handleTrainSelection = (trainNo) => {
    const train = arrivingTrains.find(t => String(t.trainNo) === String(trainNo));
    setSelectedTrain(train);
    setFreightNeedsPlatform(null);
  };

  const handleGetSuggestions = () => {
    if (!selectedTrain) { setError('Please select a train first.'); return; }
    const isWaitingTrain = !!selectedTrain?.enqueued_at; // waiting list entry
    const isReassign = !!trainToReassign;
    // For arriving (not waiting, not reassign) always allow changing line; require selection explicitly
    if (!selectedIncomingLine) {
      if (isWaitingTrain || isReassign) {
        const knownLine = selectedIncomingLine || selectedTrain?.incoming_line || selectedTrain?.incomingLine || trainToReassign?.incoming_line || trainToReassign?.incomingLine;
        if (knownLine) {
          setSelectedIncomingLine(knownLine);
        } else {
          setError('Incoming line missing for this train.');
          return;
        }
      } else {
        setError('Please select the incoming line.');
        return;
      }
    }
    if ((selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods')) && freightNeedsPlatform === null) {
      setError('Please specify if the freight train needs a platform.');
      return;
    }
    fetchSuggestionsForTrain(selectedTrain, freightNeedsPlatform, selectedIncomingLine);
  };

  const handleAssign = (platformIds) => {
    const idsToAssign = Array.isArray(platformIds) ? platformIds : [platformIds];
    onAssignPlatform(selectedTrain.trainNo, idsToAssign, loggedArrivalTime, selectedIncomingLine || selectedTrain?.incoming_line || selectedTrain?.incomingLine || trainToReassign?.incoming_line || trainToReassign?.incomingLine);
    onClose();
  };

  const handleAddToWaitingList = () => {
    if (!selectedTrain) return;
    const knownLine = selectedIncomingLine || selectedTrain?.incoming_line || selectedTrain?.incomingLine || trainToReassign?.incoming_line || trainToReassign?.incomingLine;
    if (!knownLine) { setError('Please select the incoming line before moving to waiting list.'); return; }
    // Use current time as actual arrival if not already captured
    const actualArrivalTime = loggedArrivalTime || new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    onAddToWaitingList(selectedTrain.trainNo, knownLine, actualArrivalTime);
    onClose();
  };

  const filteredTrains = arrivingTrains.filter(train => train.name.toLowerCase().includes(searchTerm.toLowerCase()) || String(train.trainNo).toLowerCase().includes(searchTerm.toLowerCase()));
  const isFreight = selectedTrain && (selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods'));
  const isReassignFlow = !!trainToReassign && mode === 'scheduled';
  const reassignIsFreight = useMemo(() => {
    const name = String((selectedTrain?.name ?? trainToReassign?.name) || '');
    return name.includes('Freight') || name.includes('Goods');
  }, [selectedTrain, trainToReassign]);
  const forceSuggestionView = isReassignFlow && !reassignIsFreight;
  const isShortTrain = useMemo(() => {
    const size = selectedTrain?.size || selectedTrain?.SIZE || selectedTrain?.length || selectedTrain?.LENGTH;
    return String(size || '').trim().toLowerCase() === 'short';
  }, [selectedTrain]);
  const canRequest = !!selectedTrain && !!selectedIncomingLine && !(isFreight && freightNeedsPlatform === null);
  const availablePlatforms = useMemo(() => (platforms || []).filter(p => String(p?.id || '').toLowerCase().startsWith('platform') && !p?.isOccupied && !p?.isUnderMaintenance), [platforms]);
  const availableTracks = useMemo(() => (
    (platforms || [])
      .filter(p => String(p?.id || '').toLowerCase().startsWith('track') && !p?.isOccupied && !p?.isUnderMaintenance)
      .filter(p => (p?.displayName) || ['track 1','track 2','track 3','track 4','track 5','track 6'].includes(String(p?.id || '').toLowerCase()))
  ), [platforms]);
  const getTrackLabel = useCallback((track) => (track?.displayName || track?.id || ''), []);

  useEffect(() => {
    if (mode === 'freight') {
      setSelectedTrain(null);
      setView('selection');
    }
  }, [mode]);

  // Reassign flow: skip the manual "Get Platform Suggestions" step.
  // As soon as required inputs are available, jump to suggestion view and auto-fetch.
  useEffect(() => {
    if (!isOpen) return;
    if (mode !== 'scheduled') return;
    if (!trainToReassign) return;
    if (!selectedTrain) return;

    const masterTrain = arrivingTrains.find(t => String(t.trainNo) === String(selectedTrain.trainNo));
    const incomingLine = selectedIncomingLine || resolveIncomingLineForTrain(selectedTrain, masterTrain);
    if (!incomingLine) return;

    const needsPlatform = isFreight ? freightNeedsPlatform : null;
    if (isFreight && needsPlatform === null) {
      // Freight reassign requires an explicit choice (platform vs track-only).
      // Once user chooses, this same effect will auto-fetch.
      return;
    }

    const key = resolveAutoFetchKey(selectedTrain.trainNo, incomingLine, needsPlatform);
    if (lastAutoFetchKeyRef.current === key) return;
    lastAutoFetchKeyRef.current = key;

    setSelectedIncomingLine(incomingLine);
    setView('suggestion');
    fetchSuggestionsForTrain(selectedTrain, needsPlatform, incomingLine);
  }, [
    isOpen,
    mode,
    trainToReassign,
    selectedTrain,
    selectedIncomingLine,
    isFreight,
    freightNeedsPlatform,
    arrivingTrains,
    fetchSuggestionsForTrain,
    resolveIncomingLineForTrain,
    resolveAutoFetchKey,
  ]);

  const handleModeChange = (nextMode) => {
    setMode(nextMode);
    setError('');
    if (nextMode === 'scheduled') {
      setFreightTarget('');
      setFreightPlatformId('');
      setFreightTrackId('');
      setFreightIncomingLine('');
    }
  };

  const handleFreightSubmit = async () => {
    if (!freightIncomingLine) {
      setError('Please select the incoming line for the freight consist.');
      return;
    }
    if (!freightTarget) {
      setError('Specify whether the freight needs a platform or can take a track.');
      return;
    }
    const payloadBase = {
      // trainName: `Freight ${freightTarget === 'track' ? 'Consist' : 'Arrival'}`,
      incomingLine: freightIncomingLine,
    };
    setFreightSubmitting(true);
    try {
      let success = false;
      if (freightTarget === 'platform') {
        if (!freightPlatformId) {
          setError('Choose an available platform for this freight train.');
          setFreightSubmitting(false);
          return;
        }
        if (!onAssignFreightToPlatform) {
          setError('Freight platform assignment handler unavailable.');
          setFreightSubmitting(false);
          return;
        }
        success = await onAssignFreightToPlatform({
          ...payloadBase,
          platformId: freightPlatformId,
        });
      } else {
        if (!freightTrackId) {
          setError('Choose an available track for this freight train.');
          setFreightSubmitting(false);
          return;
        }
        if (!onAssignFreightToTrack) {
          setError('Freight track assignment handler unavailable.');
          setFreightSubmitting(false);
          return;
        }
        success = await onAssignFreightToTrack({
          ...payloadBase,
          trackId: freightTrackId,
        });
      }
      if (success) {
        onClose();
      }
    } catch (assignErr) {
      setError(assignErr.message || 'Unable to assign freight train.');
    } finally {
      setFreightSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="TRAIN LISTS">
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => handleModeChange('scheduled')}
          className={`flex-1 py-2 rounded-md border ${mode === 'scheduled' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
        >
          Scheduled Arrivals
        </button>
        <button
          onClick={() => handleModeChange('freight')}
          className={`flex-1 py-2 rounded-md border ${mode === 'freight' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
        >
          Freight Train
        </button>
      </div>

      {mode === 'scheduled' && view === 'selection' && !forceSuggestionView && (
        <div className="space-y-4">
          <div>
            <label htmlFor="suggest-train-list" className="block text-sm font-medium text-gray-700 mb-2">1. Select Train for Assignment:</label>
            <input type="text" placeholder="Search by name or number..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} className="w-full p-2 border rounded-md mb-2" />
            <select id="suggest-train-list" value={selectedTrain?.trainNo || ''} onChange={e => handleTrainSelection(e.target.value)} className="w-full p-2 border rounded-md" disabled={!!trainToReassign} size={filteredTrains.length > 5 ? 5 : filteredTrains.length + 1}>
              <option value="" disabled hidden={!selectedTrain}>Select a train...</option>
              {filteredTrains.map(train => (
                <option key={train.trainNo} value={train.trainNo}>{train.trainNo} - {train.name} ({train.scheduled_arrival ? `${train.scheduled_arrival} Arr` : `${train.scheduled_departure} Dep`})</option>
              ))}
            </select>
          </div>

          {selectedTrain && (
            <div>
              {(() => {
                const isWaitingTrain = !!selectedTrain?.enqueued_at;
                const isReassign = !!trainToReassign;
                const locked = isWaitingTrain || isReassign; // lock only for waiting/reassign
                if (locked) {
                    const displayLine = selectedIncomingLine || selectedTrain?.incoming_line || selectedTrain?.incomingLine || trainToReassign?.incomingLine;
                    return <p className="text-xs text-gray-600">Incoming Line: <span className="font-semibold">{displayLine || 'N/A'}</span></p>;
                }
                return (
                  <>
                    <label className="block text-sm font-medium text-gray-700 mb-2">2. Select / Change Incoming Line:</label>
                    <select value={selectedIncomingLine} onChange={e => setSelectedIncomingLine(e.target.value)} className="w-full p-2 border rounded-md">
                      <option value="" disabled>Select incoming line...</option>
                      {incomingLines.map(line => (
                        <option key={line} value={line}>{line}</option>
                      ))}
                    </select>
                    {incomingLines.length === 0 && <p className="text-xs text-gray-500 mt-1">Loading lines...</p>}
                  </>
                );
              })()}
            </div>
          )}

          {isFreight && (
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p className="font-semibold text-blue-800 mb-2">Does this freight train need a platform?</p>
              <div className="flex gap-4">
                <button onClick={() => setFreightNeedsPlatform(true)} className={`flex-1 py-2 rounded-md ${freightNeedsPlatform === true ? 'bg-blue-600 text-white' : 'bg-white'}`}>Yes</button>
                <button onClick={() => setFreightNeedsPlatform(false)} className={`flex-1 py-2 rounded-md ${freightNeedsPlatform === false ? 'bg-blue-600 text-white' : 'bg-white'}`}>No (Track only)</button>
              </div>
            </div>
          )}

          <button onClick={handleGetSuggestions} disabled={!canRequest || isLoading} className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-400">{isLoading ? 'Loading...' : 'Get Platform Suggestions'}</button>
          {error && <p className="text-red-500 text-sm mt-2">{error}</p>}
        </div>
      )}

      {mode === 'scheduled' && (view === 'suggestion' || forceSuggestionView) && (
        <div className="space-y-4">
          <div className="p-3 bg-gray-100 rounded-md border">
            <p className="font-semibold">{selectedTrain?.trainNo} - {selectedTrain?.name}</p>
            <p className="text-sm font-bold text-blue-700">Arrival Time: {loggedArrivalTime || '—'}</p>
            {selectedIncomingLine && <p className="text-xs text-gray-600">Incoming Line: {selectedIncomingLine}</p>}
          </div>

          {(isLoading || (forceSuggestionView && !hasFetchedSuggestions && !error)) && (
            <div className="text-center text-gray-500">Loading suggestions...</div>
          )}
          {error && <p className="text-red-500 text-sm">{error}</p>}

          {suggestions.length > 0 ? (
            <div className="mt-4">
              <h4 className="text-lg font-semibold mb-2">2. Choose a Platform :</h4>
              <div className="space-y-3">
                {suggestions.map((suggestion, index) => {
                  const { platformId, platformIds, score, blockages, historicalMatch, historicalPlatform } = suggestion;
                  const isAPlatform = /^(?:P)?[1-4]A$/i.test(String(platformId || '').trim());
                  const blockagesNotApplicable = typeof blockages === 'string' && String(blockages).toLowerCase().includes('not applicable');
                  const showPotentialBlockages = !isShortTrain && !!blockages && !(isAPlatform && blockagesNotApplicable);
                  return (
                    <div key={index} className={`p-3 rounded-md border ${score >= 80 ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-200'}`}>
                      <div className="flex justify-between items-center">
                        <p className="font-bold text-lg">{platformId}</p>
                        <button onClick={() => handleAssign(platformIds || platformId)} className="bg-green-600 text-white px-5 py-2 rounded-md hover:bg-green-700 font-semibold">Assign</button>
                      </div>
                      <div className="text-sm mt-2 text-gray-600 flex flex-col">
                        <span className="font-semibold">{historicalMatch ? <span className="text-xs text-gray-700">  Historical Platform</span> : null}</span>
                        {showPotentialBlockages && (
                          <div className="text-xs text-gray-700">
                            <span className="font-semibold">Potential Blockages</span>{' '}
                            {typeof blockages === 'object' ? (
                              <span>{Object.entries(blockages).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`).join(' | ')}</span>
                            ) : (
                              <span>{String(blockages)}</span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            !isLoading && hasFetchedSuggestions && (
              <div className="text-center p-4 bg-yellow-50 border-yellow-200 border rounded-md">
                <p className="font-semibold text-yellow-800">No Suitable Platforms/Tracks Found</p>
                <p className="text-sm text-yellow-700">All suitable options may be occupied or under maintenance.</p>
              </div>
            )
          )}

          {!isLoading && hasFetchedSuggestions && selectedTrain && (
            <div className="mt-4 border-t pt-4">
              <button onClick={handleAddToWaitingList} className="w-full bg-red-600 text-white font-bold py-2 px-4 rounded-lg shadow-md hover:bg-red-700 transition">Move to Waiting List</button>
            </div>
          )}
        </div>
      )}

      {mode === 'freight' && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Incoming Line</label>
            <select value={freightIncomingLine} onChange={e => setFreightIncomingLine(e.target.value)} className="w-full p-2 border rounded-md">
              <option value="" disabled>Select incoming line...</option>
              {incomingLines.map(line => <option key={line} value={line}>{line}</option>)}
            </select>
            {incomingLines.length === 0 && <p className="text-xs text-gray-500 mt-1">Loading lines...</p>}
          </div>

          <div>
            <p className="font-semibold text-gray-800">Does this freight need a platform?</p>
            <div className="flex gap-4 mt-2">
              <button onClick={() => { setFreightTarget('platform'); setError(''); }} className={`flex-1 py-2 rounded-md ${freightTarget === 'platform' ? 'bg-blue-600 text-white' : 'bg-white border border-gray-300 text-gray-700'}`}>YES</button>
              <button onClick={() => { setFreightTarget('track'); setError(''); }} className={`flex-1 py-2 rounded-md ${freightTarget === 'track' ? 'bg-blue-600 text-white' : 'bg-white border border-gray-300 text-gray-700'}`}>NO</button>
            </div>
          </div>

          {freightTarget === 'platform' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Select Available Platform</label>
              {availablePlatforms.length > 0 ? (
                <select value={freightPlatformId} onChange={e => setFreightPlatformId(e.target.value)} className="w-full p-2 border rounded-md">
                  <option value="" disabled>Select platform...</option>
                  {availablePlatforms.map(p => <option key={p.id} value={p.id}>{p.id}</option>)}
                </select>
              ) : (
                <p className="text-sm text-red-600">No platforms available right now.</p>
              )}
              {/* <p className="text-xs text-gray-500 mt-1">Only free, non-maintenance platforms are shown.</p> */}
            </div>
          )}

          {freightTarget === 'track' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Select Available Track</label>
              {availableTracks.length > 0 ? (
                <select value={freightTrackId} onChange={e => setFreightTrackId(e.target.value)} className="w-full p-2 border rounded-md">
                  <option value="" disabled>Select track...</option>
                  {availableTracks.map(p => <option key={p.id} value={p.id}>{getTrackLabel(p)}</option>)}
                </select>
              ) : (
                <p className="text-sm text-red-600">No tracks are currently available.</p>
              )}
              <p className="text-xs text-gray-500 mt-1">Tracks under maintenance or occupied.</p>
            </div>
          )}

          <button onClick={handleFreightSubmit} disabled={freightSubmitting || (freightTarget === 'platform' ? availablePlatforms.length === 0 : availableTracks.length === 0)} className="w-full bg-green-600 text-white py-2 rounded-md hover:bg-green-700 disabled:bg-gray-400">
            {freightSubmitting ? 'Assigning...' : 'Assign Freight'}
          </button>
          {error && <p className="text-red-500 text-sm mt-1">{error}</p>}
        </div>
      )}
    </Modal>
  );
}
