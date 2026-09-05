import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TeamEditForm } from '../../../../../src/features/teams/edit/components/TeamEditForm';
import { useTeamName } from '../../../../../src/features/teams/edit/hooks/useTeamName';
import { useUpdateTeam } from '../../../../../src/features/teams/edit/hooks/useUpdateTeam';
import * as focusModule from '../../../../../src/utils/focus';

// Mock dependencies
vi.mock('@/features/teams/edit/hooks/useUpdateTeam');
vi.mock('@/features/teams/edit/hooks/useTeamName');
vi.mock('@/utils/focus');

const mockUpdateTeam = vi.fn();
const mockMutateTeams = vi.fn();
const mockFocus = vi.fn();

describe('TeamEditForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Setup default mocks
    vi.mocked(useUpdateTeam).mockReturnValue({
      updateTeam: mockUpdateTeam,
      mutateTeams: mockMutateTeams,
    });

    vi.mocked(useTeamName).mockReturnValue({
      teamName: '既存チーム名',
      parentTeamId: '',
      teamId: 'team-123',
    });

    vi.mocked(focusModule.focus).mockImplementation(mockFocus);
  });

  const renderWithRouter = (teamId = 'team-123') => {
    return render(
      <MemoryRouter initialEntries={[`/teams/${teamId}/edit`]}>
        <Routes>
          <Route path='/teams/:teamId/edit' element={<TeamEditForm />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  describe('Rendering', () => {
    it('renders team name input field', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /チーム名/ });
      expect(input).toBeDefined();
      expect(input.getAttribute('type')).toBe('text');
      expect(input.getAttribute('required')).toBe('');
    });

    it('renders team name with initial value', () => {
      renderWithRouter();

      const input = screen.getByRole('textbox', { name: /チーム名/ }) as HTMLInputElement;
      expect(input.value).toBe('既存チーム名');
    });

    it('renders required badge', () => {
      renderWithRouter();

      const badge = screen.getByText('※必須');
      expect(badge).toBeDefined();
    });

    it('renders submit button with correct text', () => {
      renderWithRouter();

      const button = screen.getByRole('button', { name: '変更' });
      expect(button).toBeDefined();
      expect(button.getAttribute('type')).toBe('submit');
    });
  });

  describe('Form Submission', () => {
    it('calls updateTeam with correct parameters on valid submission', async () => {
      const user = userEvent.setup();
      mockUpdateTeam.mockResolvedValue({ teamId: 'team-123' });
      renderWithRouter('team-123');

      const nameInput = screen.getByRole('textbox', { name: /チーム名/ });

      // Clear and type new value
      await user.clear(nameInput);
      await user.type(nameInput, '新しいチーム名');

      const submitButton = screen.getByRole('button', { name: '変更' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeam).toHaveBeenCalledWith('team-123', {
          teamName: '新しいチーム名',
          parentTeamId: null,
        });
      });
    });

    it('calls mutateTeams after successful submission', async () => {
      const user = userEvent.setup();
      mockUpdateTeam.mockResolvedValue({ teamId: 'team-123' });
      renderWithRouter('team-123');

      const nameInput = screen.getByRole('textbox', { name: /チーム名/ });

      await user.clear(nameInput);
      await user.type(nameInput, '新しいチーム名');

      const submitButton = screen.getByRole('button', { name: '変更' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockMutateTeams).toHaveBeenCalled();
      });
    });

    it('shows loading state during submission', async () => {
      const user = userEvent.setup();
      let resolveUpdateTeam: (value: unknown) => void;
      const updateTeamPromise = new Promise((resolve) => {
        resolveUpdateTeam = resolve;
      });
      mockUpdateTeam.mockReturnValue(updateTeamPromise);
      renderWithRouter();

      const nameInput = screen.getByRole('textbox', { name: /チーム名/ });

      await user.clear(nameInput);
      await user.type(nameInput, '新しいチーム名');

      const submitButton = screen.getByRole('button', { name: '変更' });
      await user.click(submitButton);

      await waitFor(() => {
        const loadingButton = screen.getByRole('button', { name: '変更中' });
        expect(loadingButton).toBeDefined();
      });

      resolveUpdateTeam!({ teamId: 'team-123' });
    });

    it('submits with existing value when not modified', async () => {
      const user = userEvent.setup();
      mockUpdateTeam.mockResolvedValue({ teamId: 'team-123' });
      renderWithRouter('team-123');

      const submitButton = screen.getByRole('button', { name: '変更' });
      await user.click(submitButton);

      await waitFor(() => {
        expect(mockUpdateTeam).toHaveBeenCalledWith('team-123', {
          teamName: '既存チーム名',
          parentTeamId: null,
        });
      });
    });
  });

  describe('Accessibility', () => {
    it('does not set aria-describedby when no validation error', () => {
      renderWithRouter();

      const nameInput = screen.getByRole('textbox', { name: /チーム名/ });
      expect(nameInput.getAttribute('aria-describedby')).toBeNull();
    });
  });
});
