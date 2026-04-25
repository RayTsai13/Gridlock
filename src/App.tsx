import { Map } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import './App.css';

function App() {
  return (
    <Map
      initialViewState={{
        longitude: -122.3321,
        latitude: 47.6062,
        zoom: 11,
      }}
      mapStyle="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
      style={{ width: '100vw', height: '100vh' }}
    />
  );
}

export default App;