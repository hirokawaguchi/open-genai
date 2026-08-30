import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { GuestApp } from './GuestApp';
import './guest.css';

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <GuestApp />
    </StrictMode>,
  );
}
