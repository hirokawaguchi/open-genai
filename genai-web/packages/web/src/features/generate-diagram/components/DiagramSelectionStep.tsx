import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { useDiagram } from '@/features/generate-diagram/hooks/useDiagram';
import { useUsecasePath } from '@/hooks/useUsecasePath';
import { DIAGRAM_DATA } from '../constants';

export const DiagramSelectionStep = () => {
  const { usecase, chatId } = useUsecasePath();
  const { diagramType } = useDiagram(usecase, chatId);

  return (
    <>
      {diagramType === '' && (
        <div className='flex min-h-10 items-center justify-center rounded-6 bg-solid-gray-50 p-3'>
          <ProgressIndicator label='ステップ１: 最適なダイアグラムを選んでいます' />
        </div>
      )}

      {diagramType !== '' && (
        <div className='flex min-h-10 flex-col items-center justify-center rounded-6 bg-blue-50 p-3'>
          <span className='text-solid-gray-800'>ステップ１: 完了</span>
          <span className='mt-1'>
            {DIAGRAM_DATA[diagramType as keyof typeof DIAGRAM_DATA].title}
            を選択
          </span>
        </div>
      )}
    </>
  );
};
