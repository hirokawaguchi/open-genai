import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LandingForm } from '../../../../src/features/landing/components/LandingForm';

const mockNavigate = vi.fn();

vi.mock('react-router', async () => {
  const actual = await vi.importActual('react-router');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('@/features/landing/constants', () => ({
  TOP_CHAT_SYSTEM_PROMPT: 'test-system-prompt',
  TOP_CHAT_SYSTEM_PROMPT_TITLE: 'テストAI',
}));

vi.mock('@/features/landing/components/ModelSelector', () => ({
  ModelSelector: () => null,
}));

describe('LandingForm', () => {
  const renderComponent = () => {
    return render(
      <MemoryRouter>
        <LandingForm />
      </MemoryRouter>,
    );
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders the heading with instructions', () => {
      renderComponent();

      const heading = screen.getByRole('heading', {
        name: /お手伝いできることはありますか？お気軽にご相談ください/,
      });
      expect(heading).toBeDefined();
      expect(heading.tagName).toBe('H2');
    });

    it('renders the explanatory text about navigation', () => {
      renderComponent();

      const explanatoryText = screen.getByText('（送信したらチャット画面に遷移します）');
      expect(explanatoryText).toBeDefined();
    });

    it('renders the support text', () => {
      renderComponent();

      const supportText = screen.getByText('例）"国会答弁を検索したい"、"法制度について詳しく調べたい"、"引き継ぎ作業をやりたいので適切なプロンプトを考えて"');
      expect(supportText).toBeDefined();
    });

    it('renders the textarea', () => {
      renderComponent();

      const textarea = screen.getByRole('textbox');
      expect(textarea).toBeDefined();
    });

    it('renders the submit button', () => {
      renderComponent();

      const button = screen.getByRole('button', { name: '送信' });
      expect(button).toBeDefined();
    });

    it('associates heading with textarea via aria-labelledby', () => {
      renderComponent();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('aria-labelledby')).toBe('landing-chat-input-heading');
    });

    it('associates support text with textarea via aria-describedby', () => {
      renderComponent();

      const textarea = screen.getByRole('textbox');
      expect(textarea.getAttribute('aria-describedby')).toBe(
        'chat-input-support chat-input-submit-hint',
      );
    });

    it('renders the submit key hint', () => {
      renderComponent();

      expect(screen.getByText('Enter で送信 / Shift+Enter で改行')).toBeDefined();
    });
  });

  describe('Input behavior', () => {
    it('allows typing in the textarea', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
      await user.type(textarea, 'テスト入力');

      expect(textarea.value).toBe('テスト入力');
    });

    it('updates value on input change', () => {
      renderComponent();

      const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: '新しい入力' } });

      expect(textarea.value).toBe('新しい入力');
    });
  });

  describe('Form validation', () => {
    it('has required attribute on textarea', () => {
      renderComponent();

      const textarea = screen.getByRole('textbox');
      expect(textarea.hasAttribute('required')).toBe(true);
    });

    it('shows error message when submitting whitespace-only input', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const errorMessage = screen.getByText(/メッセージは空白のみでは送信できません/);
      expect(errorMessage).toBeDefined();
    });

    it('sets aria-invalid on textarea when whitespace-only error occurs', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(textarea.getAttribute('aria-invalid')).toBe('true');
    });

    it('includes error message in aria-describedby when error occurs', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(textarea.getAttribute('aria-describedby')).toContain('chat-input-error');
    });

    it('clears error message when user starts typing after error', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const errorMessage = screen.getByText(/メッセージは空白のみでは送信できません/);
      expect(errorMessage).toBeDefined();

      await user.type(textarea, 'テスト');

      expect(screen.queryByText(/メッセージは空白のみでは送信できません/)).toBeNull();
    });

    it('removes aria-invalid when error is cleared', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(textarea.getAttribute('aria-invalid')).toBe('true');

      await user.type(textarea, 'テスト');
      expect(textarea.getAttribute('aria-invalid')).toBeNull();
    });

    it('focuses textarea when error occurs', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(document.activeElement).toBe(textarea);
    });
  });

  describe('Enter submit', () => {
    it('navigates to /chat when pressing Enter with valid input', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'Enterテスト');

      fireEvent.keyDown(textarea, { key: 'Enter' });

      await vi.waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledTimes(1);
      });
      expect(mockNavigate.mock.calls[0][0]).toBe('/chat');
      expect(mockNavigate.mock.calls[0][1].state.content).toBe('Enterテスト');
    });

    it('does not navigate when pressing Enter with whitespace-only input', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      fireEvent.keyDown(textarea, { key: 'Enter' });

      await vi.waitFor(() => {
        expect(screen.getByText(/メッセージは空白のみでは送信できません/)).toBeDefined();
      });
      expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('does not navigate when pressing Shift+Enter', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テスト');

      fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });

      expect(mockNavigate).not.toHaveBeenCalled();
    });
  });

  describe('Navigation on submit', () => {
    it('navigates to /chat on submit', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テストメッセージ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(mockNavigate).toHaveBeenCalledTimes(1);
      const navigateArg = mockNavigate.mock.calls[0][0];
      expect(navigateArg).toBe('/chat');
    });

    it('includes content in navigation state', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テストメッセージ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const navigateOptions = mockNavigate.mock.calls[0][1];
      expect(navigateOptions.state.content).toBe('テストメッセージ');
    });

    it('includes systemContext in navigation state', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テスト');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const navigateOptions = mockNavigate.mock.calls[0][1];
      expect(navigateOptions.state.systemContext).toBe('test-system-prompt');
    });

    it('includes systemContextTitle in navigation state', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テスト');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const navigateOptions = mockNavigate.mock.calls[0][1];
      expect(navigateOptions.state.systemContextTitle).toBe('テストAI');
    });

    it('includes autoSubmit in navigation state', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, 'テスト');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      const navigateOptions = mockNavigate.mock.calls[0][1];
      expect(navigateOptions.state.autoSubmit).toBe(true);
    });

    it('does not navigate when input is empty (browser validation)', async () => {
      const user = userEvent.setup();
      renderComponent();

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('does not navigate when input contains only whitespace and shows error', async () => {
      const user = userEvent.setup();
      renderComponent();

      const textarea = screen.getByRole('textbox');
      await user.type(textarea, '   ');

      const button = screen.getByRole('button', { name: '送信' });
      await user.click(button);

      expect(mockNavigate).not.toHaveBeenCalled();
      expect(screen.getByText(/メッセージは空白のみでは送信できません/)).toBeDefined();
    });
  });
});
