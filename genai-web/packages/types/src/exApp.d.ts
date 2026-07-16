export type ExAppStatus = 'draft' | 'published';

export type ExApp = {
  teamId: string;
  exAppId: string;
  exAppName: string;
  endpoint: string;
  config?: string;
  placeholder: string;
  systemPrompt?: string;
  systemPromptKeyName?: string;
  description: string;
  howToUse: string;
  apiKey: string;
  copyable?: boolean;
  status?: ExAppStatus;
  createdDate: string;
  updatedDate: string;
};

export type ListTeamExAppsResponse = {
  teamExApps: ExApp[];
  lastEvaluatedKey: string | null;
};

export type CreateExAppRequest = {
  exAppName: string;
  endpoint: string;
  config?: string;
  placeholder: string;
  systemPrompt?: string;
  systemPromptKeyName?: string;
  description: string;
  howToUse: string;
  apiKey: string;
  copyable?: boolean;
  status?: ExAppStatus;
};

export type UpdateExAppRequest = {
  exAppName?: string;
  endpoint?: string;
  config?: string;
  placeholder?: string;
  systemPrompt?: string;
  systemPromptKeyName?: string;
  description?: string;
  howToUse?: string;
  apiKey?: string;
  copyable?: boolean;
  status?: ExAppStatus;
};

export type CopyExAppRequest = {
  exAppName?: string;
  endpoint?: string;
  config?: string;
  placeholder?: string;
  systemPrompt?: string;
  systemPromptKeyName?: string;
  description?: string;
  howToUse?: string;
  apiKey?: string;
  copyable?: boolean;
  status?: ExAppStatus;
};

export type ListExAppsResponse = Array<ExApp & { teamName: string }>;
