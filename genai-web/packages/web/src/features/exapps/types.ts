import { ExAppStatus } from 'genai-web';

export type ExAppOptions = {
  [key: string]: {
    teamName: string;
    exApps: {
      label: string;
      value: string;
      description: string;
      status?: ExAppStatus;
      displayOrder?: number | null;
    }[];
  };
};

export type TeamOption = {
  value: string;
  label: string;
};
