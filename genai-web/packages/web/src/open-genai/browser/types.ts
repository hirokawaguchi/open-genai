export type BrowserConfig = {
  enabled?: boolean;
  idle_seconds?: number;
  max_sessions?: number;
  max_sessions_per_user?: number;
  width?: number;
  height?: number;
  delivery?: 'open' | 'carrier';
  error?: string;
};

export type BrowserSessionInfo = {
  id: string;
  width: number;
  height: number;
};
