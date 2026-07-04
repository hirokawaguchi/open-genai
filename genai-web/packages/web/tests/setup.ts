import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Clean up after each test
afterEach(() => {
  cleanup();
});

class ResizeObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

global.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

// Mock IntersectionObserver
// コールバックを自動的に呼び出さない（floating-ui や headlessui が内部的に使用するため）
class IntersectionObserverMock {
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
}

global.IntersectionObserver = IntersectionObserverMock as unknown as typeof IntersectionObserver;

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // deprecated
    removeListener: vi.fn(), // deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock Element.prototype.scrollTo
Element.prototype.scrollTo = vi.fn();

// Polyfill HTMLFormElement.prototype.requestSubmit for jsdom
if (!HTMLFormElement.prototype.requestSubmit) {
  HTMLFormElement.prototype.requestSubmit = function (submitter?: HTMLElement) {
    if (submitter) {
      (submitter as HTMLButtonElement).click();
      return;
    }
    const button = document.createElement('button');
    button.type = 'submit';
    button.hidden = true;
    this.appendChild(button);
    button.click();
    button.remove();
  };
}
