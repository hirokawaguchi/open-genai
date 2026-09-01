import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatPage } from '../../../src/features/chat/ChatPage';

const mockPostChat = vi.fn();
const mockSetShouldAutoSubmit = vi.fn();
const mockSetContent = vi.fn();
const mockSetInputSystemContext = vi.fn();
const mockUpdateSystemContext = vi.fn();
const mockSetFollowing = vi.fn();
const mockClearFiles = vi.fn();
let mockIsSticky = false;

let mockStoreState = {
  content: '',
  inputSystemContext: '',
  saveSystemContext: '',
  isDragOver: false,
  shouldAutoSubmit: false,
};

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useLocation: vi.fn().mockReturnValue({
      pathname: '/chat',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    }),
    useParams: vi.fn().mockReturnValue({ chatId: undefined }),
  };
});

vi.mock('@/features/chat/stores/useChatStore', () => ({
  useChatStore: () => ({
    ...mockStoreState,
    setContent: mockSetContent,
    setInputSystemContext: mockSetInputSystemContext,
    setSaveSystemContext: vi.fn(),
    setIsDragOver: vi.fn(),
    setShouldAutoSubmit: mockSetShouldAutoSubmit,
  }),
}));

vi.mock('@/hooks/useChat', () => ({
  useChat: () => ({
    loading: false,
    loadingMessages: false,
    isEmpty: true,
    messages: [],
    clear: vi.fn(),
    postChat: mockPostChat,
    updateSystemContext: mockUpdateSystemContext,
    updateSystemContextByModel: vi.fn(),
    getCurrentSystemContext: vi.fn().mockReturnValue('default-system-context'),
    retryGeneration: vi.fn(),
  }),
}));

vi.mock('@/hooks/useFiles', () => ({
  useFiles: () => ({
    clear: mockClearFiles,
    uploadedFiles: [],
    base64Cache: {},
  }),
}));

vi.mock('@/hooks/useFollow', () => ({
  useFollow: () => ({
    scrollableContainer: { current: null },
    setFollowing: mockSetFollowing,
  }),
}));

vi.mock('@/hooks/usePrompter', () => ({
  usePrompter: () => ({
    prompter: {
      chatPrompt: vi.fn().mockImplementation(({ content }) => content),
    },
  }),
}));

vi.mock('@/hooks/useScreen', () => ({
  useScreen: () => ({
    screen: { current: null },
    scrollTopAnchorRef: { current: null },
    scrollBottomAnchorRef: { current: null },
  }),
}));

vi.mock('@/features/chat/hooks/useChatTitle', () => ({
  useChatTitle: () => ({
    title: 'チャット',
  }),
}));

vi.mock('@/features/chat/hooks/useFileUploadable', () => ({
  useFileUploadable: () => ({
    accept: '',
    fileUploadable: false,
  }),
}));

vi.mock('@/features/chat/hooks/useStickyHeader', () => ({
  useStickyHeader: () => mockIsSticky,
}));

vi.mock('@/features/chat/hooks/useReset', () => ({
  useReset: vi.fn(),
}));

vi.mock('@/features/chat/hooks/useSetDefaultValues', () => ({
  useSetDefaultValues: vi.fn(),
}));

vi.mock('@/features/chat/hooks/useSystemContext', () => ({
  useSystemContext: () => ({
    systemContextList: [],
    onSaveSystemContext: vi.fn(),
    onDeleteSystemContext: vi.fn(),
    onUpdateSystemContext: vi.fn(),
  }),
}));

vi.mock('@/hooks/useLiveStatusMessage', () => ({
  useLiveStatusMessage: () => ({
    liveStatusMessage: '',
  }),
}));

vi.mock('@/components/PageTitle', () => ({
  PageTitle: () => null,
}));

vi.mock('@/features/chat/components/ChatMessage', () => ({
  ChatMessage: () => null,
}));

vi.mock('@/features/chat/components/DialogPromptList', () => ({
  DialogPromptList: () => null,
}));

vi.mock('@/features/chat/components/DialogSaveSystemContext', () => ({
  DialogSaveSystemContext: () => null,
}));

vi.mock('@/features/chat/components/FileDrop', () => ({
  FileDrop: () => null,
}));

vi.mock('@/features/chat/components/ChatInput', () => ({
  ChatInput: () => null,
}));

vi.mock('@/features/chat/components/ModelSelector', () => ({
  ModelSelector: () => <button type='button'>モデル選択</button>,
}));

vi.mock('@/features/chat/components/SystemPrompt', () => ({
  SystemPrompt: () => null,
}));

vi.mock('@/features/chat/components/Title', () => ({
  Title: () => null,
}));

vi.mock('@/components/ui/ScrollBottomButton', () => ({
  ScrollBottomButton: () => null,
}));

describe('ChatPage', () => {
  const renderComponent = () => {
    return render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>,
    );
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockIsSticky = false;
    mockStoreState = {
      content: '',
      inputSystemContext: '',
      saveSystemContext: '',
      isDragOver: false,
      shouldAutoSubmit: false,
    };
    const { useLocation } = await import('react-router');
    vi.mocked(useLocation).mockReturnValue({
      pathname: '/chat',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    });
  });

  describe('auto-submit', () => {
    it('sends chat automatically when shouldAutoSubmit is true with content and inputSystemContext', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockPostChat).toHaveBeenCalledTimes(1);
      });

      expect(mockSetShouldAutoSubmit).toHaveBeenCalledWith(false);
    });

    it('does not send chat when shouldAutoSubmit is true but content is empty', async () => {
      mockStoreState = {
        content: '',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockPostChat).not.toHaveBeenCalled();
      });
    });

    it('does not send chat when shouldAutoSubmit is true but inputSystemContext is empty', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: '',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockPostChat).not.toHaveBeenCalled();
      });
    });

    it('does not clear prefilled content from location state when messages are empty', async () => {
      const { useLocation } = await import('react-router');
      vi.mocked(useLocation).mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '',
        state: { content: 'テンプレート本文', autoSubmit: false, shouldReset: false },
        key: 'default',
      });
      mockStoreState = {
        content: 'テンプレート本文',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: false,
      };

      await act(async () => {
        renderComponent();
      });

      expect(mockSetContent).not.toHaveBeenCalledWith('');
    });

    it('does not send chat when shouldAutoSubmit is false', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: false,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockPostChat).not.toHaveBeenCalled();
      });
    });

    it('resets shouldAutoSubmit flag after sending', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockSetShouldAutoSubmit).toHaveBeenCalledWith(false);
      });
    });

    it('clears content after sending', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockSetContent).toHaveBeenCalledWith('');
      });
    });

    it('sets following to true when sending', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockSetFollowing).toHaveBeenCalledWith(true);
      });
    });

    it('clears files after sending', async () => {
      mockStoreState = {
        content: 'テストメッセージ',
        inputSystemContext: 'システムプロンプト',
        saveSystemContext: '',
        isDragOver: false,
        shouldAutoSubmit: true,
      };

      await act(async () => {
        renderComponent();
      });

      await waitFor(() => {
        expect(mockClearFiles).toHaveBeenCalled();
      });
    });
  });

});
