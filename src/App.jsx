import React, { useState, useEffect, useCallback } from 'react';

// --- Initial Data Store ---
// In a real application, this would likely come from an API.
const initialData = {
    platforms: [
        { id: 'Platform 1', isOccupied: true, trainDetails: { trainNo: '12841', name: 'Coromandel Express' }, isUnderMaintenance: false, type: 'Platform', length: 24, isTerminating: false },
        { id: 'Platform 2', isOccupied: false, trainDetails: null, isUnderMaintenance: false, type: 'Platform', length: 22, isTerminating: false },
        { id: 'Platform 3', isOccupied: true, trainDetails: { trainNo: '12262', name: 'CSMT-HWH Duronto' }, isUnderMaintenance: false, type: 'Platform', length: 24, isTerminating: false },
        { id: 'Platform 4', isOccupied: false, trainDetails: null, isUnderMaintenance: false, type: 'Platform', length: 20, isTerminating: true },
        { id: 'Platform 5', isOccupied: false, trainDetails: null, isUnderMaintenance: true, type: 'Platform', length: 22, isTerminating: false },
        { id: 'Platform 6', isOccupied: false, trainDetails: null, isUnderMaintenance: false, type: 'Platform', length: 24, isTerminating: true },
        { id: 'Siding A', isOccupied: true, trainDetails: { trainNo: 'GOODS01', name: 'Freight Carrier' }, isUnderMaintenance: false, type: 'Siding', length: 50, isTerminating: true },
        { id: 'Siding B', isOccupied: false, trainDetails: null, isUnderMaintenance: false, type: 'Siding', length: 45, isTerminating: true },
    ],
    arrivingTrains: [
        { trainNo: '12810', name: 'HWH-CSMT Mail', origin: 'Howrah' },
        { trainNo: '18048', name: 'Vasco-da-Gama Amaravati Exp', origin: 'Vasco-da-Gama' },
        { trainNo: '22892', name: 'Ranchi-Howrah Intercity', origin: 'Ranchi' },
        { trainNo: '12860', name: 'Gitanjali Express', origin: 'Howrah' },
    ],
    departedTrains: []
};

// --- Helper Functions & Components ---

// Custom hook to get and format the current time
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

// Generic Modal Component
const Modal = ({ children, isOpen, onClose, title }) => {
    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50 transition-opacity duration-300">
            <div className="modal-content bg-white w-full max-w-2xl rounded-lg shadow-xl p-6 transform scale-100 transition-transform duration-300 max-h-[90vh] overflow-y-auto">
                <h3 className="text-2xl font-bold mb-4">{title}</h3>
                {children}
                <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">
                    Close
                </button>
            </div>
        </div>
    );
};

// --- Main Application Components ---

const Header = () => {
    const currentTime = useCurrentTime();
    return (
        <header className="mb-8 text-center">
            <h1 className="text-3xl md:text-4xl font-bold text-gray-800">Kharagpur Railway Station Control</h1>
            <p className="text-lg text-gray-600">Station Master Dashboard</p>
            <div className="mt-2 text-sm text-gray-500">{currentTime}</div>
        </header>
    );
};

const ControlButtons = ({ onOpenModal }) => (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <button onClick={() => onOpenModal('arriving')} className="bg-blue-600 text-white font-bold py-3 px-4 rounded-lg shadow-md hover:bg-blue-700 transition duration-300">
            Arriving Trains
        </button>
        <button onClick={() => onOpenModal('departing')} className="bg-red-600 text-white font-bold py-3 px-4 rounded-lg shadow-md hover:bg-red-700 transition duration-300">
            Departing Trains
        </button>
        <button onClick={() => onOpenModal('maintenance')} className="bg-yellow-500 text-white font-bold py-3 px-4 rounded-lg shadow-md hover:bg-yellow-600 transition duration-300">
            Track Maintenance
        </button>
        <button onClick={() => onOpenModal('misc')} className="bg-gray-600 text-white font-bold py-3 px-4 rounded-lg shadow-md hover:bg-gray-700 transition duration-300">
            Miscellaneous
        </button>
    </div>
);

