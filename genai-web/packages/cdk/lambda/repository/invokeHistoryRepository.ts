import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { DeleteCommand, PutCommand, QueryCommand, UpdateCommand } from '@aws-sdk/lib-dynamodb';
import { InvokeExAppHistory } from 'genai-web';
import { dynamoDbDocument, INVOKE_HISTORY_TABLE_NAME, TTL_DAYS } from './client';

const s3 = new S3Client({});

const ARTIFACTS_BUCKET_NAME = process.env.ARTIFACTS_BUCKET_NAME!;

const saveFilesToS3 = async (data: any, baseS3Prefix: string, postfix: 'request' | 'response') => {
  if (typeof data !== 'object' || data === null) {
    return data;
  }

  // `outputs` が文字列化されたJSONの場合、パースを試みる
  let targetData = data;
  if (typeof data === 'string') {
    try {
      targetData = JSON.parse(data);
    } catch (e) {
      // JSONとしてパースできなければ、ファイル処理はスキップ
      return data;
    }
  }

  const TEN_KB = 10 * 1024;

  // S3アップロード処理を共通化
  const uploadToS3 = async (content: Buffer, fileName: string, contentType?: string) => {
    const s3Key = `${baseS3Prefix}/${postfix}/${fileName}`;
    await s3.send(
      new PutObjectCommand({
        Bucket: ARTIFACTS_BUCKET_NAME,
        Key: s3Key,
        Body: content,
        ContentType: contentType,
      }),
    );
    return `s3://${ARTIFACTS_BUCKET_NAME}/${s3Key}`;
  };

  const processInputFilesArray = async (fileArray: any[]) => {
    if (!Array.isArray(fileArray)) {
      return;
    }

    for (const item of fileArray) {
      if (typeof item !== 'object' || item === null) {
        continue;
      }

      // 1. 'content' または 'contents' キーを処理
      const files = item?.files ?? [];
      for (const file of files) {
        const contentData = file.content || file.contents;
        if (contentData && typeof contentData === 'string') {
          const buffer = Buffer.from(contentData, 'base64');
          const displayName = file.display_name || `file-${Date.now()}`;
          file.file_url = await uploadToS3(buffer, displayName);
          delete file.content;
          delete file.contents;
        }
      }

      // 2. display_name, content, contents 以外のキーで、値が10KBを超えるものを処理
      for (const key in item) {
        if (['display_name', 'content', 'contents', 'file_url'].includes(key)) {
          continue;
        }

        const value = item[key];
        if (typeof value === 'string' && Buffer.byteLength(value, 'utf-8') > TEN_KB) {
          const buffer = Buffer.from(value, 'utf-8');
          // display_nameがない場合はキー名からファイル名を生成
          const fileName = item.display_name ? `${item.display_name}-${key}` : `${key}.txt`;
          // プレーンテキストとして保存
          item[key] = await uploadToS3(buffer, fileName, 'text/plain');
        }
      }
    }
  };

  const processArtifactFilesArray = async (fileArray: any[]) => {
    if (!Array.isArray(fileArray)) {
      return;
    }

    for (const item of fileArray) {
      if (typeof item !== 'object' || item === null) {
        continue;
      }

      const contentData = item.content || item.contents;
      if (contentData && typeof contentData === 'string') {
        const buffer = Buffer.from(contentData, 'base64');
        const displayName = item.display_name || `file-${Date.now()}`;
        item.file_url = await uploadToS3(buffer, displayName);
        delete item.content;
        delete item.contents;
      }

      // 2. display_name, content, contents 以外のキーで、値が10KBを超えるものを処理
      for (const key in item) {
        if (['display_name', 'content', 'contents', 'file_url'].includes(key)) {
          continue;
        }

        const value = item[key];
        if (typeof value === 'string' && Buffer.byteLength(value, 'utf-8') > TEN_KB) {
          const buffer = Buffer.from(value, 'utf-8');
          // display_nameがない場合はキー名からファイル名を生成
          const fileName = item.display_name ? `${item.display_name}-${key}` : `${key}.txt`;
          // プレーンテキストとして保存
          item[key] = await uploadToS3(buffer, fileName, 'text/plain');
        }
      }
    }
  };

  if (targetData.files) {
    await processInputFilesArray(targetData.files);
  }
  if (targetData.artifacts) {
    await processArtifactFilesArray(targetData.artifacts);
  }

  return typeof data === 'string' ? JSON.stringify(targetData) : targetData;
};

