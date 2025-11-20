import { useCurrentTime, FormattedTime } from '../hooks/useCurrentTime';
import { reportDownloadUrl } from '../utils/api';

export default function Header() {
  const currentTime = useCurrentTime();
  return (
    <header className="mb-6 text-center">
      <h1 className="text-4xl font-bold text-gray-800">Kharagpur Railway Station Control</h1>
      {/* <p className="text-xl text-gray-600">Station Master Dashboard</p> */}
      <div className="mt-2 text-md text-gray-500"><FormattedTime dateObj={currentTime} /></div>
      <div className="mt-3">
        <a
          href={reportDownloadUrl()}
          className="inline-block text-sm text-blue-600 hover:underline"
        >
          Download today's report (CSV)
        </a>
      </div>
    </header>
  );
}
