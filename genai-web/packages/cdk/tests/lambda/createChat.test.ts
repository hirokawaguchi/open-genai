import { APIGatewayProxyEvent } from 'aws-lambda';
import { afterAll, beforeEach, describe, expect, type MockedFunction, test, vi } from 'vitest';
import { handler } from '../../lambda/createChat';
import { createChat } from '../../lambda/repository/chatRepository';

vi.mock('../../lambda/repository/chatRepository');

const mockedCreateChat = createChat as MockedFunction<typeof createChat>;

const originalEnv = process.env;
beforeEach(() => {
  vi.resetModules();
  process.env = { ...originalEnv };
});

afterAll(() => {
  process.env = originalEnv;
});

function createAPIGatewayProxyEvent(userId?: string): APIGatewayProxyEvent {
  return {
    body: null,
    pathParameters: {},
    requestContext: {
      authorizer: {
        claims: {
          sub: userId ?? 'test-user-id',
        },
      },
    },
  } as unknown as APIGatewayProxyEvent;
}

describe('createChat Lambda handler', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  test('チャットを正常に作成できる', async () => {
    const userId = 'test-user-id';

    mockedCreateChat.mockResolvedValue({
      id: `user#${userId}`,
      createdDate: '1234567890',
      chatId: 'chat#new-id',
      title: '',
      usecase: '',
      updatedDate: '',
    });

    const event = createAPIGatewayProxyEvent(userId);
    const result = await handler(event);

    expect(result.statusCode).toBe(200);
    const body = JSON.parse(result.body);
    expect(body.chat.chatId).toBe('chat#new-id');
    expect(mockedCreateChat).toHaveBeenCalledWith(userId, '/chat');
  });

  test('予期しないエラーが発生した場合は500エラーを返す', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

    mockedCreateChat.mockRejectedValue(new Error('Unexpected error'));

    const event = createAPIGatewayProxyEvent();
    const result = await handler(event);

    expect(result.statusCode).toBe(500);
    expect(JSON.parse(result.body)).toEqual({
      error: 'サーバ側でエラーが発生しました。管理者へご連絡ください。',
    });
    expect(consoleErrorSpy).toHaveBeenCalled();

    consoleErrorSpy.mockRestore();
  });
});