const itemToInvokeExAppHistory = (item: Record<string, any>): InvokeExAppHistory => {
  const splitedPk = item.pk.split('#');
  return {
    teamId: splitedPk[0],
    teamName: item.teamName,
    exAppId: splitedPk[1],
    exAppName: item.exAppName,
    userId: splitedPk[2],
    inputs: item.inputs,
    outputs: item.outputs,
    status: item.status,
    createdDate: item.sk,
    progress: item.progress ?? '',
    artifacts: item.artifacts,
    sessionId: item.sessionId,
  };
};

export const createInvokeExAppHistory = async (
  id: string,
  createdDate: string,
  teamId: string,
  exAppId: string,
  userId: string,
  baseS3Prefix: string,
  inputs: Record<string, any>,
  result: any, // APIからのレスポンス全体
  teamName: string,
  exAppName: string,
  status: 'ACCEPTED' | 'COMPLETED' | 'ERROR',
  sessionId?: string,
): Promise<InvokeExAppHistory> => {
  // ファイルをS3に保存
  const processedInputs = await saveFilesToS3(inputs, baseS3Prefix, 'request');
  const processedResult = await saveFilesToS3(result, baseS3Prefix, 'response');

  const expire_at = Math.floor(Date.now() / 1000) + TTL_DAYS * 24 * 60 * 60;
  const item: { [key: string]: any } = {
    pk: id,
    sk: createdDate,
    teamId,
    exAppId,
    userId,
    inputs: processedInputs,
    outputs:
      typeof processedResult.outputs === 'string'
        ? processedResult.outputs
        : JSON.stringify(processedResult.outputs || {}),
    timestamps: JSON.stringify(processedResult.timestamps || {}),
    usageMetadata: JSON.stringify(processedResult.usageMetadata || {}),
    teamName,
    exAppName,
    status,
    baseS3Prefix, // S3 prefixを保存
    expire_at,
  };

  if (processedResult.progress) {
    item.progress = processedResult.progress;
  }
  if (processedResult.artifacts) {
    item.artifacts = processedResult.artifacts;
  }
  if (sessionId) {
    item.sessionId = sessionId;
  }

  await dynamoDbDocument.send(
    new PutCommand({
      TableName: INVOKE_HISTORY_TABLE_NAME,
      Item: item,
    }),
  );

  return itemToInvokeExAppHistory(item);
};

export const updateInvokeExAppHistory = async (
  id: string, // PK
  createdDate: string, // SK
  status: 'IN_PROGRESS' | 'COMPLETED' | 'ERROR',
  result: any, // ポーリング結果の全体
  baseS3Prefix: string,
): Promise<void> => {
  const processedResult = await saveFilesToS3(result, baseS3Prefix, 'response');

  let updateExpression = 'set #status = :status, #outputs = :outputs, #updatedDate = :updatedDate';
  const expressionAttributeNames: { [key: string]: string } = {
    '#status': 'status',
    '#outputs': 'outputs',
    '#updatedDate': 'updatedDate',
  };
  const expressionAttributeValues: { [key: string]: any } = {
    ':status': status,
    ':outputs':
      typeof processedResult.outputs === 'string'
        ? processedResult.outputs
        : JSON.stringify(processedResult.outputs || 'No outputs'),
    ':updatedDate': new Date().toISOString(),
  };

  if (processedResult.progress) {
    updateExpression += ', #progress = :progress';
    expressionAttributeNames['#progress'] = 'progress';
    expressionAttributeValues[':progress'] = processedResult.progress;
  }

  if (processedResult.artifacts) {
    updateExpression += ', #artifacts = :artifacts';
    expressionAttributeNames['#artifacts'] = 'artifacts';
    expressionAttributeValues[':artifacts'] = processedResult.artifacts;
  }

  if (processedResult.usageMetadata) {
    updateExpression += ', #usageMetadata = :usageMetadata';
    expressionAttributeNames['#usageMetadata'] = 'usageMetadata';
    expressionAttributeValues[':usageMetadata'] = processedResult.usageMetadata;
  }

  if (processedResult.timestamps) {
    updateExpression += ', #timestamps = :timestamps';
    expressionAttributeNames['#timestamps'] = 'timestamps';
    expressionAttributeValues[':timestamps'] = processedResult.timestamps;
  }

  const command = new UpdateCommand({
    TableName: INVOKE_HISTORY_TABLE_NAME,
    Key: {
      pk: id,
      sk: createdDate,
    },
    UpdateExpression: updateExpression,
    ExpressionAttributeNames: expressionAttributeNames,
    ExpressionAttributeValues: expressionAttributeValues,
  });
  await dynamoDbDocument.send(command);
};

