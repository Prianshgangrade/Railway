import React, { useState } from 'react';
import Modal from '../Modal';

export default function MiscModal({ isOpen, onClose, arrivingTrains, onAddTrain, onDeleteTrain }) {
  const initialFormState = {
    'TRAIN NO': '', 'TRAIN NAME': '', 'TYPE': 'Express', 'ZONE': 'SER', 'DIRECTION': 'UP',
    'ISTERMINATING': false, 'PLATFORM NO': '', 'DAYS': 'Daily', 'LENGTH': 'long',
    'ORIGIN FROM STATION': '', 'DEPARTURE FROM ORIGIN': '', 'TERMINAL': '',
    'ARRIVAL AT KGP': '', 'DEPARTURE FROM KGP': '', 'DESTINATION': '', 'ARRIVAL AT DESTINATION': ''
  };
  const [newTrain, setNewTrain] = useState(initialFormState);
  const [trainToDelete, setTrainToDelete] = useState(null);
  const [deleteSearchTerm, setDeleteSearchTerm] = useState('');

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setNewTrain(prev => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onAddTrain(newTrain);
    setNewTrain(initialFormState);
  };

  const handleDeleteClick = (trainNo) => setTrainToDelete(trainNo);
  const confirmDelete = () => { onDeleteTrain(trainToDelete); setTrainToDelete(null); };

  const filteredDeleteList = arrivingTrains.filter(train => train.name.toLowerCase().includes(deleteSearchTerm.toLowerCase()) || String(train.trainNo).toLowerCase().includes(deleteSearchTerm.toLowerCase()));

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
        <div className="space-y-4">
          <h4 className="text-lg font-semibold border-b pb-2">Add New Train</h4>
          <form onSubmit={handleSubmit} className="space-y-3 text-sm">
            <input name="TRAIN NO" value={newTrain['TRAIN NO']} onChange={handleInputChange} placeholder="Train Number*" className="w-full p-2 border rounded-md" required />
            <input name="TRAIN NAME" value={newTrain['TRAIN NAME']} onChange={handleInputChange} placeholder="Train Name*" className="w-full p-2 border rounded-md" required />
            <div className="grid grid-cols-2 gap-2">
              <input name="ORIGIN FROM STATION" value={newTrain['ORIGIN FROM STATION']} onChange={handleInputChange} placeholder="Origin Station*" className="w-full p-2 border rounded-md" required />
              <input name="DESTINATION" value={newTrain['DESTINATION']} onChange={handleInputChange} placeholder="Destination*" className="w-full p-2 border rounded-md" required />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs">Scheduled Arrival (KGP)</label>
                <input type="time" name="ARRIVAL AT KGP" value={newTrain['ARRIVAL AT KGP']} onChange={handleInputChange} className="w-full p-2 border rounded-md" />
              </div>
              <div>
                <label className="text-xs">Scheduled Departure (KGP)*</label>
                <input type="time" name="DEPARTURE FROM KGP" value={newTrain['DEPARTURE FROM KGP']} onChange={handleInputChange} className="w-full p-2 border rounded-md" required />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select name="TYPE" value={newTrain['TYPE']} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                <option>Express</option><option>Superfast</option><option>Passenger</option><option>Local</option><option>Freight</option><option>Goods</option>
              </select>
              <select name="DIRECTION" value={newTrain['DIRECTION']} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                <option>UP</option><option>DOWN</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <select name="LENGTH" value={newTrain['LENGTH']} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                <option value="long">Long</option><option value="short">Short</option>
              </select>
              <select name="ZONE" value={newTrain['ZONE']} onChange={handleInputChange} className="w-full p-2 border rounded-md">
                <option>SER</option><option>CR</option><option>ECOR</option><option>NCR</option>
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input name="DAYS" value={newTrain['DAYS']} onChange={handleInputChange} placeholder="Days (e.g., SMTWTFS)" className="w-full p-2 border rounded-md" />
              <div className="flex items-center">
                <input type="checkbox" name="ISTERMINATING" checked={newTrain['ISTERMINATING']} onChange={handleInputChange} className="mr-2" />
                <label>Terminates at KGP</label>
              </div>
            </div>
            <button type="submit" className="w-full bg-blue-600 text-white font-bold py-2 px-4 rounded-lg shadow-md hover:bg-blue-700 transition">Add Train</button>
          </form>
        </div>
        <div className="space-y-4">
          <h4 className="text-lg font-semibold border-b pb-2">Delete Arriving Train</h4>
          <input type="text" placeholder="Search by name or number..." value={deleteSearchTerm} onChange={e => setDeleteSearchTerm(e.target.value)} className="w-full p-2 border rounded-md mb-2" />
          <div className="space-y-2 max-h-80 overflow-y-auto pr-2">
            {filteredDeleteList.length > 0 ? filteredDeleteList.map(train => (
              <div key={train.trainNo} className="flex justify-between items-center p-2 bg-gray-50 rounded-md border">
                <div className="flex-1 min-w-0 mr-2">
                  <p className="font-semibold">{train.trainNo}</p>
                  <p className="text-sm text-gray-600 truncate">{train.name}</p>
                </div>
                <button onClick={() => handleDeleteClick(train.trainNo)} className="bg-red-500 text-white text-xs font-bold py-1 px-3 rounded-md hover:bg-red-600 transition flex-shrink-0">Delete</button>
              </div>
            )) : <p className="text-gray-500 text-sm text-center pt-4">No matching trains found.</p>}
          </div>
        </div>
      </div>
      <button onClick={onClose} className="mt-6 w-full bg-gray-300 text-gray-800 py-2 rounded-md hover:bg-gray-400 transition">Close</button>
    </Modal>
  );
}
