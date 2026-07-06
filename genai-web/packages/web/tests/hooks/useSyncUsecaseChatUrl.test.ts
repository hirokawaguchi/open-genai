import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useSyncUsecaseChatUrl } from '@/hooks/useSyncUsecaseChatUrl';

const mockNavigate = vi.fn();

vi.mock('react-router', () => ({
  useNavigate: () => mockNavigate,
}));

describe('useSyncUsecaseChatUrl', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('URL に chatId が無くセッションが作成されたら usecase 付き URL へ遷移する', () => {
    renderHook(() => useSyncUsecaseChatUrl('/image', undefined, 'abc-123'));

    expect(mockNavigate).toHaveBeenCalledWith('/image/abc-123', { replace: true });
  });

  it('URL に chatId がある場合は遷移しない', () => {
    renderHook(() => useSyncUsecaseChatUrl('/image', 'existing-id', 'abc-123'));

    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
