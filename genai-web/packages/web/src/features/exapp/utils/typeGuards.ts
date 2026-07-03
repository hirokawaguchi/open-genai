import type {
  GovAIFormUICheckbox,
  GovAIFormUIFile,
  GovAIFormUIHidden,
  GovAIFormUIItem,
  GovAIFormUINumber,
  GovAIFormUIPreview,
  GovAIFormUIRadio,
  GovAIFormUISelect,
  GovAIFormUIText,
  GovAIFormUITextarea,
} from '../types';

export const isTextType = (ui: GovAIFormUIItem): ui is GovAIFormUIText => {
  return ui.type === 'text';
};

export const isNumberType = (ui: GovAIFormUIItem): ui is GovAIFormUINumber => {
  return ui.type === 'number';
};

export const isFileType = (ui: GovAIFormUIItem): ui is GovAIFormUIFile => {
  return ui.type === 'file';
};

export const isTextareaType = (ui: GovAIFormUIItem): ui is GovAIFormUITextarea => {
  return ui.type === 'textarea';
};

export const isSelectType = (ui: GovAIFormUIItem): ui is GovAIFormUISelect => {
  return ui.type === 'select';
};

export const isCheckboxType = (ui: GovAIFormUIItem): ui is GovAIFormUICheckbox => {
  return ui.type === 'checkbox';
};

export const isRadioType = (ui: GovAIFormUIItem): ui is GovAIFormUIRadio => {
  return ui.type === 'radio';
};

export const isHiddenType = (ui: GovAIFormUIItem): ui is GovAIFormUIHidden => {
  return ui.type === 'hidden';
};

export const isPreviewType = (ui: GovAIFormUIItem): ui is GovAIFormUIPreview => {
  return ui.type === 'preview';
};
