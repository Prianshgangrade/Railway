import { useEffect, useState } from 'react';

export const useCurrentTime = () => {
  const [time, setTime] = useState(new Date());
  useEffect(() => {
    const timerId = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timerId);
  }, []);
  return time;
};

export const FormattedTime = ({ dateObj }) => {
  if (!dateObj) return null;
  return dateObj.toLocaleString('en-IN', {
    dateStyle: 'full',
    timeStyle: 'medium',
    timeZone: 'Asia/Kolkata'
  });
};
