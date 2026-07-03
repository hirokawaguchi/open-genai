import { FieldValues } from 'react-hook-form';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import { GovAIFormUIPreview } from '../../types';
import { missingTemplateVars, substituteTemplate } from '../../utils/formSpec';

type Props = {
  id: string;
  classNames?: string;
  uiConfig: GovAIFormUIPreview;
  values: FieldValues;
};

/**
 * OpenGENAI exApp Form Spec v1: プレビュー（読み取り専用）。
 * template 中の {{キー}} を他フィールドの現在値で置換して表示する。
 */
export const ExAppPreview = (props: Props) => {
  const { id, classNames, uiConfig, values } = props;
  const template = uiConfig.template ?? '';
  const rendered = substituteTemplate(template, values);
  const missing = missingTemplateVars(template, values);

  return (
    <div className={`flex flex-col gap-1.5 ${classNames ?? ''}`}>
      <Label htmlFor={id} size='lg'>
        {uiConfig.title}
      </Label>
      {uiConfig.desc && (
        <SupportText id={`${id}-support-text`} className='whitespace-pre-wrap'>
          {uiConfig.desc}
        </SupportText>
      )}
      <pre
        id={id}
        aria-live='polite'
        className='border border-solid-gray-300 bg-solid-gray-50 px-3 py-2 text-dns-14N-130 leading-140 wrap-break-word whitespace-pre-wrap'
      >
        {rendered || '（プレビューする内容がありません）'}
      </pre>
      {missing.length > 0 && (
        <SupportText className='whitespace-pre-wrap'>
          未入力の変数: {missing.map((m) => `{{${m}}}`).join(', ')}
        </SupportText>
      )}
    </div>
  );
};
