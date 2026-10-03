export type NishukanCheck = {
  id: string;
  label: string;
  done: boolean;
  doneBy?: string | null;
};

export type NishukanComment = {
  id: string;
  author: string;
  body: string;
  createdAt: string;
};

export type NishukanIssue = {
  id: string;
  projectId: string;
  projectKey: string;
  projectMode: string;
  teamId: string;
  number: number;
  title: string;
  body: string;
  status: string;
  priority: string | null;
  size: number | null;
  kind: string;
  leaveName: string;
  holidayDate?: string | null;
  completionText: string;
  completionMode: string | null;
  timeboxStart: string | null;
  templateId: string | null;
  templateName?: string;
  dueDate: string | null;
  createdAt: string;
  checks: NishukanCheck[];
  comments: NishukanComment[];
};

export type NishukanTemplate = {
  id: string;
  teamId: string;
  projectId: string;
  name: string;
  size: number;
  priority: string;
  completionText: string;
  completionMode: string;
  checks: string[];
  hasReceiptKey: boolean;
  keyHint: string | null;
};

export type NishukanProject = {
  id: string;
  teamId: string;
  key: string;
  name: string;
  description: string;
  mode: 'plan' | 'routine';
  status: string;
};

export type NishukanBox = {
  start: string;
  end: string;
  size: number;
  forecastSize?: number;
  routineReserve?: number;
  issues?: NishukanIssue[];
};

export type NishukanHome = {
  enabled?: boolean;
  error?: string;
  userId?: string;
  teamId: string | null;
  isAdmin?: boolean;
  isMember?: boolean;
  isChief?: boolean;
  chiefUserId?: string | null;
  headcount?: number | null;
  teams?: { teamId: string; teamName: string; admin: boolean; member: boolean }[];
  projects?: NishukanProject[];
  templates?: NishukanTemplate[];
  boxes?: { previous: NishukanBox; current: NishukanBox; next: NishukanBox };
  pace?: number;
  planIssues?: NishukanIssue[];
  leaveIssues?: NishukanIssue[];
  routine?: {
    templateId: string;
    name: string;
    count: number;
    openCount: number;
    size: number;
    issues: NishukanIssue[];
  }[];
};
