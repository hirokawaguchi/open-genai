import { createChat } from './repository/chatRepository';
import { createApiHandler } from './utils/createApiHandler';
import { getUserId } from './utils/getUserId';

export const handler = createApiHandler(async (event) => {
  const userId = getUserId(event);
  const body = event.body ? JSON.parse(event.body) : {};
  const usecase = body.usecase || '/chat';
  const chat = await createChat(userId, usecase);

  return { statusCode: 200, body: { chat } };
});
