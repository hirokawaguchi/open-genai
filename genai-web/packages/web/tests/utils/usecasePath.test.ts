import type { Chat } from 'genai-web';
import { describe, expect, it } from 'vitest';
import {
  getChatHistoryLink,
  getUsecaseLabel,
  pathnameToUsecase,
  resolveChatUsecase,
} from '@/utils/usecasePath';

describe('usecasePath', () => {
  it('pathnameToUsecase は先頭セグメントを返す', () => {
    expect(pathnameToUsecase('/image')).toBe('/image');
    expect(pathnameToUsecase('/image/abc-123')).toBe('/image');
    expect(pathnameToUsecase('/chat/uuid')).toBe('/chat');
  });

  it('resolveChatUsecase は保存済み usecase を優先する', () => {
    const chat = {
      chatId: 'chat#id-1',
      usecase: '/diagram',
      title: 'test',
      updatedDate: '1',
    } as Chat;

    expect(resolveChatUsecase(chat)).toBe('/diagram');
  });

  it('getChatHistoryLink は usecase に応じた URL を返す', () => {
    const chat = {
      chatId: 'chat#id-1',
      usecase: '/image',
      title: 'test',
      updatedDate: '1',
    } as Chat;

    expect(getChatHistoryLink(chat)).toBe('/image/id-1');
  });

  it('getUsecaseLabel は日本語ラベルを返す', () => {
    expect(getUsecaseLabel('/image')).toBe('画像生成');
    expect(getUsecaseLabel('/unknown')).toBe('チャット');
  });
});
