import React, { useEffect, useState } from 'react';
import { ToastContainer } from 'react-toastify';
import LoginPage from './components/LoginPage';
import MainApp from './MainApp';

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Inject Toastify CSS via CDN to match existing behavior
  useEffect(() => {
    const link = document.createElement('link');
    link.href = 'https://cdnjs.cloudflare.com/ajax/libs/react-toastify/9.1.3/ReactToastify.min.css';
    link.rel = 'stylesheet';
    document.head.appendChild(link);
    return () => { document.head.removeChild(link); };
  }, []);

  if (!isAuthenticated) return <LoginPage onLogin={() => setIsAuthenticated(true)} />;

  return (
    <>
      <ToastContainer />
      <MainApp />
    </>
  );
}

