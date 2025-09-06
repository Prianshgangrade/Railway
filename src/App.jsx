import React, { useState, useEffect, useCallback } from 'react';
import { ToastContainer, toast } from 'react-toastify';

// --- LOGIN COMPONENT ---
const LoginPage = ({ onLogin }) => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');

    const handleSubmit = (e) => {
        e.preventDefault();
        if (username === 'stationmaster' && password === 'kgpcontrol123') {
            setError('');
            onLogin();
        } else {
            setError('Invalid username or password.');
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gray-100">
            <div className="w-full max-w-md p-8 space-y-6 bg-white rounded-xl shadow-lg">
                <div className="text-center">
                    <h1 className="text-3xl font-bold text-gray-800">Station Control Login</h1>
                    <p className="text-gray-500">Kharagpur Division</p>
                </div>
                <form onSubmit={handleSubmit} className="space-y-6">
                    <div>
                        <label className="block text-sm font-medium text-gray-700">Username</label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            className="w-full px-3 py-2 mt-1 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-gray-700">Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="w-full px-3 py-2 mt-1 border border-gray-300 rounded-md shadow-sm focus:ring-indigo-500 focus:border-indigo-500"
                            required
                        />
                    </div>
                    {error && <p className="text-sm text-red-600 text-center">{error}</p>}
                    <div>
                        <button
                            type="submit"
                            className="w-full px-4 py-2 font-bold text-white bg-indigo-600 rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                        >
                            Login
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};


// --- HELPER HOOKS & COMPONENTS ---
const useCurrentTime = () => {
    const [time, setTime] = useState(new Date());
    useEffect(() => {
        const timerId = setInterval(() => setTime(new Date()), 1000);
        return () => clearInterval(timerId);
    }, []);
    return time.toLocaleString('en-IN', {
        dateStyle: 'full',
        timeStyle: 'medium',
        timeZone: 'Asia/Kolkata'
    });
};

const Modal = ({ children, isOpen, onClose, title }) => {
    if (!isOpen) return null;
    return (
        <div className="fixed inset-0 bg-black bg-opacity-60 flex items-center justify-center p-4 z-50">
            <div className="bg-white w-full max-w-2xl rounded-lg shadow-xl p-6 max-h-[90vh] overflow-y-auto">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-2xl font-bold text-gray-800">{title}</h3>
                    <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
                        <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
                {children}
            </div>
        </div>
    );
};


// --- LAYOUT COMPONENTS ---
const Header = () => {
    const currentTime = useCurrentTime();
    return (
        <header className="mb-6 text-center">
            <h1 className="text-4xl font-bold text-gray-800">Kharagpur Railway Station Control</h1>
            <p className="text-xl text-gray-600">Station Master Dashboard</p>
            <div className="mt-2 text-md text-gray-500">{currentTime}</div>
        </header>
    );
};

const Track = ({ number, trackData, onUnassignPlatform }) => {
    if (!trackData) {
        return (
            <div className="bg-gray-200 p-3 rounded-lg shadow-sm border-l-4 border-gray-400">
                <h4 className="font-bold text-md text-gray-600">TRACK {number}</h4>
                <div className="h-5 mt-1"></div>
            </div>
        );
    }

    const { isUnderMaintenance, isOccupied, trainDetails, actualArrival } = trackData;
    
    const cardStyle = isUnderMaintenance 
        ? 'bg-yellow-100 border-yellow-500' 
        : isOccupied 
            ? 'bg-green-500 text-white shadow-lg'
            : 'bg-gray-200 border-gray-400';

    const statusText = isUnderMaintenance ? 'Maintenance' : isOccupied ? 'Occupied' : 'Available';
    const statusBgColor = isUnderMaintenance 
        ? 'bg-yellow-200 text-yellow-800' 
        : isOccupied 
            ? 'bg-green-200 text-green-800'
            : 'bg-gray-300 text-gray-800';

    return (
        <div className={`p-3 rounded-lg shadow-sm border-l-4 ${cardStyle} transition-all`}>
            <div className="flex justify-between items-center mb-1">
                <h4 className={`font-bold text-md ${isOccupied ? 'text-white' : 'text-gray-800'}`}>TRACK {number}</h4>
                <span className={`text-xs font-semibold px-2 py-1 rounded-full ${statusBgColor}`}>{statusText}</span>
            </div>
            {isOccupied && trainDetails ? (
                <div>
                    <div className="flex justify-between items-center mt-1">
                        <div className={`text-sm ${isOccupied ? 'text-green-100' : 'text-gray-700'}`}>
                            <p className="font-medium truncate">{trainDetails.trainNo} - {trainDetails.name}</p>
                        </div>
                        <button 
                            onClick={() => onUnassignPlatform(trackData.id, trainDetails)}
                            className="bg-red-500 text-white text-xs font-bold py-1 px-3 rounded-md hover:bg-red-600 transition-all"
                        >
                            Unassign
                        </button>
                    </div>
                    {actualArrival && (
                         <p className={`text-xs mt-1 font-semibold ${isOccupied ? 'text-green-200' : 'text-gray-600'}`}>
                            Actual Arrival: {actualArrival}
                         </p>
                    )}
                </div>
            ) : <div className="h-10"></div>}
        </div>
    );
};

const Platform = ({ name, platformData, onUnassignPlatform }) => {
    if (!platformData) {
        return (
            <div className="bg-gray-200 p-3 rounded-lg shadow-sm border-l-4 border-gray-300 animate-pulse">
                <h4 className="font-bold text-md text-gray-500">{name}</h4>
                <p className="text-xs text-gray-400">No data</p>
            </div>
        );
    }

    const { isUnderMaintenance, isOccupied, trainDetails, isTerminating, actualArrival } = platformData;

    const cardStyle = isUnderMaintenance 
        ? 'bg-yellow-100 border-yellow-500' 
        : isOccupied 
            ? 'bg-green-500 text-white shadow-lg'
            : 'bg-white border-gray-300';

    const statusText = isUnderMaintenance ? 'Maintenance' : isOccupied ? 'Occupied' : 'Available';
    const statusBgColor = isUnderMaintenance 
        ? 'bg-yellow-200 text-yellow-800' 
        : isOccupied 
            ? 'bg-green-200 text-green-800'
            : 'bg-gray-200 text-gray-800';

    return (
        <div className={`p-3 rounded-lg shadow-sm border-l-4 ${cardStyle} transition-all`}>
            <div className="flex justify-between items-center mb-1">
                <h4 className={`font-bold text-md ${isOccupied ? 'text-white' : 'text-gray-800'}`}>{name}</h4>
                <span className={`text-xs font-semibold px-2 py-1 rounded-full ${statusBgColor}`}>{statusText}</span>
            </div>
            {isOccupied && trainDetails ? (
                <div>
                    <div className="flex justify-between items-center mt-1">
                        <div className={`text-sm ${isOccupied ? 'text-green-100' : 'text-gray-700'}`}>
                            <p className="font-medium truncate">{trainDetails.trainNo} - {trainDetails.name}</p>
                        </div>
                        <button 
                            onClick={() => onUnassignPlatform(platformData.id, trainDetails)}
                            className="bg-red-500 text-white text-xs font-bold py-1 px-3 rounded-md hover:bg-red-600 transition-all"
                        >
                            Unassign
                        </button>
                    </div>
                     {actualArrival && (
                         <p className={`text-xs mt-1 font-semibold ${isOccupied ? 'text-green-200' : 'text-gray-600'}`}>
                            Actual Arrival: {actualArrival}
                         </p>
                    )}
                </div>
            ) : <div className="h-10"></div>}
            <div className={`text-xs mt-2 flex justify-end ${isOccupied ? 'text-purple-200' : 'text-purple-700'}`}>
                {isTerminating && <span className="font-semibold">Terminating</span>}
            </div>
        </div>
    );
};

const RailwayLayout = ({ platforms, onOpenModal, onUnassignPlatform }) => {
    if (!platforms) return <div className="text-center p-8 text-gray-500">Loading station layout...</div>;

    const platformMap = new Map(platforms.map(p => [p.id, p]));

    return (
        <div className="w-full max-w-4xl mx-auto p-6 space-y-3 bg-gray-200 rounded-xl shadow-lg">
            <div className="mb-6">
                <nav className="flex gap-0 justify-center bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
                    <button onClick={() => onOpenModal('suggestions')} className="flex-1 px-4 py-3 bg-orange-100 text-orange-800 hover:bg-orange-200 transition-colors border-r border-gray-200 font-semibold">
                        Arriving trains
                    </button>
                    <button onClick={() => onOpenModal('departing')} className="flex-1 px-4 py-3 bg-blue-100 text-blue-800 hover:bg-blue-200 transition-colors border-r border-gray-200 font-semibold">
                        Departing trains
                    </button>
                    <button onClick={() => onOpenModal('maintenance')} className="flex-1 px-4 py-3 bg-yellow-100 text-yellow-800 hover:bg-yellow-200 transition-colors border-r border-gray-200 font-semibold">
                        Maintenance
                    </button>
                    <button onClick={() => onOpenModal('misc')} className="flex-1 px-4 py-3 bg-purple-100 text-purple-800 hover:bg-purple-200 transition-colors border-r border-gray-200 font-semibold">
                        Miscellaneous
                    </button>
                    <button onClick={() => onOpenModal('logs')} className="flex-1 px-4 py-3 bg-gray-100 text-gray-800 hover:bg-gray-200 transition-colors font-semibold">
                        View Logs
                    </button>
                </nav>
            </div>

            <Track number="1" trackData={platformMap.get("Track 1")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="2" trackData={platformMap.get("Track 2")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="3" trackData={platformMap.get("Track 3")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="4" trackData={platformMap.get("Track 4")} onUnassignPlatform={onUnassignPlatform} />

            <div className="grid grid-cols-2 gap-3">
                <Platform name="Platform 1" platformData={platformMap.get("Platform 1")} onUnassignPlatform={onUnassignPlatform} />
                <Platform name="Platform 3" platformData={platformMap.get("Platform 3")} onUnassignPlatform={onUnassignPlatform} />
            </div>
            <div className="grid grid-cols-2 gap-3">
                <Platform name="Platform 1A" platformData={platformMap.get("Platform 1A")} onUnassignPlatform={onUnassignPlatform} />
                <Platform name="Platform 3A" platformData={platformMap.get("Platform 3A")} onUnassignPlatform={onUnassignPlatform} />
            </div>
            <div className="grid grid-cols-2 gap-3">
                <Platform name="Platform 2A" platformData={platformMap.get("Platform 2A")} onUnassignPlatform={onUnassignPlatform} />
                <Platform name="Platform 4A" platformData={platformMap.get("Platform 4A")} onUnassignPlatform={onUnassignPlatform} />
            </div>
            <div className="grid grid-cols-2 gap-3">
                <Platform name="Platform 2" platformData={platformMap.get("Platform 2")} onUnassignPlatform={onUnassignPlatform} />
                <Platform name="Platform 4" platformData={platformMap.get("Platform 4")} onUnassignPlatform={onUnassignPlatform} />
            </div>

            <Platform name="Platform 5" platformData={platformMap.get("Platform 5")} onUnassignPlatform={onUnassignPlatform} />
            <Platform name="Platform 6" platformData={platformMap.get("Platform 6")} onUnassignPlatform={onUnassignPlatform} />
            <Platform name="Platform 7" platformData={platformMap.get("Platform 7")} onUnassignPlatform={onUnassignPlatform} />
            <Platform name="Platform 8" platformData={platformMap.get("Platform 8")} onUnassignPlatform={onUnassignPlatform} />

            <Track number="5" trackData={platformMap.get("Track 5")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="6" trackData={platformMap.get("Track 6")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="7" trackData={platformMap.get("Track 7")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="8" trackData={platformMap.get("Track 8")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="9" trackData={platformMap.get("Track 9")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="10" trackData={platformMap.get("Track 10")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="11" trackData={platformMap.get("Track 11")} onUnassignPlatform={onUnassignPlatform} />
            <Track number="12" trackData={platformMap.get("Track 12")} onUnassignPlatform={onUnassignPlatform} />
        </div>
    );
}


// --- MODAL COMPONENTS ---
const SuggestionModal = ({ isOpen, onClose, arrivingTrains, platforms, onAssignPlatform, trainToReassign }) => {
    const [selectedTrain, setSelectedTrain] = useState(null);
    const [suggestions, setSuggestions] = useState([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState('');
    const [view, setView] = useState('selection');
    const [freightNeedsPlatform, setFreightNeedsPlatform] = useState(null);
    const [loggedArrivalTime, setLoggedArrivalTime] = useState('');

    const resetState = useCallback(() => {
        setSelectedTrain(null);
        setSuggestions([]);
        setError('');
        setIsLoading(false);
        setView('selection');
        setFreightNeedsPlatform(null);
        setLoggedArrivalTime('');
    }, []);

    const fetchSuggestionsForTrain = useCallback(async (train, needsPlatform) => {
        setIsLoading(true);
        setError('');
        const arrivalTimeToLog = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
        setLoggedArrivalTime(arrivalTimeToLog);

        try {
            const response = await fetch('http://localhost:5000/api/platform-suggestions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    trainNo: train.trainNo,
                    platforms: platforms,
                    freightNeedsPlatform: needsPlatform
                }),
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
            if (trainToReassign) {
                const train = arrivingTrains.find(t => t.trainNo === trainToReassign.trainNo);
                if (train) {
                    setSelectedTrain(train);
                    const isFreight = train.name.includes('Freight') || train.name.includes('Goods');
                    if (!isFreight) {
                        fetchSuggestionsForTrain(train, true);
                    }
                }
            } else {
                resetState();
            }
        } else {
           resetState();
        }
    }, [isOpen, trainToReassign, arrivingTrains, resetState, fetchSuggestionsForTrain]);

    const handleTrainSelection = (trainNo) => {
        const train = arrivingTrains.find(t => t.trainNo === trainNo);
        setSelectedTrain(train);
        setFreightNeedsPlatform(null); 
    };
    
    const handleGetSuggestions = () => {
        if (!selectedTrain) { 
            setError('Please select a train first.'); 
            return; 
        }
        if ((selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods')) && freightNeedsPlatform === null) {
            setError('Please specify if the freight train needs a platform.');
            return;
        }
        fetchSuggestionsForTrain(selectedTrain, freightNeedsPlatform);
    };
    
    const handleAssign = (platformIds) => {
        const idsToAssign = Array.isArray(platformIds) ? platformIds : [platformIds];
        onAssignPlatform(selectedTrain.trainNo, idsToAssign, loggedArrivalTime);
        onClose();
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Arriving Trains and Platform Suggestions">
            {view === 'selection' && (
                <div className="space-y-4">
                    <div>
                        <label htmlFor="suggest-train-list" className="block text-sm font-medium text-gray-700 mb-2">1. Select Arriving Train:</label>
                        <select id="suggest-train-list" value={selectedTrain?.trainNo || ''} onChange={e => handleTrainSelection(e.target.value)} className="w-full p-2 border rounded-md" disabled={!!trainToReassign}>
                            <option value="" disabled>Select a train...</option>
                            {arrivingTrains.map(train => <option key={train.trainNo} value={train.trainNo}>{train.trainNo} - {train.name}</option>)}
                        </select>
                    </div>

                    {selectedTrain && (selectedTrain.name.includes('Freight') || selectedTrain.name.includes('Goods')) && (
                        <div className="p-3 bg-blue-50 border border-blue-200 rounded-md">
                            <p className="font-semibold text-blue-800 mb-2">Does this freight train need a platform?</p>
                            <div className="flex gap-4">
                                <button onClick={() => setFreightNeedsPlatform(true)} className={`flex-1 py-2 rounded-md ${freightNeedsPlatform === true ? 'bg-blue-600 text-white' : 'bg-white'}`}>Yes</button>
                                <button onClick={() => setFreightNeedsPlatform(false)} className={`flex-1 py-2 rounded-md ${freightNeedsPlatform === false ? 'bg-blue-600 text-white' : 'bg-white'}`}>No (Track only)</button>
                            </div>
                        </div>
                    )}

                    <button onClick={handleGetSuggestions} disabled={!selectedTrain || isLoading} className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 disabled:bg-gray-400">
                        {isLoading ? 'Loading...' : 'Get Platform Suggestions'}
                    </button>
                    {error && <p className="text-red-500 text-sm mt-2">{error}</p>}
                </div>
            )}

            {view === 'suggestion' && (
                <div className="space-y-4">
                    <div className="p-3 bg-gray-100 rounded-md border">
                        <p className="font-semibold">{selectedTrain?.trainNo} - {selectedTrain?.name}</p>
                        <p className="text-sm font-bold text-blue-700">Actual Arrival Time: {loggedArrivalTime}</p>
                    </div>

                    {isLoading && <div className="text-center text-gray-500">Recalculating...</div>}
                    {error && <p className="text-red-500 text-sm">{error}</p>}
                    
                    {suggestions.length > 0 ? (
                        <div className="mt-4">
                            <h4 className="text-lg font-semibold mb-2">2. Choose a Platform (sorted by best match):</h4>
                            <div className="space-y-3">
                                {suggestions.map((suggestion, index) => {
                                    const { platformId, platformIds, score } = suggestion;
                                    return (
                                        <div key={index} className={`p-3 rounded-md border ${score >= 80 ? 'bg-green-50 border-green-200' : 'bg-blue-50 border-blue-200'}`}>
                                            <div className="flex justify-between items-center">
                                                <p className="font-bold text-lg">{platformId}</p>
                                                <button onClick={() => handleAssign(platformIds || platformId)} className="bg-green-600 text-white px-5 py-2 rounded-md hover:bg-green-700 font-semibold">Assign</button>
                                            </div>
                                            <div className="text-sm mt-2 text-gray-600">
                                                <span className="font-semibold">Score: {score}</span>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                        ) : !isLoading && (
                        <div className="text-center p-4 bg-red-50 border-red-200 border rounded-md">
                            <p className="font-semibold text-red-800">No Suitable Platforms/Tracks Found</p>
                            <p className="text-sm text-red-700">All suitable options may be occupied or under maintenance.</p>
                        </div>
                    )}
                </div>
            )}
        </Modal>
    );
};

const DepartingModal = ({ isOpen, onClose, platforms, onDepartTrain }) => {
    const occupiedPlatforms = platforms.filter(p => p.isOccupied && !p.isUnderMaintenance);
    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Depart Train from Platform">
            <div className="space-y-3">
                {occupiedPlatforms.length > 0 ? (
                    occupiedPlatforms.map(p => (
                        <div key={p.id} className="flex justify-between items-center p-3 bg-gray-100 rounded-md">
                            <div>
                                <p className="font-semibold">{p.id}: {p.trainDetails.trainNo}</p>
                                <p className="text-sm text-gray-600">{p.trainDetails.name}</p>
                            </div>
                            <button onClick={() => onDepartTrain(p.id)} className="btn-depart bg-red-500 text-white px-4 py-1 rounded-md hover:bg-red-600 transition text-sm">Depart</button>
                        </div>
                    ))
                ) : (
                    <p className="text-gray-500 text-center p-4">No trains are currently berthed on platforms.</p>
                )}
            </div>
            <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">
                Close
            </button>
        </Modal>
    );
};

const MaintenanceModal = ({ isOpen, onClose, platforms, onToggleMaintenance }) => (
    <Modal isOpen={isOpen} onClose={onClose} title="Manage Track Maintenance">
        <div className="space-y-2 max-h-96 overflow-y-auto">
            {platforms.map(p => (
                <div key={p.id} className="flex justify-between items-center p-3 bg-gray-50 rounded-md border">
                    <span className="font-medium">{p.id}</span>
                    <label className="inline-flex items-center cursor-pointer">
                        <input 
                            type="checkbox" 
                            checked={p.isUnderMaintenance}
                            onChange={() => onToggleMaintenance(p.id)}
                            disabled={p.isOccupied}
                            className="sr-only peer" 
                        />
                        <div className="relative w-11 h-6 bg-gray-200 rounded-full peer peer-focus:ring-4 peer-focus:ring-yellow-300 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-0.5 after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-yellow-400"></div>
                        <span className="ms-3 text-sm font-medium text-gray-900">{p.isOccupied ? '(Occupied)' : ''}</span>
                    </label>
                </div>
            ))}
        </div>
        <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">
            Done
        </button>
    </Modal>
);

const MiscModal = ({ isOpen, onClose, arrivingTrains, onAddTrain, onDeleteTrain }) => {
    const initialFormState = {
        trainNumber: '', train_type: 'Express', size: 'short', 
        direction: 'UP', source: '', destination: '',
        scheduled_arrival: '', scheduled_departure: '',
    };
    const [newTrain, setNewTrain] = useState(initialFormState);
    const [trainToDelete, setTrainToDelete] = useState(null);

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setNewTrain(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!newTrain.trainNumber || !newTrain.source || !newTrain.destination || !newTrain.scheduled_departure) {
            toast.error("Please fill all required fields for the new train.");
            return;
        }
        onAddTrain(newTrain);
        setNewTrain(initialFormState);
    };
    
    const handleDeleteClick = (trainNo) => {
        setTrainToDelete(trainNo);
    };

    const confirmDelete = () => {
        onDeleteTrain(trainToDelete);
        setTrainToDelete(null);
    }

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Miscellaneous Operations">
            {trainToDelete && (
                 <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center p-4 z-50">
                    <div className="bg-white p-6 rounded-lg shadow-xl text-center">
                        <h4 className="text-lg font-bold mb-4">Confirm Deletion</h4>
                        <p>Are you sure you want to delete train {trainToDelete}?</p>
                        <p className="text-sm text-gray-600">This action cannot be undone.</p>
                        <div className="mt-6 flex justify-center gap-4">
                            <button onClick={() => setTrainToDelete(null)} className="px-4 py-2 bg-gray-300 rounded-md hover:bg-gray-400">Cancel</button>
                            <button onClick={confirmDelete} className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700">Delete</button>
                        </div>
                    </div>
                </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Add Train Form */}
                <div className="space-y-4">
                    <h4 className="text-lg font-semibold border-b pb-2">Add New Train</h4>
                    <form onSubmit={handleSubmit} className="space-y-3">
                        <input name="trainNumber" value={newTrain.trainNumber} onChange={handleInputChange} placeholder="Train Number (e.g., T1234)" className="w-full p-2 border rounded-md" required />
                        <div className="grid grid-cols-2 gap-2">
                            <input name="source" value={newTrain.source} onChange={handleInputChange} placeholder="Source" className="w-full p-2 border rounded-md" required />
                            <input name="destination" value={newTrain.destination} onChange={handleInputChange} placeholder="Destination" className="w-full p-2 border rounded-md" required />
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <select name="train_type" value={newTrain.train_type} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                                <option>Express</option><option>Superfast</option><option>Passenger</option><option>Local</option><option>Freight</option><option>Goods</option>
                            </select>
                            <select name="direction" value={newTrain.direction} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                                <option>UP</option><option>DOWN</option>
                            </select>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                             <select name="size" value={newTrain.size} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                                <option value="short">Short</option>
                                <option value="long">Long</option>
                            </select>
                        </div>
                        <div className="grid grid-cols-2 gap-2">
                            <div><label className="text-xs">Scheduled Arrival</label><input type="time" name="scheduled_arrival" value={newTrain.scheduled_arrival} onChange={handleInputChange} className="w-full p-2 border rounded-md" /></div>
                            <div><label className="text-xs">Scheduled Departure</label><input type="time" name="scheduled_departure" value={newTrain.scheduled_departure} onChange={handleInputChange} className="w-full p-2 border rounded-md" required /></div>
                        </div>
                        <button type="submit" className="w-full bg-blue-600 text-white font-bold py-2 px-4 rounded-lg shadow-md hover:bg-blue-700 transition">Add Train</button>
                    </form>
                </div>
                {/* Delete Train List */}
                <div className="space-y-4">
                    <h4 className="text-lg font-semibold border-b pb-2">Delete Arriving Train</h4>
                    <div className="space-y-2 max-h-80 overflow-y-auto pr-2">
                        {arrivingTrains.length > 0 ? arrivingTrains.map(train => (
                            <div key={train.trainNo} className="flex justify-between items-center p-2 bg-gray-50 rounded-md border">
                                <div>
                                    <p className="font-semibold">{train.trainNo}</p>
                                    <p className="text-sm text-gray-600 truncate">{train.name}</p>
                                </div>
                                <button onClick={() => handleDeleteClick(train.trainNo)} className="bg-red-500 text-white text-xs font-bold py-1 px-3 rounded-md hover:bg-red-600 transition">
                                    Delete
                                </button>
                            </div>
                        )) : <p className="text-gray-500 text-sm text-center pt-4">No trains in the 'arriving' list.</p>}
                    </div>
                </div>
            </div>
            <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">
                Close
            </button>
        </Modal>
    );
};

const LogModal = ({ isOpen, onClose, logs }) => {
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
};

// --- NEW COMPONENT FOR RE-ASSIGNMENT CONFIRMATION ---
const ReassignPromptModal = ({ reassignPrompt, onCancel, onConfirmUnassign, onConfirmReassign }) => {
    if (!reassignPrompt.isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center p-4 z-50">
            <div className="bg-white p-6 rounded-lg shadow-xl text-center max-w-sm w-full">
                <h4 className="text-lg font-bold mb-2">Unassign Train</h4>
                <p className="mb-1">
                    You are about to unassign train 
                    <span className="font-bold mx-1">{reassignPrompt.trainDetails.trainNo}</span>
                    from 
                    <span className="font-bold mx-1">{reassignPrompt.platformId}</span>.
                </p>
                <p className="text-gray-600 mb-6">Do you want to find a new platform for this train immediately?</p>
                <div className="flex justify-center gap-4">
                    <button onClick={onConfirmUnassign} className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700">
                        No, Just Unassign
                    </button>
                    <button onClick={onConfirmReassign} className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                        Yes, Re-assign
                    </button>
                </div>
                 <button onClick={onCancel} className="mt-4 text-sm text-gray-500 hover:underline">Cancel</button>
            </div>
        </div>
    );
};


// --- MAIN APPLICATION WRAPPER ---
const MainApp = () => {
    const [platforms, setPlatforms] = useState([]);
    const [arrivingTrains, setArrivingTrains] = useState([]);
    const [activeModal, setActiveModal] = useState(null);
    const [error, setError] = useState(null);
    const [logs, setLogs] = useState([]);
    const [reassignPrompt, setReassignPrompt] = useState({ isOpen: false, platformId: null, trainDetails: null });
    const [trainForImmediateSuggestion, setTrainForImmediateSuggestion] = useState(null);

    const fetchStationData = useCallback(async () => {
        try {
            const response = await fetch('http://localhost:5000/api/station-data');
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            setPlatforms(data.platforms || []);
            setArrivingTrains(data.arrivingTrains || []);
        } catch (err) {
            console.error("Error fetching station data:", err);
            setError(err.message);
            toast.error(`Failed to load station data: ${err.message}`);
        }
    }, []);

    const fetchLogs = useCallback(async () => {
        try {
            const response = await fetch('http://localhost:5000/api/logs');
            if (!response.ok) throw new Error('Failed to fetch logs');
            const data = await response.json();
            setLogs(data);
        } catch (err) {
            toast.error(err.message);
        }
    }, []);

    useEffect(() => {
        if (activeModal === 'logs') {
            fetchLogs();
        }
    }, [activeModal, fetchLogs]);

    useEffect(() => {
        fetchStationData();
    }, [fetchStationData]);

    useEffect(() => {
        const sseUrl = 'http://localhost:5000/stream';
        console.log("Connecting to SSE stream at:", sseUrl);
        const eventSource = new EventSource(sseUrl);

        eventSource.addEventListener('departure_alert', (event) => {
            const data = JSON.parse(event.data);
            console.log("Received departure alert:", data);
            toast.error(
                `DEPARTURE ALERT: Train ${data.train_number} (${data.train_name}) should depart from ${data.platform_id}`, 
                { autoClose: false, position: 'top-right', toastId: `dep-${data.train_number}` }
            );
        });

        eventSource.onerror = (err) => {
            console.error("SSE Connection Error:", err);
        };

        return () => {
            console.log("Closing SSE connection.");
            eventSource.close();
        };
    }, []);

    const handleApiCall = async (endpoint, body, successMsg) => {
        try {
            const response = await fetch(`http://localhost:5000/api/${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.error || 'An unknown error occurred.');
            }
            toast.success(data.message || successMsg);
            await fetchStationData(); // Refetch data on success
            return true;
        } catch (err) {
            console.error(`Error calling ${endpoint}:`, err);
            toast.error(err.message);
            return false;
        }
    };

    // --- Action Handlers ---
    const handleAssignPlatform = useCallback((trainNo, platformIds, actualArrival) => {
        handleApiCall('assign-platform', { trainNo, platformIds, actualArrival }, `Assigning train ${trainNo}...`);
    }, [fetchStationData]);

    const handleUnassignPlatform = useCallback((platformId) => {
        return handleApiCall('unassign-platform', { platformId }, `Unassigning train from ${platformId}...`);
    }, [fetchStationData]);

    const promptForReassignment = (platformId, trainDetails) => {
        setReassignPrompt({ isOpen: true, platformId, trainDetails });
    };

    const handleConfirmReassign = async () => {
        const { platformId, trainDetails } = reassignPrompt;
        const success = await handleUnassignPlatform(platformId);
        if (success) {
            setTrainForImmediateSuggestion(trainDetails);
            setActiveModal('suggestions');
        }
        setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null });
    };

    const handleConfirmUnassign = () => {
        handleUnassignPlatform(reassignPrompt.platformId);
        setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null });
    };

    const handleDepartTrain = useCallback((platformId) => {
        handleApiCall('depart-train', { platformId }, `Departing train from ${platformId}...`);
    }, [fetchStationData]);

    const handleToggleMaintenance = useCallback((platformId) => {
        handleApiCall('toggle-maintenance', { platformId }, `Updating maintenance for ${platformId}...`);
    }, [fetchStationData]);

    const handleAddTrain = useCallback((trainData) => {
        handleApiCall('add-train', trainData, `Adding train ${trainData.trainNumber}...`);
    }, [fetchStationData]);

    const handleDeleteTrain = useCallback((trainNo) => {
        handleApiCall('delete-train', { trainNo }, `Deleting train ${trainNo}...`);
    }, [fetchStationData]);
    
    if (error) {
        return (
            <div className="h-screen flex items-center justify-center bg-red-50">
                <div className="text-center p-8 bg-white rounded-lg shadow-xl">
                    <h2 className="text-2xl font-bold text-red-600 mb-4">Connection Error</h2>
                    <p className="text-gray-700">Could not connect to the station server.</p>
                    <p className="text-sm text-gray-500 mt-2">Please ensure the backend is running and accessible.</p>
                    <p className="text-xs text-gray-400 mt-1">Details: {error}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="bg-gray-100 min-h-screen text-gray-800" style={{ fontFamily: "'Inter', sans-serif" }}>
            <ToastContainer />
            <div className="container mx-auto p-4 md:p-8">
                <Header />
                <RailwayLayout platforms={platforms} onOpenModal={setActiveModal} onUnassignPlatform={promptForReassignment} />
            </div>
            
            {/* --- Modals --- */}
            <SuggestionModal 
                isOpen={activeModal === 'suggestions'} 
                onClose={() => {
                    setActiveModal(null);
                    setTrainForImmediateSuggestion(null); // Clear the reassign trigger
                }} 
                arrivingTrains={arrivingTrains} 
                platforms={platforms} 
                onAssignPlatform={handleAssignPlatform}
                trainToReassign={trainForImmediateSuggestion}
            />
            <DepartingModal isOpen={activeModal === 'departing'} onClose={() => setActiveModal(null)} platforms={platforms} onDepartTrain={handleDepartTrain} />
            <MaintenanceModal isOpen={activeModal === 'maintenance'} onClose={() => setActiveModal(null)} platforms={platforms} onToggleMaintenance={handleToggleMaintenance} />
            <MiscModal 
                isOpen={activeModal === 'misc'} 
                onClose={() => setActiveModal(null)} 
                arrivingTrains={arrivingTrains}
                onAddTrain={handleAddTrain}
                onDeleteTrain={handleDeleteTrain}
            />
            <LogModal isOpen={activeModal === 'logs'} onClose={() => setActiveModal(null)} logs={logs} />

            <ReassignPromptModal
                reassignPrompt={reassignPrompt}
                onCancel={() => setReassignPrompt({ isOpen: false, platformId: null, trainDetails: null })}
                onConfirmUnassign={handleConfirmUnassign}
                onConfirmReassign={handleConfirmReassign}
            />
        </div>
    );
}

export default function App() {
    const [isAuthenticated, setIsAuthenticated] = useState(false);

    useEffect(() => {
        const link = document.createElement('link');
        link.href = 'https://cdnjs.cloudflare.com/ajax/libs/react-toastify/9.1.3/ReactToastify.min.css';
        link.rel = 'stylesheet';
        document.head.appendChild(link);

        return () => {
            document.head.removeChild(link);
        };
    }, []);

    const handleLogin = () => {
        setIsAuthenticated(true);
    };

    if (!isAuthenticated) {
        return <LoginPage onLogin={handleLogin} />;
    }

    return <MainApp />;
}

