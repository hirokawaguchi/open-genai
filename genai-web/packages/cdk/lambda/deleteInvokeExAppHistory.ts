import { findExAppById } from './repository/exAppRepository';
import {
  deleteInvokeExAppHistoriesBySession,
  deleteInvokeExAppHistory,
} from './repository/invokeHistoryRepository';
import { findTeamById } from './repository/teamRepository';
import { createApiHandler } from './utils/createApiHandler';
import { getUserId } from './utils/getUserId';
import { HttpError } from './utils/httpError';
import { requirePathParam } from './utils/requirePathParam';

export const handler = createApiHandler(async (event) => {
  const teamId = requirePathParam(event, 'teamId');
  const exAppId = requirePathParam(event, 'exAppId');
  const sessionId = event.queryStringParameters?.sessionId ?? '';
  const createdDate = event.queryStringParameters?.createdDate ?? '';
  const userId = getUserId(event);

  const team = await findTeamById(teamId);
  const exApp = await findExAppById(teamId, exAppId);
  if (!team || !exApp) {
    throw new HttpError(400, 'パラメータが不正です。');
  }

  // sessionId 指定でその会話の全往復を削除。無ければ createdDate で 1 往復。
  if (sessionId) {
    await deleteInvokeExAppHistoriesBySession(teamId, exAppId, userId, sessionId);
    return { statusCode: 204, body: '' };
  }

  if (!createdDate) {
    throw new HttpError(400, 'createdDate または sessionId が必要です。');
  }

  await deleteInvokeExAppHistory(teamId, exAppId, userId, createdDate);

  return { statusCode: 204, body: '' };
});
