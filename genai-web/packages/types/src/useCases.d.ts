export type HiddenUseCases = {
  generate?: boolean;
  translate?: boolean;
  image?: boolean;
  diagram?: boolean;
  shimen?: boolean;
};

export type HiddenUseCasesKeys = keyof HiddenUseCases;
