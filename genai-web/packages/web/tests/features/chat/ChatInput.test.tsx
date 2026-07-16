import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChatInput } from '../../../src/features/chat/components/ChatInput';

const mockUseParams = vi.fn().mockReturnValue({ chatId: undefined });
const mockUseLocation = vi.fn().mockReturnValue({
  pathname: '/chat',
  search: '',
  hash: '',
  state: null,
  key: 'default',
});

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useParams: () => mockUseParams(),
    useLocation: () => mockUseLocation(),
  };
});

const mockSetHasSent = vi.fn();
const mockUseChatStore = vi.fn().mockReturnValue({
  content: '',
  setContent: vi.fn(),
  hasSent: false,
  setHasSent: mockSetHasSent,
});
vi.mock('@/features/chat/stores/useChatStore', () => ({
  useChatStore: (...args: unknown[]) => mockUseChatStore(...args),
}));

vi.mock('@/hooks/useChat', () => ({
  useChat: () => ({
    loading: false,
  }),
}));

vi.mock('@/hooks/useFiles', () => ({
  useFiles: () => ({
    uploadedFiles: [],
    uploadFiles: vi.fn(),
    checkFiles: vi.fn(),
    deleteUploadedFile: vi.fn(),
    uploading: false,
    errorMessages: [],
  }),
}));

vi.mock('@/components/ui/AutoResizeTextarea', () => ({
  AutoResizeTextarea: (props: React.ComponentProps<'textarea'>) => <textarea {...props} />,
}));

vi.mock('@/components/ui/LoadingButton', () => ({
  LoadingButton: (props: React.ComponentProps<'button'>) => <button {...props} />,
}));

vi.mock('@/components/ui/dads/Button', () => ({
  Button: (props: React.ComponentProps<'button'>) => <button {...props} />,
}));

vi.mock('@/components/ui/dads/ErrorText', () => ({
  ErrorText: (props: React.ComponentProps<'span'>) => <span {...props} />,
}));

vi.mock('@/components/ui/dads/SupportText', () => ({
  SupportText: (props: React.ComponentProps<'p'>) => <p {...props} />,
}));

vi.mock('@/components/ui/dads/FileUpload', () => ({
  FileUpload: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  FileUploadFileInfo: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  FileUploadFileItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  FileUploadFileList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  FileUploadFileMarker: () => <div />,
  FileUploadFileMeta: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  FileUploadFileName: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  FileUploadInput: () => <input />,
}));

vi.mock('@/components/ui/dads/FileUpload/utils/formatSize', () => ({
  formatSize: () => '0 B',
}));

vi.mock('@/components/ui/icons/AttachmentIcon', () => ({
  AttachmentIcon: () => <span />,
}));

vi.mock('@/components/ui/icons/SendIcon', () => ({
  SendIcon: () => <span />,
}));

vi.mock('@/utils/keyboard', () => ({
  isSubmitKey: () => false,
  requestSubmitOnEnter: () => {},
  submitKeyHint: 'Enter で送信 / Shift+Enter で改行',
}));

const defaultProps = {
  onSend: vi.fn(),
  fileUpload: false,
  accept: [],
};

const renderChatInput = (props = {}) => {
  return render(
    <MemoryRouter>
      <ChatInput {...defaultProps} {...props} />
    </MemoryRouter>,
  );
};

describe('ChatInput', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseParams.mockReturnValue({ chatId: undefined });
    mockUseLocation.mockReturnValue({
      pathname: '/chat',
      search: '',
      hash: '',
      state: null,
      key: 'default',
    });
    mockUseChatStore.mockReturnValue({
      content: '',
      setContent: vi.fn(),
      hasSent: false,
      setHasSent: mockSetHasSent,
    });
  });

  describe('initial chat label visibility', () => {
    it('should show initial chat label when chatId is absent and no message sent', () => {
      renderChatInput();

      const heading = screen.getByRole('heading', { level: 2 });
      expect(heading.textContent).toBe('調べたいことやお困りごとなど、何でも入力してみましょう');
    });

    it('should show active chat label when chatId is present', () => {
      mockUseParams.mockReturnValue({ chatId: 'existing-chat-id' });
      renderChatInput();

      const heading = screen.getByRole('heading', { level: 2 });
      expect(heading.textContent).toBe('追加で質問や不明点などあれば返答してみましょう');
    });

    it('should show active chat label when hasSent is true (e.g. autoSubmit from landing)', () => {
      mockUseChatStore.mockReturnValue({
        content: '',
        setContent: vi.fn(),
        hasSent: true,
        setHasSent: mockSetHasSent,
      });
      renderChatInput();

      const heading = screen.getByRole('heading', { level: 2 });
      expect(heading.textContent).toBe('追加で質問や不明点などあれば返答してみましょう');
    });

    it('should call setHasSent(true) after sending a message', async () => {
      const onSend = vi.fn();
      renderChatInput({ onSend });

      const textarea = screen.getByRole('textbox');
      await userEvent.type(textarea, 'hello');

      const form = textarea.closest('form')!;
      form.requestSubmit();

      await waitFor(() => {
        expect(mockSetHasSent).toHaveBeenCalledWith(true);
      });
    });
  });

  describe('textarea rows', () => {
    it('should have rows=3 on initial chat', () => {
      renderChatInput();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('rows')).toBe('3');
    });

    it('should have rows=1 when chatId is present', () => {
      mockUseParams.mockReturnValue({ chatId: 'existing-chat-id' });
      renderChatInput();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('rows')).toBe('1');
    });

    it('should have rows=1 when hasSent is true (e.g. autoSubmit from landing)', () => {
      mockUseChatStore.mockReturnValue({
        content: '',
        setContent: vi.fn(),
        hasSent: true,
        setHasSent: mockSetHasSent,
      });
      renderChatInput();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('rows')).toBe('1');
    });
  });

  describe('submit key hint', () => {
    it('should show Enter/Shift+Enter hint near the input', () => {
      renderChatInput();

      expect(screen.getByText('Enter で送信 / Shift+Enter で改行')).toBeDefined();
    });

    it('should associate hint with textarea via aria-describedby', () => {
      renderChatInput();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('aria-describedby')).toContain('chat-input-submit-hint');
    });
  });

  describe('hash navigation (NavSkip)', () => {
    it('should keep active chat label after hash navigation when hasSent is true', () => {
      mockUseChatStore.mockReturnValue({
        content: '',
        setContent: vi.fn(),
        hasSent: true,
        setHasSent: mockSetHasSent,
      });

      // ハッシュ遷移後: state が失われ key が変わっても、store の hasSent は変わらない
      mockUseLocation.mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '#mainContents',
        state: null,
        key: 'hash-nav-key',
      });
      renderChatInput();

      const heading = screen.getByRole('heading', { level: 2 });
      expect(heading.textContent).toBe('追加で質問や不明点などあれば返答してみましょう');
    });

    it('should keep rows=1 after hash navigation when hasSent is true', () => {
      mockUseChatStore.mockReturnValue({
        content: '',
        setContent: vi.fn(),
        hasSent: true,
        setHasSent: mockSetHasSent,
      });

      mockUseLocation.mockReturnValue({
        pathname: '/chat',
        search: '',
        hash: '#mainContents',
        state: null,
        key: 'hash-nav-key',
      });
      renderChatInput();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('rows')).toBe('1');
    });
  });
});
