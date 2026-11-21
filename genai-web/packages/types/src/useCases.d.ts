export type HiddenUseCases = {
  generate?: boolean;
  translate?: boolean;
  image?: boolean;
  diagram?: boolean;
};

export type HiddenUseCasesKeys = keyof HiddenUseCases;
