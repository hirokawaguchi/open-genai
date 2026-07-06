import { describe, expect, it, vi } from 'vitest';
import {
  buildDirectImageAssistantContent,
  ensureImagePersistTarget,
} from '@/features/generate-image/utils/ensureImagePersistTarget';

vi.mock('@/lib/chatApi', () => ({
  createChat: vi.fn(),
  createMessages: vi.fn(),
}));

import { createChat, createMessages } from '@/lib/chatApi';

describe('ensureImagePersistTarget', () => {
  it('buildDirectImageAssistantContent は JSON 形式の assistant 本文を返す', () => {
    const content = buildDirectImageAssistantContent('a cat', 'blur');
    const parsed = JSON.parse(content);
    expect(parsed.prompt).toBe('a cat');
    expect(parsed.negativePrompt).toBe('blur');
  });

  it('既存 assistant があればその messageId を使う', async () => {
    const result = await ensureImagePersistTarget({
      usecase: '/image',
      chatId: 'chat-1',
      sessionChatId: undefined,
      lastAssistantMessageId: 'msg-existing',
      prompt: 'a cat',
      negativePrompt: 'blur',
    });

    expect(result).toEqual({ chatId: 'chat-1', messageId: 'msg-existing' });
    expect(createChat).not.toHaveBeenCalled();
    expect(createMessages).not.toHaveBeenCalled();
  });

  it('assistant が無ければ createMessages で作成する', async () => {
    vi.mocked(createMessages).mockResolvedValueOnce({
      messages: [{ messageId: 'msg-new', role: 'assistant', content: '{}', usecase: '/image' }],
    });

    const result = await ensureImagePersistTarget({
      usecase: '/image',
      chatId: 'chat-1',
      sessionChatId: undefined,
      lastAssistantMessageId: undefined,
      prompt: 'a dog',
      negativePrompt: '',
    });

    expect(result?.messageId).toBe('msg-new');
    expect(createMessages).toHaveBeenCalledOnce();
  });

  it('chatId が無ければ createChat してからメッセージを作成する', async () => {
    vi.mocked(createChat).mockResolvedValueOnce({
      chat: { chatId: 'chat#new-chat', usecase: '/image', title: '', createdDate: '', updatedDate: '' },
    });
    vi.mocked(createMessages).mockResolvedValueOnce({
      messages: [{ messageId: 'msg-new', role: 'assistant', content: '{}', usecase: '/image' }],
    });

    const result = await ensureImagePersistTarget({
      usecase: '/image',
      chatId: undefined,
      sessionChatId: undefined,
      lastAssistantMessageId: undefined,
      prompt: 'a bird',
      negativePrompt: '',
    });

    expect(createChat).toHaveBeenCalledWith({ usecase: '/image' });
    expect(result?.chatId).toBe('new-chat');
  });
});