const PlatformCard = ({ platform }) => {
    let statusClass = 'border-green-500'; // track-available
    let statusText = 'Available';
    let trainInfo = null;

    if (platform.isUnderMaintenance) {
        statusClass = 'border-yellow-500'; // track-maintenance
        statusText = 'Under Maintenance';
    } else if (platform.isOccupied) {
        statusClass = 'border-red-500'; // track-occupied
        statusText = 'Occupied';
        trainInfo = <p className="text-sm text-gray-600 truncate font-medium">{platform.trainDetails.trainNo} - {platform.trainDetails.name}</p>;
    }
    
    const statusBgColor = platform.isUnderMaintenance ? 'bg-yellow-100 text-yellow-800' : platform.isOccupied ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800';

    return (
        <div className={`track bg-gray-50 p-4 rounded-lg shadow-sm flex flex-col justify-between border-l-4 ${statusClass}`}>
            <div>
                <div className="flex justify-between items-center mb-1">
                    <h4 className="font-bold text-lg">{platform.id}</h4>
                    <span className={`text-sm font-semibold px-2 py-1 rounded-full ${statusBgColor}`}>
                        {statusText}
                    </span>
                </div>
                {trainInfo}
            </div>
            <div className="text-xs text-gray-500 mt-2 flex justify-between">
                <span>Length: {platform.length} coaches</span>
                {platform.isTerminating && <span className="font-semibold text-purple-700">Terminating</span>}
            </div>
        </div>
    );
};


const PlatformGrid = ({ platforms }) => (
    <div className="bg-white p-6 rounded-lg shadow-lg">
        <h2 className="text-2xl font-semibold mb-4 border-b pb-2">Platform & Track Status</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {platforms.map(p => <PlatformCard key={p.id} platform={p} />)}
        </div>
    </div>
);


// --- Modal Components ---