export const listInvokeExAppHistories = async (
  _teamId: string,
  _exAppId: string,
  _userId: string,
  _exclusiveStartKey?: string,
): Promise<{ history: InvokeExAppHistory[]; lastEvaluatedKey?: string }> => {
  const exclusiveStartKey = _exclusiveStartKey
    ? JSON.parse(Buffer.from(_exclusiveStartKey, 'base64').toString())
    : undefined;

  const res = await dynamoDbDocument.send(
    new QueryCommand({
      TableName: INVOKE_HISTORY_TABLE_NAME,
      KeyConditionExpression: 'pk = :pk',
      ExpressionAttributeValues: {
        ':pk': `${_teamId}#${_exAppId}#${_userId}`,
      },
      Limit: 10,
      ExclusiveStartKey: exclusiveStartKey,
      ScanIndexForward: false,
    }),
  );

  return {
    history: res.Items ? res.Items.map((item) => itemToInvokeExAppHistory(item)) : [],
    lastEvaluatedKey: res.LastEvaluatedKey
      ? Buffer.from(JSON.stringify(res.LastEvaluatedKey)).toString('base64')
      : undefined,
  };
};

export const findInvokeExAppHistory = async (
  _teamId: string,
  _exAppId: string,
  _userId: string,
  _createdDate: string,
): Promise<{ history: InvokeExAppHistory | null }> => {
  const res = await dynamoDbDocument.send(
    new QueryCommand({
      TableName: INVOKE_HISTORY_TABLE_NAME,
      KeyConditionExpression: 'pk = :pk AND sk = :sk',
      ExpressionAttributeValues: {
        ':pk': `${_teamId}#${_exAppId}#${_userId}`,
        ':sk': `${_createdDate}`,
      },
    }),
  );

  if (!res.Items || res.Items.length === 0) {
    return { history: null };
  } else {
    return {
      history: itemToInvokeExAppHistory(res.Items[0]),
    };
  }
};

export const deleteInvokeExAppHistory = async (
  _teamId: string,
  _exAppId: string,
  _userId: string,
  _createdDate: string,
): Promise<void> => {
  await dynamoDbDocument.send(
    new DeleteCommand({
      TableName: INVOKE_HISTORY_TABLE_NAME,
      Key: {
        pk: `${_teamId}#${_exAppId}#${_userId}`,
        sk: `${_createdDate}`,
      },
    }),
  );
};

export const listInvokeExAppHistoriesBySession = async (
  _teamId: string,
  _exAppId: string,
  _userId: string,
  _sessionId: string,
): Promise<InvokeExAppHistory[]> => {
  const res = await dynamoDbDocument.send(
    new QueryCommand({
      TableName: INVOKE_HISTORY_TABLE_NAME,
      KeyConditionExpression: 'pk = :pk',
      FilterExpression: 'sessionId = :sessionId',
      ExpressionAttributeValues: {
        ':pk': `${_teamId}#${_exAppId}#${_userId}`,
        ':sessionId': _sessionId,
      },
      ScanIndexForward: false,
    }),
  );

  return res.Items ? res.Items.map((item) => itemToInvokeExAppHistory(item)) : [];
};

export const deleteInvokeExAppHistoriesBySession = async (
  _teamId: string,
  _exAppId: string,
  _userId: string,
  _sessionId: string,
): Promise<void> => {
  const histories = await listInvokeExAppHistoriesBySession(
    _teamId,
    _exAppId,
    _userId,
    _sessionId,
  );
  for (const history of histories) {
    await deleteInvokeExAppHistory(_teamId, _exAppId, _userId, history.createdDate);
  }
};
