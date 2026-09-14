import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useFileUploadable } from '../../../../src/features/chat/hooks/useFileUploadable';

const mockUseSelectedModel = vi.fn();

vi.mock('@/hooks/useSelectedModel', () => ({
  useSelectedModel: () => mockUseSelectedModel(),
}));

vi.mock('@/models', () => ({
  MODELS: {
    modelMetadata: {
      'known-doc': { flags: { text: true, doc: true, image: false, video: false } },
      'known-image': { flags: { text: true, doc: true, image: true, video: false } },
    },
  },
}));

describe('useFileUploadable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('hides the attach button when no model is selected', () => {
    mockUseSelectedModel.mockReturnValue({ selectedModelId: '' });
    const { result } = renderHook(() => useFileUploadable());
    expect(result.current.fileUploadable).toBe(false);
    expect(result.current.accept).toEqual([]);
  });

  it('allows documents for a registered text/doc model', () => {
    mockUseSelectedModel.mockReturnValue({ selectedModelId: 'known-doc' });
    const { result } = renderHook(() => useFileUploadable());
    expect(result.current.fileUploadable).toBe(true);
    expect(result.current.accept).toContain('.pdf');
    expect(result.current.accept).not.toContain('.png');
  });

  it('allows images for a registered multimodal model', () => {
    mockUseSelectedModel.mockReturnValue({ selectedModelId: 'known-image' });
    const { result } = renderHook(() => useFileUploadable());
    expect(result.current.fileUploadable).toBe(true);
    expect(result.current.accept).toContain('.png');
  });

  it('falls back to document attach for an unregistered local model id', () => {
    mockUseSelectedModel.mockReturnValue({
      selectedModelId: 'gemma-4-26B-A4B-it-Q4_K_M.gguf',
    });
    const { result } = renderHook(() => useFileUploadable());
    expect(result.current.fileUploadable).toBe(true);
    expect(result.current.accept).toContain('.pdf');
    expect(result.current.accept).not.toContain('.png');
  });
});