const ArrivingModal = ({ isOpen, onClose, arrivingTrains, platforms, onAssignPlatform }) => {
    const [selectedTrain, setSelectedTrain] = useState('');
    const [selectedPlatform, setSelectedPlatform] = useState('');

    const availablePlatforms = platforms.filter(p => !p.isOccupied && !p.isUnderMaintenance);

    const handleAssign = () => {
        if (!selectedTrain || !selectedPlatform) {
            alert('Please select both a train and a platform.');
            return;
        }
        onAssignPlatform(selectedTrain, selectedPlatform);
        setSelectedTrain('');
        setSelectedPlatform('');
        onClose();
    };
    
    const handleTrainSelect = (e) => {
        setSelectedTrain(e.target.value);
        setSelectedPlatform(''); // Reset platform selection when train changes
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Assign Platform for Arriving Train">
            <div>
                <label htmlFor="arriving-train-list" className="block text-sm font-medium text-gray-700 mb-2">1. Select an incoming train:</label>
                <select id="arriving-train-list" value={selectedTrain} onChange={handleTrainSelect} className="w-full p-2 border rounded-md form-input">
                    <option value="" disabled>Select a train...</option>
                    {arrivingTrains.map(train => (
                        <option key={train.trainNo} value={train.trainNo}>{train.trainNo} - {train.name}</option>
                    ))}
                </select>
            </div>
            {selectedTrain && (
                <div className="mt-4">
                    <label htmlFor="available-platform-list" className="block text-sm font-medium text-gray-700 mb-2">2. Select an available platform:</label>
                    <select id="available-platform-list" value={selectedPlatform} onChange={e => setSelectedPlatform(e.target.value)} className="w-full p-2 border rounded-md form-input">
                        <option value="" disabled>Select a platform...</option>
                        {availablePlatforms.map(p => (
                            <option key={p.id} value={p.id}>{p.id} ({p.length} coaches)</option>
                        ))}
                    </select>
                    <button onClick={handleAssign} className="mt-4 w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 transition">Assign to Platform</button>
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
                    <p className="text-gray-500">No trains are currently ready for departure.</p>
                )}
            </div>
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
    </Modal>
);

const MiscModal = ({ isOpen, onClose, arrivingTrains, onAddTrain, onRemoveTrain, onAddTrack }) => {
    const handleAddTrain = (e) => {
        e.preventDefault();
        const form = e.target;
        const trainNo = form.elements['new-train-no'].value.trim();
        const trainName = form.elements['new-train-name'].value.trim();
        const origin = form.elements['new-train-origin'].value.trim();
        onAddTrain({ trainNo, name: trainName, origin });
        form.reset();
    };

    const handleRemoveTrain = (e) => {
        e.preventDefault();
        const trainNoToRemove = e.target.elements['remove-train-list'].value;
        if (trainNoToRemove) {
            onRemoveTrain(trainNoToRemove);
            e.target.reset();
        }
    };
    
    const handleAddTrack = (e) => {
        e.preventDefault();
        const form = e.target;
        const id = form.elements['new-track-id'].value.trim();
        const type = form.elements['new-track-type'].value;
        const length = parseInt(form.elements['new-track-length'].value, 10);
        const isTerminating = form.elements['new-track-terminating'].checked;
        onAddTrack({ id, type, length, isTerminating });
        form.reset();
    };

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Miscellaneous Operations">
            <div className="mb-8 p-4 border rounded-lg">
                <h4 className="text-lg font-semibold mb-3 text-gray-700">Add New Train</h4>
                <form onSubmit={handleAddTrain} className="space-y-3">
                    <input type="text" name="new-train-no" placeholder="Train No." className="form-input" required />
                    <input type="text" name="new-train-name" placeholder="Train Name" className="form-input" required />
                    <input type="text" name="new-train-origin" placeholder="Origin" className="form-input" required />
                    <button type="submit" className="w-full bg-green-600 text-white py-2 rounded-md hover:bg-green-700 transition">Add Train</button>
                </form>
            </div>

            <div className="mb-8 p-4 border rounded-lg">
                <h4 className="text-lg font-semibold mb-3 text-gray-700">Remove Arriving Train</h4>
                <form onSubmit={handleRemoveTrain} className="space-y-3">
                    <select name="remove-train-list" defaultValue="" className="form-input" required>
                        <option value="" disabled>Select train to remove...</option>
                        {arrivingTrains.map(train => (
                            <option key={train.trainNo} value={train.trainNo}>{train.trainNo} - {train.name}</option>
                        ))}
                    </select>
                    <button type="submit" className="w-full bg-red-600 text-white py-2 rounded-md hover:bg-red-700 transition">Remove Selected Train</button>
                </form>
            </div>
            
            <div className="p-4 border rounded-lg">
                <h4 className="text-lg font-semibold mb-3 text-gray-700">Add New Track</h4>
                <form onSubmit={handleAddTrack} className="space-y-3">
                    <input type="text" name="new-track-id" placeholder="Track Name (e.g., Platform 7)" className="form-input" required />
                    <select name="new-track-type" className="form-input">
                        <option value="Platform">Platform</option>
                        <option value="Siding">Siding</option>
                    </select>
                    <input type="number" name="new-track-length" placeholder="Length (No. of coaches)" className="form-input" required />
                    <label className="flex items-center space-x-2 text-sm text-gray-600">
                        <input type="checkbox" name="new-track-terminating" className="rounded" />
                        <span>Is it a terminating track?</span>
                    </label>
                    <button type="submit" className="w-full bg-blue-600 text-white py-2 rounded-md hover:bg-blue-700 transition">Add Track</button>
                </form>
            </div>
        </Modal>
    );
};


