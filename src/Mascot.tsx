
import './Mascot.css';

interface MascotProps {
  isDragging: boolean;
  className?: string;
}

export function Mascot({ isDragging, className = '' }: MascotProps) {
  return (
    <svg 
      className={`transit-mascot ${isDragging ? 'is-dragging' : 'is-idle'} ${className}`}
      viewBox="0 0 100 120" 
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <radialGradient id="bodyGrad" cx="30%" cy="30%" r="70%">
          <stop offset="0%" stopColor="#60A5FA" />
          <stop offset="100%" stopColor="#2563EB" />
        </radialGradient>
        <linearGradient id="legGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1E3A8A" />
          <stop offset="100%" stopColor="#1e293b" />
        </linearGradient>
      </defs>

      {/* Shadow */}
      <ellipse className="shadow" cx="50" cy="115" rx="20" ry="5" fill="rgba(0,0,0,0.15)" />

      {/* Legs (Stay mostly grounded) */}
      <line className="leg left-leg" x1="35" y1="90" x2="30" y2="110" stroke="url(#legGrad)" strokeWidth="8" strokeLinecap="round" />
      <line className="leg right-leg" x1="65" y1="90" x2="70" y2="110" stroke="url(#legGrad)" strokeWidth="8" strokeLinecap="round" />

      {/* Upper Body Group */}
      <g className="upper-body">
        {/* Left Arm */}
        <line className="arm left-arm" x1="25" y1="65" x2="5" y2="80" stroke="#3B82F6" strokeWidth="8" strokeLinecap="round" />
        {/* Right Arm */}
        <line className="arm right-arm" x1="75" y1="65" x2="95" y2="80" stroke="#3B82F6" strokeWidth="8" strokeLinecap="round" />

        {/* Body */}
        <rect className="body-shape" x="25" y="30" width="50" height="65" rx="25" fill="url(#bodyGrad)" />

        {/* Train Window / Visor */}
        <rect className="visor" x="30" y="45" width="40" height="18" rx="8" fill="#1e293b" />
        
        {/* Eyes */}
        <circle className="eye left-eye" cx="40" cy="54" r="3.5" fill="#60A5FA" />
        <circle className="eye right-eye" cx="60" cy="54" r="3.5" fill="#60A5FA" />

        {/* Train Light */}
        <circle className="light" cx="50" cy="80" r="4" fill="#FDE047" />
      </g>
    </svg>
  );
}
