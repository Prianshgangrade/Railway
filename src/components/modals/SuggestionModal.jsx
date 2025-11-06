import React, { useCallback, useEffect, useState } from 'react';
import Modal from '../Modal';
import { apiUrl } from '../../utils/api';

export default function SuggestionModal({ isOpen, onClose, arrivingTrains, platforms, onAssignPlatform, trainToReassign, onAddToWaitingList }) {
  const [selectedTrain, setSelectedTrain] = useState(null);
  const [incomingLines, setIncomingLines] = useState([]);
  const [selectedIncomingLine, setSelectedIncomingLine] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [view, setView] = useState('selection');
  const [freightNeedsPlatform, setFreightNeedsPlatform] = useState(null);
  const [loggedArrivalTime, setLoggedArrivalTime] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  const resetState = useCallback(() => {
    setSelectedTrain(null);
    setSelectedIncomingLine('');
    setSuggestions([]);
    setError('');
    setIsLoading(false);
    setView('selection');
    setFreightNeedsPlatform(null);
    setLoggedArrivalTime('');
    setSearchTerm('');
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
    }
  }, [platforms]);

  useEffect(() => {
    if (isOpen) {
      if (incomingLines.length === 0) fetchIncomingLines();
      if (trainToReassign) {
        const train = arrivingTrains.find(t => t.trainNo === trainToReassign.trainNo);
        if (train) setSelectedTrain(train);
      }
    } else {
      resetState();
    }
  }, [isOpen, trainToReassign, arrivingTrains, fetchIncomingLines, incomingLines.length, resetState]);

  const handleTrainSelection = (trainNo) => {
    const train = arrivingTrains.find(t => t.trainNo === trainNo);
    setSelectedTrain(train);
    setFreightNeedsPlatform(null);
  };

  const handleGetSuggestions = () => {
    if (!selectedTrain) { setError('Please select a train first.'); return; }
    if (!selectedIncomingLine) { setError('Please select the incoming line.'); return; }
    if ((selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods')) && freightNeedsPlatform === null) {
      setError('Please specify if the freight train needs a platform.');
      return;
    }
    fetchSuggestionsForTrain(selectedTrain, freightNeedsPlatform, selectedIncomingLine);
  };

  const handleAssign = (platformIds) => {
    const idsToAssign = Array.isArray(platformIds) ? platformIds : [platformIds];
    onAssignPlatform(selectedTrain.trainNo, idsToAssign, loggedArrivalTime);
    onClose();
  };

  const handleAddToWaitingList = () => {
    if (selectedTrain) { onAddToWaitingList(selectedTrain.trainNo); onClose(); }
  };

  const filteredTrains = arrivingTrains.filter(train => train.name.toLowerCase().includes(searchTerm.toLowerCase()) || String(train.trainNo).toLowerCase().includes(searchTerm.toLowerCase()));
  const isFreight = selectedTrain && (selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods'));
  const canRequest = !!selectedTrain && !!selectedIncomingLine && !(isFreight && freightNeedsPlatform === null);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="TRAIN LISTS">
      {view === 'selection' && (
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
              <label className="block text-sm font-medium text-gray-700 mb-2">2. Select Incoming Line:</label>
              <select value={selectedIncomingLine} onChange={e => setSelectedIncomingLine(e.target.value)} className="w-full p-2 border rounded-md">
                <option value="" disabled>Select incoming line...</option>
                {incomingLines.map(line => (
                  <option key={line} value={line}>{line}</option>
                ))}
              </select>
              {incomingLines.length === 0 && <p className="text-xs text-gray-500 mt-1">Loading lines...</p>}
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

      {view === 'suggestion' && (
        <div className="space-y-4">
          <div className="p-3 bg-gray-100 rounded-md border">
            <p className="font-semibold">{selectedTrain?.trainNo} - {selectedTrain?.name}</p>
            <p className="text-sm font-bold text-blue-700">Assignment Time: {loggedArrivalTime}</p>
            {selectedIncomingLine && <p className="text-xs text-gray-600">Incoming Line: {selectedIncomingLine}</p>}
          </div>

          {isLoading && <div className="text-center text-gray-500">Recalculating...</div>}
          {error && <p className="text-red-500 text-sm">{error}</p>}

          {suggestions.length > 0 ? (
            <div className="mt-4">
              <h4 className="text-lg font-semibold mb-2">2. Choose a Platform (sorted by best match):</h4>
              <div className="space-y-3">
                {suggestions.map((suggestion, index) => {
                  const { platformId, platformIds, score, blockages } = suggestion;
                  return (
                    <div key={index} className={`p-3 rounded-md border ${score >= 80 ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-200'}`}>
                      <div className="flex justify-between items-center">
                        <p className="font-bold text-lg">{platformId}</p>
                        <button onClick={() => handleAssign(platformIds || platformId)} className="bg-green-600 text-white px-5 py-2 rounded-md hover:bg-green-700 font-semibold">Assign</button>
                      </div>
                      <div className="text-sm mt-2 text-gray-600 flex flex-col gap-1">
                        <span className="font-semibold">Score: {score}</span>
                        {blockages && (
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
            !isLoading && (
              <div className="text-center p-4 bg-yellow-50 border-yellow-200 border rounded-md">
                <p className="font-semibold text-yellow-800">No Suitable Platforms/Tracks Found</p>
                <p className="text-sm text-yellow-700">All suitable options may be occupied or under maintenance.</p>
              </div>
            )
          )}

          {!isLoading && selectedTrain && (
            <div className="mt-4 border-t pt-4">
              <button onClick={handleAddToWaitingList} className="w-full bg-red-600 text-white font-bold py-2 px-4 rounded-lg shadow-md hover:bg-red-700 transition">Move to Waiting List</button>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
