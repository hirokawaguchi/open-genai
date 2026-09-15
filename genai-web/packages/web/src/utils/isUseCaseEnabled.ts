import { HiddenUseCases, HiddenUseCasesKeys } from 'genai-web';

const hiddenUseCases: HiddenUseCases = JSON.parse(
  import.meta.env.VITE_APP_HIDDEN_USE_CASES || '{}',
);

export const isUseCaseEnabled = (...useCases: HiddenUseCasesKeys[]): boolean => {
  return useCases.every((useCase) => !hiddenUseCases[useCase]);
};
