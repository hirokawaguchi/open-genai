import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ExApp } from 'genai-web';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamAppCopyForm } from '../../../../../src/features/team-apps/copy/components/TeamAppCopyForm';
import { useCopyTeamApp } from '../../../../../src/features/team-apps/copy/hooks/useCopyTeamApp';
import { teamAppCopySchema } from '../../../../../src/features/team-apps/copy/schema';
import { ApiError } from '../../../../../src/lib/fetcher';
import * as focusModule from '../../../../../src/utils/focus';

// Mock dependencies
vi.mock('@/features/team-apps/copy/hooks/useCopyTeamApp');
vi.mock('@/utils/focus');
const mockCopyTeamApp = vi.fn();
const mockMutateTeamApps = vi.fn();
const mockFocus = vi.fn();
const mockNavigate = vi.fn();

// Mock useNavigate
vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock ExApp data
const createMockApp = (overrides: Partial<ExApp> = {}): ExApp => ({
  teamId: 'team-1',
  exAppId: 'app-1',
  exAppName: 'テストアプリ',
  endpoint: 'https://api.example.com/test',
  config: '{"max_payload_size": 1000}',
  placeholder: '{"input": "value"}',
  systemPrompt: '',
  systemPromptKeyName: 'systemPrompt',
  description: 'テストアプリの概要',
  apiKey: '',
  howToUse: 'テストアプリの使い方',
  copyable: true,
  status: 'published',
  createdDate: '2026-01-01T00:00:00Z',
  updatedDate: '2026-01-01T00:00:00Z',
  ...overrides,
});

