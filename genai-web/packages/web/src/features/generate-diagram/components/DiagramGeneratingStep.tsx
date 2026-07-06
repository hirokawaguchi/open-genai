import { ProgressIndicator } from '@/components/ui/dads/ProgressIndicator';
import { useDiagram } from '@/features/generate-diagram/hooks/useDiagram';
import { useUsecasePath } from '@/hooks/useUsecasePath';

export const DiagramGeneratingStep = () => {
  const { usecase, chatId } = useUsecasePath();
  const { diagramType } = useDiagram(usecase, chatId);

  if (diagramType === '') {
    return null;
  }

  return (
    <div className='flex min-h-10 items-center justify-center rounded-6 bg-solid-gray-50 p-3'>
      <ProgressIndicator label='ステップ２: 図を生成しています' />
    </div>
  );
};
