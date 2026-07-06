import {
  BatchWriteCommand,
  DeleteCommand,
  PutCommand,
  QueryCommand,
  UpdateCommand,
} from '@aws-sdk/lib-dynamodb';
import * as crypto from 'crypto';
import { Chat, ListChatsResponse } from 'genai-web';
import { dynamoDbDocument, TABLE_NAME, TTL_DAYS } from './client';
import { listMessages } from './messageRepository';

export const createChat = async (_userId: string, usecase = '/chat'): Promise<Chat> => {
  const userId = `user#${_userId}`;
  const chatId = `chat#${crypto.randomUUID()}`;
  const expire_at = Math.floor(Date.now() / 1000) + TTL_DAYS * 24 * 60 * 60;
  const normalizedUsecase = usecase.startsWith('/') ? usecase : `/${usecase}`;
  const item = {
    id: userId,
    createdDate: `${Date.now()}`,
    chatId,
    usecase: normalizedUsecase,
    title: '',
    updatedDate: '',
    expire_at,
  };

  await dynamoDbDocument.send(
    new PutCommand({
      TableName: TABLE_NAME,
      Item: item,
    }),
  );

  return item;
};

export const findChatById = async (_userId: string, _chatId: string): Promise<Chat | null> => {
  const userId = `user#${_userId}`;
  const chatId = `chat#${_chatId}`;
  const res = await dynamoDbDocument.send(
    new QueryCommand({
      TableName: TABLE_NAME,
      KeyConditionExpression: '#id = :id',
      FilterExpression: '#chatId = :chatId',
      ExpressionAttributeNames: {
        '#id': 'id',
        '#chatId': 'chatId',
      },
      ExpressionAttributeValues: {
        ':id': userId,
        ':chatId': chatId,
      },
    }),
  );

  if (!res.Items || res.Items.length === 0) {
    return null;
  } else {
    return res.Items[0] as Chat;
  }
};

export const listChats = async (
  _userId: string,
  _exclusiveStartKey?: string,
): Promise<ListChatsResponse> => {
  const exclusiveStartKey = _exclusiveStartKey
    ? JSON.parse(Buffer.from(_exclusiveStartKey, 'base64').toString())
    : undefined;
  const userId = `user#${_userId}`;
  const res = await dynamoDbDocument.send(
    new QueryCommand({
      TableName: TABLE_NAME,
      KeyConditionExpression: '#id = :id',
      ExpressionAttributeNames: {
        '#id': 'id',
      },
      ExpressionAttributeValues: {
        ':id': userId,
      },
      ScanIndexForward: false,
      Limit: 100, // チャットのリストは 1 度に 100 件返す
      ExclusiveStartKey: exclusiveStartKey,
    }),
  );

  return {
    data: res.Items as Chat[],
    lastEvaluatedKey: res.LastEvaluatedKey
      ? Buffer.from(JSON.stringify(res.LastEvaluatedKey)).toString('base64')
      : undefined,
  };
};

export const setChatTitle = async (id: string, createdDate: string, title: string) => {
  const res = await dynamoDbDocument.send(
    new UpdateCommand({
      TableName: TABLE_NAME,
      Key: {
        id: id,
        createdDate: createdDate,
      },
      UpdateExpression: 'set title = :title',
      ExpressionAttributeValues: {
        ':title': title,
      },
      ReturnValues: 'ALL_NEW',
    }),
  );
  return res.Attributes as Chat;
};

export const deleteChat = async (_userId: string, _chatId: string): Promise<void> => {
  // Chat の削除
  const chatItem = await findChatById(_userId, _chatId);
  await dynamoDbDocument.send(
    new DeleteCommand({
      TableName: TABLE_NAME,
      Key: {
        id: chatItem?.id,
        createdDate: chatItem?.createdDate,
      },
    }),
  );

  // // Message の削除
  const messageItems = await listMessages(_chatId);
  await dynamoDbDocument.send(
    new BatchWriteCommand({
      RequestItems: {
        [TABLE_NAME]: messageItems.map((m) => {
          return {
            DeleteRequest: {
              Key: {
                id: m.id,
                createdDate: m.createdDate,
              },
            },
          };
        }),
      },
    }),
  );
};
