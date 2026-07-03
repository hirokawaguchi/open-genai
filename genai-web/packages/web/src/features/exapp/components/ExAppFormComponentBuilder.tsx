import {
  FieldErrors,
  FieldValues,
  UseFormClearErrors,
  UseFormRegister,
  UseFormSetValue,
  UseFormTrigger,
} from 'react-hook-form';
import { GovAIFormUIJson } from '../types';
import { isFieldVisible, isReservedFormKey } from '../utils/formSpec';
import { formatValidationErrorMessage } from '../utils/formatValidationErrorMessage';
import {
  isCheckboxType,
  isFileType,
  isHiddenType,
  isNumberType,
  isPreviewType,
  isRadioType,
  isSelectType,
  isTextareaType,
  isTextType,
} from '../utils/typeGuards';
import { ExAppCheckbox } from './form/ExAppCheckbox';
import { ExAppHidden } from './form/ExAppHidden';
import { ExAppInputFile } from './form/ExAppInputFile';
import { ExAppNumberTextInput } from './form/ExAppNumberTextInput';
import { ExAppPreview } from './form/ExAppPreview';
import { ExAppRadio } from './form/ExAppRadio';
import { ExAppSelect } from './form/ExAppSelect';
import { ExAppTextarea } from './form/ExAppTextarea';
import { ExAppTextInput } from './form/ExAppTextInput';

type Props = {
  uiJson: GovAIFormUIJson;
  register: UseFormRegister<FieldValues>;
  /** useFileUpload の状態を RHF に同期するために使用（ExAppInputFileのみ必須） */
  setValue?: UseFormSetValue<FieldValues>;
  /** ファイル追加/削除時の即時バリデーション用（ExAppInputFileのみ必須） */
  trigger?: UseFormTrigger<FieldValues>;
  /** ファイル削除時のエラークリア用（ExAppInputFileのみ必須） */
  clearErrors?: UseFormClearErrors<FieldValues>;
  errors: FieldErrors<FieldValues>;
  /** バリデーションエラー時のフォーカス制御用（ExAppInputFileのみ使用） */
  submitCount?: number;
  /** OpenGENAI Form Spec v1: visibleWhen 評価・preview 描画に使う現在値 */
  values?: FieldValues;
};

export const ExAppFormComponentBuilder = (props: Props) => {
  const { uiJson, register, setValue, trigger, clearErrors, errors, submitCount, values } = props;

  const currentValues = values ?? {};

  return (
    <>
      {Object.keys(uiJson).map((key) => {
        // keyが会話履歴用の場合はフォーム表示なし
        if (key === 'conversation_history') {
          return null;
        }

        // OpenGENAI Form Spec v1: 予約キー（$始まり）は描画しない
        if (isReservedFormKey(key)) {
          return null;
        }

        const uiConfig = uiJson[key];

        // OpenGENAI Form Spec v1: 条件表示（未指定なら常に表示＝従来動作）
        if (!isFieldVisible(uiConfig, currentValues)) {
          return null;
        }

        if (isPreviewType(uiConfig)) {
          return <ExAppPreview key={key} id={key} uiConfig={uiConfig} values={currentValues} />;
        }
        if (isTextType(uiConfig)) {
          return (
            <ExAppTextInput
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isNumberType(uiConfig)) {
          return (
            <ExAppNumberTextInput
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isTextareaType(uiConfig)) {
          return (
            <ExAppTextarea
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isFileType(uiConfig)) {
          if (!setValue || !trigger || !clearErrors) {
            return (
              <p key={key} className='my-8 text-error-1'>
                ファイルコンポーネントには setValue, trigger, clearErrors が必要です。
              </p>
            );
          }
          return (
            <ExAppInputFile
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
              setValue={setValue}
              trigger={trigger}
              clearErrors={clearErrors}
              submitCount={submitCount}
            />
          );
        } else if (isSelectType(uiConfig)) {
          return (
            <ExAppSelect
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isCheckboxType(uiConfig)) {
          return (
            <ExAppCheckbox
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isRadioType(uiConfig)) {
          return (
            <ExAppRadio
              key={key}
              id={key}
              errors={errors[key] ? formatValidationErrorMessage(key, uiConfig, errors) : ''}
              uiConfig={uiConfig}
              register={register}
            />
          );
        } else if (isHiddenType(uiConfig)) {
          return <ExAppHidden key={key} id={key} register={register} />;
        } else {
          return (
            <p key={key} className='my-8 text-error-1'>
              サポート外のコンポーネントです。
            </p>
          );
        }
      })}
    </>
  );
};
