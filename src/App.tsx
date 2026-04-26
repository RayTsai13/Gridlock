import { useCallback, useEffect, useMemo, useState, useRef } from 'react';
import { Layer, Map, NavigationControl, Source, Marker } from 'react-map-gl/maplibre';
import type { FeatureCollection, Point } from 'geojson';
import type { MapLayerMouseEvent, MapRef } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';
import { useHeatmapStream } from './heatmap/stream.ts';
import { heatmapLayer } from './heatmap/layer.ts';
import {
  DEPLOY_STEPS,
  stopsToGeoJSON,
  linesToGeoJSON,
} from './stops/data.ts';
import type { TransitStop, TransitLine } from './stops/data.ts';
import {
  lineCasingLayer,
  lineRouteLayer,
  stopCircleLayer,
  stopDotLayer,
  stopLabelLayer,
  deployPulseRingLayer,
  deployGlowDotLayer,
} from './stops/layers.ts';

const initialViewState = {
  longitude: -122.3337,
  latitude: 47.6074,
  zoom: 15.3,
  pitch: 55,
  bearing: -18,
};

function App() {
  const heatmapData = useHeatmapStream();

  // Deploy state: index of the highest deployed step (0 = Line 1 only)
  const [deployedIndex, setDeployedIndex] = useState(0);

  // Time controls
  const [timeOfDay, setTimeOfDay] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [dayOfWeek, setDayOfWeek] = useState(0);
  const [hoveredDay, setHoveredDay] = useState<number | null>(null);
  const hoverTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dialRef = useRef<HTMLDivElement>(null);
  const [isDraggingDial, setIsDraggingDial] = useState(false);
  const mapRef = useRef<MapRef | null>(null);
  const [offscreenArrow, setOffscreenArrow] = useState<{ x: number; y: number; angle: number } | null>(null);

  // ── Compute active stops/lines from deployed steps ──
  const { activeStops, activeLines } = useMemo(() => {
    const stops: TransitStop[] = [];
    const lines: TransitLine[] = [];
    const seenStopIds = new Set<string>();

    for (let i = 0; i <= deployedIndex; i++) {
      const step = DEPLOY_STEPS[i];
      lines.push(step.line);
      for (const stop of step.newStops) {
        if (!seenStopIds.has(stop.id)) {
          seenStopIds.add(stop.id);
          stops.push(stop);
        }
      }
    }
    return { activeStops: stops, activeLines: lines };
  }, [deployedIndex]);

  const stopsGeoJSON = useMemo(() => stopsToGeoJSON(activeStops), [activeStops]);
  const linesGeoJSON = useMemo(() => linesToGeoJSON(activeLines, activeStops), [activeLines, activeStops]);

  // ── Next deploy step (the one we're hinting at) ──
  const nextStep = deployedIndex < DEPLOY_STEPS.length - 1
    ? DEPLOY_STEPS[deployedIndex + 1]
    : null;

  // Resolve trigger coordinates: use custom coords if provided, else fall back to station
  const triggerCoords = useMemo<[number, number] | null>(() => {
    if (!nextStep) return null;
    if (nextStep.triggerCoordinates) return nextStep.triggerCoordinates;
    if (nextStep.triggerStopId) {
      const stop = activeStops.find((s) => s.id === nextStep.triggerStopId);
      return stop?.coordinates ?? null;
    }
    return null;
  }, [nextStep, activeStops]);

  // Trigger GeoJSON for the pulsing indicator
  const triggerGeoJSON = useMemo<FeatureCollection<Point>>(() => {
    if (!triggerCoords) return { type: 'FeatureCollection', features: [] };
    return {
      type: 'FeatureCollection',
      features: [{
        type: 'Feature',
        geometry: { type: 'Point', coordinates: triggerCoords },
        properties: { id: nextStep?.triggerStopId ?? 'deploy', name: nextStep?.label ?? '' },
      }],
    };
  }, [triggerCoords, nextStep]);

  // ── Off-screen arrow: track whether the deploy node is visible ──
  const updateOffscreenArrow = useCallback(() => {
    if (!mapRef.current || !triggerCoords) {
      setOffscreenArrow(null);
      return;
    }
    const map = mapRef.current;
    const projected = map.project(triggerCoords as [number, number]);
    const container = map.getContainer();
    const w = container.clientWidth;
    const h = container.clientHeight;
    const MARGIN = 60;

    // If on screen, no arrow needed
    if (projected.x >= MARGIN && projected.x <= w - MARGIN &&
        projected.y >= MARGIN && projected.y <= h - MARGIN) {
      setOffscreenArrow(null);
      return;
    }

    // Clamp to screen edge with padding
    const cx = w / 2;
    const cy = h / 2;
    const dx = projected.x - cx;
    const dy = projected.y - cy;
    const angle = Math.atan2(dy, dx);
    const PAD = 48;

    const edgeX = Math.max(PAD, Math.min(w - PAD, cx + Math.cos(angle) * (w / 2 - PAD)));
    const edgeY = Math.max(PAD, Math.min(h - PAD, cy + Math.sin(angle) * (h / 2 - PAD)));

    setOffscreenArrow({ x: edgeX, y: edgeY, angle: angle * (180 / Math.PI) });
  }, [triggerCoords]);

  useEffect(() => {
    updateOffscreenArrow();
  }, [updateOffscreenArrow]);

  // ── Map click handler — deploy on trigger click ──
  const handleMapClick = useCallback(
    (e: MapLayerMouseEvent) => {
      if (!nextStep) return;
      const features = e.features;
      if (features && features.length > 0) {
        setDeployedIndex((prev) => prev + 1);
      }
    },
    [nextStep],
  );

  // ── Time controls ──
  const updateTimeFromPointer = (clientX: number, clientY: number) => {
    if (!dialRef.current) return;
    const rect = dialRef.current.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const angle = Math.atan2(clientY - cy, clientX - cx);
    let shiftedAngle = angle + Math.PI / 2;
    if (shiftedAngle < 0) shiftedAngle += 2 * Math.PI;
    let newTime = Math.round((shiftedAngle / (2 * Math.PI)) * 1440);
    newTime = Math.round(newTime / 30) * 30;
    if (newTime >= 1440) newTime = 0;
    setTimeOfDay(newTime);
  };

  useEffect(() => {
    const handlePointerMove = (e: PointerEvent) => {
      if (!isDraggingDial) return;
      updateTimeFromPointer(e.clientX, e.clientY);
    };

    const handlePointerUp = () => {
      setIsDraggingDial(false);
    };

    if (isDraggingDial) {
      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', handlePointerUp);
    }
    return () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', handlePointerUp);
    };
  }, [isDraggingDial]);

  useEffect(() => {
    if (!isPlaying) return;
    const interval = setInterval(() => {
      setTimeOfDay((prev) => (prev >= 1410 ? 0 : prev + 30));
    }, 200);
    return () => clearInterval(interval);
  }, [isPlaying]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        e.preventDefault();
        setIsPlaying((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const formatTime = (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    const period = hours >= 12 ? 'PM' : 'AM';
    const displayHours = hours % 12 || 12;
    return `${displayHours}:${mins.toString().padStart(2, '0')} ${period}`;
  };

  const dialRadius = 60;
  const thumbAngle = (timeOfDay / 1440) * 2 * Math.PI - Math.PI / 2;
  const thumbX = dialRadius * Math.cos(thumbAngle);
  const thumbY = dialRadius * Math.sin(thumbAngle);

  // Dynamic angle calculation for weekday orbit nodes
  const WEEKDAYS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
  const focusIndex = hoveredDay !== null ? hoveredDay : dayOfWeek;
  const ACTIVE_WIDTH = 4.5; 
  const INACTIVE_WIDTH = 1;
  const TOTAL_SPAN = 130;
  const START_ANGLE = 160;

  const nodeWidths = WEEKDAYS.map((_, i) => i === focusIndex ? ACTIVE_WIDTH : INACTIVE_WIDTH);
  const gaps = [];
  for (let i = 0; i < 6; i++) {
    gaps.push((nodeWidths[i] + nodeWidths[i+1]) / 2);
  }
  const totalGap = gaps.reduce((a, b) => a + b, 0);

  const nodeAngles = [START_ANGLE];
  let currentGapSum = 0;
  for (let i = 0; i < 6; i++) {
    currentGapSum += gaps[i];
    nodeAngles.push(START_ANGLE + (currentGapSum / totalGap) * TOTAL_SPAN);
  }

  // Interactive layer IDs for click detection
  const interactiveLayerIds = useMemo(
    () => ['transit-stops-circle', 'transit-stops-dot', 'deploy-pulse-ring', 'deploy-glow-dot'],
    [],
  );

  return (
    <div className="map-shell">
      <Map
        ref={mapRef}
        initialViewState={initialViewState}
        mapStyle="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
        style={{ width: '100vw', height: '100vh' }}
        onClick={handleMapClick}
        onMove={updateOffscreenArrow}
        interactiveLayerIds={interactiveLayerIds}
        cursor={nextStep ? 'pointer' : undefined}
      >
        <NavigationControl position="top-right" />

        <Source id="heatmap-source" type="geojson" data={heatmapData}>
          <Layer {...heatmapLayer} />
        </Source>

        <Source id="transit-lines" type="geojson" data={linesGeoJSON}>
          <Layer {...lineCasingLayer} />
          <Layer {...lineRouteLayer} />
        </Source>

        <Source id="transit-stops" type="geojson" data={stopsGeoJSON}>
          <Layer {...stopCircleLayer} />
          <Layer {...stopDotLayer} />
          <Layer {...stopLabelLayer} />
        </Source>

        {/* Deploy indicator — pulsing ring on the next trigger station */}
        <Source id="deploy-trigger" type="geojson" data={triggerGeoJSON}>
          <Layer {...deployPulseRingLayer} />
          <Layer {...deployGlowDotLayer} />
        </Source>

        {/* Tooltip marker above the trigger node */}
        {triggerCoords && nextStep?.label && (
          <Marker
            longitude={triggerCoords[0]}
            latitude={triggerCoords[1]}
            anchor="bottom"
            offset={[0, -30]}
          >
            <div className="deploy-tooltip">
              <span className="deploy-tooltip-icon">⚡</span>
              <span>{nextStep.label}</span>
            </div>
          </Marker>
        )}
      </Map>

      {/* Off-screen arrow pointing toward the deploy node */}
      {offscreenArrow && nextStep?.label && (
        <div
          className="offscreen-arrow"
          style={{
            left: `${offscreenArrow.x}px`,
            top: `${offscreenArrow.y}px`,
            transform: `translate(-50%, -50%) rotate(${offscreenArrow.angle}deg)`,
          }}
        >
          <span className="offscreen-arrow-label">{nextStep.label}</span>
          <span className="offscreen-arrow-chevron">›</span>
        </div>
      )}

      <div className="time-controls-wrapper">
        {WEEKDAYS.map((dayLabel, index) => {
          const angleDeg = nodeAngles[index];
          const angleRad = angleDeg * Math.PI / 180;
          const isFocused = focusIndex === index;
          const R = isFocused ? 122 : 110; 
          const x = Math.cos(angleRad) * R;
          const y = Math.sin(angleRad) * R;

          return (
            <button
              key={index}
              className={`orbit-node ${dayOfWeek === index ? 'is-selected' : ''} ${focusIndex === index ? 'is-focused' : ''}`}
              style={{ '--x': `${x}px`, '--y': `${y}px` } as React.CSSProperties}
              onClick={() => setDayOfWeek(index)}
              onMouseEnter={() => {
                if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
                setHoveredDay(index);
              }}
              onMouseLeave={() => {
                hoverTimeoutRef.current = setTimeout(() => {
                  setHoveredDay(null);
                }, 150);
              }}
              aria-label={`Select day ${index + 1}`}
            >
              {dayLabel}
            </button>
          );
        })}

        <div className="radial-dial-container">
          <div 
            className="radial-dial" 
            ref={dialRef}
            onPointerDown={(e) => {
              setIsDraggingDial(true);
              updateTimeFromPointer(e.clientX, e.clientY);
            }}
            style={{ touchAction: 'none' }}
          >
            <svg viewBox="-75 -75 150 150" className="radial-dial-svg">
              <circle cx="0" cy="0" r={dialRadius} className="dial-track" />
              <line x1="0" y1={-dialRadius - 6} x2="0" y2={-dialRadius + 6} stroke="rgba(43, 77, 112, 0.4)" strokeWidth="2" />
              <line x1="0" y1={dialRadius - 6} x2="0" y2={dialRadius + 6} stroke="rgba(43, 77, 112, 0.4)" strokeWidth="2" />
              <line x1={-dialRadius - 6} y1="0" x2={-dialRadius + 6} y2="0" stroke="rgba(43, 77, 112, 0.4)" strokeWidth="2" />
              <line x1={dialRadius - 6} y1="0" x2={dialRadius + 6} y2="0" stroke="rgba(43, 77, 112, 0.4)" strokeWidth="2" />
              
              <circle 
                cx={thumbX} 
                cy={thumbY} 
                r="8" 
                className="dial-thumb" 
              />
            </svg>
            <div className="dial-center-content">
              <span className="dial-time">{formatTime(timeOfDay)}</span>
              <button
                className="dial-play-btn"
                onClick={(e) => { e.stopPropagation(); setIsPlaying(!isPlaying); }}
                aria-label={isPlaying ? 'Pause' : 'Play'}
              >
                {isPlaying ? 'PAUSE' : 'PLAY'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
