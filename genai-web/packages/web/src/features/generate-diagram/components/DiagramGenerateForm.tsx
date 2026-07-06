import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { AutoResizeTextarea } from '@/components/ui/AutoResizeTextarea';
import { Button } from '@/components/ui/dads/Button';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { ErrorText } from '@/components/ui/dads/ErrorText';
import { Label } from '@/components/ui/dads/Label';
import { Legend } from '@/components/ui/dads/Legend';
import {
  linkActiveStyle,
  linkDefaultStyle,
  linkFocusStyle,
  linkHoverStyle,
} from '@/components/ui/dads/Link';
import { RequirementBadge } from '@/components/ui/dads/RequirementBadge';
import { useDiagram } from '@/features/generate-diagram/hooks/useDiagram';
import { useDiagramStore } from '@/features/generate-diagram/stores/useDiagramStore';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { DIAGRAM_DATA } from '../constants';
import { DiagramFormSchema, diagramFormSchema } from '../schema';
import { DiagramTypeButton } from './DiagramTypeButton';

const mainTypeOptions = Object.values(DIAGRAM_DATA).filter(
  (diagram) => diagram.category === 'main',
);

const otherTypeOptions = Object.values(DIAGRAM_DATA).filter(
  (diagram) => diagram.category === 'other',
);

export const DiagramGenerateForm = () => {
  const { content, setContent, selectedType, setSelectedType, setDiagramGenerationError } =
    useDiagramStore();

  const { usecase, chatId } = useUsecasePath();

  const { loading, setLoading, postDiagram } = useDiagram(usecase, chatId);

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<DiagramFormSchema>({
    mode: 'onSubmit',
    resolver: zodResolver(diagramFormSchema),
    values: {
      type: selectedType,
      content,
    },
  });

  const onSubmit = handleSubmit(async (data) => {
    if (loading) {
      return;
    }

    setLoading(true);

    setDiagramGenerationError(null);

    try {
      await postDiagram(data.content, data.type);
    } catch (error: unknown) {
      if (error instanceof Error) setDiagramGenerationError(error);
      else setDiagramGenerationError(new Error(`${error}`));
    }
  });

  return (
    <>
      <h2 className='sr-only'>ダイアグラム生成フォーム</h2>
      <form onSubmit={onSubmit}>
        <fieldset>
          <Legend size='lg' className='mb-1'>
            図の種類を選択
            <span className='font-normal'>（{DIAGRAM_DATA[selectedType].title}を選択中）</span>
          </Legend>
          <div className='grid grid-cols-[repeat(auto-fit,minmax(calc(180/16*1rem),1fr))] gap-2'>
            {mainTypeOptions.map((option) => (
              <DiagramTypeButton
                key={option.id}
                option={option}
                isSelected={selectedType === option.id}
                onChange={(type) => {
                  setSelectedType(type);
                  setValue('type', type);
                }}
                hasError={!!errors.type}
              />
            ))}
          </div>
          <Disclosure className='mt-3'>
            <DisclosureSummary>他の図の種類を見る</DisclosureSummary>
            <div className='mt-3 grid grid-cols-[repeat(auto-fit,minmax(calc(180/16*1rem),1fr))] gap-2 pb-2'>
              {otherTypeOptions.map((option) => (
                <DiagramTypeButton
                  key={option.id}
                  option={option}
                  isSelected={selectedType === option.id}
                  onChange={(type) => {
                    setSelectedType(type);
                    setValue('type', type);
                  }}
                  hasError={!!errors.type}
                />
              ))}
            </div>
          </Disclosure>
          {errors.type && <ErrorText id='type-input-error'>＊{errors.type.message}</ErrorText>}
        </fieldset>

        <div className='mt-6 mb-4'>
          <div className='mb-2 flex flex-col gap-1.5'>
            <Label htmlFor='generate-diagram-original-input' size='lg'>
              ダイアグラム生成元の文章 <RequirementBadge>※必須</RequirementBadge>
            </Label>
            <button
              type='button'
              className={`mb-1 w-fit ${linkDefaultStyle} ${linkHoverStyle} ${linkFocusStyle} ${linkActiveStyle}`}
              onClick={() => setContent(DIAGRAM_DATA[selectedType].example.content)}
            >
              {DIAGRAM_DATA[selectedType].example.title}を入力する
            </button>
            <AutoResizeTextarea
              required
              placeholder=''
              id='generate-diagram-original-input'
              rows={2}
              maxHeight={500}
              aria-describedby={errors.content ? 'generate-diagram-content-input-error' : undefined}
              {...register('content', {
                onChange: (e) => setValue('content', e.target.value),
              })}
            />
            {errors.content && (
              <ErrorText id='generate-diagram-content-input-error'>
                ＊{errors.content.message}
              </ErrorText>
            )}
          </div>
        </div>

        <div className='flex justify-center'>
          <Button
            type='submit'
            variant='solid-fill'
            className='w-60'
            size='lg'
            aria-disabled={loading}
          >
            {loading ? '実行中...' : '実行'}
          </Button>
        </div>
      </form>
    </>
  );
};