// --- Main App Component ---
export default function App() {
    // State Management
    const [platforms, setPlatforms] = useState(initialData.platforms);
    const [arrivingTrains, setArrivingTrains] = useState(initialData.arrivingTrains);
    const [departedTrains, setDepartedTrains] = useState(initialData.departedTrains);
    const [activeModal, setActiveModal] = useState(null);

    // --- State Update Logic ---

    const handleAssignPlatform = useCallback((trainNo, platformId) => {
        const trainToAssign = arrivingTrains.find(t => t.trainNo === trainNo);
        if (!trainToAssign) return;

        setPlatforms(prev => prev.map(p => 
            p.id === platformId ? { ...p, isOccupied: true, trainDetails: trainToAssign } : p
        ));
        setArrivingTrains(prev => prev.filter(t => t.trainNo !== trainNo));
    }, [arrivingTrains]);

    const handleDepartTrain = useCallback((platformId) => {
        const platformToFree = platforms.find(p => p.id === platformId);
        if (!platformToFree || !platformToFree.trainDetails) return;

        setDepartedTrains(prev => [...prev, platformToFree.trainDetails]);
        setPlatforms(prev => prev.map(p => 
            p.id === platformId ? { ...p, isOccupied: false, trainDetails: null } : p
        ));
    }, [platforms]);

    const handleToggleMaintenance = useCallback((platformId) => {
        setPlatforms(prev => prev.map(p =>
            p.id === platformId ? { ...p, isUnderMaintenance: !p.isUnderMaintenance } : p
        ));
    }, []);
    
    const handleAddTrain = useCallback((newTrain) => {
        if (!newTrain.trainNo || !newTrain.name || !newTrain.origin) {
            alert('Please fill all train fields.');
            return;
        }
        if (arrivingTrains.some(t => t.trainNo === newTrain.trainNo)) {
            alert('A train with this number is already in the arriving list.');
            return;
        }
        setArrivingTrains(prev => [...prev, newTrain]);
        alert(`Train ${newTrain.trainNo} added successfully.`);
    }, [arrivingTrains]);
    
    const handleRemoveTrain = useCallback((trainNoToRemove) => {
        setArrivingTrains(prev => prev.filter(t => t.trainNo !== trainNoToRemove));
        alert(`Train ${trainNoToRemove} removed successfully.`);
    }, []);

    const handleAddTrack = useCallback((newTrack) => {
        if (!newTrack.id || !newTrack.length) {
            alert('Please provide a track name and length.');
            return;
        }
        if (platforms.some(p => p.id.toLowerCase() === newTrack.id.toLowerCase())) {
            alert('A track with this name already exists.');
            return;
        }
        const trackToAdd = {
            ...newTrack,
            isOccupied: false,
            trainDetails: null,
            isUnderMaintenance: false
        };
        setPlatforms(prev => [...prev, trackToAdd]);
        alert(`Track ${newTrack.id} added successfully.`);
    }, [platforms]);


    return (
        <div className="bg-gray-100 text-gray-800 min-h-screen" style={{ fontFamily: "'Inter', sans-serif" }}>
            <div className="container mx-auto p-4 md:p-8">
                <Header />
                <ControlButtons onOpenModal={setActiveModal} />
                <PlatformGrid platforms={platforms} />
            </div>

            <ArrivingModal 
                isOpen={activeModal === 'arriving'}
                onClose={() => setActiveModal(null)}
                arrivingTrains={arrivingTrains}
                platforms={platforms}
                onAssignPlatform={handleAssignPlatform}
            />
            <DepartingModal
                isOpen={activeModal === 'departing'}
                onClose={() => setActiveModal(null)}
                platforms={platforms}
                onDepartTrain={handleDepartTrain}
            />
            <MaintenanceModal
                isOpen={activeModal === 'maintenance'}
                onClose={() => setActiveModal(null)}
                platforms={platforms}
                onToggleMaintenance={handleToggleMaintenance}
            />
            <MiscModal
                isOpen={activeModal === 'misc'}
                onClose={() => setActiveModal(null)}
                arrivingTrains={arrivingTrains}
                onAddTrain={handleAddTrain}
                onRemoveTrain={handleRemoveTrain}
                onAddTrack={handleAddTrack}
            />
        </div>
    );
}

