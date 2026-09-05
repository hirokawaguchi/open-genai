import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamMemberCreateForm } from '../../../../../src/features/team-members/create/components/TeamMemberCreateForm';
import { useCreateTeamMember } from '../../../../../src/features/team-members/create/hooks/useCreateTeamMember';
import { ApiError } from '../../../../../src/lib/fetcher';
import * as focusModule from '../../../../../src/utils/focus';

// Mock dependencies
vi.mock('@/features/team-members/create/hooks/useCreateTeamMember');
vi.mock('@/utils/focus');

const mockCreateTeamMember = vi.fn();
const mockMutateTeamMembers = vi.fn();
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

describe('TeamMemberCreateForm', () => {
  const renderWithRouter = (teamId = 'team-1') => {
    return render(
      <MemoryRouter initialEntries={[`/teams/${teamId}/members/create`]}>
        <Routes>
          <Route path='/teams/:teamId/members/create' element={<TeamMemberCreateForm />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default mocks
    vi.mocked(useCreateTeamMember).mockReturnValue({
      createTeamMember: mockCreateTeamMember,
      mutateTeamMembers: mockMutateTeamMembers,
    });

    vi.mocked(focusModule.focus).mockImplementation(mockFocus);
  });

  describe('Rendering', () => {
    it('renders email input field', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /メールアドレス/ });
      expect(input).toBeDefined();
      expect(input.getAttribute('type')).toBe('text');
      expect(input.getAttribute('required')).toBe('');
    });

    it('renders admin checkbox', () => {
      renderWithRouter();

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      expect(checkbox).toBeDefined();
    });

    it('renders required badge', () => {
      const { getByText } = renderWithRouter();

      const badge = getByText('※必須');
      expect(badge).toBeDefined();
    });

    it('renders support text for email field', () => {
      renderWithRouter();

      const supportText = screen.getByText('追加するユーザーのメールアドレスを入力してください');
      expect(supportText).toBeDefined();
    });

    it('renders submit button', () => {
      renderWithRouter();

      const button = screen.getByRole('button', { name: '作成' });
      expect(button).toBeDefined();
      expect(button.getAttribute('type')).toBe('submit');
    });

    it('checkbox is unchecked by default', () => {
      renderWithRouter();

      const checkbox = screen.getByRole('checkbox', {
        name: /チーム管理者に設定する/,
      }) as HTMLInputElement;
      expect(checkbox.checked).toBe(false);
    });
  });

  describe('Form Submission', () => {
    it('calls createTeamMember with correct parameters on valid submission', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockResolvedValue({
        teamId: 'team-1',
        userId: 'user-1',
        username: 'test@example.com',
        isAdmin: false,
        createdDate: '2024-01-01T00:00:00Z',
        updatedDate: '2024-01-02T00:00:00Z',
      });

      renderWithRouter('team-123');

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCreateTeamMember).toHaveBeenCalledWith('team-123', {
          email: 'test@example.com',
          isAdmin: false,
          isPrimary: false,
        });
      });
    });

    it('calls createTeamMember with isAdmin true when checkbox is checked', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockResolvedValue({
        teamId: 'team-1',
        userId: 'user-1',
        username: 'admin@example.com',
        isAdmin: true,
        createdDate: '2024-01-01T00:00:00Z',
        updatedDate: '2024-01-02T00:00:00Z',
      });

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });

      await user.type(emailInput, 'admin@example.com');
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCreateTeamMember).toHaveBeenCalledWith('team-1', {
          email: 'admin@example.com',
          isAdmin: true,
          isPrimary: false,
        });
      });
    });

    it('calls mutateTeamMembers after successful submission', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockResolvedValue({
        teamId: 'team-1',
        userId: 'user-1',
        username: 'test@example.com',
        isAdmin: false,
        createdDate: '2024-01-01T00:00:00Z',
        updatedDate: '2024-01-02T00:00:00Z',
      });

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateTeamMembers).toHaveBeenCalled();
      });
    });

    it('navigates to members page after successful submission', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockResolvedValue({
        teamId: 'team-1',
        userId: 'user-1',
        username: 'test@example.com',
        isAdmin: false,
        createdDate: '2024-01-01T00:00:00Z',
        updatedDate: '2024-01-02T00:00:00Z',
      });

      renderWithRouter('team-456');

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/teams/team-456/members');
      });
    });

    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      let resolveCreateTeamMember: (value: unknown) => void;
      const createTeamMemberPromise = new Promise((resolve) => {
        resolveCreateTeamMember = resolve;
      });
      mockCreateTeamMember.mockReturnValue(createTeamMemberPromise);

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const loadingButton = screen.getByRole('button', { name: '作成中' });
        expect(loadingButton).toBeDefined();
      });

      resolveCreateTeamMember!({
        teamId: 'team-1',
        userId: 'user-1',
        username: 'test@example.com',
        isAdmin: false,
        createdDate: '2024-01-01T00:00:00Z',
        updatedDate: '2024-01-02T00:00:00Z',
      });
    });
  });

  describe('Validation', () => {
    it('shows error message for invalid email format', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'invalid-email');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText(/メールアドレスの形式が正しくありません/);
        expect(errorMessage).toBeDefined();
      });
    });

    it('does not call createTeamMember on validation failure', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'invalid-email');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockCreateTeamMember).not.toHaveBeenCalled();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays server error message on API error', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockRejectedValue(
        new ApiError(400, {
          error: 'このメールアドレスは既に登録されています',
        }),
      );

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'existing@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText('このメールアドレスは既に登録されています');
        expect(errorMessage).toBeDefined();
      });
    });

    it('displays generic error message on non-API error', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockRejectedValue(new Error('Unknown error'));

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
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
      mockCreateTeamMember.mockRejectedValue(
        new ApiError(500, {
          error: 'サーバーエラー',
        }),
      );

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockFocus).toHaveBeenCalledWith('server-error');
      });
    });
  });

  describe('Accessibility', () => {
    it('sets aria-describedby for support text on email field', () => {
      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      expect(emailInput.getAttribute('aria-describedby')).toBe('team-member-email-input-support');
    });

    it('includes error id in aria-describedby when email validation fails', async () => {
      const user = userEvent.setup();
      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'invalid-email');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.queryByText(/メールアドレスの形式が正しくありません/);
        if (errorMessage) {
          const ariaDescribedBy = emailInput.getAttribute('aria-describedby');
          expect(ariaDescribedBy).toContain('team-member-email-input-support');
          expect(ariaDescribedBy).toContain('team-member-email-input-error');
        }
      });
    });

    it('has sr-only heading for server error section', async () => {
      const user = userEvent.setup();
      mockCreateTeamMember.mockRejectedValue(
        new ApiError(400, {
          error: 'エラー',
        }),
      );

      renderWithRouter();

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });
      await user.type(emailInput, 'test@example.com');

      const submitButton = screen.getByRole('button', { name: '作成' });
      await user.click(submitButton);

      await waitFor(() => {
        const heading = screen.getByRole('heading', { name: 'システムエラー' });
        expect(heading).toBeDefined();
        expect(heading.className).toContain('sr-only');
      });
    });
  });
});
