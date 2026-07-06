import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatSubmit } from '../../../../src/features/chat/hooks/useChatSubmit';

const mockSetContent = vi.fn();
const mockSetShouldAutoSubmit = vi.fn();
const mockClearFiles = vi.fn();
const mockChatPrompt = vi.fn().mockReturnValue('prompted-content');

let mockStoreState = {
  content: '',
  inputSystemContext: 'system-context',
  shouldAutoSubmit: false,
};

vi.mock('react-router', () => ({
  useLocation: vi.fn().mockReturnValue({
    pathname: '/chat',
    search: '',
    hash: '',
    state: undefined,
    key: 'default',
  }),
}));

vi.mock('@/features/chat/stores/useChatStore', () => ({
  useChatStore: () => ({
    content: mockStoreState.content,
    setContent: mockSetContent,
    inputSystemContext: mockStoreState.inputSystemContext,
    shouldAutoSubmit: mockStoreState.shouldAutoSubmit,
    setShouldAutoSubmit: mockSetShouldAutoSubmit,
  }),
}));

vi.mock('@/hooks/useFiles', () => ({
  useFiles: () => ({
    clear: mockClearFiles,
    uploadedFiles: [],
    base64Cache: {},
  }),
}));

vi.mock('@/hooks/usePrompter', () => ({
  usePrompter: () => ({
    prompter: {
      chatPrompt: mockChatPrompt,
    },
  }),
}));

vi.mock('@/features/chat/hooks/useFileUploadable', () => ({
  useFileUploadable: () => ({
    fileUploadable: false,
    accept: '',
  }),
}));

vi.mock('@/hooks/useChat', () => ({
  useChat: () => ({}),
}));

const createDefaultProps = () => ({
  usecase: '/chat',
  postChat: vi.fn(),
  retryGeneration: vi.fn(),
  updateSystemContext: vi.fn(),
  getCurrentSystemContext: vi.fn().mockReturnValue('system-context'),
  loading: false,
  setFollowing: vi.fn(),
});

describe('useChatSubmit', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockStoreState = {
      content: '',
      inputSystemContext: 'system-context',
      shouldAutoSubmit: false,
    };
  });

  describe('auto-submit', () => {
    it('should call postChat and setShouldAutoSubmit(false) when shouldAutoSubmit is true', async () => {
      mockStoreState.content = 'hello';
      mockStoreState.shouldAutoSubmit = true;

      const props = createDefaultProps();

      renderHook(() => useChatSubmit(props));

      expect(props.postChat).toHaveBeenCalled();
      expect(mockSetShouldAutoSubmit).toHaveBeenCalledWith(false);
      expect(mockSetContent).toHaveBeenCalledWith('');
      expect(mockClearFiles).toHaveBeenCalled();
    });

    it('should not call postChat when loading is true', () => {
      mockStoreState.content = 'hello';
      mockStoreState.shouldAutoSubmit = true;

      const props = createDefaultProps();
      props.loading = true;

      renderHook(() => useChatSubmit(props));

      expect(props.postChat).not.toHaveBeenCalled();
      expect(mockSetShouldAutoSubmit).not.toHaveBeenCalled();
    });

    it('should not call postChat when content is empty', () => {
      mockStoreState.content = '';
      mockStoreState.shouldAutoSubmit = true;

      const props = createDefaultProps();

      renderHook(() => useChatSubmit(props));

      expect(props.postChat).not.toHaveBeenCalled();
    });

    it('should clear autoSubmit from history state via replaceState', async () => {
      mockStoreState.content = 'hello';
      mockStoreState.shouldAutoSubmit = true;

      const { useLocation } = await import('react-router');
      vi.mocked(useLocation).mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '',
        state: { autoSubmit: true, systemContext: 'ctx' },
        key: 'default',
        unstable_mask: undefined,
      });

      const replaceStateSpy = vi.spyOn(window.history, 'replaceState');

      const props = createDefaultProps();

      renderHook(() => useChatSubmit(props));

      expect(replaceStateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          usr: { systemContext: 'ctx' },
        }),
        '',
      );

      replaceStateSpy.mockRestore();
    });

    it('should set usr to undefined when autoSubmit is the only state property', async () => {
      mockStoreState.content = 'hello';
      mockStoreState.shouldAutoSubmit = true;

      const { useLocation } = await import('react-router');
      vi.mocked(useLocation).mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '',
        state: { autoSubmit: true },
        key: 'default',
        unstable_mask: undefined,
      });

      const replaceStateSpy = vi.spyOn(window.history, 'replaceState');

      const props = createDefaultProps();

      renderHook(() => useChatSubmit(props));

      expect(replaceStateSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          usr: undefined,
        }),
        '',
      );

      replaceStateSpy.mockRestore();
    });

    it('should not call replaceState when state has no autoSubmit', async () => {
      mockStoreState.content = 'hello';
      mockStoreState.shouldAutoSubmit = true;

      const { useLocation } = await import('react-router');
      vi.mocked(useLocation).mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '',
        state: undefined,
        key: 'default',
        unstable_mask: undefined,
      });

      const replaceStateSpy = vi.spyOn(window.history, 'replaceState');

      const props = createDefaultProps();

      renderHook(() => useChatSubmit(props));

      expect(props.postChat).toHaveBeenCalled();
      expect(replaceStateSpy).not.toHaveBeenCalled();

      replaceStateSpy.mockRestore();
    });
  });

  describe('onSend', () => {
    it('should update system context when inputSystemContext differs from current', () => {
      mockStoreState.content = 'hello';
      mockStoreState.inputSystemContext = 'new-system-context';

      const props = createDefaultProps();
      props.getCurrentSystemContext.mockReturnValue('old-system-context');

      const { result } = renderHook(() => useChatSubmit(props));

      act(() => {
        result.current.onSend();
      });

      expect(props.updateSystemContext).toHaveBeenCalledWith('new-system-context');
    });

    it('should not update system context when inputSystemContext matches current', () => {
      mockStoreState.content = 'hello';
      mockStoreState.inputSystemContext = 'same-context';

      const props = createDefaultProps();
      props.getCurrentSystemContext.mockReturnValue('same-context');

      const { result } = renderHook(() => useChatSubmit(props));

      act(() => {
        result.current.onSend();
      });

      expect(props.updateSystemContext).not.toHaveBeenCalled();
    });

    it('should set following to true', () => {
      mockStoreState.content = 'hello';

      const props = createDefaultProps();

      const { result } = renderHook(() => useChatSubmit(props));

      act(() => {
        result.current.onSend();
      });

      expect(props.setFollowing).toHaveBeenCalledWith(true);
    });
  });

  describe('onRetry', () => {
    it('should call retryGeneration', () => {
      const props = createDefaultProps();

      const { result } = renderHook(() => useChatSubmit(props));

      act(() => {
        result.current.onRetry();
      });

      expect(props.retryGeneration).toHaveBeenCalled();
    });
  });
});