describe('TeamAppCopyForm', () => {
  const renderWithRouter = (app: ExApp = createMockApp(), teamId = 'team-1', appId = 'app-1') => {
    return render(
      <MemoryRouter initialEntries={[`/teams/${teamId}/apps/${appId}/copy`]}>
        <Routes>
          <Route path='/teams/:teamId/apps/:appId/copy' element={<TeamAppCopyForm app={app} />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default mocks
    vi.mocked(useCopyTeamApp).mockReturnValue({
      copyTeamApp: mockCopyTeamApp,
      mutateTeamApps: mockMutateTeamApps,
    });

    vi.mocked(focusModule.focus).mockImplementation(mockFocus);
  });

  describe('Rendering', () => {
    it('renders name input field with initial value from copied app', () => {
      const app = createMockApp({ exAppName: 'コピー元アプリ' });
      renderWithRouter(app);

      const input = screen.getByRole('textbox', { name: /名前/ }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('required')).toBe('');
      expect(input.value).toBe('コピー元アプリ');
    });

    it('renders description input field with initial value', () => {
      const app = createMockApp({ description: '初期概要' });
      renderWithRouter(app);

      const input = screen.getByRole('textbox', { name: /概要/ }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('required')).toBe('');
      expect(input.value).toBe('初期概要');
    });

    it('renders how to use textarea with initial value', () => {
      const app = createMockApp({ howToUse: '初期使い方' });
      renderWithRouter(app);

      const textarea = screen.getByRole('textbox', { name: /使い方/ }) as HTMLTextAreaElement;
      expect(textarea).toBeDefined();
      expect(textarea.getAttribute('required')).toBe('');
      expect(textarea.value).toBe('初期使い方');
    });

    it('renders endpoint input field as editable with initial value', () => {
      const app = createMockApp({ endpoint: 'https://editable.example.com' });
      renderWithRouter(app);

      const input = screen.getByRole('textbox', {
        name: /APIエンドポイントのURL/,
      }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('readonly')).toBeNull();
      expect(input.value).toBe('https://editable.example.com');
    });

    it('renders API key input field as editable and empty by default', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /APIキー/ }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('readonly')).toBeNull();
      expect(input.value).toBe('');
    });

    it('renders UI format textarea with initial value', () => {
      const app = createMockApp({ placeholder: '{"test": "data"}' });
      renderWithRouter(app);

      const textarea = screen.getByRole('textbox', {
        name: /APIリクエストのデータ形式/,
      }) as HTMLTextAreaElement;
      expect(textarea).toBeDefined();
      expect(textarea.getAttribute('required')).toBeNull();
      expect(textarea.value).toBe('{"test": "data"}');
    });

    it('renders config textarea with initial value', () => {
      const app = createMockApp({ config: '{"setting": true}' });
      renderWithRouter(app);

      const textarea = screen.getByRole('textbox', { name: /コンフィグ/ }) as HTMLTextAreaElement;
      expect(textarea).toBeDefined();
      expect(textarea.value).toBe('{"setting": true}');
    });

    it('renders status select with empty initial value', () => {
      renderWithRouter();

      const select = screen.getByRole('combobox', { name: /ステータス/ }) as HTMLSelectElement;
      expect(select).toBeDefined();
      expect(select.value).toBe('');
    });

    it('renders copyable checkbox with initial value', () => {
      const app = createMockApp({ copyable: true });
      renderWithRouter(app);

      const checkbox = screen.getByRole('checkbox', {
        name: /コピー可能にする/,
      }) as HTMLInputElement;
      expect(checkbox).toBeDefined();
      expect(checkbox.checked).toBe(true);
    });

    it('renders system prompt textarea with initial value', () => {
      const app = createMockApp({ systemPrompt: '既存のシステムプロンプト' });
      renderWithRouter(app);

      const systemPromptTextarea = screen.getByRole('textbox', {
        name: (name, element) =>
          /システムプロンプト/.test(name) && element.id === 'team-app-copy-system-prompt',
      }) as HTMLTextAreaElement;
      expect(systemPromptTextarea).toBeDefined();
      expect(systemPromptTextarea.value).toBe('既存のシステムプロンプト');
    });

    it('renders system prompt key input with initial value', () => {
      const app = createMockApp({ systemPromptKeyName: 'system' });
      renderWithRouter(app);

      const systemPromptKeyInput = screen.getByRole('textbox', {
        name: /システムプロンプトのキー名/,
      }) as HTMLInputElement;
      expect(systemPromptKeyInput).toBeDefined();
      expect(systemPromptKeyInput.value).toBe('system');
    });

    it('renders submit button with copy text', () => {
      renderWithRouter();

      const button = screen.getByRole('button', { name: 'コピーして作成' });
      expect(button).toBeDefined();
      expect(button.getAttribute('type')).toBe('submit');
    });

    it('does not show readonly badges for endpoint and API key fields', () => {
      renderWithRouter();

      expect(screen.queryByText('編集不可')).toBeNull();
    });
  });

  describe('Form Submission', () => {
    const selectStatus = async (user: ReturnType<typeof userEvent.setup>) => {
      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, 'published');
    };

    it('calls copyTeamApp with correct parameters on valid submission', async () => {
      const user = userEvent.setup();
      const app = createMockApp({
        teamId: 'team-123',
        exAppId: 'app-456',
      });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-new',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app, 'team-123', 'app-456');

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          'team-123',
          'app-456',
          expect.objectContaining({
            exAppName: 'テストアプリ',
            endpoint: 'https://api.example.com/test',
            config: '{"max_payload_size": 1000}',
            placeholder: '{"input": "value"}',
            systemPrompt: '',
            systemPromptKeyName: 'systemPrompt',
            description: 'テストアプリの概要',
            howToUse: 'テストアプリの使い方',
            copyable: true,
            status: 'published',
          }),
        );
      });
    });

    it('includes edited endpoint and apiKey in copy request', async () => {
      const user = userEvent.setup();
      const app = createMockApp({
        endpoint: 'https://api.example.com/original',
      });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-new',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app);

      const endpointInput = screen.getByRole('textbox', { name: /APIエンドポイントのURL/ });
      await user.clear(endpointInput);
      await user.type(endpointInput, 'https://api.example.com/custom');

      const apiKeyInput = screen.getByRole('textbox', { name: /APIキー/ });
      await user.type(apiKeyInput, 'custom-api-key');

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            endpoint: 'https://api.example.com/custom',
            apiKey: 'custom-api-key',
          }),
        );
      });
    });

    it('allows empty UI format for chat apps', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ placeholder: '' });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-new',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app);

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            placeholder: '',
          }),
        );
      });
    });

    it('calls mutateTeamApps after successful submission', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateTeamApps).toHaveBeenCalled();
      });
    });

    it('navigates to apps page after successful submission', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ teamId: 'team-456' });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app, 'team-456');

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/teams/team-456/apps');
      });
    });

    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      let resolveCopyTeamApp: (value: unknown) => void;
      const copyTeamAppPromise = new Promise((resolve) => {
        resolveCopyTeamApp = resolve;
      });
      mockCopyTeamApp.mockReturnValue(copyTeamAppPromise);

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const loadingButton = screen.getByRole('button', { name: '作成中' });
        expect(loadingButton).toBeDefined();
      });

      resolveCopyTeamApp!({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });
    });

    it('includes updated copyable value when checkbox is toggled', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ copyable: true });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app);

      await selectStatus(user);

      const copyableCheckbox = screen.getByRole('checkbox', { name: /コピー可能にする/ });
      await user.click(copyableCheckbox);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            copyable: false,
          }),
        );
      });
    });

    it('includes system prompt values when filled', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter();

      await selectStatus(user);

      const systemPromptTextarea = screen.getByRole('textbox', {
        name: (name, element) =>
          /システムプロンプト/.test(name) && element.id === 'team-app-copy-system-prompt',
      });
      await user.type(systemPromptTextarea, 'You are a helpful assistant.');

      const systemPromptKeyInput = screen.getByRole('textbox', {
        name: /システムプロンプトのキー名/,
      });

      await user.clear(systemPromptKeyInput);
      await user.type(systemPromptKeyInput, 'system_prompt');

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            systemPrompt: 'You are a helpful assistant.',
            systemPromptKeyName: 'system_prompt',
          }),
        );
      });
    });

    it('updates app name correctly', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ exAppName: 'コピー元アプリ' });
      mockCopyTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'コピー後のアプリ名',
      });

      renderWithRouter(app);

      await selectStatus(user);

      const nameInput = screen.getByRole('textbox', { name: /名前/ });
      await user.clear(nameInput);
      await user.type(nameInput, 'コピー後のアプリ名');

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            exAppName: 'コピー後のアプリ名',
          }),
        );
      });
    });
  });

  describe('Validation', () => {
    it('validates name is required in schema', () => {
      const result = teamAppCopySchema.safeParse({
        name: '',
        endpoint: 'https://api.example.com/test',
        uiFormat: '{}',
        description: 'test',
        howToUse: 'test',
        copyable: false,
        status: 'published',
      });
      expect(result.success).toBe(false);
      if (!result.success) {
        const nameError = result.error.issues.find((issue) => issue.path.includes('name'));
        expect(nameError?.message).toContain('AIアプリ名を入力してください');
      }
    });

    it('allows empty uiFormat in schema', () => {
      const result = teamAppCopySchema.safeParse({
        name: 'test',
        endpoint: 'https://api.example.com/test',
        uiFormat: '',
        description: 'test',
        howToUse: 'test',
        copyable: false,
        status: 'published',
      });
      expect(result.success).toBe(true);
    });

    it('shows error message for invalid JSON in UI format', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const uiFormatInput = screen.getByRole('textbox', { name: /APIリクエストのデータ形式/ });
      await user.clear(uiFormatInput);
      await user.type(uiFormatInput, 'invalid json');

      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, 'published');

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/APIリクエストのデータ形式はJSON形式にしてください/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('shows error message when status is not selected', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/ステータスを選択してください/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('does not call copyTeamApp on validation failure', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const nameInput = screen.getByRole('textbox', { name: /名前/ });
      await user.clear(nameInput);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCopyTeamApp).not.toHaveBeenCalled();
      });
    });
  });

  describe('Error Handling', () => {
    const selectStatus = async (user: ReturnType<typeof userEvent.setup>) => {
      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, 'published');
    };

    it('displays server error message on API error', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockRejectedValue(
        new ApiError(400, {
          error: 'このアプリ名は既に使用されています',
        }),
      );

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText('このアプリ名は既に使用されています');
        expect(errorMessage).toBeDefined();
      });
    });

    it('displays generic error message on non-API error', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockRejectedValue(new Error('Unknown error'));

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(
          'システムエラーが発生しました。ページをリロードして再度お試しください。',
        );
        expect(errorMessage).toBeDefined();
      });
    });

    it('calls focus on server-error heading when error occurs', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockRejectedValue(
        new ApiError(500, {
          error: 'サーバーエラー',
        }),
      );

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFocus).toHaveBeenCalledWith('server-error');
      });
    });
  });

  describe('Accessibility', () => {
    const selectStatus = async (user: ReturnType<typeof userEvent.setup>) => {
      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, 'published');
    };

    it('has sr-only heading for server error section', async () => {
      const user = userEvent.setup();
      mockCopyTeamApp.mockRejectedValue(
        new ApiError(400, {
          error: 'エラー',
        }),
      );

      renderWithRouter();

      await selectStatus(user);

      const submitButton = screen.getByRole('button', { name: 'コピーして作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const heading = screen.getByRole('heading', { name: 'システムエラー' });
        expect(heading).toBeDefined();
        expect(heading.className).toContain('sr-only');
      });
    });

    it('renders required badges for mandatory fields', () => {
      renderWithRouter();

      const requiredBadges = screen.getAllByText('※必須');
      expect(requiredBadges.length).toBeGreaterThan(0);
    });

    it('renders optional badge for config field', () => {
      renderWithRouter();

      const optionalBadges = screen.getAllByText('※任意');
      expect(optionalBadges.length).toBeGreaterThan(0);
    });

    it('has support text for description field', () => {
      renderWithRouter();

      const supportText = screen.getByText(/一覧に表示する簡単な説明/);
      expect(supportText).toBeDefined();
    });

    it('has support text for how to use field', () => {
      renderWithRouter();

      const supportText = screen.getByText(/想定用途・入力例・仕組みなど/);
      expect(supportText).toBeDefined();
    });

    it('has support text indicating API key falls back to source', () => {
      renderWithRouter();

      const supportText = screen.getByText(/未入力の場合はコピー元のAPIキーを使用します/);
      expect(supportText).toBeDefined();
    });

    it('has support text indicating UI format can be empty for chat apps', () => {
      renderWithRouter();

      const supportText = screen.getByText(/対話型（Dify チャット）や入力不要のアプリでは空で構いません/);
      expect(supportText).toBeDefined();
    });
  });
});
