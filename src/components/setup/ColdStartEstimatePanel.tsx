import React from 'react';
import { Clock } from 'lucide-react';
import { ColdStartEstimate, ExposureLevel, formatColdStartRange } from '../../utils/drillEngine';

const EXPOSURE_LEVELS: { level: ExposureLevel; label: string }[] = [
  { level: 'fresh', label: 'First time seeing this material' },
  { level: 'once', label: 'Studied it once or twice' },
  { level: 'familiar', label: 'Reviewed it several times' },
];

interface ColdStartEstimatePanelProps {
  estimate: ColdStartEstimate | null;
  // Whether this deck has a measured multiplier from a past session; if so
  // the familiarity picker isn't needed.
  hasPersonalHistory: boolean;
  exposureLevel: ExposureLevel;
  onExposureLevelChange: (level: ExposureLevel) => void;
}

// Cold-start time estimate for the deck, with the familiarity picker that
// seeds it when there's no personal history yet.
export const ColdStartEstimatePanel: React.FC<ColdStartEstimatePanelProps> = ({
  estimate: coldStartEstimate,
  hasPersonalHistory: personalHistory,
  exposureLevel,
  onExposureLevelChange: setExposureLevel,
}) => (
  <div className="flex flex-col gap-2.5 border-t border-[var(--border)] pt-3.5">
    <div className="flex items-center justify-between gap-2">
      <label className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
        <Clock size={13} className="text-[var(--accent)]" />
        <span>Estimated time for this deck:</span>
      </label>
      {coldStartEstimate && (
        <span
          id="cold-start-estimate"
          className="text-xs font-bold text-[var(--text-primary)] bg-[var(--surface-1)] border border-[var(--border)] px-2.5 py-0.5 rounded-lg shadow-xs"
        >
          {formatColdStartRange(coldStartEstimate.floorSeconds, coldStartEstimate.ceilingSeconds)}
        </span>
      )}
    </div>

    {personalHistory ? (
      <p className="text-[11px] text-[var(--text-muted)]">
        Rough estimate, based on your last session with this deck.
      </p>
    ) : (
      <div className="space-y-2 bg-[var(--surface-1)]/50 p-3 rounded-xl border border-[var(--border)]">
        <p className="text-[11px] font-medium text-[var(--text-secondary)]">
          How familiar are you with this material? (rough estimate)
        </p>
        <div className="flex flex-wrap items-center gap-1 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg p-0.5 w-fit">
          {EXPOSURE_LEVELS.map(({ level, label }) => (
            <button
              key={level}
              type="button"
              id={`exposure-${level}`}
              onClick={() => setExposureLevel(level)}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all cursor-pointer ${
                exposureLevel === level
                  ? 'bg-[var(--accent)] text-white shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    )}
  </div>
);
