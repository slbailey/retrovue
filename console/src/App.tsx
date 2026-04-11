import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AssetsPage } from './AssetsPage';

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen flex-col bg-gray-950">
        <header className="border-b border-gray-800 px-4 py-3">
          <span className="text-lg font-semibold text-gray-100">RetroVue Console</span>
        </header>
        <main className="flex-1">
          <Routes>
            <Route path="/assets" element={<AssetsPage />} />
            <Route path="*" element={<Navigate to="/assets" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
