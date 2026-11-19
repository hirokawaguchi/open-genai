import { createWithEqualityFn as create } from 'zustand/traditional';

export type KnowledgePick = {
  scope: string;
  scopeName: string;
  tag: string;
};

type ChatState = {
  content: string;
  inputSystemContext: string;
  saveSystemContext: string;
  systemContextTitle: string;
  isDragOver: boolean;
  shouldAutoSubmit: boolean;
  hasSent: boolean;
  knowledgePicks: KnowledgePick[];
  knowledgeSearching: boolean;
};

type ChatActions = {
  setContent: (content: string) => void;
  setInputSystemContext: (inputSystemContext: string) => void;
  setSaveSystemContext: (saveSystemContext: string) => void;
  setSystemContextTitle: (systemContextTitle: string) => void;
  setIsDragOver: (isDragOver: boolean) => void;
  setShouldAutoSubmit: (shouldAutoSubmit: boolean) => void;
  setHasSent: (hasSent: boolean) => void;
  setKnowledgePicks: (knowledgePicks: KnowledgePick[]) => void;
  setKnowledgeSearching: (knowledgeSearching: boolean) => void;
};

type ChatStore = ChatState & ChatActions;

const initialState: ChatState = {
  content: '',
  inputSystemContext: '',
  saveSystemContext: '',
  systemContextTitle: '',
  isDragOver: false,
  shouldAutoSubmit: false,
  hasSent: false,
  knowledgePicks: [],
  knowledgeSearching: false,
};

export const useChatStore = create<ChatStore>((set) => ({
  ...initialState,
  setContent: (content) => set({ content }),
  setInputSystemContext: (inputSystemContext) => set({ inputSystemContext }),
  setSaveSystemContext: (saveSystemContext) => set({ saveSystemContext }),
  setSystemContextTitle: (systemContextTitle) => set({ systemContextTitle }),
  setIsDragOver: (isDragOver) => set({ isDragOver }),
  setShouldAutoSubmit: (shouldAutoSubmit) => set({ shouldAutoSubmit }),
  setHasSent: (hasSent) => set({ hasSent }),
  setKnowledgePicks: (knowledgePicks) => set({ knowledgePicks }),
  setKnowledgeSearching: (knowledgeSearching) => set({ knowledgeSearching }),
}));
