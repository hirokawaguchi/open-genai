import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ExApp } from 'genai-web';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamAppEditForm } from '../../../../../src/features/team-apps/edit/components/TeamAppEditForm';
import { useUpdateTeamApp } from '../../../../../src/features/team-apps/edit/hooks/useUpdateTeamApp';
import { teamAppEditSchema } from '../../../../../src/features/team-apps/edit/schema';
import { ApiError } from '../../../../../src/lib/fetcher';
import * as focusModule from '../../../../../src/utils/focus';

// Mock dependencies
vi.mock('@/features/team-apps/edit/hooks/useUpdateTeamApp');
vi.mock('@/utils/focus');

const mockUpdateTeamApp = vi.fn();
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

// Helper to fill input without userEvent special character parsing issues
const fillInput = (element: HTMLElement, value: string) => {
  fireEvent.change(element, { target: { value } });
};

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
  copyable: false,
  status: 'published',
  createdDate: '2026-01-01T00:00:00Z',
  updatedDate: '2026-01-01T00:00:00Z',
  ...overrides,
});

describe('TeamAppEditForm', () => {
  const renderWithRouter = (app: ExApp = createMockApp(), teamId = 'team-1', appId = 'app-1') => {
    return render(
      <MemoryRouter initialEntries={[`/teams/${teamId}/apps/${appId}/edit`]}>
        <Routes>
          <Route path='/teams/:teamId/apps/:appId/edit' element={<TeamAppEditForm app={app} />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default mocks
    vi.mocked(useUpdateTeamApp).mockReturnValue({
      updateTeamApp: mockUpdateTeamApp,
      mutateTeamApps: mockMutateTeamApps,
    });

    vi.mocked(focusModule.focus).mockImplementation(mockFocus);
  });

  describe('Rendering', () => {
    it('renders name input field with initial value', () => {
      const app = createMockApp({ exAppName: '初期アプリ名' });
      renderWithRouter(app);

      const input = screen.getByRole('textbox', { name: /名前/ }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('required')).toBe('');
      expect(input.value).toBe('初期アプリ名');
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

    it('renders endpoint input field with initial value', () => {
      const app = createMockApp({ endpoint: 'https://initial.example.com' });
      renderWithRouter(app);

      const input = screen.getByRole('textbox', {
        name: /APIエンドポイントのURL/,
      }) as HTMLInputElement;
      expect(input).toBeDefined();
      expect(input.getAttribute('type')).toBe('url');
      expect(input.getAttribute('required')).toBe('');
      expect(input.value).toBe('https://initial.example.com');
    });

    it('renders API key input field (optional in edit mode)', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /APIキー/ });
      expect(input).toBeDefined();
    });

    it('renders UI format textarea with initial value', () => {
      const app = createMockApp({ placeholder: '{"test": "data"}' });
      renderWithRouter(app);

      const textarea = screen.getByRole('textbox', {
        name: /APIリクエストのデータ形式/,
      }) as HTMLTextAreaElement;
      expect(textarea).toBeDefined();
      expect(textarea.getAttribute('required')).toBe('');
      expect(textarea.value).toBe('{"test": "data"}');
    });

    it('renders config textarea with initial value', () => {
      const app = createMockApp({ config: '{"setting": true}' });
      renderWithRouter(app);

      const textarea = screen.getByRole('textbox', { name: /コンフィグ/ }) as HTMLTextAreaElement;
      expect(textarea).toBeDefined();
      expect(textarea.value).toBe('{"setting": true}');
    });

    it('renders status select with initial value', () => {
      const app = createMockApp({ status: 'draft' });
      renderWithRouter(app);

      const select = screen.getByRole('combobox', { name: /ステータス/ }) as HTMLSelectElement;
      expect(select).toBeDefined();
      expect(select.value).toBe('draft');
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
          /システムプロンプト/.test(name) && element.id === 'team-app-system-prompt',
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

    it('renders submit button with update text', () => {
      renderWithRouter();

      const button = screen.getByRole('button', { name: '更新' });
      expect(button).toBeDefined();
      expect(button.getAttribute('type')).toBe('submit');
    });
  });

  describe('Form Submission', () => {
    it('calls updateTeamApp with correct parameters on valid submission', async () => {
      const user = userEvent.setup();
      const app = createMockApp({
        teamId: 'team-123',
        exAppId: 'app-456',
      });
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-456',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app, 'team-123', 'app-456');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).toHaveBeenCalledWith(
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
            copyable: false,
            status: 'published',
          }),
        );
      });
    });

    it('calls mutateTeamApps after successful submission', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateTeamApps).toHaveBeenCalled();
      });
    });

    it('navigates to apps page after successful submission', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ teamId: 'team-456' });
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app, 'team-456');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/teams/team-456/apps');
      });
    });

    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      let resolveUpdateTeamApp: (value: unknown) => void;
      const updateTeamAppPromise = new Promise((resolve) => {
        resolveUpdateTeamApp = resolve;
      });
      mockUpdateTeamApp.mockReturnValue(updateTeamAppPromise);

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const loadingButton = screen.getByRole('button', { name: '更新中' });
        expect(loadingButton).toBeDefined();
      });

      resolveUpdateTeamApp!({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });
    });

    it('includes updated copyable value when checkbox is toggled', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ copyable: false });
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter(app);

      const copyableCheckbox = screen.getByRole('checkbox', { name: /コピー可能にする/ });
      await user.click(copyableCheckbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            copyable: true,
          }),
        );
      });
    });

    it('includes new API key when provided', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter();

      const apiKeyInput = screen.getByRole('textbox', { name: /APIキー/ });
      await user.type(apiKeyInput, 'new-api-key-123');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            apiKey: 'new-api-key-123',
          }),
        );
      });
    });

    it('includes system prompt values when filled', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: 'テストアプリ',
      });

      renderWithRouter();

      const systemPromptTextarea = screen.getByRole('textbox', {
        name: (name, element) =>
          /システムプロンプト/.test(name) && element.id === 'team-app-system-prompt',
      });
      await user.type(systemPromptTextarea, 'You are a helpful assistant.');

      const systemPromptKeyInput = screen.getByRole('textbox', {
        name: /システムプロンプトのキー名/,
      });
      await user.clear(systemPromptKeyInput);
      await user.type(systemPromptKeyInput, 'system_prompt');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            systemPrompt: 'You are a helpful assistant.',
            systemPromptKeyName: 'system_prompt',
          }),
        );
      });
    });

    it('updates existing app fields correctly', async () => {
      const user = userEvent.setup();
      const app = createMockApp({
        exAppName: '元のアプリ名',
        description: '元の概要',
      });
      mockUpdateTeamApp.mockResolvedValue({
        exAppId: 'app-1',
        exAppName: '新しいアプリ名',
      });

      renderWithRouter(app);

      const nameInput = screen.getByRole('textbox', { name: /名前/ });
      await user.clear(nameInput);
      await user.type(nameInput, '新しいアプリ名');

      const descriptionInput = screen.getByRole('textbox', { name: /概要/ });
      await user.clear(descriptionInput);
      await user.type(descriptionInput, '新しい概要');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).toHaveBeenCalledWith(
          expect.any(String),
          expect.any(String),
          expect.objectContaining({
            exAppName: '新しいアプリ名',
            description: '新しい概要',
          }),
        );
      });
    });
  });

  describe('Validation', () => {
    it('validates name is required in schema', () => {
      // Test the schema directly since HTML5 validation interferes with testing empty fields
      const result = teamAppEditSchema.safeParse({
        name: '',
        endpoint: 'https://example.com',
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

    it('shows error message for invalid endpoint URL', async () => {
      const user = userEvent.setup();
      const app = createMockApp({ endpoint: 'https://valid.example.com' });
      renderWithRouter(app);

      const endpointInput = screen.getByRole('textbox', { name: /APIエンドポイントのURL/ });
      await user.clear(endpointInput);
      // Use http instead of https to trigger schema validation error
      fillInput(endpointInput, 'http://invalid.example.com');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/URLの形式が正しくありません/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('rejects endpoint URLs with credentials in schema', () => {
      const result = teamAppEditSchema.safeParse({
        name: 'テストアプリ',
        endpoint: 'https://user:pass@example.com/test',
        uiFormat: '{}',
        description: 'test',
        howToUse: 'test',
        copyable: false,
        status: 'published',
      });

      expect(result.success).toBe(false);
      if (!result.success) {
        const endpointError = result.error.issues.find((issue) => issue.path.includes('endpoint'));
        expect(endpointError?.message).toContain('URLの形式が正しくありません');
      }
    });

    it('shows error message for invalid JSON in UI format', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const uiFormatInput = screen.getByRole('textbox', { name: /APIリクエストのデータ形式/ });
      await user.clear(uiFormatInput);
      await user.type(uiFormatInput, 'invalid json');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/APIリクエストのデータ形式はJSON形式にしてください/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('shows error message when status is cleared', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, '');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/ステータスを選択してください/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('does not call updateTeamApp on validation failure', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const nameInput = screen.getByRole('textbox', { name: /名前/ });
      await user.clear(nameInput);

      const statusSelect = screen.getByRole('combobox', { name: /ステータス/ });
      await user.selectOptions(statusSelect, '');

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamApp).not.toHaveBeenCalled();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays server error message on API error', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockRejectedValue(
        new ApiError(400, {
          error: 'このアプリ名は既に使用されています',
        }),
      );

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText('このアプリ名は既に使用されています');
        expect(errorMessage).toBeDefined();
      });
    });

    it('displays generic error message on non-API error', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockRejectedValue(new Error('Unknown error'));

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
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
      mockUpdateTeamApp.mockRejectedValue(
        new ApiError(500, {
          error: 'サーバーエラー',
        }),
      );

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFocus).toHaveBeenCalledWith('server-error');
      });
    });
  });

  describe('Accessibility', () => {
    it('has sr-only heading for server error section', async () => {
      const user = userEvent.setup();
      mockUpdateTeamApp.mockRejectedValue(
        new ApiError(400, {
          error: 'エラー',
        }),
      );

      renderWithRouter();

      const submitButton = screen.getByRole('button', { name: '更新' });
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

      const supportText = screen.getByText(/アプリ一覧に表示する簡単な説明/);
      expect(supportText).toBeDefined();
    });

    it('has support text for how to use field', () => {
      renderWithRouter();

      const supportText = screen.getByText(/想定用途・入力例・仕組みなど/);
      expect(supportText).toBeDefined();
    });

    it('has support text for API key field indicating optional update', () => {
      renderWithRouter();

      const supportText = screen.getByText(/APIキーの更新が必要な場合のみ入力してください/);
      expect(supportText).toBeDefined();
    });
  });
});
