import { useCurrentTime, FormattedTime } from '../hooks/useCurrentTime';

export default function Header() {
  const currentTime = useCurrentTime();
  return (
    <header className="mb-6 text-center">
      <h1 className="text-4xl font-bold text-gray-800">Kharagpur Railway Station Control</h1>
      {/* <p className="text-xl text-gray-600">Station Master Dashboard</p> */}
      <div className="mt-2 text-md text-gray-500"><FormattedTime dateObj={currentTime} /></div>
    </header>
  );
}
