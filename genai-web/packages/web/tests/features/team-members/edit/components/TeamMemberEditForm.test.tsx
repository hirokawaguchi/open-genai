import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TeamUser } from 'genai-web';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamMemberEditForm } from '../../../../../src/features/team-members/edit/components/TeamMemberEditForm';
import { useUpdateTeamMember } from '../../../../../src/features/team-members/edit/hooks/useUpdateTeamMember';
import { ApiError } from '../../../../../src/lib/fetcher';
import * as focusModule from '../../../../../src/utils/focus';

// Mock dependencies
vi.mock('@/features/team-members/edit/hooks/useUpdateTeamMember');
vi.mock('@/utils/focus');

const mockUpdateTeamMember = vi.fn();
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

const mockMember: TeamUser = {
  teamId: 'team-1',
  userId: 'user-1',
  username: 'test@example.com',
  isAdmin: false,
  createdDate: '2024-01-01T00:00:00Z',
  updatedDate: '2024-01-02T00:00:00Z',
};

const mockAdminMember: TeamUser = {
  teamId: 'team-1',
  userId: 'user-2',
  username: 'admin@example.com',
  isAdmin: true,
  createdDate: '2024-01-01T00:00:00Z',
  updatedDate: '2024-01-02T00:00:00Z',
};

describe('TeamMemberEditForm', () => {
  const renderWithRouter = (member: TeamUser = mockMember) => {
    return render(
      <MemoryRouter initialEntries={[`/teams/${member.teamId}/members/${member.userId}/edit`]}>
        <Routes>
          <Route
            path='/teams/:teamId/members/:userId/edit'
            element={<TeamMemberEditForm member={member} />}
          />
        </Routes>
      </MemoryRouter>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default mocks
    vi.mocked(useUpdateTeamMember).mockReturnValue({
      updateTeamMember: mockUpdateTeamMember,
      mutateTeamMembers: mockMutateTeamMembers,
    });

    vi.mocked(focusModule.focus).mockImplementation(mockFocus);
  });

  describe('Rendering', () => {
    it('renders email input field as readonly', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /メールアドレス/ });
      expect(input).toBeDefined();
      expect(input.getAttribute('type')).toBe('text');
      expect(input.getAttribute('required')).toBe('');
      expect(input.getAttribute('readonly')).toBe('');
    });

    it('renders email with member value', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /メールアドレス/ }) as HTMLInputElement;
      expect(input.value).toBe('test@example.com');
    });

    it('renders admin checkbox', () => {
      renderWithRouter();

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      expect(checkbox).toBeDefined();
    });

    it('renders checkbox unchecked when member is not admin', () => {
      renderWithRouter(mockMember);

      const checkbox = screen.getByRole('checkbox', {
        name: /チーム管理者に設定する/,
      }) as HTMLInputElement;
      expect(checkbox.checked).toBe(false);
    });

    it('renders checkbox checked when member is admin', () => {
      renderWithRouter(mockAdminMember);

      const checkbox = screen.getByRole('checkbox', {
        name: /チーム管理者に設定する/,
      }) as HTMLInputElement;
      expect(checkbox.checked).toBe(true);
    });

    it('renders edit disabled badge', () => {
      renderWithRouter();

      const badge = screen.getByText('編集不可');
      expect(badge).toBeDefined();
    });

    it('renders support text for email field', () => {
      renderWithRouter();

      const supportText = screen.getByText('ユーザーのメールアドレスは編集できません');
      expect(supportText).toBeDefined();
    });

    it('renders submit button with correct text', () => {
      renderWithRouter();

      const button = screen.getByRole('button', { name: '更新' });
      expect(button).toBeDefined();
      expect(button.getAttribute('type')).toBe('submit');
    });
  });

  describe('Form Submission', () => {
    it('calls updateTeamMember with correct parameters when changing admin status', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockResolvedValue(mockAdminMember);
      renderWithRouter(mockMember);

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamMember).toHaveBeenCalledWith('team-1', 'user-1', {
          isAdmin: true,
          isPrimary: false,
        });
      });
    });

    it('calls updateTeamMember with isAdmin false when unchecking admin checkbox', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockResolvedValue(mockMember);
      renderWithRouter(mockAdminMember);

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamMember).toHaveBeenCalledWith('team-1', 'user-2', {
          isAdmin: false,
          isPrimary: false,
        });
      });
    });

    it('calls mutateTeamMembers after successful submission', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockResolvedValue(mockAdminMember);
      renderWithRouter(mockMember);

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateTeamMembers).toHaveBeenCalled();
      });
    });

    it('navigates to members page after successful submission', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockResolvedValue(mockAdminMember);
      renderWithRouter(mockMember);

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/teams/team-1/members');
      });
    });

    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      let resolveUpdateTeamMember: (value: unknown) => void;
      const updateTeamMemberPromise = new Promise((resolve) => {
        resolveUpdateTeamMember = resolve;
      });
      mockUpdateTeamMember.mockReturnValue(updateTeamMemberPromise);
      renderWithRouter(mockMember);

      const checkbox = screen.getByRole('checkbox', { name: /チーム管理者に設定する/ });
      await user.click(checkbox);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const loadingButton = screen.getByRole('button', { name: '更新中' });
        expect(loadingButton).toBeDefined();
      });

      resolveUpdateTeamMember!(mockAdminMember);
    });

    it('submits with existing value when not modified', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockResolvedValue(mockMember);
      renderWithRouter(mockMember);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeamMember).toHaveBeenCalledWith('team-1', 'user-1', {
          isAdmin: false,
          isPrimary: false,
        });
      });
    });
  });

  describe('Error Handling', () => {
    it('displays server error message on API error', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockRejectedValue(
        new ApiError(403, {
          error: '権限がありません',
        }),
      );

      renderWithRouter(mockMember);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const errorMessage = screen.getByText('権限がありません');
        expect(errorMessage).toBeDefined();
      });
    });

    it('displays generic error message on non-API error', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockRejectedValue(new Error('Unknown error'));

      renderWithRouter(mockMember);

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
      mockUpdateTeamMember.mockRejectedValue(
        new ApiError(500, {
          error: 'サーバーエラー',
        }),
      );

      renderWithRouter(mockMember);

      const submitButton = screen.getByRole('button', { name: '更新' });
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
      expect(emailInput.getAttribute('aria-describedby')).toBe(
        'team-member-edit-email-input-support',
      );
    });

    it('has sr-only heading for server error section', async () => {
      const user = userEvent.setup();
      mockUpdateTeamMember.mockRejectedValue(
        new ApiError(400, {
          error: 'エラー',
        }),
      );

      renderWithRouter(mockMember);

      const submitButton = screen.getByRole('button', { name: '更新' });
      await user.click(submitButton);

      await waitFor(() => {
        const heading = screen.getByRole('heading', { name: 'システムエラー' });
        expect(heading).toBeDefined();
        expect(heading.className).toContain('sr-only');
      });
    });
  });

  describe('Email Field', () => {
    it('does not allow email to be edited', async () => {
      const user = userEvent.setup();
      renderWithRouter(mockMember);

      const emailInput = screen.getByRole('textbox', { name: /メールアドレス/ });

      // Try to type in the readonly field
      await user.click(emailInput);
      await user.type(emailInput, 'newemail@example.com');

      // Value should remain unchanged
      expect((emailInput as HTMLInputElement).value).toBe('test@example.com');
    });
  });
});
