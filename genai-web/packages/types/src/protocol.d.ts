import { StopReason } from '@aws-sdk/client-bedrock-runtime';
import { Chat } from './chat';
import { GenerateImageParams } from './image';
import { Model, RecordedMessage, ToBeRecordedMessage, UnrecordedMessage } from './message';
import { SystemContext } from './systemContext';

export type StreamingChunk = {
  text: string;
  trace?: string;
  stopReason?: StopReason | 'error';
  sessionId?: string;
};

export type Pagination<T> = {
  data: T[];
  lastEvaluatedKey?: string;
};

export type CreateChatRequest = {
  usecase?: string;
};

export type CreateChatResponse = {
  chat: Chat;
};

export type CreateMessagesRequest = {
  messages: ToBeRecordedMessage[];
};

export type CreateMessagesResponse = {
  messages: RecordedMessage[];
};

export type ListChatsResponse = Pagination<Chat>;

export type FindChatByIdResponse = {
  chat: Chat;
};

export type ListMessagesResponse = {
  messages: RecordedMessage[];
};

export type CreateSystemContextRequest = {
  systemContext: SystemContext;
};

export type UpdateSystemContextTitleRequest = {
  title: string;
};

export type UpdateSystemContextTitleResponse = {
  systemContext: SystemContext;
};

export type UpdateTitleRequest = {
  title: string;
};

export type UpdateTitleResponse = {
  chat: Chat;
};

export type PredictRequest = {
  model?: Model;
  messages: UnrecordedMessage[];
  id: string;
};

export type PredictResponse = string;

export type PredictTitleRequest = {
  model: Model;
  chat: Chat;
  prompt: string;
  id: string;
};

export type PredictTitleResponse = string;

export type RetrieveKnowledgeBaseRequest = {
  query: string;
};

export type GetFileDownloadSignedUrlRequest = {
  bucketName: string;
  filePrefix: string;
  region?: string;
  contentType?: string;
};

export type GetFileDownloadSignedUrlResponse = string;

export type GetArtifactFileRequest = {
  s3Url: string;
};

export type GetArtifactFileResponse = {
  data: string;
};

export type GenerateImageRequest = {
  model?: Model;
  params: GenerateImageParams;
};
export type GenerateImageResponse = string;

export type DeleteFileRequest = {
  fileName: string;
};
export type DeleteFileResponse = null;

export type StartTranscriptionRequest = {
  audioKey: string;
  speakerLabel: boolean;
  maxSpeakers: number;
};

export type StartTranscriptionResponse = {
  jobName: string;
};

export type Transcript = {
  speakerLabel?: string;
  transcript: string;
};

export type GetTranscriptionResponse = {
  status: string;
  languageCode: string;
  transcripts?: Transcript[];
};

export type UploadAudioRequest = {
  file: File;
};

export type GetFileUploadSignedUrlRequest = {
  filename?: string;
  mediaFormat: string;
};

export type GetFileUploadSignedUrlResponse = string;

export type UploadFileRequest = {
  file: File;
};
